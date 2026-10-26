# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Make the seed vocabulary of a language pack (assistant_x/lang/<code>/vocab.txt) from an open Hunspell dictionary,
for the recognition score of a library that has no texts yet (audit 6, M-015). A developer's tool, run by hand:

    python scripts/seed_vocab.py ru path/to/ru_RU.dic path/to/ru_RU.aff "notice line" ...

The words of the dictionary starting in lower case are expanded with their affix rules (one suffix and one prefix,
the cross product where the rule allows it). Written: the forms shorter than STEM_MIN letters as they are (a short
word is known by its form only), and the stems (ocr_score.stem) of the longer forms as "~stem" lines; the lines of the
pack's former seed (the words of its own data) are kept. The notice lines given go into the header: the copyright and
the license of the dictionary, which its license asks to be kept."""

import re, sys
from pathlib import Path


def read_aff(path):
    """{flag: (kind, cross, [(strip, add, condition regex)])} of the PFX/SFX rules of a .aff file."""
    rules, lines = {}, Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    i = 0
    while i < len(lines):
        f = lines[i].split()
        if len(f) >= 4 and f[0] in ("PFX", "SFX") and f[2] in ("Y", "N") and f[3].isdigit():
            kind, flag, cross, n = f[0], f[1], f[2] == "Y", int(f[3])
            out = []
            for line in lines[i + 1 : i + 1 + n]:
                g = line.split()
                if len(g) < 4:
                    continue
                strip = "" if g[2] == "0" else g[2]
                add = "" if g[3] == "0" else g[3].split("/")[0]
                cond = g[4] if len(g) > 4 else "."
                rx = re.compile((f"^{cond}" if kind == "PFX" else f"{cond}$") if cond != "." else ".")
                out.append((strip, add, rx))
            rules[flag] = (kind, cross, out)
            i += n + 1
            continue
        i += 1
    return rules


def expand(word, flags, rules):
    """The forms of a word: itself, with each suffix, with each prefix, and both where the rules cross."""
    forms, suf, pre = {word}, [], []
    for fl in flags:
        r = rules.get(fl)
        if not r:
            continue
        kind, cross, items = r
        for strip, add, rx in items:
            if kind == "SFX" and rx.search(word) and (not strip or word.endswith(strip)):
                w = (word[: len(word) - len(strip)] if strip else word) + add
                forms.add(w)
                if cross:
                    suf.append(w)
            elif kind == "PFX" and rx.search(word) and (not strip or word.startswith(strip)):
                w = add + (word[len(strip) :] if strip else word)
                forms.add(w)
                if cross:
                    pre.append((strip, add))
    for w in suf:
        for strip, add in pre:
            forms.add(add + (w[len(strip) :] if strip else w))
    return forms


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    code, dic, aff, notice = argv[0], argv[1], argv[2], argv[3:]
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from assistant_x.intake.tools import ocr_score

    rules = read_aff(aff)
    forms = set()
    for line in Path(dic).read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
        word, _, flags = line.strip().partition("/")
        word = word.strip()
        if not word or not word[0].islower() or not word.isalpha() and "-" not in word:
            continue  # a name, an abbreviation, a number: no word of a recognition check
        forms |= expand(word, flags.split()[0] if flags else "", rules)
    norm = {ocr_score.norm(w) for w in forms if w}
    short = sorted(w for w in norm if len(w) < ocr_score.STEM_MIN)
    stems = sorted({ocr_score.stem(w) for w in norm if len(w) >= ocr_score.STEM_MIN})
    out = Path(__file__).resolve().parent.parent / "assistant_x" / "lang" / code / "vocab.txt"
    old = [x for x in out.read_text(encoding="utf-8").splitlines() if x and x[0] != "#"] if out.exists() else []
    keep = sorted(set(old) - set(short))
    head = [
        f"# seed vocabulary of the recognition score ({code}): {len(short) + len(keep)} word forms and {len(stems)} stems "
        "(~), known under the vocabulary of the library (ocr_score.seed); made by scripts/seed_vocab.py from the "
        f"Hunspell dictionary {Path(dic).name} (modified: expanded to forms and stems), and the words of this pack.",
        *[f"# {x}" for x in notice],
    ]
    out.write_text("\n".join(head + keep + short + [f"~{s}" for s in stems]) + "\n", encoding="utf-8", newline="\n")
    print(f"{out}: {len(short) + len(keep)} forms, {len(stems)} stems")


if __name__ == "__main__":
    main(sys.argv[1:])
