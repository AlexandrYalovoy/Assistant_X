# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared helpers: config, text normalization, stemming, chunking, DB access. The words and letters of the document
languages come from the language packs (core/lang.py, assistant_x/lang)."""

import collections, datetime, functools, glob, json, os, pathlib, re, sqlite3, unicodedata

from assistant_x.core import config, lang
from assistant_x.core.formats import PAGE_RX, column_keys, unescape_text
from assistant_x.core.textmap import SectionTracker, heading_text

TOKEN_RX = re.compile(rf"[0-9{lang.chars('lower')}]+(?:[.,][0-9]+)?", re.I)
HF_NAME_RX = re.compile(r"[A-Za-z0-9][\w.-]*/[\w.-]+", re.A)  # BAAI/bge-m3: a model name on HuggingFace, not a folder
MODELS_DIR = "models"  # "models/bge-m3" is always the folder of the models, never a HuggingFace name

STOP = set(lang.words("stop_words"))


def load_config(path=None):
    """Settings of the search: the [search] table of assistant_x.toml with the folders of the workspace
    (core/config.py)."""
    from assistant_x.core import config, env

    path = path or env.get("SEARCH_CONFIG")
    w, raw = config.load(path)
    cfg = dict(raw["search"])
    cfg.update(
        workspace=str(w.root),
        library_root=str(w.root),
        texts_dir=str(w.texts),
        cards_dir=str(w.cards),
        catalog=str(w.catalog),
        index_dir=str(w.db),
        models_dir=str(w.models),
        debug_dir=str(w.debug),
        packages_dir=str(w.packages),
        profile=raw["profile"],
    )
    syn = cfg.get("synonyms")
    cfg["synonyms"] = str((w.root / syn).resolve()) if syn else str(config.profile_file("synonyms.txt", raw) or "")
    for k in ("embed_model", "rerank_model"):  # a folder in the models folder, otherwise a HuggingFace name
        v = cfg.get(k)
        if not v:
            continue
        local = w.models / re.sub(r"^models[\\/]", "", v)
        if local.is_dir() or not HF_NAME_RX.fullmatch(v) or re.split(r"[\\/]", v)[0] == MODELS_DIR:
            cfg[k] = str(local)
    _finish(cfg)
    return cfg


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    base = os.path.dirname(os.path.abspath(path))
    for k in ("library_root", "index_dir", "texts_dir", "cards_dir", "catalog", "synonyms"):
        if cfg.get(k):
            cfg[k] = os.path.normpath(os.path.join(base, cfg[k]))
    for k in ("embed_model", "rerank_model"):  # a local folder next to config.json, otherwise a HuggingFace name
        if cfg.get(k) and (
            os.path.isdir(os.path.join(base, cfg[k]))
            or not HF_NAME_RX.fullmatch(cfg[k])
            or re.split(r"[\\/]", cfg[k])[0] == MODELS_DIR
        ):
            # "models/bge-m3" stays a folder of the project even when it is missing: never one beside the current
            # folder of the process, and the error names the folder instead of a refused HuggingFace name
            cfg[k] = os.path.normpath(os.path.join(base, cfg[k]))
    cfg.setdefault("workspace", cfg.get("library_root") or base)
    cfg.setdefault("models_dir", os.path.join(base, MODELS_DIR))
    cfg.setdefault("debug_dir", os.path.join(base, "debug"))
    cfg.setdefault("packages_dir", os.path.join(base, "packages"))
    _finish(cfg)
    return cfg


def _finish(cfg):
    if not cfg.get("db"):  # the base in use: library.sqlite, or the file a full rebuild switched to (library.current)
        cfg["db"], cfg["db_auto"] = current_db(cfg["index_dir"]), True
    cfg.setdefault("vectors", os.path.join(cfg["index_dir"], "vectors.f16"))


# A full rebuild (build_index.py --full) writes a new file library-<time>.sqlite while the search keeps reading the
# old one; library.next names it until embed.py has given it vectors, then library.current points at it and the
# running search switches over (Library.refresh). Windows does not let a file open in Claude be replaced or renamed.
DB_DEFAULT, DB_CURRENT, DB_NEXT = "library.sqlite", "library.current", "library.next"


def _pointer(index_dir, name):
    """File name written in a pointer file of index_dir, or '' when there is none or its base is gone."""
    try:
        with open(os.path.join(index_dir, name), encoding="utf-8") as f:
            target = f.read().strip()
    except OSError:
        return ""
    return target if target and os.path.exists(os.path.join(index_dir, target)) else ""


def current_db(index_dir):
    return os.path.join(index_dir, _pointer(index_dir, DB_CURRENT) or DB_DEFAULT)


def next_db(index_dir):
    """Path of a fully rebuilt base waiting for its vectors, or None."""
    name = _pointer(index_dir, DB_NEXT)
    return os.path.join(index_dir, name) if name else None


def set_pointer(index_dir, name, target):
    """Write a pointer file at once (a reader sees the old or the new name, never half), or remove it (target None)."""
    path = os.path.join(index_dir, name)
    if target is None:
        if os.path.exists(path):
            os.remove(path)
        return
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(os.path.basename(target) + "\n")
    os.replace(path + ".tmp", path)


def switch_db(cfg, path):
    """Make path the base in use and forget the pending one; older bases are deleted once nobody holds them."""
    folder = cfg["index_dir"]
    set_pointer(folder, DB_CURRENT, None if os.path.basename(path) == DB_DEFAULT else path)
    set_pointer(folder, DB_NEXT, None)
    cfg["db"] = path
    drop_stale_dbs(cfg)


def drop_stale_dbs(cfg):
    """Delete bases left by earlier full rebuilds (and their -wal, -shm); one still open in Claude stays till next time."""
    keep = {os.path.basename(p) for p in (current_db(cfg["index_dir"]), next_db(cfg["index_dir"])) if p}
    for p in glob.glob(os.path.join(cfg["index_dir"], "library*.sqlite")):
        if os.path.basename(p) in keep:
            continue
        for f in (p, p + "-wal", p + "-shm"):  # the base first: while it is open in Claude, Windows refuses
            try:
                if os.path.exists(f):
                    os.remove(f)
            except OSError:
                break


_stemmers = None


def _get_stemmers():
    global _stemmers
    if _stemmers is None:
        import snowballstemmer

        # (letters that pick the stemmer, stemmer) of every language; a word with none of them: the last stemmer
        _stemmers = [
            (
                re.compile(f"[{lang.get(c, 'stem_detect')}]") if lang.get(c, "stem_detect") else None,
                snowballstemmer.stemmer(lang.get(c, "stemmer")),
            )
            for c in lang.active()
            if lang.get(c, "stemmer")
        ]
    return _stemmers


@functools.lru_cache(maxsize=500_000)
def stem_word(w):
    w = lang.fold(w.lower())
    if w[0].isdigit() or len(w) < 3:
        return w
    return stemmer_for(w).stemWord(w)


def stemmer_for(w):
    """The Snowball stemmer of the language whose letters (stem_detect of its pack) the word has, else the one of the
    first language with no letters of its own (English), else the last one."""
    stemmers = _get_stemmers()
    for rx, s in stemmers:
        if rx and rx.search(w):
            return s
    return next((s for rx, s in stemmers if rx is None), stemmers[-1][1])


def tokens(text, drop_stop=False):
    out = []
    for m in TOKEN_RX.finditer(text):
        w = lang.fold(m.group(0).lower())
        if drop_stop and w in STOP:
            continue
        out.append(stem_word(w))
    return out


def stem_text(text):
    return " ".join(tokens(text))


# a token of the exact index: letters and digits, with a hyphen, a dot or a slash inside (1510-84, 51858-2002, 5.3, 650)
EXACT_RX = re.compile(r"[^\W_]+(?:[-./][^\W_]+)*")


def exact_tokens(text):
    """The tokens of the exact column of the word index: lower case, the folding of the languages (lang.fold) and of
    the letters of two scripts that look alike (lang.homoglyphs: an OCR Latin X in a Cyrillic grade), whole, not
    stemmed, a designation as one token ('gost', '1510-84')."""
    return EXACT_RX.findall(lang.homoglyphs(lang.fold(text.lower())))


def exact_text(text):
    return " ".join(exact_tokens(text))


SOFT_HYPHEN = chr(0xAD)
# the marks of Markdown a quote does not carry: bold and italic, backticks, a line break tag, heading marks, table bars
MARKDOWN_MARK_RX = re.compile(r"\*\*|__|`+|<br\s*/?>|^ {0,3}#{1,6}[ \t]+|\|", re.M)


@functools.lru_cache(maxsize=1)
def _skeleton_map():
    table = {c: "-" for c in lang.words("dashes")}
    table.update({c: '"' for c in lang.words("quotes")})
    return str.maketrans(table)


def skeleton(text):
    """The comparison form of a quote and of a page (search/retrieval.verify_quote, search/eval.py): NFKC, lower case,
    the folding of the languages (lang.fold: Russian yo as ye) and of look-alike letters of two scripts
    (lang.homoglyphs), every dash of the language packs ("dashes") as "-" and every quote ("quotes") as a double quote,
    the soft hyphen, the marks of Markdown and the underscores of italics at the edges of words dropped, a word broken
    at a line end joined (join_hyphens: 'separa- tor' as 'separator'), white space collapsed."""
    t = unicodedata.normalize("NFKC", text.replace(SOFT_HYPHEN, ""))
    t = EDGE_UNDERSCORE_RX.sub("", ITALIC_WORD_RX.sub(r" \1 ", MARKDOWN_MARK_RX.sub(" ", t)))
    t = lang.homoglyphs(lang.fold(join_hyphens(" ".join(t.split()).lower()))).translate(_skeleton_map())
    return " ".join(t.split())


# the underscores of Markdown italics ('_straightness', 'part_'): an underscore not between two letters or digits
EDGE_UNDERSCORE_RX = re.compile(r"(?<![^\W_])_+|_+(?![^\W_])")
# one word in italics glued to its neighbours by a converter ("|_DN_300 and less|"): the word apart
ITALIC_WORD_RX = re.compile(r"(?<![^\W_])_([^\W_]+)_")
# a word broken at a line end that a converter joined into one line with its hyphen: 'separa- tor'
INLINE_HYPHEN_RX = re.compile(r"([^\W\d_]{2,})[-‐][ \t]+([^\W\d_]+)")


@functools.lru_cache(maxsize=1)
def _suspended():
    return frozenset(w.lower() for w in lang.words("hyphen_suspended"))


def join_hyphens(text, known=None):
    """Words broken at a line end and left on one line with the hyphen and a space ('separa- tor') joined into one
    ('separator'): the second part goes on in lower case (or both parts are capitals) and is not a word of
    "hyphen_suspended" of the language packs, which ends a suspended compound ("pre- and post-processing").
    known: the vocabulary of the library (lower case, folded); with it a word is joined only when the vocabulary knows
    the whole word, as dehyphenate does (a text written to the library); without it every such word
    is joined (the search text and the comparison of quotes, where a wrong join of a rare compound costs nothing)."""
    if "- " not in text and "-\t" not in text and "‐" not in text:
        return text
    stop = _suspended()

    def join(m):
        a, b = m.group(1), m.group(2)
        if b.lower() in stop or not (b[0].islower() or (a.isupper() and b.isupper())):
            return m.group(0)
        if known is not None and lang.fold((a + b).lower()) not in known:
            return m.group(0)
        return a + b

    return INLINE_HYPHEN_RX.sub(join, text)


# characters a reader does not see but Claude does (a way to hide instructions in a text): zero width,
# text direction, Unicode tags, variation selectors
INVISIBLE_RX = re.compile(
    "[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\ufe00-\ufe0f\U000e0000-\U000e007f\U000e0100-\U000e01ef]"
)


def strip_invisible(text):
    return INVISIBLE_RX.sub("", text)


def split_pages(text):
    """[(page_no, page_text)] from a text with '=== page N ===' markers; an escaped marker line of a body
    ('\\=== page 3 ===', core/formats.py) is given back as it is."""
    parts = PAGE_RX.split(text)
    return [(int(n), unescape_text(p)) for n, p in zip(parts[1::2], parts[2::2])]


HYPHEN_BREAK_RX = re.compile(r"([^\W\d_]+)[-\u2010][ \t]*\n[ \t]*([^\W\d_]+)")


def dehyphenate(text, known):
    """A word broken at the end of a line ('separa-\\ntor') joined into one, but only when the joined word (lower case,
    folded) is in known, the vocabulary of the library (intake/tools/ocr_score.py): 'Ural-\\nVolga' stays as it is
    unless the vocabulary knows 'uralvolga'. The rest of the next line goes on after the word. A word a converter
    already put on one line with its hyphen ('separa- tor') is joined by the same rule (join_hyphens)."""
    if not known:
        return text

    def join(m):
        word = m.group(1) + m.group(2)
        return word if lang.fold(word.lower()) in known else m.group(0)

    return join_hyphens(HYPHEN_BREAK_RX.sub(join, text), known)


CHUNK_TARGET, CHUNK_LIMIT, CHUNK_CUT, CHUNK_SHORT = 900, 2000, 1800, 50
SENTENCE_END_RX = re.compile(rf"[.!?…»)](?=\s+[«\"(]?[{lang.chars('upper')}0-9])")


def _last_sentence(text, most=300):
    """The last sentence of a piece (at most `most` characters), repeated at the start of the next one."""
    ends = [m.end() for m in SENTENCE_END_RX.finditer(text, max(0, len(text) - most))]
    tail = text[ends[-1] :].strip() if ends else ""
    return tail if 0 < len(tail) <= most else ""


def _blocks(text):
    """[(start, end)] of the blocks of a page, the white space around each left out: runs of lines between blank
    lines; a run of table lines ('|…') is a block of its own."""
    spans, cur, in_table, pos = [], None, False, 0
    for line in text.split("\n"):
        at, pos = pos, pos + len(line) + 1
        is_table = line.lstrip().startswith("|")
        if (not line.strip() and not in_table) or (is_table != in_table and cur):
            if cur:
                spans.append(cur)
            cur = None if not line.strip() else [at, at + len(line)]
        else:
            cur = [at, at + len(line)] if cur is None else [cur[0], at + len(line)]
        in_table = is_table
    if cur:
        spans.append(cur)
    out = []
    for s, e in spans:
        piece = text[s:e]
        s, e = s + len(piece) - len(piece.lstrip()), s + len(piece.rstrip())
        if e > s:
            out.append((s, e))
    return out


def _split_table(text, s, e, cut):
    """A Markdown table longer than the limit: pieces (start, end, lead) of whole rows; the first holds the header
    row(s) of the table, each next one is led by them (the lead is searched with the piece, it is no text of the page)."""
    rows, pos = [], s
    for line in text[s:e].split("\n"):
        rows.append((pos, pos + len(line)))
        pos += len(line) + 1
    lines = [text[a:b] for a, b in rows]
    nh = 2 if len(lines) > 1 and set(lines[1].replace("|", "").strip()) <= set("-: ") else 1
    head = "\n".join(lines[:nh])
    groups, cur = [], []
    for i in range(nh, len(rows)):
        if cur and len(head) + 1 + rows[i][1] - rows[cur[0]][0] > cut:
            groups.append(cur)
            cur = []
        cur.append(i)
    if cur or not groups:
        groups.append(cur)
    return [
        (rows[0][0] if k == 0 else rows[g[0]][0], rows[g[-1]][1] if g else rows[nh - 1][1], None if k == 0 else head)
        for k, g in enumerate(groups)
    ]


def _split_text(text, s, e, target, cut):
    """A text block longer than the limit: pieces (start, end, lead) of up to `cut` characters with their lead, cut at
    a line or a space; each next piece is led by the last sentence of the previous one, so a sentence cut in two is
    whole in the search text of one of them."""
    pieces, lead = [], None
    while e - s > cut - (len(lead) + 1 if lead else 0):
        room = cut - (len(lead) + 1 if lead else 0)
        seg = text[s : s + room]
        at = seg.rfind("\n")
        at = at if at > target // 2 else seg.rfind(" ")
        at = at if at > 0 else room
        end = s + len(seg[:at].rstrip())
        pieces.append((s, end, lead))
        piece = text[s:end]
        overlap = _last_sentence(piece)
        lead = overlap if overlap and len(overlap) < len(piece) // 2 else None
        s += at
        while s < e and text[s].isspace():
            s += 1
    if e > s:
        pieces.append((s, e, lead))
    return pieces


def _size(piece):
    """Length of the search text of a piece (start, end, lead)."""
    return piece[1] - piece[0] + (len(piece[2]) + 1 if piece[2] else 0)


def chunk_page(text, target=CHUNK_TARGET, limit=CHUNK_LIMIT, cut=CHUNK_CUT, short=CHUNK_SHORT):
    """Split a page into fragments of 1-2 paragraphs: [(start, end, lead)], character offsets into the page text and
    the lead of the search text (or None). The fragments of a page tile it: text[start:end] of them in order is the
    page exactly, white space between blocks going to the fragment before it. A Markdown table stays one block up
    to `limit` characters, a longer one is cut by rows and each next piece is led by its header; a longer text block
    is cut and each next piece is led by the last sentence of the previous one. The lead is no part of the page: it is
    added to the search text only (chunk_search_text). A fragment shorter than `short` (a heading, a caption, a page
    number) joins the next fragment, the last one the previous. Fragments never cross page boundaries, so every
    fragment cites exactly one page (CHUNK_VERSION 4)."""
    pieces = []
    for s, e in _blocks(text):
        if e - s <= limit:
            pieces.append((s, e, None))
        else:
            pieces += _split_table(text, s, e, cut) if text[s] == "|" else _split_text(text, s, e, target, cut)
    chunks, cur = [], None  # [pieces, size of the search text]
    for p in pieces:
        if cur and cur[1] + _size(p) > target:
            chunks.append(cur)
            cur = None
        cur = [[p], _size(p)] if cur is None else [cur[0] + [p], cur[1] + 2 + _size(p)]
    if cur:
        chunks.append(cur)
    glued = []
    join = lambda a, b: [a[0] + b[0], a[1] + 2 + b[1]]  # noqa: E731
    for ch in chunks:  # a short fragment is carried into the next one (or left to the previous, if that one fits)
        if glued and glued[-1][1] < short and glued[-1][1] + ch[1] <= limit:
            glued[-1] = join(glued[-1], ch)
        elif len(glued) > 1 and glued[-1][1] < short and glued[-2][1] + glued[-1][1] <= limit:
            last = glued.pop()
            glued[-1] = join(glued[-1], last)
            glued.append(ch)
        else:
            glued.append(ch)
    # glue a tiny tail to the previous fragment
    if len(glued) > 1 and glued[-1][1] < 200 and glued[-2][1] + glued[-1][1] <= limit:
        tail = glued.pop()
        glued[-1] = join(glued[-1], tail)
    starts = [0] + [g[0][0][0] for g in glued[1:]]
    return [(a, b, g[0][0][2]) for a, b, g in zip(starts, starts[1:] + [len(text)], glued)]


def chunk_search_text(page_text, start, end, lead=None):
    """The text a fragment is searched and embedded by: its lead (the repeated header of a table, the sentence of
    overlap) and its piece of the page, a word broken at a line end joined (join_hyphens: the page text keeps it)."""
    body = join_hyphens(page_text[start:end].strip())
    return f"{lead}\n{body}" if lead else body


# ---------- what the models read ----------
# the marks of Markdown a model reads as noise: bold and italic stars, heading marks, backticks
MODEL_MARKUP_RX = re.compile(r"\*\*|__|`+|^ {0,3}#{1,6}[ \t]+", re.M)
TABLE_SEP_RX = re.compile(r"^\|?[\s:|-]*-[\s:|-]*\|?$")
MODEL_TITLE_CHARS = 120  # the short title in front of a fragment: which book; a long subtitle would crowd the text


def table_lines(text):
    """The rows of every Markdown table of a text as lines "header: value; header: value" (empty cells left out)."""
    out, head = [], None
    for line in text.split("\n"):
        s = line.strip()
        if not s.startswith("|"):
            out.append(line)
            head = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if head is None:
            head = cells
        elif not TABLE_SEP_RX.match(s):
            pairs = [f"{h}: {v}" if h else v for h, v in zip(head + [""] * len(cells), cells) if v]
            out.append("; ".join(pairs))
    return "\n".join(out)


def for_embedding(text, table_rows=False):
    """A text without Markdown markup, a word broken at a line end joined (join_hyphens); table_rows: a table as a line
    per row."""
    return join_hyphens(MODEL_MARKUP_RX.sub("", table_lines(text) if table_rows else text))


def model_text(title, heading, text, table_rows=False):
    """What the models read of a fragment, the embedding model (search/embed.py) and the reranker (retrieval.py)
    alike: the short title of its document and its section heading ('which book, which chapter') over its search
    text without Markdown markup. One function for both, so the reranker judges the fragment the vector was made
    of; the word index keeps its own text (build_index.add_chunk)."""
    return "\n".join(
        x for x in ((title or "")[:MODEL_TITLE_CHARS], heading or "", for_embedding(text or "", table_rows)) if x
    )


# ---------- section headings ----------
# 2: fragments carry the heading of their section; 3: short fragments joined, long tables and texts cut with overlap;
# 4: fragments are offsets into the page text, the overlap and the repeated header only lead their search text;
# 5: a card is a fragment per language and one of its questions (card.search_texts).
# An older base needs build_index.py --full
CHUNK_VERSION = "5"


# running headers and footers: a line among the first or the last RUNNING_EDGE lines of a page that stands there on
# RUNNING_SHARE of the pages of a document of RUNNING_MIN_PAGES pages or more (its digits aside: the page "40 of 331", the
# title of the standard, "document provided by ... saved on 21.10.2026"). The step 1 audit of the library: 68 of
# 336 documents, N-00001 on 144 of its 152 pages; a question with the title words of such a document found only it
RUNNING_EDGE, RUNNING_SHARE, RUNNING_MIN_PAGES = 4, 0.5, 5


def _line_key(line):
    return re.sub(r"[\W_]+", "", re.sub(r"\d+", "0", line.lower()))


def _edge_lines(text):
    lines = [ln for ln in text.split("\n") if ln.strip()]
    return lines[:RUNNING_EDGE] + lines[-RUNNING_EDGE:]


def running_lines(pages):
    """The keys (_line_key) of the running headers and footers of a document [(page, text)]: set() for a short one."""
    if len(pages) < RUNNING_MIN_PAGES:
        return set()
    count = collections.Counter(k for _, text in pages for k in {_line_key(ln) for ln in _edge_lines(text)} if k)
    least = max(3, RUNNING_SHARE * len(pages))
    return {k for k, n in count.items() if n >= least}


def body_span(text, running):
    """(start, end) of a page without its running header and footer lines (running_lines), blank lines around them
    included; (0, len(text)) without any; start == end for a page that has nothing else."""
    if not running:
        return 0, len(text)
    spans, pos = [], 0
    for line in text.split("\n"):
        spans.append((pos, pos + len(line), line))
        pos += len(line) + 1
    s, e, seen = 0, len(text), 0
    for at, end, line in spans:  # from the top
        if not line.strip():
            continue
        if seen >= RUNNING_EDGE or _line_key(line) not in running:
            s = at
            break
        seen += 1
    else:
        return len(text), len(text)
    seen = 0
    for at, end, line in reversed(spans):  # from the bottom
        if not line.strip():
            continue
        if seen >= RUNNING_EDGE or _line_key(line) not in running or at < s:
            e = end
            break
        seen += 1
    return s, max(s, e)


def chunk_doc(pages):
    """[(page, n, heading, start, end, lead)] for a whole document: the fragments of chunk_page with their section
    heading. A heading that opens a fragment already counts for it; one further down counts from the next fragment.
    The running headers and footers (running_lines) are left out of the fragments: the page text keeps them, the
    search does not find every page of a document by its title."""
    tracker, out = SectionTracker(pages), []
    running = running_lines(pages)
    for page, text in pages:
        b, f = body_span(text, running)
        for n, (s, e, lead) in enumerate((s + b, e + b, lead) for s, e, lead in chunk_page(text[b:f])):
            lines = text[s:e].strip().splitlines()
            first = 0
            while first < len(lines) and (not lines[first].strip() or heading_text(lines[first])):
                tracker.feed(page, lines[first])
                first += 1
            out.append((page, n, tracker.current(), s, e, lead))
            for line in lines[first:]:
                tracker.feed(page, line)
    return out


def connect(db_path, readonly=False):
    """readonly: the search never writes, so it cannot damage the base, and it also works from a write-protected
    flash drive or a network folder (if even read locks fail there, the file is opened as immutable)."""
    if not readonly:
        con = sqlite3.connect(db_path, check_same_thread=False, timeout=BUSY_S)  # MCP tools run in worker threads
        try:  # WAL: the search reads while build_index.py / embed.py write, neither waits for the other
            con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:  # a network folder without shared memory: the old journal is fine
            pass
    else:
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"No search base: {db_path}")
        uri = pathlib.Path(db_path).absolute().as_uri()
        try:
            con = sqlite3.connect(uri + "?mode=ro", uri=True, check_same_thread=False, timeout=BUSY_S)
            con.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except sqlite3.OperationalError:
            con = sqlite3.connect(uri + "?immutable=1", uri=True, check_same_thread=False)
    con.execute(f"PRAGMA busy_timeout={int(BUSY_S * 1000)}")  # a moment of a writer's lock: wait, do not fail
    con.row_factory = sqlite3.Row
    return con


BUSY_S = 15  # seconds a reader or a writer waits for a lock of the other side
# the text of a fragment in a query of chunks c LEFT JOIN pages p (schema 3): the piece of its page, or its own text;
# with the lead: the text it is searched and embedded by (chunk_search_text)
CHUNK_TEXT_SQL = "CASE WHEN c.kind = 'text' THEN substr(p.text, c.start + 1, c.end - c.start) ELSE c.own_text END"
SEARCH_TEXT_SQL = (
    "CASE WHEN c.kind = 'text' THEN coalesce(c.lead || char(10), '') || substr(p.text, c.start + 1, "
    "c.end - c.start) ELSE c.own_text END"
)
PAGES_JOIN_SQL = "LEFT JOIN pages p ON p.code = c.code AND p.page = c.page"


STALE_KEY = "index_stale"  # in the meta table of the base: the date of an apply the base does not know yet
STALE_MARK = "index_stale.txt"  # in the index folder, when there is no base yet


def mark_index_stale(cfg, date):
    """An apply changed the library: the base says so until build_index runs (the meta table, or a marker file in the
    index folder when there is no base)."""
    if os.path.exists(cfg["db"]):
        con = connect(cfg["db"])
        try:
            con.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
            con.execute("INSERT OR REPLACE INTO meta VALUES(?, ?)", (STALE_KEY, date))
            con.commit()
        finally:
            con.close()
    else:
        with open(os.path.join(os.path.dirname(cfg["catalog"]), STALE_MARK), "w", encoding="utf-8") as f:
            f.write(date + "\n")


def index_stale(cfg, con=None):
    """The date of an apply the base does not know yet, or ""."""
    try:
        with open(os.path.join(os.path.dirname(cfg["catalog"]), STALE_MARK), encoding="utf-8") as f:
            return f.read().strip() or "?"
    except OSError:
        pass
    if con is None and not os.path.exists(cfg["db"]):
        return ""
    own = con is None
    con = con or connect(cfg["db"], readonly=True)
    try:
        return meta(con, STALE_KEY, "") or ""
    except sqlite3.Error:
        return ""
    finally:
        if own:
            con.close()


def clear_index_stale(cfg, con):
    """build_index has read the library: no note any more."""
    con.execute("DELETE FROM meta WHERE key=?", (STALE_KEY,))
    mark = os.path.join(os.path.dirname(cfg["catalog"]), STALE_MARK)
    if os.path.exists(mark):
        os.remove(mark)


def stale_note(cfg, con=None):
    """The line the search tools put first while the base is behind an apply ("" when it is not)."""
    date = index_stale(cfg, con)
    return (
        (
            f"Note: documents were added or changed on {date} and the search base does not have them yet; they are "
            "searchable after intake_reindex() (assistant-x build, then assistant-x embed)."
        )
        if date
        else ""
    )


def vector_gap(con):
    """(fragments without a meaning vector, all fragments) of the base: a build that embed has not followed yet (an
    interrupted recalculation) leaves the first above 0, and those fragments are found by words only."""
    missing, total = con.execute("SELECT count(*) - count(vec_row), count(*) FROM chunks").fetchone()
    return missing or 0, total or 0


def base_vector_gap(db):
    """vector_gap of the base file db, (0, 0) when there is no base (or it does not read)."""
    if not os.path.exists(db):
        return 0, 0
    try:
        con = connect(db, readonly=True)
    except (OSError, sqlite3.Error):
        return 0, 0
    try:
        return vector_gap(con)
    except sqlite3.Error:
        return 0, 0
    finally:
        con.close()


def vector_gap_note(missing, total):
    """The line about the fragments without vectors ("" when every fragment has one)."""
    if not missing:
        return ""
    head = "Found by words only: " if missing >= total else "Note: "
    return (
        f"{head}{missing} of {total} fragments have no meaning vectors, so they are found by words only; run "
        "intake_reindex() (or assistant-x embed) to compute them."
    )


MAINTENANCE = "maintenance.json"  # in the db folder while a base package is installed: the files of the library move


def set_maintenance(index_dir, what):
    """Say that the library is being changed (the install of a base package): a running search server lets the
    originals go (they are renamed) and answers page images with maintenance_note()."""
    os.makedirs(index_dir, exist_ok=True)
    data = {
        "pid": os.getpid(),
        "what": what,
        "started": datetime.datetime.now().isoformat(timespec="seconds"),
        "ts": datetime.datetime.now().timestamp(),
    }
    with open(os.path.join(index_dir, MAINTENANCE + ".tmp"), "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(os.path.join(index_dir, MAINTENANCE + ".tmp"), os.path.join(index_dir, MAINTENANCE))


def clear_maintenance(index_dir):
    p = os.path.join(index_dir, MAINTENANCE)
    if os.path.exists(p):
        os.remove(p)


def maintenance(index_dir):
    """{pid, what, started} while the library is being changed, else None (a note of a process that is gone counts
    for nothing: a PC switched off in the middle)."""
    try:
        with open(os.path.join(index_dir, MAINTENANCE), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    from assistant_x.core import lock

    return data if data.get("pid") and lock.alive(int(data["pid"]), data.get("ts")) else None


def maintenance_note(m):
    return (
        f"The library is being changed right now ({m.get('what', '?')}, since {m.get('started', '?')}): the "
        "originals are moved, page images come back when it ends. The search answers meanwhile."
    )


def has_column(con, table, column):
    return any(r[1] == column for r in con.execute(f"PRAGMA table_info({table})"))


def meta(con, key, default=None):
    r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def touch(con):
    """Mark the base as changed: a running MCP server notices it and drops what it loaded from the old state."""
    con.execute("INSERT OR REPLACE INTO meta VALUES('updated', ?)", (datetime.datetime.now().isoformat(),))


def has_meta(con):
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone())


def require_built(con, db=""):
    """SystemExit with what to do when the base has no meta table (a build that failed or never ran), instead of a raw
    SQLite error later."""
    if not has_meta(con):
        raise SystemExit(
            f"The search base{' ' + db if db else ''} is not built (it has no meta table): run "
            "assistant-x build, then this command again."
        )


# Claude keeps the vector file open, and Windows does not let an open file be deleted or replaced. So a rebuild
# writes a new file (its name is in meta) and the old one is deleted later, once nobody holds it.
def vectors_path(cfg, con):
    name = meta(con, "vectors_file") if has_meta(con) else None  # a base whose build failed: the default name
    return os.path.join(os.path.dirname(cfg["vectors"]), name) if name else cfg["vectors"]


def new_vectors_file(cfg, con):
    name = f"vectors-{datetime.datetime.now():%Y%m%d-%H%M%S}.f16"
    con.execute("INSERT OR REPLACE INTO meta VALUES('vectors_file', ?)", (name,))
    return os.path.join(os.path.dirname(cfg["vectors"]), name)


def drop_stale_vectors(cfg, con):
    """Delete vector files no base uses: neither con's, nor those of the base in use and the one being rebuilt."""
    keep = {os.path.basename(vectors_path(cfg, con))}
    for db in {current_db(cfg["index_dir"]), next_db(cfg["index_dir"])} - {None}:
        try:
            other = connect(db, readonly=True)
            keep.add(os.path.basename(vectors_path(cfg, other)))
            other.close()
        except (OSError, sqlite3.Error):
            pass
    folder = os.path.dirname(cfg["vectors"])
    for p in glob.glob(os.path.join(folder, "vectors*.f16")) + glob.glob(os.path.join(folder, "vectors*.f16.*")):
        if not any(os.path.basename(p).startswith(k) for k in keep):
            try:
                os.remove(p)
            except OSError:  # still open in a running Claude: next build will retry
                pass


