# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""The workspace: the user's folder with the documents, the index and everything the tool writes. The code never
writes into its own folder.

    <workspace>\assistant_x.toml          settings (shared, may go to Git)
    <workspace>\assistant_x.local.toml    settings of this PC (program paths); not in Git
    <workspace>\inbox                     new documents
    <workspace>\library                   the originals, by section
    <workspace>\index                     catalog, cards, texts, journal
    <workspace>\reports                   reports of the intake
    <workspace>\.assistant_x\db           the search base and its vectors
    <workspace>\.assistant_x\models       embedding and reranking models kept with the workspace (or a link to them):
                                          when the folder is there, it is used instead of the models of the PC
    <workspace>\.assistant_x\work         batches of the intake
    <workspace>\.assistant_x\debug        failure and call journals, debug reports
    %LOCALAPPDATA%\AssistantX             per PC: the program (app\<version>, venv), the models (models), the
                                          bundled programs (programs), the machine lock; AX_MACHINE_DIR moves it

The models are of the PC: %LOCALAPPDATA%\AssistantX\models, unless [paths] models of assistant_x.toml names a folder or
the workspace has its own .assistant_x\models (an older workspace; a linked folder of models stays where it is).

Which workspace: AX_WORKSPACE, else the folder of AX_CONFIG, else the nearest folder holding assistant_x.toml from
the current folder up, else the default Documents\Assistant X (chosen at `assistant-x init`).
"""

import functools, os
from pathlib import Path

from assistant_x.core import env

CONFIG = "assistant_x.toml"
LOCAL_CONFIG = "assistant_x.local.toml"
DATA = ".assistant_x"
DEFAULT_NAME = "Assistant X"


def default_root():
    return Path.home() / "Documents" / DEFAULT_NAME


def machine_dir():
    r"""Per-PC folder outside any workspace: %LOCALAPPDATA%\AssistantX (~/.cache/AssistantX elsewhere); AX_MACHINE_DIR
    gives another one (the tests)."""
    given = env.get("MACHINE_DIR")
    if given:
        return Path(given)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    return Path(base) / "AssistantX"


def find(start=None):
    """Root of the workspace in use (it may not exist yet: `assistant-x init` makes it)."""
    given = env.get("WORKSPACE")
    if given:
        return Path(given).resolve()
    cfg = env.get("CONFIG")
    if cfg and not cfg.lower().endswith(".json"):
        return Path(cfg).resolve().parent
    here = Path(start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / CONFIG).is_file():
            return d
    return default_root()


class Workspace:
    """Folders of one workspace. Paths only; nothing is created here (ensure() does)."""

    def __init__(self, root=None, paths=None):
        self.root = Path(root).resolve() if root else find()
        p = paths or {}

        def at(key, default):
            return (self.root / (p.get(key) or default)).resolve()

        self.config = self.root / CONFIG
        self.local_config = self.root / LOCAL_CONFIG
        self.inbox = at("inbox", "inbox")
        self.library = at("library", "library")
        self.index = at("index", "index")
        self.reports = at("reports", "reports")
        self.data = at("data", DATA)
        self.db = at("db", Path(DATA) / "db")
        own = self.data / "models"  # models kept with the workspace (or a link to them), else those of the PC
        self.models = at("models", "") if p.get("models") else own if own.exists() else machine_dir() / "models"
        self.packages = at("packages", Path(DATA) / "packages")  # an older offline installation: its wheels
        self.work = at("work", Path(DATA) / "work")
        self.debug = at("debug", Path(DATA) / "debug")
        self.fingerprints = self.data / "fingerprints"
        self.ocr_vocab = self.data / "ocr_vocab.txt"
        self.cards = self.index / "cards"
        self.texts = self.index / "texts"
        self.catalog = self.index / "CATALOG.md"

    def __repr__(self):
        return f"Workspace({str(self.root)!r})"

    def exists(self):
        return self.config.is_file()

    def ensure(self, *names):
        """Make the folders named (all the data folders when none are named); returns self."""
        for n in names or ("inbox", "library", "index", "reports", "db", "work", "debug"):
            getattr(self, n).mkdir(parents=True, exist_ok=True)
        return self


@functools.lru_cache(maxsize=None)
def _current(root):
    from assistant_x.core import config

    return Workspace(root, config.read(Path(root) / CONFIG).get("paths"))


def current():
    """The workspace of this process (found anew when AX_WORKSPACE changes, as in the tests)."""
    return _current(str(find()))


def reset():
    _current.cache_clear()
