"""The MCP tools.

Three tools, whatever the catalogue size -- one per disclosure layer. Skills are
data behind ``read_skill``, never tools in their own right, so adding a pack
never grows the tool list.

The alternative, FastMCP's generic ``ResourcesAsTools`` bridge, is too expensive
here: it lists three entries per skill (``SKILL.md``, ``_manifest``, and a file
template), each repeating the skill's full description -- 192 entries and ~16k
tokens for 64 skills, paid on every listing call.
"""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

from .skills import SkillIndex

# Per-request scope. A client that sets this sees only that pack, whatever it
# asks for -- which is how one deployment serves several single-pack agents.
PACK_HEADER = "x-skill-pack"


def requested_pack() -> str:
    """The pack this request is pinned to, or "" when it is unpinned.

    Read from the ``X-Skill-Pack`` header, which a client sets once in its
    connection config. It is a ceiling, not a suggestion: the model can narrow
    further with the ``pack`` argument but can never widen past it. That is the
    difference between a scope an agent has and one it merely was asked to keep.

    Returns "" outside an HTTP request (stdio), where there is no header to read.
    """
    return get_http_headers().get(PACK_HEADER, "").strip()


def register(mcp: FastMCP, index: SkillIndex) -> None:
    """Register the skill tools on ``mcp``."""

    @mcp.tool
    def list_packs() -> str:
        """List the skill packs available, with a skill count for each.

        Start here. Each pack is one upstream source, so the pack name tells you
        what domain its skills cover.
        """
        visible = index.visible(requested_pack())
        if not visible:
            return "No skills are installed."

        lines: list[str] = []
        for pack in sorted({s.pack for s in visible}):
            in_pack = [s for s in visible if s.pack == pack]
            lines.append(f"{pack} ({len(in_pack)} skills)")
            # A flat source's group is just the pack again, so it adds nothing.
            groups = sorted({s.group for s in in_pack} - {pack})
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
        pinned = requested_pack()
        selected = index.select(pinned, pack)
        if not selected:
            known = ", ".join(index.selectors(pinned)) or "none"
            return f"No skills for pack '{pack}'. Valid selectors: {known}."

        lines = [
            f"{s.name}: {s.description}" for s in sorted(selected, key=lambda s: s.name)
        ]
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
        found = index.get(skill, requested_pack())
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
