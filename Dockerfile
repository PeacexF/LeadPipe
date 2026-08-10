FROM ghcr.io/astral-sh/uv:0.12 AS uv

FROM python:3.14-slim AS builder

COPY --from=uv /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /build

COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-editable --no-install-project

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --locked --no-dev --no-editable


FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home --uid 10001 leadpipe

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=leadpipe:leadpipe migrations ./migrations
COPY --chown=leadpipe:leadpipe examples ./examples
COPY --chown=leadpipe:leadpipe alembic.ini pyproject.toml ./

USER leadpipe

EXPOSE 8000

CMD ["leadpipe", "serve"]