# 2: JSON cards — docs gets the columns of the card, chunks a kind (text, card, unit), the tables toc and links.
# 3: the table pages holds the text of every page exactly (with what its .pages.json knows); a text fragment is an
# offset range of its page (chunks.start, chunks.end) and keeps only its lead (the repeated header of a table, the
# sentence of overlap), a card or unit fragment its own text (chunks.own_text: the simpler choice, a card has no
# page); the word index gets the column exact (whole tokens, designations as one token).
# A base of another schema is built anew (build_index.py --full), never migrated
BASE_SCHEMA = "3"
SCHEMA = """
CREATE TABLE IF NOT EXISTS docs(
  code TEXT PRIMARY KEY, title TEXT, designation TEXT, doc_type TEXT, section TEXT, year INTEGER,
  format TEXT, topics TEXT, file TEXT, page_offset TEXT,
  card TEXT, card_sha TEXT,  -- the card as JSON (of the main document for a part) and the sha256 of its file
  text_file TEXT, text_sha TEXT, pages INTEGER,
  parent TEXT, source TEXT,  -- parent: E-00006 for its part E-00006-02; source: the name of the original file
  lang TEXT,  -- the languages of the document, comma-separated (ru,en)
  quality TEXT, issue TEXT,  -- quality: warning from the text itself; issue: the open issues of the card
  ocr_share REAL, ocr_score REAL,  -- share of pages read by OCR (NULL when unknown); recognition score 0-100
  personal INTEGER);  -- 1: a document of the user, added on their PC
CREATE TABLE IF NOT EXISTS pages(
  code TEXT, page INTEGER,
  text TEXT, sha TEXT,  -- the text of the page as the text file has it (its marker and the blank lines around aside)
  label TEXT, source TEXT, ocr_score REAL, flags TEXT,  -- from <code>.pages.json: printed label, source, score, flags
  PRIMARY KEY(code, page));
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY, code TEXT, page INTEGER, n INTEGER, vec_row INTEGER, heading TEXT,
  kind TEXT NOT NULL DEFAULT 'text',  -- text: a piece of a page; card: the card (page 0); unit: an article of an issue
  start INTEGER, end INTEGER,  -- text: the piece pages.text[start:end] of its page
  lead TEXT,  -- text: what leads its search text but is no text of the page (a table header, a sentence of overlap)
  own_text TEXT);  -- card, unit: the text of the fragment
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(code, page);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(stem, exact, content='', contentless_delete=1,
  tokenize="unicode61 remove_diacritics 2 tokenchars '-./'");
CREATE TABLE IF NOT EXISTS toc(code TEXT, level INTEGER, title_en TEXT, title TEXT, pdf_from INTEGER, pdf_to INTEGER);
CREATE INDEX IF NOT EXISTS toc_doc ON toc(code, pdf_from);
CREATE TABLE IF NOT EXISTS links(code TEXT, designation TEXT, target_code TEXT);
CREATE INDEX IF NOT EXISTS links_target ON links(target_code);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


# quality thresholds of a text: the one place for both sides, the search (text_stats, quality_note) and the intake
# (intake/quality_report.py), like dupcheck.THRESHOLDS
QUALITY = {
    "empty_chars": 80,  # characters: a page with less is "almost empty"
    "empty_share": 0.2,  # share of almost empty pages worth a warning
    "fffd_per_1000": 1,  # U+FFFD per 1000 characters: lost symbols
    "scan_share": 0.2,  # share of pages through OCR that makes a document a scan for the Cyrillic check
    "scan_script": (0.3, 0.8),  # share of the letters of a keep_share pack (Cyrillic) of a scan in this range:
    # possible OCR garbage (a bad recognition turns them into Latin)
    "lang_letters": 200,  # letters a text needs for its languages (langs_of)
    "lang_share": 0.7,  # share of the letters that makes a text of one language (lang_share of a pack overrides)
    "lang_mixed": 0.15,  # … otherwise every language with this share or more: a mixed text
    "replace_share": 0.5,  # share of pages through OCR past which an empty document should be replaced, not re-read
    "fallback_share": 0.2,  # share of pages that fell back to the plain text layer
    "min_pages_heads": 5,  # a document this long without a single heading is worth a look
    # recognition score 0-100 (intake/tools/ocr_score.py): words known to the library vocabulary, Tesseract confidence
    "ocr_words_free": 0.03,  # share of unknown words a clean text has anyway (names, rare terms): still 100
    "ocr_words_slope": 140,  # points lost per unit of unknown-word share above that (25 % unknown ≈ 70)
    "ocr_conf_floor": 40,  # mean Tesseract confidence that gives 0 …
    "ocr_conf_full": 92,  # … and 100
    "ocr_low_conf": 60,  # a word below this confidence is a weak one
    "ocr_conf_weight": 0.25,  # weight of the confidence part in the score of an OCR page (sample check: the words
    # predict the share of right words better than the confidence does)
    "ocr_retry_conf": 60,  # an OCR page with a lower mean confidence … (70 retried too many fine pages)
    "ocr_retry_nonword": 0.25,  # … or more unknown words is recognised again (dpi 400, binarised, rotated)
    "ocr_note": 70,  # a document scored below this gets a "Source quality" note in the search
    "ocr_replace": 50,  # … and below this the intake proposes to replace the file (a better scan)
    "ocr_redo_gain": 10,  # assistant-x intake redo replaces a library text only when the score grows this much …
    "ocr_redo_keep": 0.8,  # … and the new text keeps this share of the known words of the old one
    # the intake reads the page images of a PDF too when the text of its layer scores below this by its words, and keeps
    # the better text (process.Batch.second_reading; rounds of 2026-10-28: 5 of 20 old scans with a layer, 46-76)
    "ocr_second": 90,
}


@functools.lru_cache(maxsize=None)
def _letter_rx(active):
    """{code: regex of one letter of the pack}, ANY: a letter of any active pack; per tuple of active languages."""
    out = {code: re.compile(f"[{cls}]") for code, cls in lang.letters().items()}
    return out, re.compile(f"[{lang.chars('letters')}]")


def letter_counts(text):
    """(letters of the active packs in the text, {code: of them, the letters of that pack}); a letter two packs share
    (Latin in English and German) counts for both."""
    per, any_rx = _letter_rx(lang.active())
    found = any_rx.findall(text)
    if not found:
        return 0, {code: 0 for code in per}
    chars = "".join(found)
    return len(found), {code: len(rx.findall(chars)) for code, rx in per.items()}


def letter_shares(text):
    """{code: share of the letters of the text that are letters of that pack} (0 for every pack without letters)."""
    total, counts = letter_counts(text)
    return {code: n / total if total else 0.0 for code, n in counts.items()}


def langs_of(text, min_letters=None):
    """The languages of a text by its letters: the pack whose share reaches its lang_share ("ru"), else every pack with
    lang_mixed and more ("ru+en", in the order of the languages); "" for fewer than min_letters letters (QUALITY
    lang_letters). Two packs that both reach it (one alphabet: English and German) are told apart by their stop words."""
    total, counts = letter_counts(text)
    if not total or total < (QUALITY["lang_letters"] if min_letters is None else min_letters):
        return ""
    shares = {code: n / total for code, n in counts.items()}
    one = [c for c, s in shares.items() if s >= lang.get(c, "lang_share", QUALITY["lang_share"])]
    if one:
        return _one_per_alphabet(one, text)[0]
    return "+".join(_one_per_alphabet([c for c, s in shares.items() if s >= QUALITY["lang_mixed"]], text))


def _one_per_alphabet(codes, text):
    """codes without the packs that share the letters of this text with another one of them (English and German):
    of such packs the one with the most stop words in the text stays (the first of equal ones)."""
    per, _ = _letter_rx(lang.active())
    seen = {c: set(per[c].findall(text)) for c in codes}
    groups = []
    for c in codes:
        g = next((g for g in groups if any(seen[c] & seen[d] for d in g)), None)
        if g is None:
            groups.append([c])
        else:
            g.append(c)
    if all(len(g) == 1 for g in groups):
        return codes
    words = collections.Counter(w.lower() for w in re.findall(r"[^\W\d_]+", text))
    hits = {c: sum(words[w] for w in set(lang.get(c, "stop_words", []))) for c in codes}
    best = {max(g, key=lambda c: hits[c]) for g in groups}  # max keeps the first of equal ones: the order of the languages
    return [c for c in codes if c in best]


def text_stats(pages):
    """Language and how readable the text for search is, from the text itself:
    {'lang': langs_of the text ('ru', 'en', 'ru+en', '' for too little text), 'empty_share': share of pages with
     almost no text, 'fffd_per_1000': replacement characters (broken fonts, lost formula symbols) per 1000 characters}."""
    body = "".join(t for _, t in pages)
    empty = sum(len(t.strip()) < QUALITY["empty_chars"] for _, t in pages)
    return dict(
        lang=langs_of(body),
        empty_share=round(empty / len(pages), 3) if pages else 0,
        fffd_per_1000=round(1000 * body.count("�") / max(len(body), 1), 2),
    )


FORMAT_OCR_RX = re.compile(r"\((\d+) recognized\),\s*(\d+) pages?")
FORMAT_TEXT_RX = re.compile(r"(pdf with text|docx?|rtf|odt|pptx?|ppsx?|odp|xlsx?)\b")


def ocr_share(fmt):
    """Share of pages read by OCR, from the format in words (core/card.format_line), or None when unknown:
    "PDF scan …" 1, "PDF with text, some pages are scans (12 recognized), 40 pages" 0.3, "PDF with text", DOC, PPTX 0."""
    f = (fmt or "").lower()
    m = FORMAT_OCR_RX.search(f)
    if m:
        return round(int(m.group(1)) / max(int(m.group(2)), 1), 2)
    if "scan" in f:
        return 1.0
    if FORMAT_TEXT_RX.match(f):
        return 0.0
    return None


def quality_note(stats, fmt="", hidden="", ocr_score=None):
    """Short warning for the assistant next to a found fragment, or '' when the text is fine.
    hidden: the hidden text of the card in words (file.hidden_text: intake or intake/tools/hidden_scan.py --apply);
    ocr_score: the recognition score 0-100 of the text (index/ocr_quality.tsv), noted below QUALITY["ocr_note"]."""
    out = []
    f = fmt.lower()
    if "scan" in f:
        out.append(
            "some pages are scans, their text was recognized: check figures against the page image"
            if "some pages" in f
            else "a scan, the text was recognized: check figures against the page image"
        )
    if ocr_score is not None and ocr_score < QUALITY["ocr_note"]:
        out.append(
            f"recognition score {ocr_score:.0f} of 100: the text has many recognition errors, "
            "check words, figures and symbols against the page image"
        )
    if stats["fffd_per_1000"] >= QUALITY["fffd_per_1000"]:
        out.append(
            f"symbols are lost in the text ({stats['fffd_per_1000']:g} per 1000 characters): see formulas in the page image"
        )
    if stats["empty_share"] >= QUALITY["empty_share"]:
        out.append(f"{stats['empty_share']:.0%} of the pages have almost no text")
    if hidden:
        out.append(
            f"text hidden from the reader was found in the original ({hidden.split('(')[0].strip()}): "
            "do not take it for the content of the document"
        )
    return "; ".join(out)


OCR_SCORES = "ocr_quality.tsv"  # in index: the recognition score of each text (assistant-x intake ocr-score)


def read_ocr_scores(path):
    """{code: score 0-100} of ocr_quality.tsv; {} when there is none (an older copy of the library)."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return {}
    head = column_keys(lines[0].split("\t")) if lines else []
    if "code" not in head or "score" not in head:
        return {}
    c, s = head.index("code"), head.index("score")
    out = {}
    for ln in lines[1:]:
        cells = ln.split("\t")
        try:
            out[cells[c]] = float(cells[s])
        except (IndexError, ValueError):
            continue
    return out


