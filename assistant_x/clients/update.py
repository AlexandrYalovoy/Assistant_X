# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""assistant-x update: every app of connections.json connected again with its own settings, its skill refreshed
(clients/connect.py)."""

import sys

from assistant_x.clients.connect import update_main

if __name__ == "__main__":
    sys.exit(update_main())
