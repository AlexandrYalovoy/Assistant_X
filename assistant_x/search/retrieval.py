# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hybrid search over library.sqlite: words (FTS5 + stemming + synonyms), meaning (vectors), reranking.
The fragments are the pages of the texts, the cards and the units of journal issues (chunks.kind): a designation named
in the question puts the card of its document first, a fragment in a chapter of the contents (toc) whose title matches
the question is raised, the terms of the cards (an abbreviation and its expansion, in every language) join the
synonyms. The word index has two columns (base schema 3): stem (word stems, synonyms) and exact (whole tokens, a
designation one token: common.exact_tokens); the designations the question names, its phrases in quotes and its
codes ('1510-84', '12X18H10T') are looked for in exact as well. A result is the exact text of its page (the table
pages), never the lead its fragment is searched by.
Usage: assistant-x search "question" [--k 10] [--section Standards] [--code L-00015] [--doc-type standard] [--lang ru]
       [--no-dense] [--rerank | --no-rerank]"""

import argparse, difflib, json, os, re, threading
from assistant_x.core import card as C
from assistant_x.core import debuglog, lang
from assistant_x.core.common import (
    load_config,
    connect,
    current_db,
    has_column,
    meta,
    vectors_path,
    vector_gap,
    tokens,
    exact_tokens,
    skeleton,
    model_text,
    BASE_SCHEMA,
    CHUNK_TEXT_SQL,
    PAGES_JOIN_SQL,
    SEARCH_TEXT_SQL,
    QUALITY,
)
from assistant_x.core import config as settings
from assistant_x.core.formats import escape_marker, page_marker, place_path
from assistant_x.core.txn import lp
from assistant_x.search.bookmap import Maps

RRF_K = 60
# a question for every place: "all", "list", "where else", "every place" in the document languages
ALL_PLACES_RX = re.compile(lang.alt("all_places_rx"), re.I)
CODE_RX = re.compile(r"^[A-Z]-\d{1,6}(?:-\d{1,3})?$")  # N-00001, E-00006-02
# the weight of the fragments of each kind in the fusion: a card says what a document is about but cites no page
KIND_WEIGHT = {"text": 1.0, "card": 0.7, "card_q": 0.85, "unit": 1.0}
GARBLED_WEIGHT = 0.7  # a page whose recognition is garbled (page flag): its fragments weigh less in the answer
MAX_CARDS = 2  # cards in one answer at most ([search] max_cards): the rest of the k are pages (audit 6, M-030)
# the fragments of a card ('card' per language, 'card_q' its questions) are one result of kind 'card'
SHOWN_KIND = {"card_q": "card"}
# a designation named in the question puts the card of its document first: after the reranking, by place, not by a
# score (a score added to the fused one would also flatten the normalized fused scores of everything else)
TOC_BOOST = 0.25  # a fragment in a chapter whose title shares words of the question (toc_match)
TOC_MIN_SHARED, TOC_MIN_SHARE = 2, 0.4  # toc_match: two stems of the question, or 40 % of them
POOL = 50  # the candidates before the merging of pages and documents (and the reranking): max(POOL, 4 k)
MAX_PER_DOC = 3  # pages of one document in an answer, unless the other documents leave places free (M-080)
RERANK_WEIGHT = 1.0  # final = fused / max(fused) + weight * sigmoid(logit of the reranker); [search] rerank_weight
RERANK_CHARS = 2000  # what the reranker reads of a fragment at most (it truncates at its max_length anyway)
EXACT_ROWS = 100_000  # a filter letting fewer fragments through: exact search over them, even with a FAISS index
SCORE_STEP = 20_000  # rows scored at once: a block of float32 vectors stays below ~100 MB
MIN_DESIG_KEY = 5  # shorter designations ("API") are no exact match
QUOTED_RX = re.compile(r'["«“]([^"«»“”]{2,300})["»”]')  # a phrase in quotes in a question
DIGIT_RX, LETTER_RX, INNER_RX = re.compile(r"\d"), re.compile(r"[^\W\d_]"), re.compile(r"[-./]")
QUOTE_RATIO = 0.9  # verify_quote: a place this similar to the quote (difflib) is found with small differences
MAX_QUOTE = 2000  # verify_quote: characters of a quote it compares (a longer one would hold a thread of the service)
ELLIPSIS = re.compile(r"…|\.{3,}")  # where a quote was cut: its parts are found in order
CLOSEST_CHARS = 400  # verify_quote: the longest closest place shown
PUNCT = ".,;:!?()[]\"'"  # the punctuation around a word word_diff does not count


DOC_SQL = "d.doc_type, d.personal"
QUALITY_SQL = "d.quality, d.issue"  # warnings about the source: scan, lost symbols, a row of sources_to_update
PAGE_SQL = "p.label, p.ocr_score AS page_score, p.flags AS page_flags"


class OldBase(RuntimeError):
    """A search base of another schema: it is built anew (assistant-x build --full), never read half-way."""


class Library:
    def __init__(self, cfg=None):
        self.cfg = cfg or load_config()
        self._local = threading.local()
        self.syn_profile = load_synonyms(self.cfg.get("synonyms"))
        self.syn = list(self.syn_profile)
        self._embedder = self._reranker = None
        self._init_lock = threading.RLock()  # the MCP server may load models from two threads at once
        # one encode or predict at a time: the MCP server calls the tools from worker threads, and CUDA (and the
        # tokenizers) are not safe for two calls on one model at once
        self._model_lock = threading.Lock()
        # the MCP server loads the model in the background (warm_up) and sets no_wait: until it is ready the search
        # answers by words at once instead of keeping Claude waiting ~10 s (stats["dense_pending"])
        self.no_wait = False
        self.dense_ready = threading.Event()
        self._cuda = None  # is there a video card: found out on the first question that may want reranking
        self._dml = False  # "dml:N" when DirectML runs the models (onnx_models.dml_device), None when not; False: not asked
        # the second MCP server on the PC loads the meaning model on the processor ("cpu"); None: assistant_x.toml decides
        self.device_override = None
        # why the meaning search is off (no model, a model that does not load): the search goes by words and says so
        self.dense_error = None
        self._no_vectors_logged = False
        self._stamp = object()
        self._names = None  # the map of the file names of the library (_by_name)
        self.refresh()

    @property
    def con(self):
        """The connection of this thread: the MCP server calls tools from worker threads, and threads sharing one
        sqlite3 connection get in each other's way. Opened on first use in each thread."""
        con = getattr(self._local, "con", None)
        if con is None or self._local.db != self.cfg["db"]:  # a full rebuild switched to a new file
            if con is not None:
                con.close()  # let the old file go: it is deleted once no thread holds it
            con = connect(self.cfg["db"], readonly=True)  # the search only reads: safe on a flash drive or a share
            # document frequency of words for fts_query; a temp table exists only in the connection that made it
            con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.vocab USING fts5vocab(main, 'chunks_fts', 'row')")
            self._local.con, self._local.db = con, self.cfg["db"]
        return con

    def refresh(self):
        """build_index.py / embed.py ran while Claude keeps this server open: forget what was loaded from the old
        base. Every public method calls it first (search, pages, doc, list_docs, book map): one tiny query per
        call; reloading takes a moment only right after a rebuild. After a full rebuild library.current names
        a new file: the connections of all threads move to it."""
        if self.cfg.get("db_auto"):
            self.cfg["db"] = current_db(self.cfg["index_dir"])
        stamp = (self.cfg["db"], meta(self.con, "updated"))
        if stamp == self._stamp:
            return
        with self._init_lock:
            self._vstate = None  # (vectors, row -> fragment id, FAISS index), replaced as a whole
            self._names = None  # the map of the file names of the library (_by_name), made again when asked
            self._vpath = vectors_path(self.cfg, self.con)
            self._total = self.con.execute("SELECT count(*) FROM chunks").fetchone()[0] or 1
            self._gap = vector_gap(self.con)  # (without a vector, all): counted once per state of the base
            # base schema 3 (the table pages, fragments as offsets, the exact column of the word index): a base of
            # another schema is built anew, it is never read half-way
            if meta(self.con, "base_schema") != BASE_SCHEMA or not has_column(self.con, "chunks", "own_text"):
                raise OldBase(
                    f"The search base {os.path.basename(self.cfg['db'])} is of another version of the program: "
                    "build it anew (assistant-x build --full, then assistant-x embed)."
                )
            from assistant_x.search import models

            # vectors of another model than the one this workspace is set to: the meaning search stays off
            self._model_mismatch = models.model_mismatch(self.cfg, self.con)
            self._load_cards()
            self.maps = Maps(lambda: self.con)  # outline and tables/figures/formulas of each document (bookmap.py)
            self._stamp = stamp

    def _load_cards(self):
        """From the cards of the base: the designations (exact match) and the terms (synonym groups)."""
        self._desig, groups = [], []
        for r in self.con.execute("SELECT code, card FROM docs WHERE coalesce(parent, '') = ''"):
            try:
                doc = json.loads(r["card"] or "{}").get("doc") or {}
            except ValueError:
                continue
            for d in C.all_texts(doc.get("designation")):
                k = C.designation_key(d)
                if len(k) >= MIN_DESIG_KEY and re.search(r"\d", k):
                    self._desig.append((k, r["code"], d))
            for t in doc.get("terms") or []:
                g = [tuple(tokens(x)) for x in C.all_texts(t.get("name")) + ([t["expansion"]] if t.get("expansion") else [])]
                g = list(dict.fromkeys(x for x in g if x))
                if len(g) > 1:
                    groups.append(g)
        self._desig.sort(key=lambda x: -len(x[0]))
        self.syn = self.syn_profile + groups

    def designations_in(self, query):
        """Codes of the documents whose designation the question names (in any language of the card)."""
        return list(dict.fromkeys(code for code, _ in self._named(query)))

    def _named(self, query):
        """[(code, designation)] of the designations of the cards the question names."""
        q = C.designation_key(query)
        out = []
        for k, code, text in self._desig:
            at = q.find(k)
            if at >= 0 and not q[at + len(k) : at + len(k) + 1].isdigit():
                out.append((code, text))
        return out

    def book_map(self, code, page=None):
        """Outline of a document around a page (bookmap.render) on the current state of the base."""
        from assistant_x.search import bookmap

        self.refresh()
        return bookmap.render(self.maps, code.strip().upper(), page)

    # ---------- filters ----------
    def with_parts(self, codes):
        """['E-00006'] -> ['E-00006', 'E-00006-02', ...]: a document is searched together with its parts."""
        codes = list(dict.fromkeys(c.strip().upper() for c in codes))
        q = ",".join("?" * len(codes))
        return codes + [
            r[0] for r in self.con.execute(f"SELECT code FROM docs WHERE parent IN ({q})", codes) if r[0] not in codes
        ]

    SCOPES = ("all", "own", "package", "personal")

    def _filter_sql(self, sections=None, codes=None, year_from=None, year_to=None, doc_types=None, langs=None, scope=None):
        where, args = [], []
        if scope and scope not in self.SCOPES:
            raise ValueError(f"scope {scope!r}: one of {', '.join(self.SCOPES)}")
        if scope in ("own", "package"):  # a document of an installed base package names it in its card
            where.append(f"json_extract(d.card, '$.intake.package') IS {'NULL' if scope == 'own' else 'NOT NULL'}")
        if scope == "personal":
            where.append("d.personal = 1")
        if doc_types:
            where.append(f"d.doc_type IN ({','.join('?' * len(doc_types))})")
            args += [t.strip().lower() for t in doc_types]
        if langs:  # a document in any of these languages
            where.append("(" + " OR ".join("(',' || coalesce(d.lang, '') || ',') LIKE ?" for _ in langs) + ")")
            args += [f"%,{x.strip().lower()},%" for x in langs]
        if sections:  # by the letter of the code: the catalog may name a section "Datasheets and catalogs"
            letters = [section_letter(s, self.cfg) for s in sections]
            where.append(f"substr(d.code, 1, 1) IN ({','.join('?' * len(letters))})")
            args += letters
        if codes:
            codes = self.with_parts(codes)
            where.append(f"d.code IN ({','.join('?' * len(codes))})")
            args += codes
        if year_from:
            where.append("d.year >= ?")
            args.append(year_from)
        if year_to:
            where.append("d.year <= ?")
            args.append(year_to)
        return (" AND " + " AND ".join(where)) if where else "", args

    # ---------- words ----------
    def df(self, stem):
        r = self.con.execute("SELECT doc FROM temp.vocab WHERE term=?", (stem,)).fetchone()
        return r[0] if r else 0

    def exact_terms(self, query):
        """Phrases for the exact column: the designations of the cards the question names (in the spelling of the
        card), its phrases in quotes, and its tokens with a digit and a letter or an inner hyphen, dot or slash
        ('1510-84', '12X18H10T': a Latin look-alike letter matches the Cyrillic one)."""
        out = [tuple(exact_tokens(d)) for _, d in self._named(query)]
        out += [tuple(exact_tokens(m.group(1))) for m in QUOTED_RX.finditer(query)]
        out += [(t,) for t in exact_tokens(query) if DIGIT_RX.search(t) and (LETTER_RX.search(t) or INNER_RX.search(t))]
        return list(dict.fromkeys(t for t in out if t))

    def fts_query(self, query):
        """Stemmed OR-query with synonym phrases added, and (base schema 3) the exact phrases of exact_terms:
        'stem : (…) OR exact : (…)'.
        Words found in more than ~5 % of fragments ('oil', 'calculation') are dropped: they barely change the ranking
        but make SQLite sort hundreds of thousands of matches, so a big library would answer in seconds."""
        toks = tokens(query, drop_stop=True)
        terms = {(t,) for t in toks}
        for group in self.syn:
            if any(_contains(toks, alt) for alt in group):
                terms |= set(group)
        scored = sorted((min(self.df(w) for w in t), t) for t in terms)
        scored = [(d, t) for d, t in scored if d > 0]
        limit = self.cfg.get("common_term_share", 0.05) * self._total
        keep = [t for d, t in scored if d <= limit] or [t for _, t in scored[:2]]
        if len(keep) < 2:
            keep = [t for _, t in scored[:2]]
        stem = " OR ".join(sorted('"' + " ".join(t) + '"' for t in keep))
        exact = " OR ".join('"' + " ".join(t) + '"' for t in self.exact_terms(query))
        return " OR ".join(x for x in (stem and f"stem : ({stem})", exact and f"exact : ({exact})") if x)

    def word_search(self, query, n=200, **flt):
        q = self.fts_query(query)
        if not q:
            return []
        fsql, fargs = self._filter_sql(**flt)
        if not fsql:  # no filters: skip the joins, they double the time on a big library
            return [
                r[0]
                for r in self.con.execute(
                    "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?", [q, n]
                )
            ]
        rows = self.con.execute(
            f"""SELECT c.id FROM chunks_fts f JOIN chunks c ON c.id=f.rowid JOIN docs d ON d.code=c.code
                WHERE chunks_fts MATCH ? {fsql} ORDER BY bm25(chunks_fts) LIMIT ?""",
            [q, *fargs, n],
        ).fetchall()
        return [r[0] for r in rows]

    # ---------- meaning ----------
    def has_vectors(self):
        return os.path.exists(self._vpath) and os.path.getsize(self._vpath) > 0

    def _load_vectors(self):
        """(vectors, row -> fragment id, FAISS index or None); callers keep the tuple, so a reload cannot pull
        the vectors from under a search that is running."""
        with self._init_lock:
            if self._vstate is None:
                import numpy as np

                dim = int(meta(self.con, "dim"))
                vecs = np.memmap(self._vpath, dtype=np.float16, mode="r").reshape(-1, dim)
                pairs = np.array(
                    self.con.execute("SELECT vec_row, id FROM chunks WHERE vec_row IS NOT NULL").fetchall(), dtype=np.int64
                ).reshape(-1, 2)
                pairs = pairs[pairs[:, 0] < len(vecs)]  # rows embed.py is writing right now
                row2id = np.full(len(vecs), -1, dtype=np.int64)
                row2id[pairs[:, 0]] = pairs[:, 1]
                self._vstate = (vecs, row2id, self._open_ann())
            return self._vstate

    def _open_ann(self):
        """FAISS index built by ann.py; None (exact search) if it is missing or faiss is not installed."""
        path = self._vpath + ".ivfpq.faiss"
        if not os.path.exists(path):
            return None
        try:
            from assistant_x.search import ann

            index = ann.load_index(path)
        except ImportError:
            return None
        index.nprobe = self.cfg.get("ann_nprobe", 64)
        return index

    def embedder(self):
        with self._init_lock:
            return self._embedder_locked()

    def _embedder_locked(self):
        if self._embedder is None:
            self._embedder = self._load_embedder(self.device_override or self.cfg.get("device"))
        return self._embedder

    def _load_embedder(self, device):
        """The embedding model on device (None: DirectML when it is chosen, else CUDA or the processor): models.py,
        the same factory as embed.py, so the questions are embedded as the fragments were."""
        from assistant_x.search import models

        model = self.cfg.get("embed_model", "BAAI/bge-m3")
        if os.path.isabs(model) and not os.path.isdir(model):
            raise FileNotFoundError(f"no embedding model (folder {self.short_path(model)})")
        return models.load_embedder(self.cfg, device or (self.dml() if device is None else None))

    def dml(self):
        """ "dml:N" when the models run through DirectML (assistant_x.toml backend, no CUDA, a discrete AMD/Intel card)."""
        if self._dml is False:
            try:
                from assistant_x.search import onnx_models

                self._dml = onnx_models.dml_device(self.cfg)
            except Exception as e:  # noqa: BLE001 — DirectML is an option: torch still works
                debuglog.log_error("choosing DirectML", e)
                self._dml = None
        return self._dml

    def use_device(self, device):
        """Move the meaning model to another device (the second server took over the video card from the first):
        the new copy is loaded aside and swapped in, the old one keeps answering meanwhile."""
        if self._embedder is not None and device == self.device_override:
            return
        model = self._load_embedder(device or self.cfg.get("device"))
        with self._init_lock:
            self._embedder, self.device_override = model, device

    def short_path(self, path):
        """A path below the project folder as search\\models\\bge-m3: messages to Claude do not show where it lies."""
        try:
            return os.path.relpath(path, self.cfg["library_root"])
        except ValueError:  # another drive
            return os.path.basename(path)

    def warm_up(self):
        """Load the model and the vectors and encode a trial query (the first CUDA call is slow), then let the
        search use meaning. Run in a background thread by the MCP server. A model that does not load leaves the
        search by words with dense_error set (and a line in failures.log) instead of failing every question."""
        try:
            if self.has_vectors():
                model = self.embedder()
                with self._model_lock:
                    model.encode(["model warm-up"], normalize_embeddings=True)
                self._load_vectors()
                self.dense_ready.set()
        except Exception as e:
            self.dense_failed(e, "loading the embedding model", what="the embedding model did not load")

    def dense_failed(self, e, where, sticky=True, what="the semantic search failed"):
        """Reason for Claude; sticky (a model that did not load) keeps the meaning search off until the restart,
        a one-off failure of a question does not."""
        why = str(e) if isinstance(e, FileNotFoundError) else f"{what} ({type(e).__name__})"
        if sticky:
            self.dense_error = why
        debuglog.log_error(where, e)
        return why

    def vectors_missing(self):
        """Name of the vectors file the base expects but the PC lacks (an incomplete copy), else None."""
        if self.has_vectors() or not meta(self.con, "vectors_file"):
            return None
        if not self._no_vectors_logged:
            self._no_vectors_logged = True
            debuglog.log_error("no embeddings file of the fragments", FileNotFoundError(self.short_path(self._vpath)))
        return os.path.basename(self._vpath)

    def dense_search(self, query, n=200, stats=None, **flt):
        """Fragment ids by meaning, the closest first. A filter is applied before the search: the rows of the vectors it
        lets through (allowed_rows) are compared exactly when there are few of them or there is no FAISS index, else
        the index looks among them only (an IDSelectorBatch); without a filter the index, or every vector."""
        import numpy as np

        vecs, row2id, ann = self._load_vectors()
        model = self.embedder()
        with self._model_lock:
            q = model.encode([query], normalize_embeddings=True)[0].astype(np.float32)
        want = n * 3
        allowed = self.allowed_rows(**flt) if any(flt.values()) else None
        if allowed is not None and (ann is None or len(allowed) <= EXACT_ROWS):
            rows = allowed[allowed < len(vecs)]
        elif ann is not None:  # approximate candidates + vectors added after the index was built
            rows = ann_rows(ann, q, want, allowed, len(vecs))
        else:
            rows = np.arange(len(vecs))
        scores = score_rows(vecs, rows, q)
        scores[row2id[rows] < 0] = -1
        top = np.argsort(-scores)[:want] if len(scores) <= 50_000 else np.argpartition(-scores, want)[:want]
        top = top[np.argsort(-scores[top])]
        ids = [int(row2id[rows[t]]) for t in top if scores[t] > -1]
        if stats is not None:  # closeness of the best fragment: below ~0.5 the library hardly knows the topic
            stats["dense_top"] = round(float(scores[top[0]]), 3) if len(ids) else None
        return ids[:n]

    def allowed_rows(self, **flt):
        """The rows of vectors.f16 of the fragments the filters let through (sorted, int64)."""
        import numpy as np

        fsql, fargs = self._filter_sql(**flt)
        return np.unique(
            np.array(
                [
                    r[0]
                    for r in self.con.execute(
                        f"SELECT c.vec_row FROM chunks c JOIN docs d ON d.code=c.code WHERE c.vec_row IS NOT NULL {fsql}",
                        fargs,
                    )
                ],
                dtype=np.int64,
            )
        )

    # ---------- reranking ----------
    def want_rerank(self, query=None, k=None):
        """ "rerank" of assistant_x.toml: true / false, or "auto" (the default): every question on a video card (CUDA
        or DirectML, ~0.1 s for the pool) with the model lying in models/; on a processor it takes seconds per
        question, so there only with rerank = true. While the background warm-up of the MCP server is still loading
        the model, the question goes without it. (The question and k no longer matter: kept for the callers.)"""
        if self.cfg.get("rerank", False) != "auto":
            return bool(self.cfg.get("rerank", False))
        if not self.may_rerank():
            return False
        return self._reranker is not None or not self.no_wait

    def may_rerank(self):
        """True when reranking is on, or "auto" on a video card with the model in models/ (warm_up loads it then)."""
        mode = self.cfg.get("rerank", False)
        if mode == "auto":
            return (self.has_cuda() or bool(self.dml())) and os.path.isdir(self.cfg.get("rerank_model") or "")
        return bool(mode)

    def has_cuda(self):
        if self._cuda is None:
            dev = str(self.cfg.get("device") or "")
            if dev:
                self._cuda = dev.startswith("cuda")
            else:
                try:
                    import torch

                    self._cuda = torch.cuda.is_available()
                except ImportError:
                    self._cuda = False
        return self._cuda

    def reranker(self):
        with self._init_lock:
            return self._reranker_locked()

    def _reranker_locked(self):
        if self._reranker is None:
            from assistant_x.search import models

            dml = self.device_override is None and self.dml() and not self.has_cuda()
            self._reranker = models.load_reranker(self.cfg, self.dml() if dml else self.cfg.get("device"))
        return self._reranker

    def rerank(self, query, order, rows, fused, stats=None):
        """order by final = fused / max(fused) + rerank_weight * sigmoid(logit): the reranker refines the hybrid
        order instead of replacing it (a fragment both lists found high keeps its lead over one the reranker alone
        likes). The reranker reads what the vector was made of (common.model_text)."""
        import numpy as np

        model = self.reranker()
        pairs = [
            (query, model_text(rows[i]["title"], rows[i]["heading"], rows[i]["model_src"])[:RERANK_CHARS]) for i in order
        ]
        with self._model_lock:
            logits = np.asarray(model.predict(pairs), dtype=np.float64).reshape(-1)
        top = max(fused[i] for i in order) or 1.0
        weight = float(self.cfg.get("rerank_weight", RERANK_WEIGHT))
        final = {i: fused[i] / top + weight / (1 + np.exp(-x)) for i, x in zip(order, logits)}
        if stats is not None and len(logits):  # how sure the reranker is of its best fragment (the low closeness note)
            stats["rerank_top"] = round(float(1 / (1 + np.exp(-logits.max()))), 3)
        return sorted(order, key=lambda i: -final[i])

    # ---------- all together ----------
    def search(self, query, k=10, dense=None, rerank=None, max_per_doc=None, stats=None, max_cards=None, **flt):
        """stats: a dict to receive how strong the match was (for the call journal and query_log.py). max_cards: the
        cards of documents in the answer at most ([search] max_cards, 2); the card of a document named in the question
        by its designation always comes."""
        self.refresh()
        max_cards = int(self.cfg.get("max_cards", MAX_CARDS)) if max_cards is None else max_cards
        stats = {} if stats is None else stats
        if dense is not False and self.vectors_missing():
            stats["no_vectors"] = self.vectors_missing()
        elif dense is not False and self._gap[0]:
            stats["unvectored"] = self._gap
        dense = self.has_vectors() if dense is None else dense and self.has_vectors()
        rerank = self.want_rerank(query, k) if rerank is None else rerank
        stats["rerank"] = bool(rerank)
        lists = [self.word_search(query, **flt)]
        stats["words"] = len(lists[0])
        if dense and (self.dense_error or self._model_mismatch):
            dense, stats["dense_error"] = False, self.dense_error or self._model_mismatch
        elif dense and self.no_wait and not self.dense_ready.is_set():
            dense, stats["dense_pending"] = False, True
        if dense:
            try:
                lists.append(self.dense_search(query, stats=stats, **flt))
            except Exception as e:  # the words still answer; the reason goes to Claude and to failures.log
                stats["dense_error"] = self.dense_failed(e, "semantic search", sticky=self._embedder is None)
        fused = {}
        for lst in lists:
            for rank, cid in enumerate(lst):
                fused[cid] = fused.get(cid, 0) + 1 / (RRF_K + rank)
        named = self.designations_in(query)
        stats["designation"] = named
        first = []
        if named:  # "GOST 1510-84" in the question: the card of that document first (unless the filters exclude it)
            fsql, fargs = self._filter_sql(**flt)
            first = [
                r[0]
                for r in self.con.execute(
                    f"""SELECT c.id FROM chunks c JOIN docs d ON d.code=c.code WHERE c.kind='card'
                    AND c.code IN ({",".join("?" * len(named))}) {fsql} ORDER BY c.code, c.n""",
                    [*named, *fargs],
                )
            ]
        self._weigh(query, fused)
        # the pool before the merging: a document of many close pages must not fill it alone (max 3 per document)
        order = sorted(fused, key=fused.get, reverse=True)[: max(POOL, k * 4)]
        rows = {
            r["id"]: dict(r, text=(r["text"] or "").strip("\n"))
            for r in self.con.execute(
                f"""SELECT c.id, c.code, c.page, {CHUNK_TEXT_SQL} AS text, {SEARCH_TEXT_SQL} AS model_src, c.heading,
                c.kind, d.title, d.section, d.year, d.page_offset, {DOC_SQL}, {QUALITY_SQL}, {PAGE_SQL}
                FROM chunks c JOIN docs d ON d.code=c.code {PAGES_JOIN_SQL}
                WHERE c.id IN ({",".join(map(str, dict.fromkeys(order + first))) or 0})"""
            )
        }
        order = [i for i in order if i in rows]  # a fragment removed by a rebuild a moment ago
        for i in order:  # a garbled or doubled page answers less well than a clean one of the same closeness
            if {"garbled", "doubled"} & set((rows[i].get("page_flags") or "").split(",")):
                fused[i] *= GARBLED_WEIGHT
        order.sort(key=lambda i: -fused[i])
        if rerank and order:
            order = self.rerank(query, order, rows, fused, stats)
        order = [i for i in first if i in rows] + [i for i in order if i not in first]
        fill = max_per_doc is None  # the default quota gives way to free places; one asked for holds
        max_per_doc = MAX_PER_DOC if fill else max_per_doc
        out, per_doc, seen, cards, over = [], {}, {}, 0, []

        def add(r, at, card):
            per_doc[r["code"]] = per_doc.get(r["code"], 0) + 1
            out.append(
                dict(
                    code=r["code"],
                    page=r["page"],
                    title=r["title"],
                    section=r["section"],
                    year=r["year"],
                    page_numbering=r["page_offset"],
                    heading=r["heading"] or "",
                    text=r["text"],
                    quality=r["quality"] or "",
                    issue=r["issue"] or "",
                    kind=r["kind"],
                    doc_type=r["doc_type"] or "",
                    personal=bool(r["personal"]),
                    named=r["code"] in named,
                    label=None if card else r["label"],
                    page_note="" if card else page_note(r["page_score"], r["page_flags"]),
                )
            )
            seen[at] = out[-1]

        for cid in order:
            r = rows[cid]
            r["kind"] = SHOWN_KIND.get(r["kind"], r["kind"])
            at = (r["code"], r["page"], r["kind"])
            if at in seen:  # second fragment of a page already listed: join them
                seen[at]["text"] += "\n\n" + r["text"]
                continue
            card = r["kind"] == "card"
            if per_doc.get(r["code"], 0) >= max_per_doc:
                if not card:
                    over.append((cid, at))
                continue
            if card and cards >= max_cards and r["code"] not in named:  # pages answer, cards point to documents
                continue
            cards += card
            add(r, at, card)
            if len(out) >= k:
                break
        if len(out) < k and fill:
            # the other documents left places free: a document that fills the candidates alone (a big book, a question
            # in the words of its title) gives its pages over the quota, in their order (M-080: L-00005 p.209 was the
            # 4th page of the book and the answer had 3 results)
            for cid, at in over:
                if len(out) >= k:
                    break
                if at in seen:
                    seen[at]["text"] += "\n\n" + rows[cid]["text"]
                else:
                    add(rows[cid], at, False)
        for r in out:  # where "see table 4.2", "formula (12)", "see 5.3" in the fragment lead within the book
            r["refs"] = self.maps.targets(r["code"], r["page"], r["text"]) if r["kind"] == "text" else []
            r["related_pages"] = sorted({p for _, p in r["refs"]})
        return out

    def _weigh(self, query, fused):
        """The fused scores weighted by the kind of the fragment (KIND_WEIGHT, [search] card_weight, card_q_weight: the
        questions of a card are what the document answers, as good a hit as a page) and raised for a
        fragment in a chapter of the contents of its card whose title matches the question (toc_match)."""
        if not fused:
            return
        ids = ",".join(map(str, fused))
        found = self.con.execute(f"SELECT id, code, page, kind FROM chunks WHERE id IN ({ids})").fetchall()
        weight = dict(
            KIND_WEIGHT,
            card=float(self.cfg.get("card_weight", KIND_WEIGHT["card"])),
            card_q=float(self.cfg.get("card_q_weight", KIND_WEIGHT["card_q"])),
        )
        want = set(tokens(query, drop_stop=True))
        boost = float(self.cfg.get("toc_boost", TOC_BOOST))
        chapters = {}
        if want and boost:
            codes = sorted({r["code"] for r in found if r["kind"] == "text"})
            for t in (
                self.con.execute(
                    f"SELECT code, title, pdf_from, pdf_to FROM toc WHERE code IN ({','.join('?' * len(codes))})", codes
                )
                if codes
                else ()
            ):
                if toc_match(want, set(tokens(t["title"] or "", drop_stop=True))):
                    chapters.setdefault(t["code"], []).append((t["pdf_from"], t["pdf_to"]))
        for r in found:
            w = weight.get(r["kind"], 1.0)
            if r["kind"] == "text" and any(a <= r["page"] <= b for a, b in chapters.get(r["code"], ())):
                w *= 1 + boost
            fused[r["id"]] *= w

    # ---------- reading ----------
    def pages(self, code, start, end, max_chars=30000):
        """Text of the pages; a cut is said at the end, so Claude asks for the rest instead of taking it for all.
        Base schema 3: every page exactly as its text file has it, the marker line, a blank line and the body (a line
        of the body that reads as a marker escaped, as in the file)."""
        self.refresh()
        rows = self.con.execute(
            "SELECT page, text FROM pages WHERE code=? AND page BETWEEN ? AND ? ORDER BY page", (code, start, end)
        ).fetchall()
        out, ends, size = [], {}, -2
        for r in rows:
            out.append(f"{page_marker(r['page'])}\n\n{escape_marker(r['text'])}")
            size += len(out[-1]) + 2
            ends[r["page"]] = size
        return _cut("\n\n".join(out), ends, max_chars)

    def page_text(self, code, page):
        """The text of one page of a document, or None when the base has no such page."""
        self.refresh()
        r = self.con.execute("SELECT text FROM pages WHERE code=? AND page=?", (code, page)).fetchone()
        return r[0] if r else None

    def verify_quote(self, code, page, text):
        """Is a quote (a sentence, a number of a table) on a page? The quote and the pages are compared by their
        skeleton (common.skeleton): the page, then the one before and the one after it. Word for word: "found" on the
        page, "found_nearby" on a neighbour (exact True); else the closest window of words of the three pages
        (difflib.SequenceMatcher): QUOTE_RATIO or more is found or found_nearby with exact False, less "not_found".
        {status, code, page (where it is, or the asked one), asked, label, ocr_score, flags (of that page), exact,
        ratio, closest (the words of the page), diff (how the quote differs from them, short)}."""
        code = code.strip().upper()
        texts = [(p, self.page_text(code, p)) for p in (page, page - 1, page + 1)]
        texts = [(p, t) for p, t in texts if t is not None]
        info = self.page_info(code, page - 1, page + 1)

        def result(status, at, exact, ratio=0.0, closest="", diff=""):
            label, score, flags = info.get(at, (None, None, None))
            return dict(
                status=status,
                code=code,
                page=at,
                asked=page,
                label=label,
                ocr_score=score,
                flags=[f for f in (flags or "").split(",") if f],
                exact=exact,
                ratio=ratio,
                closest=closest,
                diff=diff,
            )

        if len(text) > MAX_QUOTE:
            return result("not_found", page, False, diff=f"a quote longer than {MAX_QUOTE} characters: check it in parts")
        want = skeleton(text)
        if not texts or not want:
            return result("not_found", page, False, diff="no text of this page in the library" if want else "an empty quote")
        for p, t in texts:
            if want in skeleton(t):
                return result("found" if p == page else "found_nearby", p, True, 1.0, closest_window(t, text)[1])
        parts = [s for s in (skeleton(x) for x in ELLIPSIS.split(text)) if s]
        if len(parts) > 1:
            for p, t in texts:
                body, at = skeleton(t), 0
                for s in parts:
                    at = body.find(s, at)
                    if at < 0:
                        break
                    at += len(s)
                else:
                    first = closest_window(t, ELLIPSIS.split(text)[0])[1]
                    return result(
                        "found" if p == page else "found_nearby", p, True, 1.0, first, "an elided quote: its parts in order"
                    )
            text = " ".join(x.strip() for x in ELLIPSIS.split(text))  # compared without the cuts below
        ratio, closest, diff, at = max(
            (closest_window(t, text) + (p,) for p, t in texts), key=lambda x: (x[0], x[3] == page)
        )
        status = "not_found" if ratio < QUOTE_RATIO else "found" if at == page else "found_nearby"
        return result(status, at, False, ratio, closest, diff)

    def page_info(self, code, start, end):
        """{page: (label, recognition score, flags)} of the pages of a document."""
        self.refresh()
        return {
            r[0]: (r[1], r[2], r[3])
            for r in self.con.execute(
                "SELECT page, label, ocr_score, flags FROM pages WHERE code=? AND page BETWEEN ? AND ? ORDER BY page",
                (code.strip().upper(), start, end),
            )
        }

    def doc(self, code):
        self.refresh()
        r = self.con.execute("SELECT * FROM docs WHERE code=?", (code.strip().upper(),)).fetchone()
        return dict(r) if r else None

    NAMES_TTL = 60  # seconds: a name not found in the map of the library walks it again at most this often

    def _by_name(self, root, names):
        """{index: path} of the file names (lower case) found anywhere in the library, from a map of the names of
        the library made once per state of the base (refresh) and made again when a name is missing from it and the
        map is older than NAMES_TTL (a file moved by hand): not a walk of the whole library for every page image."""
        import time

        for again in (False, True):
            if again or self._names is None:
                if again and time.time() - self._names[1] < self.NAMES_TTL:
                    break
                names_of = {}
                for dp, dirs, fs in os.walk(root):
                    dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
                    for f in fs:
                        names_of.setdefault(f.lower(), os.path.join(dp, f))
                self._names = (names_of, time.time())
            hits = {
                i: self._names[0][n]
                for n, i in names.items()
                if n in self._names[0] and os.path.isfile(lp(self._names[0][n]))
            }
            if hits:
                return hits
        return {}

    def original(self, code):
        """(path to the PDF of the original, None) or (None, why not). Looks in library, then where the file
        came from (inbox, before it is moved), then for the same file name anywhere in the library.
        A DOC/DOCX is shown through the PDF made from it that lies next to it."""
        code = code.strip().upper()
        if not CODE_RX.match(code):
            return None, f'The code "{code[:40]}" does not follow the pattern N-00001 or E-00006-02.'
        d = self.doc(code)  # doc() refreshes the state first
        if not d:
            return None, f"No document {code} in the catalog."
        root = self.cfg["library_root"]
        card = json.loads(d.get("card") or "{}")
        f = card.get("file") or {}
        if code != card.get("code"):
            f = next((p for p in f.get("parts") or [] if p.get("code") == code), {})
        known = [p for p in (f.get("pdf_copy"), d["file"], d.get("source")) if p and not p.endswith(("\\", "/"))]
        paths = [place_path(root, p) for p in known]
        want = [q for p in paths for q in dict.fromkeys((os.path.splitext(p)[0] + ".pdf", p))]
        found = next((p for p in want if p.lower().endswith(".pdf") and os.path.isfile(lp(p))), None)
        if not found and want:  # only a file name is known, or the file was moved: look for it by name
            names = {os.path.basename(p).lower(): i for i, p in enumerate(want) if p.lower().endswith(".pdf")}
            hits = self._by_name(root, names)
            found = hits[min(hits)] if hits else None
        if found:
            return self._inside_library(code, found)
        if not known:
            return None, f"The original file of {code} is not known."
        # only the file name: the card's "Original file" is a path in the intake folder of whoever built the library
        name = os.path.splitext(os.path.basename(known[0].replace("\\", "/")))[0] + ".pdf"
        return None, (
            f"The original of {code} ({name}) is not in the library folder, so there is no page image: read "
            "the text of the page (read_pages). If the document has not been moved into the library yet, or "
            "it is a DOC/DOCX without a PDF copy beside it, this is expected; otherwise copy the library "
            "folder from the media in full."
        )

    def _inside_library(self, code, path):
        """(real path, None) or a refusal: a card with "..\\..\\" in its path must not open files elsewhere on the PC."""
        real, top = os.path.realpath(path), os.path.realpath(self.cfg["library_root"])
        try:
            inside = os.path.commonpath([os.path.normcase(real), os.path.normcase(top)]) == os.path.normcase(top)
        except ValueError:  # another drive
            inside = False
        if inside:
            return real, None
        debuglog.log_error("original outside the library", ValueError(f"{code}: {real} outside {top}"), {"code": code})
        return None, "The path of the original is outside the library: refused"

    def list_docs(self, text=None, **flt):
        self.refresh()
        fsql, fargs = self._filter_sql(**flt)
        fsql += " AND coalesce(d.parent, '') = ''"  # parts of documents are listed in the card of their document
        more = ", d.doc_type, d.designation, d.lang, d.personal, d.card"
        rows = [
            dict(r)
            for r in self.con.execute(
                f"SELECT code,title,section,year,topics,pages{more} FROM docs d WHERE 1=1 {fsql} ORDER BY code", fargs
            )
        ]
        if text:
            want = set(tokens(text, drop_stop=True))
            rows = [r for r in rows if want & set(tokens(_listed_text(r)))]
        for r in rows:
            r.pop("card", None)
        return rows


