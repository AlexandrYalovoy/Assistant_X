# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""LM Studio: mcpServers of ~/.lmstudio/mcp.json (the notation of Cursor); LM Studio reloads its servers when the file
is saved. No skills: the rules reach the model through the tool library_guide and the preset "Assistant X" written
beside the servers (config-presets: the guide as the system prompt, thinking off so that it cannot eat the answer; the
user picks it once in the chat). The one tool `library` with the commands of the reference mode, and the compact
answers, by default: the models of LM Studio are small and local. LM Studio asks before every tool call unless settings.json lists it in
chat.skipToolConfirmationPatterns: connect adds "mcp/assistant-x:*" there (the author, 2026-11-04: no question, or one at
the first start), disconnect takes it out; the other settings stay."""

import json
import os
from pathlib import Path

from assistant_x import clients as K

NAME, TITLE = "lmstudio", "LM Studio"
TOOLSET, COMPACT = "one", True
SETTINGS = "`~/.lmstudio/mcp.json`, `mcpServers`"
SKILL = "the preset `~/.lmstudio/config-presets/Assistant X.preset.json` (the guide as the system prompt)"
PRESET = "Assistant X.preset.json"


def folder():
    return K.home() / ".lmstudio"


def found():
    return folder().is_dir()


def configs():
    return [str(folder() / "mcp.json")]


def read():
    return K.json_entry(configs()[0])


def connect(e, dry):
    path = configs()[0]
    try:
        out = [(path, K.json_connect(path, e, dry))]
    except K.Refused as why:
        out = [(path, f"left alone: {why}; add by hand:\n{K.by_hand(e)}")]
    return out + [write_preset(dry), skip_confirmation(dry)] + model_context(dry)


CONTEXT = 32768  # tokens: the rules, the tool and 15 quote lines fit; at 8192 the model loses the references


def model_keys():
    """The keys of the models of LM Studio as its per-model settings name them: <publisher>/<name> of a model of its
    hub (hub/models), <publisher>/<repo>/<file>.gguf of a downloaded file (the models folder; no mmproj file)."""
    keys = []
    hub = folder() / "hub" / "models"
    if hub.is_dir():
        keys += sorted(f"{p.parent.name}/{p.name}" for p in hub.glob("*/*") if (p / "model.yaml").exists())
    models = models_folder()
    if models.is_dir():
        keys += sorted(
            p.relative_to(models).as_posix() for p in models.glob("*/*/*.gguf") if not p.name.lower().startswith("mmproj")
        )
    return keys


def models_folder():
    try:
        conf = json.loads((folder() / "settings.json").read_text(encoding="utf-8-sig") or "{}")
        given = conf.get("downloadsFolder") if isinstance(conf, dict) else None
    except (OSError, ValueError):
        given = None
    return Path(given) if given else folder() / "models"


def model_context(dry):
    """[(path, status)] of the default load settings of every model of LM Studio (its own per-model files,
    .internal/user-concrete-model-default-config/<key>.json): a context below CONTEXT raised to it, the other
    settings kept. The author, 2026-11-04: a model picked in the chat loaded with 8192 by default, and the answers
    lost their quotes; it must load right by itself. A file that cannot be read is left alone."""
    out = []
    base = folder() / ".internal" / "user-concrete-model-default-config"
    for key in model_keys():
        p = base / f"{key}.json"
        try:
            conf = json.loads(p.read_text(encoding="utf-8-sig") or "{}") if p.exists() else {}
        except (OSError, ValueError) as why:
            out.append((str(p), f"left alone: cannot be read ({why})"))
            continue
        if not isinstance(conf, dict):
            out.append((str(p), "left alone: not a JSON object"))
            continue
        conf.setdefault("preset", "")
        conf.setdefault("operation", {"fields": []})
        load = conf.setdefault("load", {"fields": []})
        fields = load.setdefault("fields", []) if isinstance(load, dict) else None
        if not isinstance(fields, list):
            out.append((str(p), "left alone: no load fields"))
            continue
        ctx = next((f for f in fields if isinstance(f, dict) and f.get("key") == "llm.load.contextLength"), None)
        if ctx is not None and isinstance(ctx.get("value"), int) and ctx["value"] >= CONTEXT:
            continue
        if ctx is None:
            fields.append({"key": "llm.load.contextLength", "value": CONTEXT})
        else:
            ctx["value"] = CONTEXT
        if not dry:  # no backup beside it: LM Studio would read a second file of that folder as another model
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(json.dumps(conf, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, p)
        out.append((str(p), f"context {CONTEXT}" if not dry else f"would set context {CONTEXT}"))
    return out


PATTERN = f"mcp/{K.SERVER}:*"


def skip_confirmation(dry, add=True):
    """(path, status) of PATTERN added to (or taken out of) chat.skipToolConfirmationPatterns of ~/.lmstudio/settings.json;
    a file that is not a JSON object, or missing (LM Studio not started yet), is left alone."""
    p = folder() / "settings.json"
    if not p.exists():
        return (str(p), "left alone: LM Studio has not written its settings yet")
    try:
        conf = json.loads(p.read_text(encoding="utf-8-sig") or "{}")
    except (OSError, ValueError) as why:
        return (str(p), f"left alone: the settings file cannot be read ({why})")
    chat = conf.get("chat", {}) if isinstance(conf, dict) else None
    pats = chat.get("skipToolConfirmationPatterns", []) if isinstance(chat, dict) else None
    if not isinstance(pats, list):
        return (str(p), "left alone: the settings file is not a JSON object with chat.skipToolConfirmationPatterns")
    new = pats + [PATTERN] if add and PATTERN not in pats else [x for x in pats if x != PATTERN] if not add else pats
    if new == pats:
        return (str(p), "unchanged")
    conf.setdefault("chat", {})["skipToolConfirmationPatterns"] = new
    return (str(p), K.put(p, K.json_text(conf), dry))


def disconnect(dry):
    path = configs()[0]
    try:
        out = [(path, K.json_disconnect(path, dry))]
    except K.Refused as why:
        out = [(path, f"left alone: {why}")]
    ours = preset_path()
    if ours.exists():
        if not dry:
            ours.unlink()
        out.append((str(ours), "removed"))
    return out + [skip_confirmation(dry, add=False)]


def preset_path():
    return folder() / "config-presets" / PRESET


def preset():
    """The preset of LM Studio (the format of its config-presets): the rules of the reference mode as the system
    prompt (a small local model quotes the library with its references, the engineering answer is for Claude or
    Codex) and the thinking of the model off (a small model thinking at length leaves no tokens for the answer)."""
    from assistant_x.setup import skill

    return {
        "identifier": "@local:assistant-x",
        "name": "Assistant X",
        "changed": False,
        "operation": {
            "fields": [
                {"key": "llm.prediction.systemPrompt", "value": skill.reference_guide()},
                {"key": "llm.prediction.reasoning.enableThinking", "value": False},
            ]
        },
        "load": {"fields": []},
    }


def write_preset(dry):
    """(path, what happened) for our preset file; no other file of LM Studio is written."""
    path = preset_path()
    text = json.dumps(preset(), ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return (str(path), "unchanged")
    if not dry:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if dry:
        return (str(path), "would write")
    return (str(path), "preset written: pick «Assistant X» in a chat of LM Studio")


def skill_dir():
    return None


def link(e):
    """The "Add to LM Studio" link of an entry: lmstudio://add_mcp with the name and the entry as base64 JSON; opened,
    it asks the user to add the server (for a PC where the entry was not written by connect)."""
    import base64, json, urllib.parse

    config = base64.b64encode(json.dumps(e, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return f"lmstudio://add_mcp?name={K.SERVER}&config={urllib.parse.quote(config, safe='')}"
