# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""State of one intake batch: work/<date>/state.sqlite.
Only the main process of intake.py writes; workers return results. One row per file of inbox:
tid (T0001…), rel (path inside inbox with /), size, status, why, data (JSON with everything else).

status: queued → done | dup | error | skipped; applied after assistant-x intake apply.
"""

import json, sqlite3, time

SCHEMA = """CREATE TABLE IF NOT EXISTS files(tid TEXT PRIMARY KEY, rel TEXT UNIQUE NOT NULL, size INTEGER,
  status TEXT NOT NULL, why TEXT, data TEXT NOT NULL DEFAULT '{}', updated REAL);
CREATE INDEX IF NOT EXISTS files_status ON files(status);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);"""
COLUMNS = ("tid", "rel", "size", "status", "why")
OPEN = ("queued", "running")


class State:
    def __init__(self, path):
        self.path = str(path)
        self.con = sqlite3.connect(self.path, timeout=30)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(SCHEMA)

    def close(self):
        self.con.close()

    def _row(self, r):
        return None if r is None else {**json.loads(r["data"]), **{k: r[k] for k in COLUMNS}}

    def add(self, rel, size, **data):
        """tid of the file; a file seen before keeps its tid and state."""
        r = self.con.execute("SELECT tid FROM files WHERE rel=?", (rel,)).fetchone()
        if r:
            return r[0]
        n = self.con.execute("SELECT coalesce(max(CAST(substr(tid, 2) AS INTEGER)), 0) FROM files").fetchone()[0] + 1
        tid = f"T{n:04d}"
        self.con.execute(
            "INSERT INTO files(tid, rel, size, status, data, updated) VALUES(?,?,?,?,?,?)",
            (tid, rel, size, "queued", json.dumps(data, ensure_ascii=False), time.time()),
        )
        self.con.commit()
        return tid

    def get(self, tid):
        return self._row(self.con.execute("SELECT * FROM files WHERE tid=?", (tid,)).fetchone())

    def by_rel(self, rel):
        return self._row(self.con.execute("SELECT * FROM files WHERE rel=?", (rel,)).fetchone())

    def update(self, tid, **kw):
        """Merge fields; tid/rel/size/status/why go to their columns, the rest to data."""
        r = self.con.execute("SELECT data FROM files WHERE tid=?", (tid,)).fetchone()
        if r is None:
            raise KeyError(tid)
        data = json.loads(r[0])
        cols = {k: kw.pop(k) for k in list(kw) if k in COLUMNS[2:]}
        data.update(kw)
        sets = ", ".join(f"{k}=?" for k in cols)
        self.con.execute(
            f"UPDATE files SET {sets + ', ' if sets else ''}data=?, updated=? WHERE tid=?",
            (*cols.values(), json.dumps(data, ensure_ascii=False), time.time(), tid),
        )
        self.con.commit()

    def all(self, *statuses):
        q = "SELECT * FROM files" + (f" WHERE status IN ({','.join('?' * len(statuses))})" if statuses else "")
        return [self._row(r) for r in self.con.execute(q + " ORDER BY tid", statuses)]

    def counts(self):
        return dict(self.con.execute("SELECT status, count(*) FROM files GROUP BY status").fetchall())

    def reset_running(self):
        """After a crash or Ctrl+C: files that were being processed go back to the queue (the cache keeps pages done)."""
        n = self.con.execute("UPDATE files SET status='queued' WHERE status='running'").rowcount
        self.con.commit()
        return n

    def get_meta(self, key, default=None):
        r = self.con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def set_meta(self, key, value):
        self.con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))
        self.con.commit()
