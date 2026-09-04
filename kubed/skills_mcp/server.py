"""Skills MCP server.

Serves Agent Skills (``SKILL.md`` packages) over MCP. Skill sources are pinned
in ``skills.toml`` and fetched into the image at build time; nothing is fetched
at runtime.

Skills are exposed two ways:

*Resources*, via FastMCP's ``SkillsDirectoryProvider`` -- ``skill://<name>/...``
for clients that speak the resource half of MCP.

*Tools*, hand-rolled here, because the generic ``ResourcesAsTools`` bridge is
too expensive for a catalogue this size. It lists three entries per skill
(``SKILL.md``, ``_manifest``, and a file template), each repeating the skill's
full description -- 192 entries and ~16k tokens for 64 skills, paid on every
call. The three tools below give the same access in a fraction of that: a pack
index, a filtered skill index, then one skill body.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.providers.skills import SkillsDirectoryProvider

# Per-request scope. A client that sets this sees only that pack, whatever it
# asks for -- which is how one deployment serves several single-pack agents.
PACK_HEADER = "x-skill-pack"

DEFAULT_SKILLS_DIR = Path(os.environ.get("SKILLS_DIR", "/skills"))

INSTRUCTIONS = """\
This server hosts Agent Skills: instruction packages that teach you how to \
perform a specific task.

Work down the layers, cheapest first. `list_packs` shows which families of \
skills exist. `list_skills` gives the index for one pack -- always pass `pack` \
if you know which one you need, since the unfiltered index is much larger. \
`read_skill` returns a skill's full instructions, which you then follow.

