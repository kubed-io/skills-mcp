"""The MCP server itself: wiring, and nothing else.

Assembles a FastMCP instance from the skill catalogue -- the resource provider,
the tools, the routes -- and runs it on a transport. The catalogue lives in
``skills.py``, the tool bodies in ``tools.py``, the endpoints in ``routes.py``;
this module only connects them, so a new tool never means editing the server.
"""

from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers.skills import SkillsDirectoryProvider

from . import routes, tools
from .skills import SkillIndex, discover_roots, load_skills

DEFAULT_SKILLS_DIR = Path("/skills")

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


class SkillsMCP:
    """An MCP server over a directory of Agent Skills.

    Skills are exposed twice, because MCP clients are not all alike. As
    ``skill://`` **resources** via FastMCP's ``SkillsDirectoryProvider``, for
    clients that speak the resource half of the protocol; and as three
    **tools**, for the many that only implement tools -- n8n among them, to
    which a resource-only server looks empty.
    """

    def __init__(
        self,
        skills_dir: Path = DEFAULT_SKILLS_DIR,
        packs: list[str] | None = None,
    ):
        self.skills_dir = skills_dir
        self.packs = packs
        self.index = SkillIndex(load_skills(skills_dir, packs))
        self.mcp = FastMCP("Skills", instructions=INSTRUCTIONS)

        self._add_resource_provider()
        tools.register(self.mcp, self.index)
        routes.register(self.mcp, self.index)

    def _add_resource_provider(self) -> None:
        """Publish the skills as ``skill://`` resources.

        Roots are filtered the same way the index is, so ``packs`` scopes both
        halves of the server; otherwise a resource-capable client could read
        past a scope the tools enforce.
        """
        roots = discover_roots(self.skills_dir)
        if self.packs:
            roots = [
                r
                for r in roots
                if r.relative_to(self.skills_dir).parts[0] in self.packs
            ]
        if roots:
            self.mcp.add_provider(SkillsDirectoryProvider(roots=roots))

    def run(
        self, transport: str = "http", host: str = "0.0.0.0", port: int = 8000
    ) -> None:
        """Serve on ``transport``, blocking until the process is stopped."""
        if transport == "stdio":
            self.mcp.run(transport="stdio")
        else:
            self.mcp.run(transport="http", host=host, port=port)
