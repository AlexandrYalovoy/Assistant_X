# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""Recognition score of a page and a document, 0-100, from the words of the text and (for an OCR page) the word
confidence of Tesseract. 100: every word is known and Tesseract was sure; below 50: mostly garbage.

Words. The text without markup is cut at spaces. A piece of symbols only is junk when it holds a sign OCR makes of
specks and lines (| \ { } ~ ^ ¦) or three different signs ("=:>"); a lone sign or a leader line ("....." , "———") is
neutral. In a piece with letters each token is: neutral with a digit (numbers, 10704-91, M100, designations of
standards), with one letter, in another script (Greek), or a two-letter capital abbreviation; an error when it mixes
the letters of two language packs (Latin and Cyrillic), holds a lost symbol U+FFFD, repeats a letter three times
("AARAAA"), is a pair of the same capital ("XX" as a background pattern; Roman II and XX aside), or a two-letter word
outside the short list of the pack of its letters (TWO: lang/<code>/ocr.json; crumbs like "iW Wl"); otherwise known
when its lower-case form
(folded: core/lang.fold)
occurs in at least VOCAB_DF documents of the library (index/texts, parts of one document count once; a vocabulary of
fewer than MIN_VOCAB_WORDS forms, as in a new library, is not used: the shape of the words decides), or, for a long
word, its stem does, or each part of a hyphenated word does. One-letter tokens past SHORT_FREE of all tokens are
errors too (specks read as letters). nonword = (unknown words + junk pieces + extra one-letter tokens) / counted.
The weights were checked on 20 pages looked at by eye (debug/ocr_quality/review.md, assistant-x intake sample).

Score of a page (thresholds in common.QUALITY):
    words  = 100 - ocr_words_slope * (nonword - ocr_words_free), within 0..100
    conf   = 100 * (mean confidence - ocr_conf_floor) / (ocr_conf_full - ocr_conf_floor), within 0..100,
             minus 50 * share of words with confidence below ocr_low_conf
    score  = words for a text page; ocr_conf_weight * conf + (1 - ocr_conf_weight) * words for an OCR page
A document: the mean of its page scores weighted by the counted words of the page; no counted words, no score.