def toc_match(want, have):
    """Does the title of a chapter (its stems have) match a question (its stems want)? At least TOC_MIN_SHARED shared
    stems, or TOC_MIN_SHARE of the stems of the question: a long question naming a chapter in two words counts (half
    of its words was too much), a one-word title still needs that word."""
    shared = len(want & have)
    return bool(shared) and (shared >= TOC_MIN_SHARED or shared >= TOC_MIN_SHARE * len(want))


def score_rows(vecs, rows, q):
    """Inner products of the vectors of rows with q, blockwise: the float16 file never sits in RAM as float32."""
    import numpy as np

    out = np.empty(len(rows), dtype=np.float32)
    for i in range(0, len(rows), SCORE_STEP):
        part = rows[i : i + SCORE_STEP]
        block = vecs[part[0] : part[-1] + 1] if part[-1] - part[0] + 1 == len(part) else vecs[part]  # a run: a slice
        out[i : i + SCORE_STEP] = np.asarray(block, np.float32) @ q
    return out


def ann_rows(index, q, want, allowed, total):
    """Candidate rows from the FAISS index (PQ scores are rough: 4x more, rescored exactly by the caller) and the rows
    added after it was built. allowed: only among these rows (a filter) — an IDSelectorBatch inside the index, or
    20x more candidates kept when allowed where this FAISS build lacks the selector."""
    import numpy as np

    tail = np.arange(index.ntotal, total)
    if allowed is None:
        _, found = index.search(q[None], want * 4)
        return np.unique(np.concatenate([found[0][found[0] >= 0], tail]))
    try:
        import faiss

        params = faiss.SearchParametersIVF(sel=faiss.IDSelectorBatch(allowed), nprobe=index.nprobe)
        _, found = index.search(q[None], want * 4, params=params)
        found = found[0][found[0] >= 0]
    except (AttributeError, TypeError):  # an older FAISS: no search parameters
        _, found = index.search(q[None], want * 20)
        found = found[0][np.isin(found[0], allowed)]
    return np.unique(np.concatenate([found, tail[np.isin(tail, allowed)]]))


