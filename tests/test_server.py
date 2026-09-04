"""Tests for skill discovery and the tool-only surface."""

import json

import pytest
from fastmcp import Client

from kubed.skills_mcp.server import build_server, discover_roots


@pytest.mark.unit
def test_discover_roots_handles_both_depths(skills_dir):
    """A root must be the PARENT of skill folders, at whatever depth it sits."""
    roots = discover_roots(skills_dir)
    assert set(roots) == {
        skills_dir / "flatsource",
        skills_dir / "deepsource" / "plugin-a",
        skills_dir / "deepsource" / "plugin-b",
    }
    # The shared ancestor is NOT a root -- SkillsDirectoryProvider does not
    # recurse, so returning it here would yield zero skills.
    assert skills_dir / "deepsource" not in roots


@pytest.mark.unit
def test_discover_roots_missing_dir_is_empty(tmp_path):
    assert discover_roots(tmp_path / "nope") == []


@pytest.mark.unit
async def test_only_tools_are_exposed(skills_dir):
    """Tool-only clients (n8n) must see the resource bridge, nothing else."""
    async with Client(build_server(skills_dir)) as client:
        names = sorted(t.name for t in await client.list_tools())
    assert names == ["list_resources", "read_resource"]


@pytest.mark.unit
async def test_lists_every_skill_across_sources(skills_dir):
    async with Client(build_server(skills_dir)) as client:
        result = await client.call_tool("list_resources", {})
    listed = json.loads(result.content[0].text)
    found = {e["uri"].split("//")[1].split("/")[0] for e in listed if e.get("uri")}
    assert {"alpha", "beta", "gamma", "delta"} <= found


@pytest.mark.unit
async def test_reads_a_skill_body(skills_dir):
    async with Client(build_server(skills_dir)) as client:
        result = await client.call_tool(
            "read_resource", {"uri": "skill://gamma/SKILL.md"}
        )
    assert "Third skill." in result.content[0].text


@pytest.mark.unit
async def test_empty_skills_dir_still_serves(tmp_path):
    """No skills mounted must not crash the server -- it just serves nothing."""
    async with Client(build_server(tmp_path)) as client:
        names = sorted(t.name for t in await client.list_tools())
    assert names == ["list_resources", "read_resource"]
