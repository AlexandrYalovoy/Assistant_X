# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""assistant-x base <command>: base packages.

assistant-x base export OUT.axbase --id ID --version V ...   the library of this workspace as a package
assistant-x base inspect PACKAGE [--keep own|package]          what installing it here would do (changes nothing)
assistant-x base install PACKAGE [--confirm] [--resume | --rollback] ...   install it (base/install.py)
assistant-x base update PACKAGE [--confirm] [--resume | --rollback]     a new version of an installed package
assistant-x base remove ID [--confirm] [--resume | --rollback]          an installed package out of the library"""

import sys

COMMANDS = {
    "export": "assistant_x.base.export",
    "inspect": "assistant_x.base.inspection",
    "install": "assistant_x.base.install",
    "update": "assistant_x.base.update:main_update",
    "remove": "assistant_x.base.update:main_remove",
}


def main(argv=None):
    import importlib

    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        return 0 if argv[:1] in ([], ["help"], ["-h"], ["--help"]) else 2
    module, _, func = COMMANDS[argv[0]].partition(":")
    return getattr(importlib.import_module(module), func or "main")(argv[1:])


if __name__ == "__main__":
    sys.exit(main())