def _cut(text, ends, max_chars):
    """The text of pages within max_chars; ends: page -> where its text ends in it. A cut says which pages are left."""
    if len(text) <= max_chars:
        return text
    first = next(p for p, e in ends.items() if e > max_chars)  # the first page not shown in full
    last = max(ends)
    rest = f"pages {first}–{last} are not shown" if last > first else f"page {first} is not shown"
    return text[:max_chars] + f"\n\n…text cut at {max_chars} characters: {rest}, ask for them separately"


def page_note(score, flags):
    """What Claude should know of one page before citing it: a low recognition score, a complex table."""
    out = []
    if score is not None and score < QUALITY["ocr_note"]:
        out.append(f"recognition score {score:.0f} of 100 on this page: check words and figures with page_image")
    if "complex_table" in (flags or "").split(","):
        out.append("complex table on this page — check numbers with page_image")
    if "garbled" in (flags or "").split(","):
        out.append("garbled recognition on this page (glued or unknown words) — check the words with page_image")
    if "doubled" in (flags or "").split(","):
        out.append("every phrase of this page is in the text twice — read it once, check with page_image")
    if "dpi_reduced" in (flags or "").split(","):
        out.append("recognized at a reduced resolution (a very large page) — check small print with page_image")
    return "; ".join(out)