The vocabulary is cached in .assistant_x/ocr_vocab.txt of the workspace; rebuilt by `assistant-x intake vocab` (or when the file is missing).
"""

import collections, functools, glob, os, re

from assistant_x.core import lang
from assistant_x.core.common import QUALITY, stemmer_for
from assistant_x.core.formats import OCR_HEADER, PAGE_SPLIT_RX, column_keys

from assistant_x.core import workspace

VOCAB_DF = 3  # documents a word form must occur in to be known
# a vocabulary smaller than this (a new or small library) cannot tell an unknown word from a recognition error: the
# words are then judged by their shape only (mixed scripts, lost symbols, letter triples, crumbs), not by the vocabulary
MIN_VOCAB_WORDS = 1000
# a seed vocabulary of the packs this big (forms and stems of an open dictionary, lang/<code>/vocab.txt) judges the words
# of a new library by itself: its first batch is scored as a later one (audit 6, M-015)
SEED_FULL = 20000
GLUED = 16  # letters of an unknown token without a hyphen from which it is checked for words glued together
SPLIT_MIN = 3  # letters of a word of a glued token at least
# an unknown word when only the seed judges (a new library): as much of an error as this. Measured on the 79 texts of
# a real library: the seed alone 85.8 on average with a full error, the vocabulary of the library 91.2, the shape of the
# words alone (0.1) 96.0; with half an error the seed gives about the score of the library
SEED_ONLY = 0.5
REPEAT = re.compile(r"([^\W\d_]{3,})\1", re.I)  # a piece said twice inside a token ("gasgas"): a line read twice
DOUBLED = 0.4  # the share of repeated word 3-grams of a page from which its text is doubled (page flag "doubled")
REPEAT_MIN = 30  # words a page needs for its share of repeated 3-grams
GARBLED = 0.25  # the share of unknown words of a page from which the page is garbled (page flag, search weight)
STEM_MIN = 6  # a word this long is also known by its stem
LOST = "\ufffd"
HY = "-\u2010'\u2019"  # hyphens and apostrophes inside a word
MARK = PAGE_SPLIT_RX
MARKUP = re.compile(r"<!--.*?-->|<[^>\n]{1,40}>|\]\([^)\s]*\)|\\(?=[^\w\s])|~~|[*_#`]", re.S)
TABLE_ROW = re.compile(r"(?m)^\s*\|.*$")
HYPHEN_BREAK = re.compile(r"(?<=[^\W\d_])[-\u2010\u00ad]\s*\n\s*(?=[^\W\d_])")
TOKEN = re.compile(rf"[\w{LOST}]+(?:[{HY}][\w{LOST}]+)*")
# the lower-case letters of every active pack, ordered by their first letter (Latin before Cyrillic) on purpose: the
# hyphen of HY after the last letter makes a range of the class, as it always did (the measured behaviour of the score)
LOWER = "".join(sorted(lang.letters("lower").values(), key=lambda cls: cls[0]))
OTHER = re.compile(rf"[^{LOWER}{HY}]", re.I)
PACK_LETTER = re.compile(f"[{lang.chars('lower')}]", re.I)  # a letter of any active pack
SCRIPT = {code: re.compile(f"[{cls}]+", re.I) for code, cls in lang.letters("lower").items()}  # the letters of a pack
BROKEN_FONT = re.compile(r"[\u0180-\u02af]")  # Latin Extended-B and IPA: a font read with a wrong code table
TRIPLE = re.compile(r"([^\W\d_])\1\1", re.I)
JUNK_SIGNS = set("|\\{}~^¦¬¤")
MATH_SIGNS = set("+-−/±=<>≤≥×·*°%()[].,:;'\"«»–—…")
LEADER = re.compile(r"[.…·_\-\u2010\u2013\u2014=*]+")
# the two-letter words and units of every pack (English ones with the chemical elements); other lower-case pairs are
# crumbs
TWO = {code: set(lang.get(code, "two_letter_words", [])) for code in lang.active()}
NOT_TRIPLE = set(lang.words("not_triple"))  # a company form and a web address are no garbage
SHORT_FREE = 0.2  # share of one-letter tokens a text has anyway (prepositions, initials, variables); more is crumbs


def vocab_file():
    """The vocabulary file of the workspace in use (resolved at the call: a worker or a test may change it)."""
    return str(workspace.current().ocr_vocab)


def texts_dir():
    """The library texts of the workspace in use."""
    return str(workspace.current().texts)


def clean(text):
    """Text without Markdown and HTML markup (pipes of table rows too); a word broken at the line end is joined back."""
    text = TABLE_ROW.sub(lambda m: m.group(0).replace("|", " "), text.replace("<br>", "\n"))
    return HYPHEN_BREAK.sub("", MARKUP.sub(" ", text))


def script(tok):
    """The first active pack that has every letter of the token its packs know ("" for a token of letters of no pack),
    or None when no single pack has them all: the token mixes scripts (a Latin word with a Cyrillic e in it)."""
    known = "".join(PACK_LETTER.findall(tok))
    if not known:
        return ""
    return next((code for code, rx in SCRIPT.items() if rx.fullmatch(known)), None)


def two_known(tok):
    """A two-letter token is a word or a unit of a pack whose letters it has (its list in lang/<code>/ocr.json; two
    packs of one alphabet, English and German: either list); letters of no pack: the list of the first language."""
    known = "".join(PACK_LETTER.findall(tok))
    codes = [code for code, rx in SCRIPT.items() if known and rx.fullmatch(known)] or [next(iter(TWO))]
    return any(norm(tok) in TWO[code] for code in codes)


def kind(tok):
    """'num' | 'short' | 'other' | 'abbr' | 'broken' | 'mixed' | 'junk' | '<code>2' (a two-letter word of the pack of
    that language: 'en2', 'ru2') | 'word' of a token."""
    if LOST in tok or BROKEN_FONT.search(tok):  # a broken font encoding: the word is lost
        return "broken" if len(tok) > 1 else "short"  # a lone lost symbol is a formula sign
    if any(c.isdigit() for c in tok):
        return "num"
    letters = re.sub(f"[{HY}]", "", tok)
    if len(letters) < 2:
        return "short"
    if OTHER.search(tok) or "_" in tok:
        return "other"
    code = script(tok)
    if code is None:
        return "mixed"
    if TRIPLE.search(tok) and tok.lower() not in NOT_TRIPLE:
        return "junk"
    if len(letters) == 2:
        if letters.isupper():
            # a pair of the same capital: a pattern, not an abbreviation; Roman II and XX are numbers
            return "junk" if letters[0] == letters[1] and letters not in ("II", "XX") else "abbr"
        return (code or next(iter(TWO))) + "2"  # letters of no pack: the list of the first language
    return "word"


def norm(w):
    return lang.fold(w.lower())


def doc_words(text):
    """Set of the normalised words of a text (for the vocabulary): whole words and the parts of hyphenated ones."""
    out = set()
    for m in TOKEN.finditer(clean(text)):
        t = m.group(0)
        if kind(t) == "word":
            w = norm(t)
            out.add(w)
            if re.search(f"[{HY}]", w):
                out.update(p for p in re.split(f"[{HY}]", w) if len(p) >= 2)
    return out


@functools.lru_cache(maxsize=300_000)
def stem(w):
    """The stem of a normalised word by the stemmer of the pack whose letters it has (core/common.stemmer_for)."""
    return stemmer_for(w).stemWord(w)


def group_of(code):
    """Parts of one document (N-00101-21) count as the document N-00101: copies of one scan are not three documents."""
    return re.sub(r"^([A-Z]-\d{5})-\d{2,3}$", r"\1", code)


def build_vocab(texts=None, out=None, df_min=VOCAB_DF):
    """Count the documents of every word form of the texts (default: the library texts) and write the forms seen in
    df_min or more documents to out (default: the vocabulary of the workspace). Returns the count."""
    texts, out = texts or texts_dir(), out or vocab_file()
    groups = collections.defaultdict(set)
    files = sorted(p for p in glob.glob(os.path.join(texts, "*.md")) if not os.path.basename(p).startswith("_"))
    for p in files:
        with open(p, encoding="utf-8") as f:
            groups[group_of(os.path.basename(p)[:-3])] |= doc_words(f.read())
    df = collections.Counter()
    for words in groups.values():
        df.update(words)
    known = sorted(w for w, n in df.items() if n >= df_min)
    sdf = collections.Counter()
    for words in groups.values():
        sdf.update({stem(w) for w in words if len(w) >= STEM_MIN})
    stems = sorted(s for s, n in sdf.items() if n >= df_min)
    tmp = out + ".tmp"
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(
            f"# vocabulary of the recognition score: {len(groups)} documents, a word in {df_min}+ documents "
            f"(ocr_score.py; rebuild: assistant-x intake vocab)\n"
        )
        f.writelines(w + "\n" for w in known)
        f.write("# stems\n")
        f.writelines("~" + s + "\n" for s in stems)
    os.replace(tmp, out)
    _read_vocab.cache_clear()
    return len(known), len(stems), len(groups)


def load_vocab(path=None):
    """(set of word forms, set of stems) of a vocabulary file (default: the one of the workspace); the file is built
    first when missing."""
    return _read_vocab(str(path or vocab_file()))


@functools.lru_cache(maxsize=2)
def _read_vocab(path):
    if not os.path.exists(path):
        build_vocab(out=path)
    words, stems = set(), set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line[0] == "#":
                continue
            (stems.add(line[1:]) if line[0] == "~" else words.add(line))
    return frozenset(words), frozenset(stems)


@functools.lru_cache(maxsize=1)
def seed():
    """(word forms, stems) of the seed vocabularies of the active packs (lang/<code>/vocab.txt): known under the
    vocabulary of the library. They count only once the library vocabulary is big enough (MIN_VOCAB_WORDS): a seed
    alone would call the terms of a new library unknown."""
    words = frozenset(norm(w) for code in lang.active() for w in lang.vocab(code))
    stems = frozenset(s for code in lang.active() for s in lang.vocab_stems(code))
    return words, stems | frozenset(stem(w) for w in words if len(w) >= STEM_MIN)


def judged_by_vocab(vocab, tok=None):
    """Are the words (or the word tok) judged by the vocabulary: the library's is big enough; or, for a word, the seed
    of every active pack whose letters it has is (a German word of Latin letters is not judged by an English seed)."""
    if len(vocab[0]) >= MIN_VOCAB_WORDS:
        return True
    letters = "".join(PACK_LETTER.findall(tok)) if tok else ""
    codes = [code for code, rx in SCRIPT.items() if letters and rx.fullmatch(letters)] if tok else list(SCRIPT)
    return bool(codes) and all(code in seeded() for code in codes)


@functools.lru_cache(maxsize=1)
def seeded():
    """The active packs whose seed vocabulary is big enough to judge words by itself (SEED_FULL)."""
    return frozenset(c for c in lang.active() if len(lang.vocab(c)) + len(lang.vocab_stems(c)) >= SEED_FULL)


def glued(t, long_ones=True, vocab=None):
    """A token that is words glued or read twice: a piece repeated in it, or (long_ones: where the words are judged by
    a vocabulary — a German compound is one word) GLUED letters and more without a hyphen that split into known words
    ("installationofgasdrying"); a long term the vocabulary does not split stays a word."""
    if REPEAT.search(t):
        return True
    w = norm(t)
    if not long_ones or len(w) < GLUED or re.search(f"[{HY}]", w):
        return False
    vocab = vocab or (frozenset(), frozenset())

    @functools.lru_cache(maxsize=None)
    def splits(i, parts):
        if i == len(w):
            return parts >= 2
        return parts < 4 and any(known(w[i:j], vocab) and splits(j, parts + 1) for j in range(len(w), i + SPLIT_MIN - 1, -1))

    return splits(0, 0)


SHORT_WORDS = None  # the stop words of one or two letters (prepositions, conjunctions): the glue of a glued phrase
# the cost of a piece of a glued token (segment): a word form of the vocabulary, a stop word of one or two letters, a word
# known by its stem only (a broken ending reads as a word by its stem: it costs more), a form of three letters
COST_FORM, COST_SHORT, COST_STEM, COST_THREE = 1.0, 1.6, 2.5, 3.0  # a form of three letters: rarely glued
SPLIT_SHORT = 0.25  # the share of pieces of SPLIT_MIN letters (stop words aside) a split may have
LINKS = frozenset(x for code in lang.active() for x in lang.get(code, "compound_links", []))  # no words of their own


def segment(t, vocab):
    """The words a glued token is made of (a table cell whose spaces OCR lost), each piece a word form of the
    vocabulary, a stop word of one or two letters (not a linking vowel of a compound, compound_links of the packs) or a
    longer word known by its stem; the cheapest split (COST_*), of two pieces at least. None when the token is no GLUED
    letters long, is a word itself or does not split so. The pieces keep the case of the token."""
    global SHORT_WORDS
    w = norm(t)
    if len(w) < GLUED or len(w) != len(t) or re.search(f"[{HY}]", w) or known(w, vocab):
        return None
    if SHORT_WORDS is None:
        from assistant_x.core.common import STOP

        SHORT_WORDS = frozenset(x for x in STOP if len(x) <= 2) - LINKS
    forms = (vocab[0], seed()[0])
    best = [None] * (len(w) + 1)
    best[0] = (0.0, ())
    for i in range(len(w)):
        if best[i] is None:
            continue
        for j in range(i + 1, min(len(w), i + 40) + 1):
            piece = w[i:j]
            if len(piece) >= SPLIT_MIN and (piece in forms[0] or piece in forms[1]):
                cost = COST_FORM if len(piece) > SPLIT_MIN else COST_THREE
            elif piece in SHORT_WORDS:
                cost = COST_SHORT
            elif len(piece) >= STEM_MIN and known(piece, vocab):
                cost = COST_STEM
            else:
                continue
            cand = (best[i][0] + cost, best[i][1] + (j,))
            if best[j] is None or cand[0] < best[j][0]:
                best[j] = cand
    if best[-1] is None or len(best[-1][1]) < 2:
        return None
    cuts = (0, *best[-1][1])
    pieces = [t[a:b] for a, b in zip(cuts, cuts[1:])]
    # a split into many words of three letters is a token cut anyhow (a word broken at the line end in it): left as it is
    if sum(len(p) == SPLIT_MIN and norm(p) not in SHORT_WORDS for p in pieces) > SPLIT_SHORT * len(pieces):
        return None
    return pieces


def known(w, vocab):
    words, stems = vocab
    sw, ss = seed()
    if w in words or w in sw:
        return True
    if len(w) >= STEM_MIN and (stem(w) in stems or stem(w) in ss):
        return True
    parts = [p for p in re.split(f"[{HY}]", w) if p]
    return len(parts) > 1 and all(
        len(p) < 2 or p in words or p in sw or (len(p) >= STEM_MIN and stem(p) in stems | ss) for p in parts
    )


def word_counts(text, vocab=None):
    """(counted words, unknown words and junk pieces, examples of them) of a text."""
    vocab = vocab or load_vocab()
    by_library = len(vocab[0]) >= MIN_VOCAB_WORDS
    n = bad = tokens = short = 0
    ex = []

    def error(what, weight=1):
        nonlocal bad
        bad += weight
        if len(ex) < 8:
            ex.append(what)

    for piece in clean(text).split():
        toks = TOKEN.findall(piece)
        if not toks:
            signs = set(piece)
            if (
                len(piece) > 1
                and not LEADER.fullmatch(piece)
                and (signs & JUNK_SIGNS or len(signs - MATH_SIGNS) + (len(signs) >= 3) >= 2)
            ):
                n += 1
                error(piece)
            continue
        for t in toks:
            k = kind(t)
            tokens += 1
            short += k == "short"
            if k in ("num", "short", "other", "abbr"):
                continue
            n += 1
            if k in ("mixed", "broken", "junk") or (k[:-1] in TWO and k[-1] == "2" and not two_known(t)):
                error(t)
            elif k == "word" and not known(norm(t), vocab):
                judged = by_library or judged_by_vocab(vocab, t)
                if by_library or glued(t, judged, vocab):
                    error(t)
                elif judged:  # the seed alone does not know the terms of a field: half an error (calibrated, M-015)
                    error(t, SEED_ONLY)
    crumbs = int(short - SHORT_FREE * tokens)  # one-letter tokens past the usual share: specks read as letters
    if crumbs > 0:
        n += crumbs
        bad += crumbs
    return n, bad, ex


def words_score(nonword):
    q = QUALITY
    return max(0.0, min(100.0, 100 - q["ocr_words_slope"] * (nonword - q["ocr_words_free"])))


def conf_score(mean_conf, low_share):
    q = QUALITY
    s = 100 * (mean_conf - q["ocr_conf_floor"]) / (q["ocr_conf_full"] - q["ocr_conf_floor"])
    return max(0.0, min(100.0, s) - 50 * low_share)


def page_score(words, bad, conf=None, low=None):
    """Score 0-100 of a page, or None when it has no counted words and no confidence."""
    if not words and conf is None:
        return None
    w = words_score(bad / words) if words else None
    if conf is None:
        return round(w, 1)
    c = conf_score(conf, low or 0.0)
    if w is None:
        return round(c, 1)
    k = QUALITY["ocr_conf_weight"]
    return round(k * c + (1 - k) * w, 1)


def pages_of(md):
    parts = MARK.split(md)
    return [(int(parts[i]), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def doc_score(page_rows):
    """Weighted mean of [(score, counted words)]; None when nothing is counted."""
    rows = [(s, max(w, 1)) for s, w in page_rows if s is not None]
    total = sum(w for _, w in rows)
    return round(sum(s * w for s, w in rows) / total, 1) if total else None


A4_AREA = 595 * 842  # points
DRAWING_WORDS = 150


def is_drawing(pages, page_area, words=None):
    """A drawing sheet: 1-2 pages bigger than A3 with little text. Its score says nothing of the
    recognition: it gets one sparse-text pass (psm 11), no retries, no redo and no "to update" line."""
    return bool(pages) and pages <= 2 and page_area >= 1.9 * A4_AREA and (words is None or words < DRAWING_WORDS)


def pdf_is_drawing(path, words=None):
    """is_drawing for a PDF file (its first page); False when it cannot be opened."""
    try:
        import pymupdf

        with pymupdf.open(path) as d:
            r = d[0].rect if d.page_count else None
            return bool(r) and is_drawing(d.page_count, r.width * r.height, words)
    except Exception:  # noqa: BLE001 — a broken file is not a drawing
        return False


def repeated(text):
    """Share of the word 3-grams of a page that occur twice or more in it (normalised words of two characters and more,
    table rows aside); 0.0 for a page of fewer than REPEAT_MIN words. A text extracted twice (a scan's visible layer
    and an invisible copy of its recognition) is near 1.0."""
    body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("|"))
    ws = [w for w in re.findall(r"[^\W_]+", MARKUP.sub(" ", body).lower()) if len(w) >= 2]
    if len(ws) < REPEAT_MIN:
        return 0.0
    grams = list(zip(ws, ws[1:], ws[2:]))
    count = collections.Counter(grams)
    return round(sum(count[g] >= 2 for g in grams) / len(grams), 3)


def known_distinct(md, vocab=None):
    """Distinct known words of each page of a text, summed over the pages. A text extracted twice (a scan's visible layer
    and an invisible copy of its recognition) counts each of its words once, as its clean recognition does."""
    vocab = vocab or load_vocab()
    total = 0
    for _, text in pages_of(md) or [(1, md)]:
        seen = set()
        for m in TOKEN.finditer(clean(text)):
            t = m.group(0)
            if kind(t) == "word" and (w := norm(t)) not in seen and known(w, vocab):
                seen.add(w)
        total += len(seen)
    return total


def score_text(md, conf=None, vocab=None):
    """{'score', 'words', 'nonword', 'pages': [{page, words, bad, score, repeated, ...}]} of a Markdown text with page
    marks.
    conf: {page: {'conf': mean, 'low': share}} from the OCR of the intake (absent: words only)."""
    vocab = vocab or load_vocab()
    pages, n_all, bad_all = [], 0, 0
    for no, text in pages_of(md) or [(1, md)]:
        n, bad, ex = word_counts(text, vocab)
        c = {k: v for k, v in ((conf or {}).get(no) or {}).items() if k in ("conf", "low", "tokens", "variant", "rotate")}
        if c.get("conf") is None or c.get("tokens", n) < 0.3 * n:  # OCR read only a stamp or a picture of the page
            c.pop("conf", None)
        s = page_score(n, bad, c.get("conf"), c.get("low"))
        pages.append({"page": no, "words": n, "bad": bad, "score": s, "examples": ex, "repeated": repeated(text), **c})
        n_all += n
        bad_all += bad
    return {
        "score": doc_score([(p["score"], p["words"]) for p in pages]),
        "words": n_all,
        "nonword": round(bad_all / n_all, 3) if n_all else None,
        "pages": pages,
    }


# ---------- index/ocr_quality.tsv: the score of every library text (read by search/build_index.py) ----------
TSV_NAME = "ocr_quality.tsv"
TSV_HEAD = OCR_HEADER


def row_of(code, res, source, date):
    """A row of ocr_quality.tsv from score_text(); source: "text" (the library text, words only), "intake" (at intake,
    with the Tesseract confidence of OCR pages), «redo» (assistant-x intake redo)."""
    lim = QUALITY["ocr_note"]
    scored = [p for p in res["pages"] if p["score"] is not None and p["words"] >= 20]
    worst = sorted(scored, key=lambda p: p["score"])[:5]
    return {
        "code": code,
        "score": "" if res["score"] is None else f"{res['score']:.1f}",
        "nonword": "" if res["nonword"] is None else f"{res['nonword']:.3f}",
        "words": str(res["words"]),
        "pages": str(len(res["pages"])),
        "pages_below_threshold": str(sum(p["score"] < lim for p in scored)),
        "worst_pages": ", ".join(f"{p['page']}:{p['score']:.0f}" for p in worst if p["score"] < 95),
        "source": source,
        "date": date,
    }


def read_tsv(path):
    """{code: row} of ocr_quality.tsv; {} when there is none."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    head = column_keys(lines[0].split("\t")) if lines else TSV_HEAD
    return {r["code"]: r for r in (dict(zip(head, ln.split("\t"))) for ln in lines[1:] if ln.strip())}


def write_tsv(path, rows):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(TSV_HEAD) + "\n")
        for code in sorted(rows):
            f.write("\t".join(str(rows[code].get(k, "")).replace("\t", " ") for k in TSV_HEAD) + "\n")
    os.replace(tmp, path)


def _score_file(path):
    with open(path, encoding="utf-8") as f:
        return os.path.basename(path)[:-3], score_text(f.read())


def score_library(texts=None, codes=None, workers=8):
    """{code: score_text()} of the library texts (all, or the given codes; default folder: the workspace's), words only."""
    from concurrent.futures import ProcessPoolExecutor

    files = sorted(
        p
        for p in glob.glob(os.path.join(texts or texts_dir(), "*.md"))
        if not os.path.basename(p).startswith("_") and (codes is None or os.path.basename(p)[:-3] in codes)
    )
    load_vocab()
    if workers <= 1 or len(files) < 20:
        return dict(map(_score_file, files))
    with ProcessPoolExecutor(workers) as ex:
        return dict(ex.map(_score_file, files, chunksize=8))


if __name__ == "__main__":
    print(build_vocab())
