# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compare evidence delivery on an isolated mini library; no LLM or private documents required."""

import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from unittest.mock import patch

from tests.golden.context_cost import score
from tests.search.conftest import build, make_library, card, text_pdf


def add_editions(root):
    """Two revisions of the same test instruction with an explicit project approval for the newer one."""
    from assistant_x.core.card import dump
    from assistant_x.search import catalog

    root = Path(root)
    for year, code, status in (
        (2020, "N-00003", "Superseded by the 2024 edition."),
        (2024, "N-00004", "Approved for project Delta by approval D-17."),
    ):
        title = f"Separator Zeta {year}"
        filename = f"{code}_Zeta-{year}.pdf"
        row = card(code, title, title, "standard", "01_Standards", filename, "pdf_text", 1)
        row["doc"].update(edition=str(year), year=year, jurisdiction="KZ", designation={"en": "ZETA-17", "ru": "ZETA-17"})
        if year == 2024:
            row["doc"]["applicability_source"] = "Project Delta approval D-17"
        body = f"ZETA-17. Separator Zeta inspection instruction. Edition {year}. {status}"
        text_pdf(root / row["file"]["library"], [body])
        (root / row["file"]["text"]).write_text("=== page 1 ===\n\n" + body, encoding="utf-8")
        dump(row, root / "index" / "cards" / f"{code}.json")
    catalog.write(str(root / "index"), "2026-11-26", {"profile": "oil-gas-ru"})


def separate_calls(server, query, k, count):
    found = server.search_library_data(query, k=k)
    messages, pages, seen = [found], [], set()
    for hit in found["hits"]:
        key = hit["code"], hit["pdf_page"]
        if not key[1] or key in seen or hit["kind"] in ("card", "card_q"):
            continue
        seen.add(key)
        body = server.read_pages(*key, key[1])
        messages.append(body)
        # These fixture pages are short. Extract only the delivered page, excluding citation metadata.
        marker = f"=== page {key[1]} ===\n\n"
        text = body.partition(marker)[2].split("\n\nPrinted pages:")[0].split("\n\nPage: PDF ")[0]
        pages.append(dict(hit, text=text))
        if len(pages) == count:
            break
    return messages, dict(matches=found["hits"], pages=pages)


def main():
    from assistant_x.search.context import MODES
    from assistant_x.server import mcp_server as m
    from assistant_x.search.retrieval import Library
    from assistant_x.core.common import load_config

    questions = json.loads(Path(__file__).with_name("fixture_questions.json").read_text(encoding="utf-8"))["questions"]
    with (
        TemporaryDirectory() as tmp,
        patch.dict(os.environ, {"AX_WORKSPACE": tmp, "AX_MACHINE_DIR": str(Path(tmp) / "machine")}),
    ):
        cfg = make_library(tmp)
        add_editions(tmp)
        with redirect_stdout(sys.stderr):
            build(cfg)
        lib = Library(load_config(cfg))
        with patch.object(m, "_lib", lib), patch.object(m, "_owner", object()):
            for item in questions:
                for mode, (k, n, _) in MODES.items():
                    for route in ("single", "steps"):
                        start = monotonic()
                        if route == "single":
                            out = m.answer_context(item["q"], mode)
                            messages = [out]
                        else:
                            messages, out = separate_calls(m, item["q"], k, n)
                        chars = sum(len(json.dumps(v, ensure_ascii=False, separators=(",", ":"))) for v in messages)
                        print(
                            json.dumps(
                                dict(
                                    id=item["id"],
                                    mode=mode,
                                    route=route,
                                    calls=len(messages),
                                    chars=chars,
                                    seconds=round(monotonic() - start, 3),
                                    **score(item, out),
                                )
                            )
                        )

        lib.con.close()


if __name__ == "__main__":
    main()