def _word_skeletons(text):
    """[(start, end, skeleton)] of the words of a text (a Markdown mark alone is no word)."""
    out = []
    for m in re.finditer(r"\S+", text):
        s = "" if re.fullmatch(r"#{1,6}", m.group(0)) else skeleton(m.group(0))
        if s:
            out.append((m.start(), m.end(), s))
    return out


def closest_window(page, quote):
    """(ratio, the closest run of words of the page, how the quote differs from it): windows of the words of the page
    as long as the quote (one word more or less), compared by their skeleton with difflib.SequenceMatcher."""
    words, want = _word_skeletons(page), skeleton(quote)
    n = len(want.split())
    if not words or not want:
        return 0.0, "", ""
    best, sm = (0.0, 0, 0), difflib.SequenceMatcher(None, autojunk=False)
    sm.set_seq2(want)
    for size in sorted({max(1, n - 1), n, n + 1}):
        for i in range(max(1, len(words) - size + 1)):
            j = min(len(words), i + size) - 1
            sm.set_seq1(" ".join(w[2] for w in words[i : j + 1]))
            if sm.real_quick_ratio() > best[0] and sm.quick_ratio() > best[0]:
                r = sm.ratio()
                if r > best[0]:
                    best = (r, i, j)
    r, i, j = best
    found = page[words[i][0] : words[j][1]]
    return round(r, 3), found[:CLOSEST_CHARS], word_diff(quote, found)


