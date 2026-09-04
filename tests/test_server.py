"""Tests for skill discovery, pack filtering and the tool surface."""

import pytest
from fastmcp import Client

from kubed.skills_mcp import SkillsMCP, discover_roots, load_skills


async def call(client, name, **args):
    result = await client.call_tool(name, args)
    return result.content[0].text


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
def test_pack_is_the_source_and_group_is_its_parent(skills_dir):
    """A flat source's group collapses onto the pack; a nested one does not."""
    by_name = {s.name: s for s in load_skills(skills_dir)}
    assert (by_name["alpha"].pack, by_name["alpha"].group) == ("flatsource", "flatsource")
    assert (by_name["gamma"].pack, by_name["gamma"].group) == ("deepsource", "plugin-a")


@pytest.mark.unit
def test_load_skills_can_hard_scope_to_packs(skills_dir):
    names = {s.name for s in load_skills(skills_dir, packs=["flatsource"])}
    assert names == {"alpha", "beta"}


@pytest.mark.unit
async def test_tool_surface_stays_fixed(skills_dir):
    """Three disclosure layers plus pack-level files -- never one tool per skill."""
    async with Client(SkillsMCP(skills_dir).mcp) as client:
        names = sorted(t.name for t in await client.list_tools())
    assert names == ["list_packs", "list_skills", "read_pack_file", "read_skill"]


@pytest.mark.unit
async def test_list_packs_shows_sources_and_nested_groups(skills_dir):
    async with Client(SkillsMCP(skills_dir).mcp) as client:
        out = await call(client, "list_packs")
    assert "flatsource (2 skills)" in out
    assert "deepsource (2 skills)" in out
    assert "plugin-a (1)" in out
    # A flat source has no sub-group worth listing.
    assert "  flatsource" not in out


@pytest.mark.unit
async def test_list_skills_filters_by_pack_or_group(skills_dir):
    async with Client(SkillsMCP(skills_dir).mcp) as client:
        everything = await call(client, "list_skills")
        by_pack = await call(client, "list_skills", pack="flatsource")
        by_group = await call(client, "list_skills", pack="plugin-a")

    assert all(n in everything for n in ("alpha", "beta", "gamma", "delta"))
    assert "alpha" in by_pack and "gamma" not in by_pack
    assert "gamma" in by_group and "delta" not in by_group
    # Filtering has to actually pay for itself.
    assert len(by_group) < len(everything)


@pytest.mark.unit
async def test_unknown_pack_names_the_valid_selectors(skills_dir):
    async with Client(SkillsMCP(skills_dir).mcp) as client:
        out = await call(client, "list_skills", pack="nope")
    assert "plugin-a" in out and "flatsource" in out


@pytest.mark.unit
async def test_read_skill_returns_the_body(skills_dir):
    async with Client(SkillsMCP(skills_dir).mcp) as client:
        assert "Third skill." in await call(client, "read_skill", skill="gamma")


@pytest.mark.unit
async def test_read_skill_manifest_lists_files(skills_dir):
    async with Client(SkillsMCP(skills_dir).mcp) as client:
        out = await call(client, "read_skill", skill="alpha", file="_manifest")
    assert "SKILL.md" in out


@pytest.mark.unit
async def test_read_skill_rejects_traversal(skills_dir):
    """A model-supplied path must never escape the skill directory."""
    async with Client(SkillsMCP(skills_dir).mcp) as client:
        out = await call(
            client, "read_skill", skill="alpha", file="../../deepsource/README.md"
        )
    assert out.startswith("No file")


@pytest.mark.unit
async def test_read_skill_rejects_unknown_name(skills_dir):
    async with Client(SkillsMCP(skills_dir).mcp) as client:
        out = await call(client, "read_skill", skill="nope")
    assert out.startswith("Unknown skill")


@pytest.mark.unit
async def test_server_scoped_to_packs_hides_the_rest(skills_dir):
    """SKILL_PACKS is the hard scope: the other pack is not reachable at all."""
    async with Client(SkillsMCP(skills_dir, packs=["flatsource"]).mcp) as client:
        assert "deepsource" not in await call(client, "list_packs")
        assert (await call(client, "read_skill", skill="gamma")).startswith("Unknown")


@pytest.mark.unit
async def test_empty_skills_dir_still_serves(tmp_path):
    """No skills mounted must not crash the server -- it just serves nothing."""
    async with Client(SkillsMCP(tmp_path).mcp) as client:
        assert "No skills" in await call(client, "list_packs")


@pytest.mark.unit
async def test_read_pack_file_serves_pack_level_material(skills_dir):
    """Kit-level files a skill references must be reachable somehow."""
    async with Client(SkillsMCP(skills_dir).mcp) as client:
        manifest = await call(client, "read_pack_file", pack="deepsource")
        body = await call(
            client, "read_pack_file", pack="deepsource", file="shared/guide.md"
        )
    assert "shared/guide.md" in manifest
    assert body == "shared guidance\n"


@pytest.mark.unit
async def test_read_pack_file_explains_when_a_pack_has_none(skills_dir):
    async with Client(SkillsMCP(skills_dir).mcp) as client:
        out = await call(client, "read_pack_file", pack="flatsource")
    assert "no pack-level files" in out


@pytest.mark.unit
async def test_read_pack_file_honours_the_request_scope(skills_dir):
    """A scoped instance must not read an unindexed pack's shared material."""
    async with Client(SkillsMCP(skills_dir, packs=["flatsource"]).mcp) as client:
        out = await call(client, "read_pack_file", pack="deepsource")
    assert out.startswith("Unknown pack")