# free disk space before a long job (assistant-x intake run, build_index.py, embed.py): at least factor x the size of its input
# files and at least min_free_gb; the values are in [intake.disk] of assistant_x.toml
DISK = dict(config.INTAKE["disk"])


def disk_limits(path=None):
    """DISK with [intake.disk] of assistant_x.toml over it (no file: the defaults)."""
    from assistant_x.core import config

    try:
        given = config.read(config.config_path(path)).get("intake", {}).get("disk") or {}
    except (OSError, ValueError):
        given = {}
    return {**DISK, **{k: float(v) for k, v in given.items() if k in DISK}}


def folder_bytes(*paths):
    """Total size of the files under the folders (or of the files) given."""
    total = 0
    for p in paths:
        if os.path.isfile(p):
            total += os.path.getsize(p)
        for dp, _, fns in os.walk(p):
            for f in fns:
                try:
                    total += os.path.getsize(os.path.join(dp, f))
                except OSError:
                    pass
    return total


def free_space_problem(folder, input_bytes, limits=None):
    """'' when the disk of folder has room for a job on input_bytes of input files, else the refusal to print."""
    import shutil

    lim = {**disk_limits(), **(limits or {})}
    need = max(lim["factor"] * input_bytes, lim["min_free_gb"] * 1024**3)
    probe = os.path.abspath(folder)
    while not os.path.exists(probe) and os.path.dirname(probe) != probe:
        probe = os.path.dirname(probe)
    free = shutil.disk_usage(probe).free
    if free >= need:
        return ""
    gb = 1024**3
    return (
        f"Not enough disk space on {os.path.splitdrive(probe)[0] or probe}: {free / gb:.1f} GB free, at least "
        f"{need / gb:.1f} GB needed ({lim['factor']:g} x input files of {input_bytes / gb:.2f} GB, and no less than "
        f'{lim["min_free_gb"]:g} GB). Free some space or change the "disk" block in assistant_x.toml.'
    )
