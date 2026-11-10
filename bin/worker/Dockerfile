# The image `pak task` runs its engine in (bin/pak_worker.py): Claude Code at the version in
# configs/claude-code.version, and what the kit's guard hooks need to judge inside it (bash,
# python3, jq). `pak task image` builds it as pak-worker:<version>-<first 8 of this file's sha256>,
# never latest. No secret is baked in: the key reaches the container only when a task runs.
FROM node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d

ARG CLAUDE_CODE_VERSION
RUN test -n "$CLAUDE_CODE_VERSION" \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git jq python3 \
    && apt-get clean \
    && npm install --global "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && npm cache clean --force
