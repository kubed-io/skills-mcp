# Skills MCP

Serves [Agent Skills](https://code.claude.com/docs/en/skills) over MCP, so any client can
discover and read them — including clients that only speak tools.

Skills are declared as pinned dependencies in `skills.toml` and fetched at image build
time. Nothing is fetched at runtime.

```
docker run -p 8000:8000 kubed/skills-mcp:latest
```

Point a client at `http://localhost:8000/mcp` and it gets **three tools — never one per
skill**. Skills are data behind `read_skill`, not entries in the tool list.

| tool | returns | cost |
| --- | --- | --- |
| `list_packs()` | every pack and its groups, with counts | ~75 tokens |
| `list_skills(pack)` | `name: description` for that pack or group | ~1–2k tokens |
| `read_skill(skill, file)` | one skill's instructions, manifest, or a file | one skill |

Each layer is cheap enough to call speculatively and narrow enough that the next one
stays small:

```
list_packs()                        →  grafana (50), n8n (14), penpot (12), and grafana's 7 groups
list_skills(pack="grafana-lgtm")    →  6 skills, ~945 tokens
read_skill(skill="loki")            →  the instructions to follow
read_skill(skill="loki", file="_manifest")  →  what else it ships
```

## Filtering to one pack

`pack` accepts either a source (`n8n`, `grafana`, `penpot`) or one of its groups
(`grafana-core`, `grafana-lgtm`). That is the soft filter, chosen per call.

For a **hard** scope — an n8n agent that can never see Grafana skills — set
`SKILL_PACKS` and the rest of the catalogue does not exist for that instance:

```
SKILL_PACKS=n8n
```

Same image, second Deployment, different env. Nothing the model does can widen it.

## Why three tools and not resources

MCP has three primitives — tools, resources and prompts. Skills map naturally onto
resources, and `SkillsDirectoryProvider` still publishes them that way for clients that
speak the resource half of the protocol. But many clients only implement tools — n8n's
MCP Client Tool is one — and to those a resource-only server looks empty.

FastMCP ships a generic `ResourcesAsTools` bridge for exactly that, but it is too
expensive here: it lists three entries per skill (`SKILL.md`, `_manifest`, and a file
template), each repeating the skill's full description. For 64 skills that is 192
entries and **~16k tokens on every listing call** — the opposite of what skills are for.
The three tools above are hand-rolled to give the same access for a fraction of it.

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
| `SKILL_PACKS` | *(all)* | comma-separated packs to serve; hard scope |
| `TRANSPORT` | `http` | `http` or `stdio` |
| `HOST` | `0.0.0.0` | bind address |
| `PORT` | `8000` | port |

`GET /health` reports status, the packs served, and the skill count.

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
