# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The journal of the intake moved to core/journal.py (the search checks it too, and core is what both sides share);
this name stays so `python -m assistant_x.intake.journal` and older imports keep working."""

import sys

from assistant_x.core.journal import *  # noqa: F401,F403
from assistant_x.core.journal import main

if __name__ == "__main__":
    sys.exit(main())
