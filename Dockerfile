# Production image for Railway. Local dev doesn't use this - it's
# `uv run uvicorn ...` directly, see README.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Dependencies first, in their own layer, so code-only changes rebuild fast.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

ENV PORT=8000 HTTPS_ONLY_COOKIES=1
EXPOSE 8000

CMD ["sh", "-c", "/app/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
