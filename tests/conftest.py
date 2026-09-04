"""Shared fixtures: a synthetic skills tree covering both nesting depths."""

import pytest

FLAT = {"alpha": "First skill.", "beta": "Second skill."}
NESTED = {"plugin-a": {"gamma": "Third skill."}, "plugin-b": {"delta": "Fourth skill."}}


def _write(path, name, description):
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\nBody.\n"
    )


@pytest.fixture
def skills_dir(tmp_path):
    """A skills root holding one flat source and one two-level source.

    Mirrors the real sources: n8n is ``<source>/<skill>/`` while grafana is
    ``<source>/<plugin>/<skill>/``.
    """
    for name, desc in FLAT.items():
        _write(tmp_path / "flatsource" / name, name, desc)
    for plugin, skills in NESTED.items():
        for name, desc in skills.items():
            _write(tmp_path / "deepsource" / plugin / name, name, desc)
    (tmp_path / "deepsource" / "README.md").write_text("not a skill\n")
    return tmp_path