def word_diff(quote, found, most=5):
    """How the words of a quote differ from the words found on the page, short: «a» → «b»; … (by their skeleton)."""
    a, b = quote.split(), found.split()
    key = lambda w: skeleton(w).strip(PUNCT)  # noqa: E731 - a comma after a word is no difference
    ops = difflib.SequenceMatcher(None, [key(w) for w in a], [key(w) for w in b], autojunk=False).get_opcodes()
    out = []
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":
            continue
        x, y = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        out.append(f"«{x}» → «{y}»" if x and y else f"«{x}» is not on the page" if x else f"the page adds «{y}»")
    return "; ".join(out[:most]) + (f"; and {len(out) - most} more" if len(out) > most else "")


def _listed_text(row):
    """What the text of list_docs is looked for in: the titles in every language, the designations, the keywords and
    the topics of the card (the title and topics of the row for a base without cards)."""
    try:
        doc = json.loads(row.get("card") or "{}").get("doc") or {}
    except ValueError:
        doc = {}
    return " ".join(
        [
            row.get("title") or "",
            row.get("topics") or "",
            row.get("designation") or "",
            *C.all_texts(doc.get("title")),
            *C.keywords(doc),
        ]
    )


SKIP_DIRS = {".venv", "venv", "__pycache__", ".git", "index", "search", "models", "packages", "db", "debug"}


