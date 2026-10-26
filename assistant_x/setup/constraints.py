# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""assistant_x/setup/constraints.txt: the one list of the exact versions of the packages of Assistant X, made at a release
on the build PC and used by every installation:

    online    setup/install.py: pip install -c constraints.txt -e <code>[dense,intake]; torch, onnxruntime and
              onnxruntime-directml at their versions here (pin())
    offline   prepare-media downloads exactly these versions onto a medium (its requirements-lock.txt is this list)

    python -m assistant_x.setup.constraints --write     the build PC: the dependencies of pyproject.toml (the program and
                                                       the extras dense, intake and dml) with every package they need,
                                                       at the versions installed here
    python -m assistant_x.setup.constraints --check     exit code 1 when the installed versions differ from the file

Reading it (read, pin) needs the standard library only: the installer runs before the environment exists. torch is
listed without its local build ("2.11.0", the CPU and CUDA builds take "+cpu" and "+cu128" of it). The file is package
data, so the installer of a medium and an installed program read the same one."""

import argparse, os, re, sys

CODE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the folder with pyproject.toml
PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "constraints.txt")  # in the package: also in a wheel
EXTRAS = ("dense", "intake", "dml")  # dml: onnxruntime-directml, installed instead of onnxruntime on an AMD or Intel card
BUILD_TOOLS = ("setuptools", "wheel", "pip")  # not pinned here: pip and the build of the program bring their own


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def read(path=None):
    """{normalized name: (name, version)} of the constraints file ({} when there is none)."""
    out = {}
    try:
        lines = open(path or PATH, encoding="utf-8").read().splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if "==" in line:
            name, ver = (x.strip() for x in line.split("==", 1))
            out[norm(name)] = (name, ver)
    return out


def pin(name, path=None):
    """The version of a package in the constraints file; SystemExit when it is not there (a release without it)."""
    got = read(path).get(norm(name))
    if not got:
        raise SystemExit(f"{path or PATH} has no version of {name}: python -m assistant_x.setup.constraints --write")
    return got[1]


def _packaging():
    try:
        from packaging.requirements import Requirement
    except ImportError:  # pip carries its own copy
        from pip._vendor.packaging.requirements import Requirement
    return Requirement


def declared(extras=EXTRAS):
    """The requirements of pyproject.toml: the dependencies and those of the extras given."""
    import tomllib

    data = tomllib.loads(open(os.path.join(CODE, "pyproject.toml"), encoding="utf-8").read())["project"]
    return list(data.get("dependencies") or []) + [r for e in extras for r in (data.get("optional-dependencies") or {})[e]]


def closure(requirements):
    """{normalized name: (name, version)} of the installed packages these requirements need, with every package those
    need in turn (the markers of this PC); a requirement that is not installed: SystemExit."""
    from importlib import metadata

    Requirement = _packaging()
    out, todo = {}, [(Requirement(r), ()) for r in requirements]
    while todo:
        req, extras = todo.pop()
        env_extras = extras or ("",)
        if req.marker and not any(req.marker.evaluate({"extra": e}) for e in env_extras):
            continue
        key = norm(req.name)
        try:
            dist = metadata.distribution(req.name)
        except metadata.PackageNotFoundError:
            raise SystemExit(
                f"{req.name} is not installed here: install the program with its extras "
                f"({', '.join(EXTRAS)}) on the build PC first"
            ) from None
        new = key not in out
        out[key] = (dist.metadata["Name"], dist.version.split("+")[0])
        if new or req.extras:
            todo += [(Requirement(r), tuple(req.extras)) for r in dist.requires or []]
    return out


def current(path=None):
    """{normalized name: (name, version)} of the packages installed here that the program needs (the build tools
    aside: they come with pip and the medium); a package of the extra dml that is not installed (the build PC runs
    onnxruntime, not onnxruntime-directml: they are one module) keeps the version the file has."""
    Requirement = _packaging()
    pins = {k: v for k, v in closure(declared(("dense", "intake"))).items() if k not in BUILD_TOOLS}
    before = read(path)
    for r in declared(("dml",)):
        name = Requirement(r).name
        try:
            pins.update(closure([r]))
        except SystemExit:
            if norm(name) not in before:
                raise SystemExit(f"{name} is neither installed here nor in {path or PATH}: add its line by hand")
            pins[norm(name)] = before[norm(name)]
    return pins


def write(path=None):
    pins = current(path)
    lines = [
        "# The exact versions of the packages of Assistant X: python -m assistant_x.setup.constraints --write on the",
        "# build PC at a release (assistant_x/setup/constraints.py). Used by the online install (pip -c) and by",
        "# prepare-media (the packages of a medium); torch without its local build (+cpu, +cu128).",
    ]
    lines += [f"{name}=={ver}" for _, (name, ver) in sorted(pins.items())]
    with open(path or PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return pins


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m assistant_x.setup.constraints")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.write:
        print(f"{len(write())} packages in {PATH}")
        return 0
    if a.check:
        have, want = current(), read()
        diff = sorted(k for k in set(have) | set(want) if have.get(k, (0, None))[1] != want.get(k, (0, None))[1])
        for k in diff:
            print(f"{k}: installed {have.get(k, (0, '-'))[1]}, constraints {want.get(k, (0, '-'))[1]}")
        return 1 if diff else 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
