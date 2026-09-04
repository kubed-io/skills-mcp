#!/usr/bin/env python3
"""Fetch the skill sources declared in skills.toml.

Runs in the Docker build (and locally for development). Each source is fetched
at its pinned commit and its ``path`` subdirectory is copied to
``<out>/<name>/``, which is the layout the server scans. Any ``extras``
directories are copied alongside for ``read_pack_file`` to serve.

Deliberately dependency-free: ``tomllib`` is stdlib on 3.11+, so this runs in a
plain python image before the project itself is installed.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import tomllib


def run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        args, cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def resolve_head(repo: str) -> str:
    """Return the commit the source repo's default branch currently points at."""
    out = run("git", "ls-remote", repo, "HEAD")
    return out.split()[0]


def update_manifest(manifest_path: Path, sources: list[dict]) -> list[str]:
    """Repin every source to its upstream HEAD; return the sources that moved.

    Rewrites only the ``ref`` line inside each ``[[source]]`` block so the file
    stays byte-stable everywhere else and the diff is one line per bump.
    """
    lines = manifest_path.read_text().splitlines(keepends=True)
    latest = {s["name"]: resolve_head(s["repo"]) for s in sources}
    current = {s["name"]: s["ref"] for s in sources}
    moved = [n for n in latest if latest[n] != current[n]]

    name = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("name ="):
            name = stripped.split("=", 1)[1].strip().strip('"')
        elif stripped.startswith("ref =") and name in latest:
            lines[i] = f'ref = "{latest[name]}"\n'

    manifest_path.write_text("".join(lines))
    for n in sorted(latest):
        state = f"{current[n][:12]} -> {latest[n][:12]}" if n in moved else "unchanged"
        print(f"  {n:10} {state}")
    return moved


def fetch(source: dict, out: Path, workdir: Path) -> int:
    """Fetch one source at its pinned ref; return the number of skills copied."""
    name, repo, ref = source["name"], source["repo"], source["ref"]
    clone = workdir / name
    clone.mkdir(parents=True)

    # Fetch the single pinned commit rather than cloning a branch. GitHub allows
    # fetching a SHA directly, so this stays a one-commit download.
    run("git", "init", "-q", str(clone))
    run("git", "remote", "add", "origin", repo, cwd=clone)
    run("git", "fetch", "-q", "--depth", "1", "origin", ref, cwd=clone)
    run("git", "checkout", "-q", "FETCH_HEAD", cwd=clone)

    actual = run("git", "rev-parse", "HEAD", cwd=clone)
    if actual != ref:
        raise SystemExit(f"{name}: expected {ref}, got {actual}")

    src = clone / source.get("path", ".")
    if not src.is_dir():
        raise SystemExit(f"{name}: path '{source.get('path')}' not found in {repo}")

    dest = out / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git"))

    # Kit-level directories that sit OUTSIDE the skill folders. The Agent Skills
    # spec says a skill references files "relative to the skill root", but some
    # kits (penpot) factor shared material up to the repo root and point at it
    # from many skills. Copying those alongside keeps the pack whole; they are
    # served by read_pack_file, never as skills.
    for extra in source.get("extras", []):
        extra_src = clone / extra
        if not extra_src.is_dir():
            raise SystemExit(f"{name}: extras entry '{extra}' not found in {repo}")
        if any(extra_src.rglob("SKILL.md")):
            raise SystemExit(
                f"{name}: extras entry '{extra}' contains a SKILL.md; "
                "it belongs under `path`, not `extras`"
            )
        shutil.copytree(
            extra_src, dest / extra, ignore=shutil.ignore_patterns(".git")
        )

    count = len(list(dest.rglob("SKILL.md")))
    print(f"  {name:10} {ref[:12]}  {count} skills")
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=Path("skills.toml"), help="manifest to read"
    )
    parser.add_argument(
        "--out", type=Path, default=Path("skills"), help="directory to fetch into"
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="repin every source to its upstream HEAD before fetching",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="only rewrite the manifest; do not download anything",
    )
    args = parser.parse_args(argv)

    manifest = tomllib.loads(args.manifest.read_text())
    sources = manifest.get("source", [])
    if not sources:
        print(f"no [[source]] entries in {args.manifest}", file=sys.stderr)
        return 1

    if args.update:
        print(f"resolving {len(sources)} skill sources to upstream HEAD")
        moved = update_manifest(args.manifest, sources)
        print(f"{len(moved)} source(s) moved")
        sources = tomllib.loads(args.manifest.read_text()).get("source", [])

    if args.no_fetch:
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"fetching {len(sources)} skill sources into {args.out}/")

    total = 0
    with tempfile.TemporaryDirectory() as tmp:
        for source in sources:
            total += fetch(source, args.out, Path(tmp))

    print(f"{total} skills total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
