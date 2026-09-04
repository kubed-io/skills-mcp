"""The skill catalogue: reading skills off disk and querying them.

Pure domain logic -- nothing here imports FastMCP or knows what MCP is. The
tools in ``tools.py`` are thin wrappers over ``SkillIndex``, which keeps the
scoping rules in one testable place instead of repeated in every handler.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

MAIN_FILE = "SKILL.md"


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
    return sorted({p.parent.parent for p in base.rglob(MAIN_FILE)})


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
    """Read every skill under ``base``.

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
    for skill_md in sorted(base.rglob(MAIN_FILE)):
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


class SkillIndex:
    """A queryable catalogue that enforces the per-request scope.

    Every read goes through ``pinned``, the pack a client is restricted to.
    Centralising it here is the point: a handler that forgot to apply it would
    silently hand a scoped client somebody else's skills.
    """

    def __init__(self, skills: list[Skill]):
        self._skills = skills
        # First writer wins on the bare name, so a duplicate across packs stays
        # reachable through its qualified "<pack>/<name>" form.
        self._by_name: dict[str, Skill] = {}
        for skill in skills:
            self._by_name.setdefault(skill.name, skill)
            self._by_name[skill.qualified] = skill

    def __len__(self) -> int:
        return len(self._skills)

    @property
    def packs(self) -> list[str]:
        """Every pack in the catalogue, ignoring any request scope."""
        return sorted({s.pack for s in self._skills})

    def visible(self, pinned: str = "") -> list[Skill]:
        """The skills a client pinned to ``pinned`` may see."""
        return [s for s in self._skills if not pinned or s.in_pack(pinned)]

    def select(self, pinned: str = "", pack: str = "") -> list[Skill]:
        """Visible skills narrowed further by the caller's ``pack`` argument."""
        return [s for s in self.visible(pinned) if not pack or s.in_pack(pack)]

    def selectors(self, pinned: str = "") -> list[str]:
        """Valid ``pack`` values for this client -- packs and their groups.

        Scoped by ``pinned`` on purpose: an error message that listed every
        selector would leak the other packs' names to a pinned client.
        """
        visible = self.visible(pinned)
        return sorted({s.pack for s in visible} | {s.group for s in visible})

    def get(self, name: str, pinned: str = "") -> Skill | None:
        """Look up one skill, or None when it is absent or out of scope.

        Out-of-scope reads are indistinguishable from missing ones by design:
        knowing a skill's exact name must not be enough to confirm it exists.
        """
        found = self._by_name.get(name)
        if found is not None and pinned and not found.in_pack(pinned):
            return None
        return found
