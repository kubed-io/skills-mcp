# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--
  These ARE the release notes. One line per entry, written for someone reading
  "what's new" — never a paragraph. Length tracks impact: functional changes get
  the most words (still one line); refactors/tests stay short; CI/devops are
  shortest. Only **BREAKING:** may stretch.

  ONLY EVER EDIT THE [Unreleased] SECTION. Every section below it carries a
  version number and is IMMUTABLE — those notes shipped with a release and must
  never be reworded, reordered, or removed. Add new work under [Unreleased].
  publish.yml (duplocloud/version-bump) rolls [Unreleased] into a dated version
  section at release time.
-->

## [Unreleased]

### Added

- MCP server serving Agent Skills, with a three-tool progressive-disclosure surface — `list_packs` / `list_skills` / `read_skill` — so a client sees three tools no matter how many skills are installed.
- `pack` filtering by source (`n8n`, `grafana`) or group (`grafana-core`, `grafana-lgtm`), plus `SKILL_PACKS` to hard-scope an instance to a subset the model cannot widen.
- Skills also published as `skill://` resources for clients that speak the resource half of MCP.
- Skill sources declared as pinned dependencies in `skills.toml` and fetched at image build time, never vendored — currently 64 skills from n8n-io/skills and grafana/skills.
- Root discovery that walks for `SKILL.md`, so a source may nest its skills at any depth even though `SkillsDirectoryProvider` does not recurse.
- `GET /health` reporting status and discovered root count, wired to the Kubernetes readiness and liveness probes.
- Weekly **Update Skills** workflow that repins every source to upstream HEAD and opens a PR.
- Kubernetes manifests deploying to the `flow` namespace as `skills-mcp:8000`, unauthenticated and read-only.