def section_letter(s, profile=None):
    """'N', 'Standards', 'Datasheets and catalogs' -> the letter of the codes of that shelf; an unknown
    name is returned as it is."""
    s = s.strip()
    return settings.section_letter(s, profile) or s


def load_synonyms(path):
    groups = []
    if path and os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                g = [tuple(tokens(a)) for a in line.split("=")]
                groups.append([a for a in g if a])
    return groups


def _contains(seq, sub):
    n = len(sub)
    return n > 0 and any(tuple(seq[i : i + n]) == sub for i in range(len(seq) - n + 1))


def main():
    ap = argparse.ArgumentParser(prog="assistant-x search")
    ap.add_argument("query")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--section", action="append")
    ap.add_argument("--code", action="append")
    ap.add_argument("--doc-type", action="append")
    ap.add_argument("--lang", action="append")
    ap.add_argument("--no-dense", action="store_true")
    ap.add_argument("--rerank", action="store_true")
    ap.add_argument("--no-rerank", action="store_true")
    ap.add_argument("--config")
    a = ap.parse_args()
    cfg = load_config(a.config)
    if not os.path.exists(cfg["db"]):
        raise SystemExit(
            f"No search base yet ({cfg['db']}): put documents into inbox, assistant-x intake run, then assistant-x build."
        )
    lib = Library(cfg)
    res = lib.search(
        a.query,
        k=a.k,
        dense=not a.no_dense,
        rerank=False if a.no_rerank else (a.rerank or None),
        sections=a.section,
        codes=a.code,
        doc_types=a.doc_type,
        langs=a.lang,
    )
    for r in res:
        snip = re.sub(r"\s+", " ", r["text"])[:300]
        head = f"\n    section: {r['heading'][:150]}" if r["heading"] else ""
        refs = ("\n    references: " + "; ".join(f"{t} → PDF {p}" for t, p in r["refs"])) if r["refs"] else ""
        where = "card" if r["kind"] == "card" else f"PDF {r['page']}"
        print(f"[{r['code']}, {where}] {r['title'][:70]}{head}{refs}\n    {snip}\n")
    if not res:
        print("Nothing found.")


if __name__ == "__main__":
    from assistant_x.core import debuglog

    debuglog.run(main, "search")
