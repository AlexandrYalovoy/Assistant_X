# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""A base package installed without a command line (the author, 2026-11-01: a colleague with LM Studio only).

Setup.bat, at its end: a .axbase file beside Setup.bat or in its base\ folder is named with its title and count of
documents and installed on a "yes"; with none there, the standard Windows dialog "Open a file" asks for one (Cancel:
go on without a base). Install-Base.bat (a double click, the program installed already): the file beside it, else
the same dialog; the plan of the installation, one confirmation, then "Base installed: N documents".
The messages follow the language of the Windows interface (templates/setup/messages.json: en, ru).

    python -m assistant_x.setup.base_pick [PACKAGE] [--folder DIR] [--yes]    what Install-Base.bat runs

Standard library only (the installer imports it)."""

import argparse, json, locale, os, sys, zipfile
from pathlib import Path

MESSAGES = Path(__file__).resolve().parent.parent / "templates" / "setup" / "messages.json"
EXT = ".axbase"
MANIFEST = "axbase.json"


def language():
    """ "ru" when the interface of Windows (else the locale) is Russian, else "en"."""
    lang = ""
    if os.name == "nt":
        try:
            import ctypes

            lang = "ru" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x19 else "en"
        except (AttributeError, OSError):
            lang = ""
    if not lang:
        lang = "ru" if (locale.getlocale()[0] or "").lower().startswith(("ru", "russian")) else "en"
    return lang


def texts(lang=None):
    data = json.loads(MESSAGES.read_text(encoding="utf-8"))
    return data.get(lang or language()) or data["en"]


def packages(*folders):
    """The base packages (.axbase files, or folders holding axbase.json) in these folders and in their base\\ folder,
    the newest first."""
    out = []
    for d in folders:
        for top in (Path(d), Path(d) / "base"):
            if not top.is_dir():
                continue
            for p in top.iterdir():
                if (p.is_file() and p.suffix.lower() == EXT) or (p.is_dir() and (p / MANIFEST).is_file()):
                    out.append(p)
    return sorted(dict.fromkeys(out), key=lambda p: p.stat().st_mtime, reverse=True)


def describe(path):
    """(the title of a package in the language given or English, its count of documents) from its axbase.json."""
    path = Path(path)
    try:
        if path.is_dir():
            man = json.loads((path / MANIFEST).read_text(encoding="utf-8"))
        else:
            with zipfile.ZipFile(path) as z:
                man = json.loads(z.read(MANIFEST).decode("utf-8"))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return path.stem, "?"
    name = man.get("name") or {}
    title = (name.get(language()) or name.get("en") or man.get("id") or path.stem) if isinstance(name, dict) else name
    return str(title), man.get("documents", "?")


def dialog(title, msgs):
    """The path chosen in the standard Windows dialog "Open a file", or None (Cancel, or no dialog here)."""
    if os.name != "nt":
        return None
    from assistant_x.core import proc

    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$d = New-Object System.Windows.Forms.OpenFileDialog;"
        f"$d.Title = '{title.replace(chr(39), chr(39) * 2)}';"
        f"$d.Filter = '{msgs['dialog_filter'].replace(chr(39), chr(39) * 2)}';"
        "$d.InitialDirectory = [Environment]::GetFolderPath('Desktop');"
        "if ($d.ShowDialog() -eq 'OK') { [Console]::OutputEncoding = [Text.Encoding]::UTF8; $d.FileName }"
    )
    try:
        p = proc.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
        )
    except (OSError, proc.TimeoutExpired):
        return None
    chosen = (p.stdout or "").strip().splitlines()
    return chosen[-1] if chosen and os.path.exists(chosen[-1]) else None


def choose(folders, ask=input, pick=dialog, yes=False, alone=False, say=print):
    """The base package to install, or None: one found in folders is offered with its title and count (a "yes"
    installs it, --yes takes it at once); with none there the dialog asks for one (not with --yes: no window then)."""
    msgs = texts()
    found = packages(*folders)
    if found:
        title, n = describe(found[0])
        if yes:
            return str(found[0])
        try:
            answer = ask(msgs["found"].format(name=title, documents=n, file=found[0].name))
        except (EOFError, KeyboardInterrupt):
            return None
        return str(found[0]) if answer.strip().lower() in msgs["yes"] else None
    if yes:
        return None
    chosen = pick(msgs["dialog_title_alone" if alone else "dialog_title"], msgs)
    if not chosen:
        say(msgs["no_base"] if not alone else msgs["cancelled"])
    return chosen


def installed_python():
    """The python of the installed program (the environment of the machine folder), or None."""
    from assistant_x.core import workspace

    machine = Path(workspace.machine_dir())
    try:  # the one in use (setup/install.py and self_update.py write it), else the environment of the first install
        py = Path((machine / "python.txt").read_text(encoding="utf-8").strip())
    except OSError:
        py = machine / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(py) if py.is_file() else None


INTERRUPTED = "was interrupted (started"  # the answer of base install when an install of the package is open


def install(path, py, ask=input, say=print):
    """The plan of the installation shown, one confirmation, the install; True when it is in."""
    from assistant_x.core import proc

    msgs = texts()
    base = [py, "-m", "assistant_x.base.cli", "install", str(path)]
    env = dict(os.environ, PYTHONUTF8="1")
    plan = proc.run(base, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    # the plan without its hint for the command line ("the same command with --confirm"): the question below is it
    said = plan.stdout + plan.stderr
    say("\n".join(ln for ln in said.splitlines() if not ln.startswith("Nothing changed.")))
    resume = bool(plan.returncode) and INTERRUPTED in said  # an install of this package stopped midway: it goes on
    if plan.returncode and not resume:
        say(msgs["failed"])
        return False
    try:
        if ask(msgs["interrupted" if resume else "plan"]).strip().lower() not in msgs["yes"]:
            say(msgs["cancelled"])
            return False
    except (EOFError, KeyboardInterrupt):
        say(msgs["cancelled"])
        return False
    more = ["--resume"] if resume else ["--confirm"]
    done = proc.run(base + more, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    say(done.stdout + done.stderr)
    if done.returncode:  # stopped before its start or midway: the next double click shows the plan or goes on
        say(msgs["stopped"])
        return False
    say(msgs["done"].format(documents=describe(path)[1]))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(prog="Install-Base.bat", description=__doc__.split("\n\n")[0])
    ap.add_argument("package", nargs="?", help="the .axbase file (default: one beside Install-Base.bat, else a dialog)")
    ap.add_argument("--folder", default=os.getcwd(), help="where to look for a .axbase file (Install-Base.bat: its own)")
    a = ap.parse_args(argv)
    msgs = texts()
    py = installed_python()
    if not py:
        print(msgs["no_program"])
        return 1
    path = a.package or choose([a.folder], alone=True)
    if not path:
        return 1
    return 0 if install(path, py) else 1


if __name__ == "__main__":
    sys.exit(main())
