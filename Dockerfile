# swipe591: the 591 swipe web app and its poller (one image, two commands —
# see deploy/docker-compose.yml). The MCP server itself is not run from here.
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 PYTHONUNBUFFERED=1

# Dependencies first, so a code change doesn't reinstall them.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --extra web --no-install-project

COPY mcp_591 ./mcp_591
COPY swipe591 ./swipe591
RUN uv sync --locked --extra web

ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA} PATH="/app/.venv/bin:$PATH"

RUN useradd --uid 1000 --create-home swipe
USER swipe

EXPOSE 8080
CMD ["uvicorn", "--factory", "swipe591.app:from_env", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
