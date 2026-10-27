# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The regulator of audit 7 (M-038, M-036, M-037, M-034): a worker is one core, so a free PC runs a worker on every
usable CPU the memory allows; the disk slows the work only by its latency and only at the computer; a line of the
load every minute; the time left by the cost of the files, not by pages."""

import json

from assistant_x.intake import balance, review
from assistant_x.intake.state import State
from assistant_x.server import intake_tools

PC = {"logical": 24, "physical": 16, "avail_gb": 17, "ram_gb": 17, "ecores": None, "gpu": None}


def sample(cpu=30, disk=10, disk_ms=1.0, idle=0, avail=12):
    return {"cpu": cpu, "ours": 20, "disk": disk, "disk_ms": disk_ms, "avail_gb": avail, "idle_s": idle, "temp": None}


def test_a_worker_is_one_core():
    o = balance.options({})
    b = balance.budget(PC, o)
    assert b["threads"] == 1 and b["free"] >= 12 and b["workers"] == b["free"]
    assert b["active"] <= PC["physical"] - 2
    assert balance.budget(PC, o, cap=6)["free"] == 6  # the workers of the settings stay a cap
    assert balance.budget(PC, balance.options({"threads": 2}))["free"] <= (24 - 2) // 2
    assert balance.options({})["cpu_share_idle"] == 0.8


def test_a_busy_fast_disk_does_not_pause():
    b = {"workers": 8, "threads": 1, "free": 8, "active": 8}
    r = balance.Regulator(b, balance.options({"profile": "day"}), PC)
    for t in range(0, 60, 5):  # 100 % busy, 0.2 ms a transfer: an SSD at work, nobody feels it
        n, _, why = r.step(sample(disk=100, disk_ms=0.2), t)
        assert n == 8 and not any("disk" in w or "emergency" in w for w in why)
    n, _, why = r.step(sample(disk=60, disk_ms=80), 70)  # the user at the computer feels a slow disk
    assert n == 7 and any("ms" in w for w in why)
    night = balance.Regulator(b, balance.options({"profile": "night"}), PC)
    assert night.step(sample(disk=60, disk_ms=80), 0)[0] == 8  # nobody at the computer: the disk does not matter


def test_the_line_of_the_load():
    s = {**sample(cpu=42), "ours": 31, "avail_gb": 17.2, "gpu": 0.0}
    assert balance.heartbeat(s, 8, 8) == "cpu 42 % (ours 31 %), workers 8/8 active, mem 17.2 GB free, disk 1 ms, gpu 0 %"
    load = balance.Load()
    load.add({"ours": 30}, 8, 8, 4)
    load.add({"ours": 50}, 4, 8, 120)
    assert balance.load_line(load.data()) == "Load: mean CPU share 40 %, paused 2 min"


def test_time_left_by_cost(tmp_path):
    st = State(tmp_path / "state.sqlite")
    for i in range(5):  # cheap files first: 10 text pages each
        t = st.add(f"small{i}.pdf", 100_000)
        st.update(t, status="done", pages=10)
    big = st.add("scan.pdf", 10_000_000)
    st.update(big, status="queued", pages=100, ocr_pages=100)
    raw = st.add("raw.pdf", 1_000_000)  # not prepared yet: by its bytes
    started = 1000.0
    data = review.status_data(tmp_path, st, started, now=started + 100)  # 5 x 5 s of cost in 100 s
    per_cost = 100 / 25
    cost_big = 100 * 3.3
    bytes_cost = (25 + cost_big) / (5 * 100_000 + 10_000_000) * 1_000_000
    assert data["eta_seconds"] == round((cost_big + bytes_cost) * per_cost)
    pages_eta = round((100 + 21) / (50 / 100))  # what pages per second would promise
    assert data["eta_seconds"] > pages_eta
    st.update(raw, status="error")
    st.update(st.add("x.pdf", 1), status="done")  # a file without pages has no cost
    assert intake_tools.batch_words(review.status_data(tmp_path, st, started, now=started + 100)).count("left") == 1
    st.close()


def test_no_time_left_before_five_files(tmp_path):
    st = State(tmp_path / "state.sqlite")
    for i in range(4):
        st.update(st.add(f"f{i}.pdf", 1), status="done", pages=10)
    st.add("q.pdf", 1)
    assert review.status_data(tmp_path, st, 1000.0, now=1100.0)["eta_seconds"] is None
    st.close()


def test_load_in_the_summary(tmp_path):
    (tmp_path / "load.json").write_text(json.dumps({"mean_ours": 63.4, "paused_s": 600}), encoding="utf-8")
    assert review.load_of(tmp_path) == "Load: mean CPU share 63 %, paused 10 min"
    assert review.load_of(tmp_path / "none") == ""
