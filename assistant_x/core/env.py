# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Environment variables of Assistant X: AX_<NAME>."""

import os


def get(name, default=None):
    """AX_<name>, else default. Empty values count as unset."""
    return os.environ.get("AX_" + name) or default


def flag(name):
    return bool(get(name))


# the libraries of the models keep their progress bars, warnings and info boxes out of the console and of the logs
# Claude reads (the background jobs of the server, the model commands of the command line)
QUIET = {
    "TQDM_DISABLE": "1",
    "HF_HUB_DISABLE_PROGRESS_BARS": "1",
    "TRANSFORMERS_VERBOSITY": "error",
    "TRANSFORMERS_NO_ADVISORY_WARNINGS": "1",
    "PYTHONWARNINGS": "ignore",
}


def quiet(environ):
    """QUIET put into environ where it has no value of its own (set by the user, it stays)."""
    return {**environ, **{k: v for k, v in QUIET.items() if k not in environ}}


def quiet_here():
    """This process (a model command of the command line), before the libraries of the models are imported: QUIET in
    its environment, the Python warnings off unless the user set PYTHONWARNINGS, and the note of torch about
    redirects (a logging line, not a warning) left out."""
    import logging, warnings

    if "PYTHONWARNINGS" not in os.environ:
        warnings.simplefilter("ignore")
    os.environ.update(quiet(os.environ))
    logging.getLogger("torch.distributed.elastic.multiprocessing.redirects").setLevel(logging.ERROR)
