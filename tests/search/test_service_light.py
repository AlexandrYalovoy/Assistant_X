# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The library service says in its info file where its models are (device, reranker); doctor warns of a service
that searches on the processor without the reranker (service-light)."""

import json

from assistant_x.server import service


def test_the_info_file_says_where_the_models_are(tmp_path, monkeypatch):
    from assistant_x.server import mcp_server as S

    class Lib:
        _reranker = object()

        def on_card(self):
            return True

        def has_cuda(self):
            return True

    monkeypatch.setattr(S, "_lib", Lib())
    assert service.models_state(True) == {"models": True, "device": "cuda", "reranker": True}
    assert service.models_state(False) == {"models": False, "device": "cpu", "reranker": False}
    path = str(tmp_path / "service.json")
    service.write_info(path, {"pid": 1, "port": 8765})
    monkeypatch.setattr(service, "MODELS_WAIT", 0)
    service.note_models(path, False)
    info = json.load(open(path, encoding="utf-8"))
    assert info["port"] == 8765 and info["models"] is False and service.light(info) is True
    assert service.light({"port": 8765}) is None  # an older service did not say: no warning
    assert service.light({"models": True, "device": "cuda", "reranker": True}) is False


def test_doctor_warns_of_a_light_service(mini, monkeypatch):
    from assistant_x.cli import main as cli
    from assistant_x.core import lock, workspace

    monkeypatch.setattr(lock, "alive", lambda pid, since=None: True)
    w = workspace.Workspace(mini["root"])
    monkeypatch.setattr(service, "read_info", lambda root=None: {"pid": 1, "port": 1, "models": False})
    assert "service-light" in [r["code"] for r in cli.diagnose(w)[1]]
    monkeypatch.setattr(service, "read_info", lambda root=None: {"pid": 1, "port": 1, "models": True, "reranker": True})
    assert "service-light" not in [r["code"] for r in cli.diagnose(w)[1]]
