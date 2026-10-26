# Contributing to Assistant X

Thank you for wanting to help. Proposals, questions and bug reports are welcome as issues; code, documentation,
language packs and profiles as pull requests. The project lives at https://github.com/AlexandrYalovoy/Assistant_X:
issues and pull requests go there (the GitFlic mirror, https://gitflic.ru/project/alexandryalovoy/assistant_x, is a
copy for reading and cloning). Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Before the first pull request

- **The Contributor License Agreement.** Every contribution is accepted under [`CLA.md`](CLA.md): you keep your copyright and
  grant the author a license that also allows offering the project under other licenses later. Agree to it once,
  with the line given in [`CLA.md`](CLA.md), in the description of your first pull request. Pull requests without it cannot be
  merged.
- **Licenses.** The code is GNU AGPL-3.0-or-later ([`LICENSE`](LICENSE)); the data folders [`assistant_x/lang`](assistant_x/lang),
  [`assistant_x/profiles`](assistant_x/profiles) and [`assistant_x/schemas`](assistant_x/schemas) are also under CC-BY-4.0 ([`LICENSES/CC-BY-4.0.txt`](LICENSES/CC-BY-4.0.txt), see [`NOTICE`](NOTICE)).
  Bring code or data of others only under a license compatible with these, and say where it comes from.
  A new dependency needs a license compatible with the AGPL-3.0; write it into [`NOTICE`](NOTICE) when it is a program, a model
  or a library with its own notice.
- **No documents of others.** Tests and examples use free or invented documents with neutral names; no real company
  documents, personal data or names of companies and people.

## The rules of the repository

- Everything in the repository is US English: code, comments, messages, documentation. Words that match documents
  (patterns, synonyms, stop words of a language pack or profile) stay in the language of the documents.
- A new source file starts with the two header lines of the others:
  `# Assistant X — Copyright (C) 2026 Alexandr Yalovoy` and `# SPDX-License-Identifier: AGPL-3.0-or-later`
  (add your own copyright line under them if you like).
- Format the code with `python -m ruff format .` (line length 125, pyproject.toml) and run [`scripts\check.ps1`](scripts/check.ps1)
  (`ruff check`, `ruff format --check` and every test) before you send the pull request; add a test for what you
  change.
- Add a line to [`CHANGELOG.md`](CHANGELOG.md) under the version being prepared.

## Releases

- The version is `assistant_x.__version__` (`0.1`, later `0.2`, `0.2.1` for a fix): pyproject.toml, the wheel and
  `assistant-x --version` read it there.
- Releases are tagged `vX.Y[.Z]` on `main` (`v0.1` for `0.1`): an annotated tag on a commit whose CI is green,
  `git tag -a v0.1 -m "Assistant X 0.1"`.
- Until the tag the CHANGELOG heading of the version reads `## 0.1 — unreleased`; in the commit that is tagged it
  gets the date of the tag instead: `## 0.1 — 2026-MM-DD`. The next version then gets a new `unreleased` heading.
- Pushing the tag runs [`.github/workflows/release.yml`](.github/workflows/release.yml): it checks that the tag is the
  version of the code, builds the wheel from a clean copy of the tagged commit, checks that it holds exactly the files
  of `assistant_x/`, and makes the GitHub release with the wheel, its SHA-256 and the CHANGELOG section as the notes.
