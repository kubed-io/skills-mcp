ARG PY_VERSION=3.13

# Stage 1: fetch the pinned skill sources. Isolated so it only re-runs when
# skills.toml or the fetch script changes, not on every source edit.
FROM python:${PY_VERSION}-slim AS skills

WORKDIR /fetch

RUN apt-get update && apt-get install -y --no-install-recommends git \
  && rm -rf /var/lib/apt/lists/*

COPY skills.toml ./
COPY scripts/fetch_skills.py ./

RUN python fetch_skills.py --out /skills

# Stage 2: source + build tooling. setuptools_scm reads .git for the version,
# so git must be installed and .git must survive .dockerignore.
FROM python:${PY_VERSION} AS setup

WORKDIR /app

COPY . .

RUN <<EOF
apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
git config --global --add safe.directory /app
pip install --no-cache-dir --upgrade pip
pip install --no-cache-dir .[build]
EOF

FROM setup AS builder
RUN python -m build --no-isolation

# Final stage: just the wheel and the skills.
FROM python:${PY_VERSION}-slim AS runner

WORKDIR /app

COPY --from=builder /app/dist ./dist/
RUN pip install --no-cache-dir ./dist/*.whl && rm -rf ./dist

COPY --from=skills /skills /skills

ENV SKILLS_DIR=/skills \
    TRANSPORT=http \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000
# Numeric UID, not the name: with runAsNonRoot set, the kubelet cannot verify a
# non-numeric USER and refuses to start the container.
USER 65534

ENTRYPOINT ["skills-mcp"]
