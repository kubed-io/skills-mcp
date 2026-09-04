# Skills MCP

Serves [Agent Skills](https://code.claude.com/docs/en/skills) over MCP, so any client can
discover and read them — including clients that only speak tools.

Skills are declared as pinned dependencies in `skills.toml` and fetched at image build
time. Nothing is fetched at runtime.

```
docker run -p 8000:8000 kubed/skills-mcp:latest
```

Point a client at `http://localhost:8000/mcp` and it gets two tools:

| tool | returns |
| --- | --- |
| `list_resources` | every available skill, names and one-line descriptions |
| `read_resource` | one skill's `SKILL.md`, its `_manifest`, or a supporting file |

Skills are addressed by URI, so an agent pays only for what it reads:

```
skill://promql/SKILL.md        the instructions
skill://promql/_manifest       what else the skill ships, with sizes and hashes
skill://promql/reference.md    a supporting file, on demand
```

## Why tools and not resources

MCP has three primitives — tools, resources and prompts. Skills map naturally onto
resources, and that is what FastMCP's `SkillsDirectoryProvider` produces. But several
popular clients implement only the tool half of the protocol; n8n's MCP Client Tool is
one, and to it a resource-only server looks empty. The `ResourcesAsTools` transform
re-exposes the same resources as `list_resources` / `read_resource`, so the server works
everywhere without a second implementation.

## Skills as dependencies

`skills.toml` is the source of truth:

```toml
[[source]]
name = "n8n"
repo = "https://github.com/n8n-io/skills.git"
ref  = "180b8415e3b73f78828cfa01e908e67f89f2a139"
path = "skills"
```

`ref` is a commit, so an image is reproducible. `path` is the subdirectory holding the
skill folders — not the repo root. `skills/` is gitignored; upstream markdown is never
vendored into this repo, so a skill bump reviews as a one-line ref change.

Currently served: **64 skills** from [n8n-io/skills](https://github.com/n8n-io/skills)
and [grafana/skills](https://github.com/grafana/skills).

Fetch them locally:

```
python scripts/fetch_skills.py            # fetch at the pinned refs
python scripts/fetch_skills.py --update   # repin everything to upstream HEAD
```

The **Update Skills** workflow runs that weekly and opens a PR.

## Adding a source

Add a `[[source]]` block, then one `COPY` line in the Dockerfile's `skills` stage.
A source may nest its skills at any depth — the server discovers roots by walking for
`SKILL.md`, because `SkillsDirectoryProvider` itself does not recurse.

## Configuration

| variable | default | meaning |
| --- | --- | --- |
| `SKILLS_DIR` | `/skills` | directory to scan |
| `TRANSPORT` | `http` | `http` or `stdio` |
| `HOST` | `0.0.0.0` | bind address |
| `PORT` | `8000` | port |

`GET /health` reports status and the number of discovered roots.

## Deploying

```
kubectl apply -k .
```

Runs in the `flow` namespace as `skills-mcp:8000`. There is no authentication: every
skill served is public markdown, the server has no write path and holds no credentials.

## Development

```
pip install -e .[test]
pytest
```

## License

MIT
