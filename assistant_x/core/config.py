# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Settings: <workspace>/assistant_x.toml with <workspace>/assistant_x.local.toml (this PC) over it, over the
defaults below. One file for the search and the intake:

    profile = "general"               # domain data: synonyms, the wording of the skill (assistant_x/profiles)
    [documents] languages = ["ru", "en"]   # the language packs used to read documents (assistant_x/lang)
    [paths]                           # folders, relative to the workspace (core/workspace.py has the defaults)
    [search]                          # the search and the models
    [intake]                          # the intake (program paths go to the local file)
"""

import functools, json, os, sys, tomllib
from pathlib import Path

from assistant_x.core import workspace as ws_mod

PROFILE = "general"  # the default profile; "oil-gas-ru" is chosen at assistant-x init --profile oil-gas-ru
PROFILES = Path(__file__).resolve().parent.parent / "profiles"
SEARCH = {
    "embed_model": "bge-m3",  # a folder in the models folder, or a HuggingFace name (BAAI/bge-m3)
    "rerank_model": "bge-reranker-v2-m3",
    "rerank": "auto",  # "auto": every question on a video card (search/retrieval.want_rerank)
    "rerank_weight": 1.0,  # the reranker's share in the final score, beside the normalized hybrid one
    "max_seq_length": 1024,  # tokens the embedding model reads of a fragment and of a question
    # on a processor bge-m3 in int8 ONNX when models/onnx/bge-m3/model.int8.onnx is there: faster, but its vectors are
    # about 2 % different (cosine 0.98 to those of the full model), so off unless asked
    "cpu_int8": False,
    "backend": "auto",
    "gpu_min_free_gb": 5,
    "gpu_wait_minutes": 60,
    "table_rows": False,  # embed a table as a line per row "header: value; …" (search/embed.py)
}
# the defaults of [intake]: the one place for them (intake/config.py, intake/balance.py, core/common.DISK read them)
INTAKE = {
    "stage_mode": "inproc",
    "workers": 8,
    "profile": "auto",
    "priority": "below_normal",
    "affinity": "auto",
    "idle_minutes": 7,
    "cpu_share_idle": 0.75,
    "cpu_share_active": 0.5,
    "temp_max_c": 85,
    "temp_cool_c": 75,
    "heavy_mb": 40,
    "ocr_shards": "auto",
    "ocr_threads": 2,
    "worker_memory_mb": 3072,
    "timeouts": {"soffice": 900, "hidden": 1800, "convert": 14400, "unpack": 1800},
    "unpack": {"max_total_gb": 5, "max_depth": 3},
    "disk": {"factor": 3, "min_free_gb": 10},
}
INTAKE_INTS = ("workers", "ocr_threads", "worker_memory_mb")  # numbers of [intake] that AX_<NAME> may override
LOCAL_KEYS = ("soffice", "tesseract", "tessdata", "sevenzip", "ddjvu")  # paths of programs: this PC only


def merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def local_of(path):
    return Path(path).with_name(ws_mod.LOCAL_CONFIG)


def read(path):
    """assistant_x.toml with assistant_x.local.toml beside it over it; {} when neither is there. The paths of
    programs (LOCAL_KEYS) are read only from the local file: the shared one may come from someone else (a package, a
    copied workspace) and must not choose which program runs on this PC."""
    path = Path(path)
    out = {}
    for p in (path, local_of(path)):
        if p.is_file():
            with open(p, "rb") as f:
                try:
                    data = tomllib.load(f)
                except tomllib.TOMLDecodeError as e:
                    sys.exit(f"{p}: {e}")
            if p == path and isinstance(data.get("intake"), dict):
                data["intake"] = {k: v for k, v in data["intake"].items() if k not in LOCAL_KEYS}
            out = merge(out, data)
    return out


def config_path(path=None):
    """The assistant_x.toml in use: the one given, AX_CONFIG, or the one of the workspace found."""
    from assistant_x.core import env

    given = path or env.get("CONFIG")
    return Path(given).resolve() if given else ws_mod.find() / ws_mod.CONFIG


def load(path=None):
    """(workspace, settings with the defaults under them)."""
    path = config_path(path)
    raw = read(path)
    w = ws_mod.Workspace(path.parent, raw.get("paths"))
    raw.setdefault("profile", PROFILE)
    raw["search"] = merge(SEARCH, raw.get("search"))
    raw["intake"] = merge(INTAKE, raw.get("intake"))
    return w, raw


def profile_dir(name=None):
    return PROFILES / (name or PROFILE)


def profiles():
    return sorted(p.name for p in PROFILES.iterdir() if (p / "profile.json").is_file())


def profile_info(raw=None):
    """profile.json of the profile in use (its name, the wording of the skill, its data files); a missing profile is
    an error.
    raw: the settings (or the search settings, or {"profile": name}); None: the default profile."""
    name = (raw or {}).get("domain_profile") or (raw or {}).get("profile") or PROFILE  # the intake: "profile" is its load
    return _profile(name)


@functools.lru_cache(maxsize=8)
def _profile(name):
    p = profile_dir(name) / "profile.json"
    if not p.is_file():
        sys.exit(f"No profile {name!r} (profiles: {', '.join(profiles())}); set `profile` in assistant_x.toml")
    return json.loads(p.read_text(encoding="utf-8"))


SHELVES = Path(__file__).resolve().parent.parent / "schemas" / "shelves.json"


@functools.lru_cache(maxsize=1)
def _shelves():
    return json.loads(SHELVES.read_text(encoding="utf-8"))["shelves"]


def sections(raw=None):
    """The shelves of every library (schemas/shelves.json, the same whatever the profile): [{letter, folder,
    name: {en, ru}, about, doc_types}], in order. raw is accepted for the callers and not used."""
    return _shelves()


def section(letter, raw=None):
    """The shelf of a letter, or None."""
    return next((s for s in sections(raw) if s["letter"] == letter), None)


def section_name(letter, raw=None, lang="en"):
    """'N' -> 'Standards' (the name in lang, else English); an unknown letter is returned as it is."""
    s = section(letter, raw)
    return (s["name"].get(lang) or s["name"]["en"]) if s else letter


def section_letter(name, raw=None):
    """The letter of a shelf from its letter, its name in any language or its folder ('Standards', 'n', '01_Standards',
    'Datasheets', 'Datasheets and catalogs': the first word too); None for an unknown one."""
    s = (name or "").strip()
    if not s:
        return None
    for cand in (s.lower(), s.split()[0].lower()):
        for sec in sections(raw):
            if (
                cand == sec["letter"].lower()
                or cand in (sec["folder"].lower(), sec["folder"].split("_", 1)[-1].lower())
                or cand in (n.lower() for n in sec["name"].values())
            ):
                return sec["letter"]
    return None


def card_languages(raw=None):
    """The languages every searchable text of a card has: English first, then every language the documents are read
    in ([documents] languages of the settings raw, else of the workspace; by default Russian and English)."""
    given = ((raw or {}).get("documents") or {}).get("languages")
    if not given:
        from assistant_x.core import lang

        given = lang.active()
    return list(dict.fromkeys(["en", *given]))


def topics(raw=None):
    """The controlled list of topic ids of the profile ({id: {language: name}}), or None when it gives none (then the
    topics of a card are free ids, and the intake shows Claude the ones the library uses already)."""
    t = profile_info(raw).get("topics")
    return {x["id"]: x.get("name", {}) for x in t} if t else None


def doc_types():
    """The genres of the documents (doc_type of the cards): one universal list, schemas/card-1.json."""
    from assistant_x.core import card

    return card.doc_types()


def profile_file(name, raw=None):
    """A data file of the profile in use; None when the profile has no such file."""
    p = profile_dir((raw or {}).get("profile")) / name
    return p if p.is_file() else None


def read_profile_json(name, raw=None, default=None):
    p = profile_file(name, raw)
    if not p:
        return default
    return json.loads(p.read_text(encoding="utf-8"))


# --- writing (the local file of this PC, or values of the shared file) ---


def toml_value(v):
    """A value as TOML: strings escaped as JSON strings (a TOML basic string is one), so a value never closes its
    quotes and adds keys of its own."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)  # a TOML basic string is a JSON string


def dumps(data, prefix=""):
    """TOML text of a dict of scalars, lists and tables (None values are left out)."""
    lines, tables = [], []
    for k, v in data.items():
        if v is None:
            continue
        if isinstance(v, dict):
            tables.append((k, v))
        else:
            lines.append(f"{k} = {toml_value(v)}")
    for k, v in tables:
        name = f"{prefix}.{k}" if prefix else k
        body = dumps(v, name)
        lines += ["", f"[{name}]", *([body] if body else [])]
    return "\n".join(lines).strip("\n")


def save(updates, section="intake", path=None):
    """Write values of a section: program paths into assistant_x.local.toml, the rest into assistant_x.toml.
    Rewriting a file keeps its values but not its comments."""
    path = config_path(path)
    for target, part in (
        (path, {k: v for k, v in updates.items() if k not in LOCAL_KEYS}),
        (local_of(path), {k: v for k, v in updates.items() if k in LOCAL_KEYS}),
    ):
        if not part:
            continue
        data = {}
        if target.is_file():
            with open(target, "rb") as f:
                data = tomllib.load(f)
        data[section] = merge(data.get(section, {}), part)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(dumps(data) + "\n", encoding="utf-8", newline="\n")
        os.replace(tmp, target)
