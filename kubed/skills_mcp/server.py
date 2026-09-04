"""Skills MCP server.

Serves Agent Skills (``SKILL.md`` packages) over MCP. Skills arrive as git
submodules under ``skills/`` so they are pinned, reviewable dependencies
rather than files copied by hand.

Everything here is configuration around two FastMCP built-ins:

``SkillsDirectoryProvider``
    Turns each skill folder into ``skill://<name>/SKILL.md``, a synthetic
    ``skill://<name>/_manifest``, and templated supporting files.

``ResourcesAsTools``
    Re-exposes those resources as ``list_resources`` / ``read_resource``
    tools. Tool-only clients -- n8n's MCP Client Tool is one -- cannot speak
    the resource half of MCP at all, so without this they see an empty server.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers.skills import SkillsDirectoryProvider
from fastmcp.server.transforms import ResourcesAsTools

DEFAULT_SKILLS_DIR = Path(os.environ.get("SKILLS_DIR", "/skills"))

INSTRUCTIONS = """\
This server hosts Agent Skills: self-contained instruction packages that teach \
you how to perform a specific task.

Call `list_resources` first to see what is available -- it is cheap and returns \
only names and one-line descriptions. When one matches the task at hand, call \
`read_resource` with its `skill://<name>/SKILL.md` URI and follow the \
instructions you get back.

Skills may reference supporting files. Read `skill://<name>/_manifest` to see \
what a skill ships, then fetch individual files by URI as you need them. Do not \
read files you have no use for -- the point of the layered URIs is that you pay \
only for what you actually use.
"""


def discover_roots(base: Path) -> list[Path]:
    """Find every directory that *directly contains* skill folders.

    ``SkillsDirectoryProvider`` does not recurse: a root must be the parent of
    the skill folders, not an ancestor. Sources nest differently -- n8n is
    ``skills/<skill>/SKILL.md`` while grafana is
    ``skills/<plugin>/<skill>/SKILL.md`` -- so pointing at one shared parent
    silently yields zero skills. Walking for ``SKILL.md`` and collecting each
    one's grandparent handles any depth without hard-coding either layout.
    """
    if not base.is_dir():
        return []
    return sorted({p.parent.parent for p in base.rglob("SKILL.md")})


def build_server(skills_dir: Path = DEFAULT_SKILLS_DIR) -> FastMCP:
    """Build the MCP server for the skills under ``skills_dir``."""
    mcp = FastMCP("Skills", instructions=INSTRUCTIONS)

    roots = discover_roots(skills_dir)
    if roots:
        mcp.add_provider(SkillsDirectoryProvider(roots=roots))
    mcp.add_transform(ResourcesAsTools(mcp))

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request):
        from starlette.responses import JSONResponse

        return JSONResponse({"status": "ok", "roots": len(roots)})

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

    mcp = build_server(args.skills_dir)
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
