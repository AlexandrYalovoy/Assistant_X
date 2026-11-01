# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""assistant-x update --from URL: a newer release of the program from its GitHub or GitFlic page, side by side.

    assistant-x update --from https://github.com/OWNER/REPO [--dry-run] [--force]
    assistant-x update --from https://gitflic.ru/project/OWNER/REPO

1. The latest release with a tag (a draft, a pre-release or the last commit of a branch is never taken): its version,
   its wheel assistant_x-<version>-py3-none-any.whl and its SHA256SUMS (or SHA256SUMS.txt).
2. Nothing to do when this version is that one or newer (--force installs it again).
3. The wheel is downloaded into the machine folder (updates\<version>) and checked against SHA256SUMS: a release
   without the sum of its wheel is refused.
4. A new environment venv-<version> beside the one in use: it sees the packages of the old one (a .pth line), so only
   what the new version needs more is installed; the program is installed into it from the wheel.
5. The apps are connected again with the new python (assistant-x update: the entries and the skills), and assistant-x
   doctor --json runs there. When a step fails, the apps are connected back to the old python, the new environment
   is removed and the old one keeps working.
The library, the workspace and its settings are never touched; the old environment stays (an older one than the
previous version is removed only by hand). Standard library only."""

import argparse, json, os, re, shutil, sys, urllib.parse, urllib.request
from pathlib import Path

from assistant_x.core import proc, workspace

WHEEL_RX = re.compile(r"^assistant_x-(\d+(?:\.\d+)*)-py3-none-any\.whl$")
SUMS = ("SHA256SUMS", "SHA256SUMS.txt")
TIMEOUT = 60


def say(msg=""):
    print(msg, flush=True)


def version_key(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v)))


def source(url):
    """("github" | "gitflic", owner, repository) of the page of a project, SystemExit for another address."""
    u = urllib.parse.urlparse(url.strip())
    parts = [p for p in u.path.split("/") if p]
    host = (u.hostname or "").lower()
    if host in ("github.com", "www.github.com") and len(parts) >= 2:
        return "github", parts[0], parts[1].removesuffix(".git")
    if host in ("gitflic.ru", "www.gitflic.ru") and len(parts) >= 3 and parts[0] == "project":
        return "gitflic", parts[1], parts[2].removesuffix(".git")
    raise SystemExit(f"Not the page of a project on GitHub or GitFlic: {url} (https://github.com/OWNER/REPO)")


def get_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "assistant-x-update"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 — an https address built here
        return json.loads(r.read().decode("utf-8"))


def latest(kind, owner, repo):
    """{tag, version, assets: {name: url}} of the latest release with a tag."""
    if kind == "github":
        rel = get_json(f"https://api.github.com/repos/{owner}/{repo}/releases/latest")  # never a draft or pre-release
        if rel.get("draft") or rel.get("prerelease"):
            raise SystemExit("The latest release is a draft or a pre-release: nothing to install")
        assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets") or []}
        tag = rel.get("tag_name") or ""
    else:
        rels = get_json(f"https://api.gitflic.ru/project/{owner}/{repo}/release")
        rels = rels.get("_embedded", {}).get("releaseTagModelList", rels) if isinstance(rels, dict) else rels
        rels = [r for r in rels or [] if not r.get("isDraft") and not r.get("isPrerelease")]
        if not rels:
            raise SystemExit("The project has no release with a tag")
        rel = max(rels, key=lambda r: version_key(r.get("tagName") or ""))
        tag = rel.get("tagName") or ""
        assets = {
            a.get("name") or a.get("fileName"): a.get("link") or a.get("downloadUrl")
            for a in rel.get("attachmentFiles") or rel.get("assets") or []
        }
    wheels = {WHEEL_RX.match(n).group(1): n for n in assets if n and WHEEL_RX.match(n)}
    if not wheels:
        raise SystemExit(f"The release {tag} has no wheel assistant_x-<version>-py3-none-any.whl")
    version = max(wheels, key=version_key)
    return {"tag": tag, "version": version, "wheel": wheels[version], "assets": assets}


def sum_of(text, name):
    for line in text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+)$", line.strip())
        if m and m.group(2).strip() == name:
            return m.group(1).lower()
    return None


def download(rel, folder, say=say):
    """The wheel of the release in folder, checked against its SHA256SUMS; its path."""
    from assistant_x.setup import downloads

    sums = next((n for n in SUMS if n in rel["assets"]), None)
    if not sums:
        raise SystemExit(f"The release {rel['tag']} has no SHA256SUMS: its wheel cannot be checked, not installed")
    os.makedirs(folder, exist_ok=True)
    sums_path = downloads.fetch(rel["assets"][sums], None, os.path.join(folder, sums), say=say)
    sha = sum_of(Path(sums_path).read_text(encoding="utf-8", errors="replace"), rel["wheel"])
    if not sha:
        raise SystemExit(f"{sums} of the release {rel['tag']} names no sum of {rel['wheel']}: not installed")
    return downloads.fetch(rel["assets"][rel["wheel"]], sha, os.path.join(folder, rel["wheel"]), say=say)


def venv_python(d):
    return os.path.join(d, "Scripts", "python.exe") if os.name == "nt" else os.path.join(d, "bin", "python")


def site_packages(py):
    out = proc.run(
        [py, "-c", "import sys; print(next(p for p in sys.path if p.endswith('site-packages')))"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return out.stdout.strip()


def run(cmd, dry):
    if dry:
        say("   would run: " + " ".join(cmd))
        return 0
    return proc.call(cmd)


def install(old_py, wheel, new_dir, dry):
    """A new environment new_dir that sees the packages of old_py, the program installed into it; its python."""
    base = getattr(sys, "_base_executable", None) or sys.executable
    new_py = venv_python(new_dir)
    if run([base, "-m", "venv", new_dir], dry):
        raise SystemExit(f"The new environment {new_dir} could not be made")
    if not dry:
        old_site = site_packages(old_py)
        new_site = site_packages(new_py)
        Path(new_site, "_assistant_x_previous.pth").write_text(old_site + "\n", encoding="utf-8")
    if run(
        [new_py, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade-strategy", "only-if-needed", wheel], dry
    ):
        raise SystemExit(f"The program could not be installed into {new_dir}")
    return new_py


def reconnect(py, dry):
    return run([py, "-m", "assistant_x.cli.main", "update"], dry)


def doctor(py, dry):
    if dry:
        return True
    out = proc.run([py, "-m", "assistant_x.cli.main", "doctor", "--json"], capture_output=True, text=True, timeout=600)
    try:
        return bool(json.loads(out.stdout).get("ok"))
    except ValueError:
        return False


def update(url, dry=False, force=False, old_py=None):
    from assistant_x import __version__

    old_py = old_py or sys.executable
    kind, owner, repo = source(url)
    rel = latest(kind, owner, repo)
    say(f"This program: {__version__}; the latest release of {owner}/{repo}: {rel['tag']} ({rel['version']})")
    if version_key(rel["version"]) <= version_key(__version__) and not force:
        say("Nothing to do: this version is the latest one (--force installs the release again).")
        return 0
    machine = workspace.machine_dir()
    folder = os.path.join(str(machine), "updates", rel["version"])
    new_dir = os.path.join(str(machine), f"venv-{rel['version']}")
    if dry:
        say(f"Would download {rel['wheel']} with its SHA256SUMS into {folder}, install it into {new_dir} beside the")
        say(f"environment in use ({old_py}), connect the apps again and run doctor; the library stays as it is.")
        return 0
    wheel = download(rel, folder)
    if os.path.exists(new_dir):
        shutil.rmtree(new_dir)
    try:
        new_py = install(old_py, wheel, new_dir, dry)
        if reconnect(new_py, dry) or not doctor(new_py, dry):
            raise SystemExit("assistant-x doctor found a problem in the new version")
    except (SystemExit, OSError, ValueError, proc.SubprocessError) as e:
        say(f"The update failed ({e}): the apps are connected back to {old_py}; the new environment is removed.")
        reconnect(old_py, dry)
        shutil.rmtree(new_dir, ignore_errors=True)
        return 1
    say(f"Updated to {rel['version']}: {new_py}. Restart the apps (Claude, Codex, LM Studio …) to use it.")
    say(f"The old environment stays for a return: {os.path.dirname(os.path.dirname(old_py))}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="assistant-x update", description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="url", required=True, help="the page of the project on GitHub or GitFlic")
    ap.add_argument("--dry-run", action="store_true", help="say what would be done, download nothing")
    ap.add_argument("--force", action="store_true", help="install the latest release even when it is this version")
    a = ap.parse_args(argv)
    return update(a.url, a.dry_run, a.force)


if __name__ == "__main__":
    sys.exit(main())