Skills may ship supporting files. `read_skill` with `file="_manifest"` lists \
them; pass a path to read one. Do not read files you have no use for.
"""


@dataclass(frozen=True)
class Skill:
    """One skill on disk."""

    name: str
    pack: str
    group: str
    description: str
    path: Path

    @property
    def qualified(self) -> str:
        return f"{self.pack}/{self.name}"

    def in_pack(self, selector: str) -> bool:
        """Match a selector against either the source or the group."""
        return selector in (self.pack, self.group)


def discover_roots(base: Path) -> list[Path]:
    """Find every directory that *directly contains* skill folders.

    ``SkillsDirectoryProvider`` does not recurse: a root must be the parent of
    the skill folders, not an ancestor. Sources nest differently -- n8n is
    ``<pack>/<skill>/SKILL.md`` while grafana is
    ``<pack>/<group>/<skill>/SKILL.md`` -- so pointing at one shared parent
    silently yields zero skills. Walking for ``SKILL.md`` and collecting each
    one's grandparent handles any depth without hard-coding either layout.
    """
    if not base.is_dir():
        return []
    return sorted({p.parent.parent for p in base.rglob("SKILL.md")})


def _frontmatter(skill_md: Path) -> dict:
    """Parse a SKILL.md YAML frontmatter block, tolerating a malformed one."""
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}
    _, _, rest = text.partition("---")
    block, sep, _ = rest.partition("\n---")
    if not sep:
        return {}
    try:
        return yaml.safe_load(block) or {}
    except yaml.YAMLError:
        return {}


def load_skills(base: Path, packs: list[str] | None = None) -> list[Skill]:
    """Build the skill index.

    ``pack`` is the top-level directory under ``base`` -- one skill source, one
    pack. ``group`` is the directory that immediately contains the skill, which
    for a nested source (grafana) is a meaningful sub-family and for a flat one
    (n8n) is just the pack again. Both are selectable, so an agent can narrow to
    a whole source or to one family within it.

    ``packs`` hard-scopes the server to a subset, which is how a single image
    serves a narrower catalogue without a separate build.
    """
    if not base.is_dir():
        return []

    skills: list[Skill] = []
    for skill_md in sorted(base.rglob("SKILL.md")):
        rel = skill_md.relative_to(base)
        if len(rel.parts) < 2:
            continue
        pack = rel.parts[0]
        if packs and pack not in packs:
            continue
        meta = _frontmatter(skill_md)
        skills.append(
            Skill(
                name=str(meta.get("name") or skill_md.parent.name),
                pack=pack,
                group=rel.parts[-3],
                description=" ".join(str(meta.get("description", "")).split()),
                path=skill_md.parent,
            )
        )
    return skills


def _requested_pack() -> str:
    """The pack this request is pinned to, or "" when it is unpinned.

    Read from the ``X-Skill-Pack`` header, which a client sets once in its
    connection config. It is a ceiling, not a suggestion: the model can narrow
    further with the ``pack`` argument but can never widen past it. That is the
    difference between a scope an agent has and one it merely was asked to keep.

    Returns "" outside an HTTP request (stdio), where there is no header to read.
    """
    return get_http_headers().get(PACK_HEADER, "").strip()


def build_server(
    skills_dir: Path = DEFAULT_SKILLS_DIR, packs: list[str] | None = None
) -> FastMCP:
    """Build the MCP server for the skills under ``skills_dir``."""
    mcp = FastMCP("Skills", instructions=INSTRUCTIONS)

    skills = load_skills(skills_dir, packs)
    by_name: dict[str, Skill] = {}
    for skill in skills:
        by_name.setdefault(skill.name, skill)
        by_name[skill.qualified] = skill

    roots = discover_roots(skills_dir)
    if packs:
        roots = [r for r in roots if r.relative_to(skills_dir).parts[0] in packs]
    if roots:
        mcp.add_provider(SkillsDirectoryProvider(roots=roots))

    pack_names = sorted({s.pack for s in skills})

    @mcp.tool
    def list_packs() -> str:
        """List the skill packs available, with a skill count for each.

        Start here. Each pack is one upstream source, so the pack name tells you
        what domain its skills cover.
        """
        pinned = _requested_pack()
        visible = [s for s in skills if not pinned or s.in_pack(pinned)]
        if not visible:
            return "No skills are installed."
        lines = []
        for p in sorted({s.pack for s in visible}):
            in_pack = [s for s in visible if s.pack == p]
            lines.append(f"{p} ({len(in_pack)} skills)")
            groups = sorted({s.group for s in in_pack} - {p})
            lines += [
                f"  {g} ({sum(1 for s in in_pack if s.group == g)})" for g in groups
            ]
        return (
            "\n".join(lines)
            + "\n\nCall list_skills(pack=...) with any name above -- a pack or one"
            " of its groups. Narrower is cheaper."
        )

    @mcp.tool
    def list_skills(pack: str = "") -> str:
        """List skills as `name: description`, one per line.

        Args:
            pack: Restrict to one pack ("n8n", "grafana") or one of its groups
                ("grafana-core", "grafana-lgtm") as shown by list_packs.
                Strongly preferred -- the unfiltered index is large. Leave empty
                only when you do not yet know which pack applies.
        """
        pinned = _requested_pack()
        selected = [
            s
            for s in skills
            if (not pinned or s.in_pack(pinned)) and (not pack or s.in_pack(pack))
        ]
        if not selected:
            # Derive the suggestions from what this client may see. Listing
            # every pack here would leak the other packs' names to a pinned
            # client through an error message.
            allowed = [s for s in skills if not pinned or s.in_pack(pinned)]
            known = (
                ", ".join(sorted({s.pack for s in allowed} | {s.group for s in allowed}))
                or "none"
            )
            return f"No skills for pack '{pack}'. Valid selectors: {known}."
        lines = [f"{s.name}: {s.description}" for s in sorted(selected, key=lambda s: s.name)]
        return "\n".join(lines) + "\n\nCall read_skill(skill=...) to read one."

    @mcp.tool
    def read_skill(skill: str, file: str = "SKILL.md") -> str:
        """Read a skill's instructions, its manifest, or one supporting file.

        Args:
            skill: Skill name from list_skills, e.g. "promql". Qualify it as
                "<pack>/<name>" if the same name exists in two packs.
            file: "SKILL.md" for the instructions (the default), "_manifest" for
                the list of supporting files, or a path from that manifest.
        """
        pinned = _requested_pack()
        found = by_name.get(skill)
        if found is not None and pinned and not found.in_pack(pinned):
            found = None
        if found is None:
            return f"Unknown skill '{skill}'. Call list_skills to see valid names."

        if file == "_manifest":
            files = sorted(
                str(p.relative_to(found.path))
                for p in found.path.rglob("*")
                if p.is_file()
            )
            return "\n".join(files)

        # Resolve before comparing: blocks ../ traversal and symlinks that
        # point outside the skill directory.
        target = (found.path / file).resolve()
        if not target.is_relative_to(found.path.resolve()) or not target.is_file():
            return f"No file '{file}' in skill '{skill}'."
        return target.read_text(encoding="utf-8", errors="replace")

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request):
        from starlette.responses import JSONResponse

        return JSONResponse(
            {"status": "ok", "packs": pack_names, "skills": len(skills)}
        )

    return mcp


def main(argv: list[str] | None = None) -> None:
    """Entry point for the ``skills-mcp`` console script."""
    parser = argparse.ArgumentParser(prog="skills-mcp", description=__doc__)
    parser.add_argument(
        "--skills-dir",
        type=Path,
        default=DEFAULT_SKILLS_DIR,
        help="directory to scan for skills (env: SKILLS_DIR)",
    )
    parser.add_argument(
        "--packs",
        default=os.environ.get("SKILL_PACKS", ""),
        help="comma-separated packs to serve; empty serves all (env: SKILL_PACKS)",
    )
    parser.add_argument(
        "--transport",
        default=os.environ.get("TRANSPORT", "http"),
        choices=["stdio", "http"],
        help="transport to serve on (env: TRANSPORT)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("HOST", "0.0.0.0"),
        help="bind address for http transport (env: HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8000")),
        help="port for http transport (env: PORT)",
    )
    args = parser.parse_args(argv)

    packs = [p.strip() for p in args.packs.split(",") if p.strip()] or None
    mcp = build_server(args.skills_dir, packs)
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
