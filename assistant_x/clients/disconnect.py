# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""assistant-x disconnect APP|all [--dry-run]: the entry of the library (and its skill) out of the settings of an app
(clients/connect.py)."""

import sys

from assistant_x.clients.connect import disconnect_main

if __name__ == "__main__":
    sys.exit(disconnect_main())
