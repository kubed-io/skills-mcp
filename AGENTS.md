# Working on skills-mcp

An MCP server that serves Agent Skills — `SKILL.md` packages — over HTTP so
clients that cannot read a filesystem (n8n agents, above all) can still use
them. Skills are **fetched at build time** from pinned upstream repos and baked
into the image; nothing is fetched at runtime.

## Layout

| Path | What it is |
| --- | --- |
| `skills.toml` | the pack manifest — the source of truth for what gets served |
| `scripts/fetch_skills.py` | clones each pinned source at build time; stdlib only |
| `kubed/skills_mcp/server.py` | the whole server: index, three tools, `/health` |
| `deploy/` | raw Deployment + Service |
| `kustomization.yaml` | the one kustomization; `newTag` is the deployed version |
| `skills/` | **gitignored** — build output, never commit it |

## Adding a skill pack

The manifest is the only file you edit. A pack is a dependency, pinned like one.

```toml
[[source]]
name = "penpot"                                        # becomes the pack name
repo = "https://github.com/penpot/penpot-ai-kit.git"
ref  = "c63d8e3717323fad859e794848e5a602b155a7ec"      # a commit SHA
path = "skills"                                        # dir CONTAINING skill folders
```

Two things go wrong here, both silently:

- **`path` must be the directory that *contains* skill folders, never the repo
  root.** `grafana/skills` ships a `template/SKILL.md` at the top level that
  would otherwise be served as a skill named "template".
- **Pin a SHA, not a branch.** None of these upstreams tag releases. A branch
  ref makes the image irreproducible and the pack can change under you.

Then verify locally before pushing:

```bash
python scripts/fetch_skills.py --out /tmp/skills   # clone the packs
SKILLS_DIR=/tmp/skills python -m pytest -q         # 14 tests
SKILLS_DIR=/tmp/skills skills-mcp --transport stdio
```

Nesting depth does **not** matter. `discover_roots` walks for `SKILL.md` and
takes each one's grandparent, so a flat source (`<pack>/<skill>/SKILL.md`, n8n)
and a nested one (`<pack>/<group>/<skill>/SKILL.md`, grafana) both work. This is
load-bearing: `SkillsDirectoryProvider` does not recurse, so pointing it at a
shared ancestor yields zero skills with no error.

Bumping existing packs is the `🧠 Update Skills` workflow — Mondays 09:00 UTC,
or dispatch it. It repins every source to upstream HEAD and opens a PR, because
a bump is new upstream *instruction* content and deserves a read before it ships.

## Shipping a change

Two workflows, in this order. Neither runs on a push to main.

**1. `🧬 Publish Version`** (`workflow_dispatch`) — three jobs:

```
version → pins kustomization.yaml newTag, rolls CHANGELOG, commits + tags main
image   → checks out that tag, builds and pushes kubed/skills-mcp:vX.Y.Z
release → cuts the GitHub Release
```

Run it once with **`push: false`** first. That is a real dry run: it computes
the next version and builds the image without pushing either. Then run with
`push: true`.

The pin happens *before* the tag, so the tag's tree already references its own
image. This is the only workflow that writes `newTag`, and it only ever writes a
semver — so main always sits on something deployable.

**2. `🚀 Deploy`** (`workflow_dispatch`) — runs `kubectl up` (applyset + prune).
Preview locally first:

```bash
kubectl plan .    # diff against the live cluster, read-only
kubectl up .      # what the workflow runs
```

`image.yml` on its own only builds. A push to main publishes `:main` and
`:latest` for testing; it never changes what is deployed.

## Things that already cost someone an afternoon

- **`USER` in the Dockerfile must be numeric.** With `runAsNonRoot: true` the
  kubelet refuses a non-numeric user — `image has non-numeric user (nobody),
  cannot verify user is non-root` — and the pod sits in
  `CreateContainerConfigError`. It is `USER 65534`, pinned again as `runAsUser`
  in the pod spec.
- **The control-plane nodes carry no taint in this cluster.** Without the node
  affinity in `deploy/deployment.yaml` the scheduler will put this pod on an
  etcd/master node; it did exactly that on the first rollout.
- **`imagePullPolicy: Always` pairs with a floating tag.** While `newTag` is
  `latest`, `IfNotPresent` pins a node to whatever layer it cached first. Once
  `publish.yml` pins a semver this is just a cheap registry check.
- **Do not reach for `ResourcesAsTools`.** FastMCP's generic bridge lists three
  entries per skill (`SKILL.md`, `_manifest`, a file template), each repeating
  the full description — 192 entries and ~16k tokens per listing call for 64
  skills, paid every time. The three hand-rolled tools exist for that reason.
  Skills stay data behind `read_skill`; they are never tools themselves.

## The tool surface, and why it is three tools

Progressive disclosure, cheapest layer first. Adding packs must not add tools.

| tool | returns | cost |
| --- | --- | --- |
| `list_packs()` | packs and their groups, with counts | ~75 tokens |
| `list_skills(pack)` | `name: description` for one pack or group | ~1–2k tokens |
| `read_skill(skill, file)` | one skill's body, `_manifest`, or one file | one file |

`read_skill` returns **only** what was asked for. A skill body may cite
`references/FOO.md`; citing it does not fetch it. That laziness is the point —
keep it when changing this code.

`SKILL_PACKS=n8n` hard-scopes an instance to a subset the model cannot widen.
Same image, second Deployment, different env — the way to give one agent a
catalogue it cannot escape.

## Verifying in the cluster

```bash
kubectl -n flow rollout status deploy/skills-mcp
kubectl -n flow port-forward svc/skills-mcp 18000:8000
curl -s localhost:18000/health   # {"status":"ok","packs":[...],"skills":N}
```

`/health` reports the packs and skill count, which is the fastest way to tell
which image a pod is actually running.

## House rules that apply here

- Every PR needs a `CHANGELOG.md` entry under `[Unreleased]`; `pr.yml` enforces
  it. Dependabot PRs carry the `no changelog` label instead.
- No `Makefile`. Everything is `pyproject.toml` plus the two scripts.
- No auth on this server, by design: every skill it serves is public markdown
  that is already on GitHub. Do not add a token without a reason to.
