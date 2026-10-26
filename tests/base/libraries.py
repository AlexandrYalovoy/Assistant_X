# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Two mini libraries for the merges of base packages, made here with pymupdf (no models, no real library):

  A  the mini library of the search tests (tests/search/conftest.make_library): N-00001, N-00002, E-00001 (+ part
     E-00001-02), L-00001, J-00001, X-00001
  B  three documents whose codes collide with A (N-00001, L-00001) and one that does not (P-00001), with other
     contents: a package of another library

renumber(root, mapping) gives documents of a workspace new codes the plain way (two-phase renames, no journal): what
the install of a package does under its journal, so the tests can say what must hold after it."""

import json, os

from assistant_x.core import card as C
from assistant_x.base import remap as R
from tests.search.conftest import make_library as make_a, text_pdf, write  # noqa: F401 — A for the callers

B_DOCS = [  # code, title en, title ru, doc_type, folder, file, pages of the text
    (
        "N-00001",
        "Package standard on pipelines",
        "Стандарт пакета о трубопроводах",
        "standard",
        "01_Standards",
        "N-00001_Package-Pipeline-Standard.pdf",
        ["# 1. Pipelines\n\nThe wall thickness of a field pipeline is found with a corrosion allowance of two millimetres."],
    ),
    (
        "L-00001",
        "Package handbook of pumps",
        "Справочник пакета по насосам",
        "handbook",
        "02_Literature",
        "L-00001_Package-Pump-Handbook.pdf",
        [
            "# Pumps\n\nA multistage centrifugal pump injects produced water into the reservoir.",
            "# Seals\n\nMechanical seals of the pumps are checked for leaks before start-up.",
        ],
    ),
    (
        "P-00001",
        "Package report on a gas plant",
        "Отчёт пакета о газовом заводе",
        "report",
        "03_Projects",
        "P-00001_Package-Gas-Plant-Report.pdf",
        ["# Summary\n\nThe gas plant treats associated gas: dehydration by glycol and dew point control."],
    ),
]


def make_b(root, package=None):
    """Library B in root (cards, texts, originals, the catalog, assistant_x.toml); package: {id, version} puts
    intake.package into every card (the cards as an installed package has them). Returns the path of the settings."""
    from assistant_x.search import catalog

    idx = os.path.join(root, "index")
    for code, title, title_ru, doc_type, folder, file, pages in B_DOCS:
        os.makedirs(os.path.join(root, "library", folder), exist_ok=True)
        text_pdf(os.path.join(root, "library", folder, file), [f"{code} page {i + 1}" for i in range(len(pages))])
        intake = {"batch": "package", "date": "2026-10-20", "personal": False}
        if package:
            intake["package"] = dict(package, code=code)
        card = C.complete(
            {
                "schema": 1,
                "code": code,
                "section": code[0],
                "doc_type": doc_type,
                "doc": {
                    "title": {"en": title, "ru": title_ru},
                    "lang": ["en"],
                    "year": 2025,
                    "topics": ["package"],
                    "summary": f"{title}: a document of package B.",
                    "keywords": {"en": ["package"], "ru": ["пакет"]},
                },
                "file": {
                    "library": f"library/{folder}/{file}",
                    "source_name": f"{code}.pdf",
                    "text": f"index/texts/{code}.md",
                    "format": {"kind": "pdf_text", "pages": len(pages)},
                },
                "intake": intake,
            }
        )
        C.dump(card, os.path.join(idx, "cards", f"{code}.json"))
        write(
            os.path.join(idx, "texts", f"{code}.md"),
            "".join(f"=== page {i + 1} ===\n\n{p}\n\n" for i, p in enumerate(pages)),
        )
    catalog.write(idx, "2026-10-20", {"profile": "oil-gas-ru"})
    path = os.path.join(root, "assistant_x.toml")
    write(
        path,
        'profile = "oil-gas-ru"\n\n[paths]\ndb = "search/db"\nmodels = "models"\n\n[search]\n'
        'embed_model = "models/bge-m3"\nrerank = false\n',
    )
    return path


def renumber(root, mapping, date="2026-10-25"):
    """Give documents of the workspace root new codes: the cards rewritten under their new names, the texts and the
    originals renamed through temporary names (a swap A <-> B works), manifest.tsv and ocr_quality.tsv rewritten, the
    fingerprint caches of the codes dropped, questions.md and eval_baseline.json rewritten, the views made again, a
    row per document in intake_events.tsv."""
    from assistant_x.core import journal
    from assistant_x.intake import manifest
    from assistant_x.search import catalog

    assert not C.check_mapping(mapping)
    idx = os.path.join(root, "index")
    cards = {code: C.load(p) for code, p in C.paths(os.path.join(idx, "cards")).items()}
    moves = []
    for code, card in cards.items():
        for old, new in C.renames(card, mapping):
            if os.path.exists(os.path.join(root, old)):
                moves.append((old, new))
    for k, (old, _) in enumerate(moves):  # phase one: every file to a temporary name
        os.replace(os.path.join(root, old), os.path.join(root, old) + f".ax-renumber-{k}")
    for k, (old, new) in enumerate(moves):  # phase two: to its new name
        os.makedirs(os.path.dirname(os.path.join(root, new)), exist_ok=True)
        os.replace(os.path.join(root, old) + f".ax-renumber-{k}", os.path.join(root, new))
    for code, card in cards.items():
        new, _ = C.remap(card, mapping)
        C.dump(new, os.path.join(idx, "cards", f"{new['code']}.json"))
    for dp, dns, _ in os.walk(os.path.join(root, "library"), topdown=False):  # the emptied folders of moved documents
        for d in dns:
            if not os.listdir(os.path.join(dp, d)):
                os.rmdir(os.path.join(dp, d))
    man = manifest.manifest_path(root)
    if man.exists():
        manifest.save(R.manifest_rows(manifest.load(man), mapping), man)
    for name in ("ocr_quality.tsv",):
        p = os.path.join(idx, name)
        if os.path.exists(p):
            write(p, R.tsv_codes(open(p, encoding="utf-8").read(), mapping))
    for p in R.fingerprint_files(
        [os.path.join(root, ".assistant_x", "fingerprints")], list(mapping) + list(mapping.values())
    ):
        os.remove(p)
    q = os.path.join(root, "questions.md")
    if os.path.exists(q):
        write(q, R.questions_text(open(q, encoding="utf-8").read(), mapping)[0])
    b = os.path.join(root, "eval_baseline.json")
    if os.path.exists(b):
        write(b, json.dumps(R.any_json(json.load(open(b, encoding="utf-8")), mapping), ensure_ascii=False, indent=1))
    journal.append_events(os.path.join(idx, "intake_events.tsv"), R.events(date, mapping))
    C.raise_high_water(idx, mapping.values())
    catalog.write(idx, date, {"profile": "oil-gas-ru"})
    if os.path.exists(os.path.join(idx, "intake_events.tsv")):
        journal.sync(idx)
