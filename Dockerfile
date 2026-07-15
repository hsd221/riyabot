FROM python:3.13-slim@sha256:bffeb7bd6a85767587059c6ba23e1e9122078e3aa3fa836099171b9bb5a9bb00
COPY --from=ghcr.io/astral-sh/uv:0.11.21@sha256:ff07b86af50d4d9391d9daf4ff89ce427bc544f9aae87057e69a1cc0aa369946 /uv /uvx /bin/

WORKDIR /RiyaBot

ENV PATH="/RiyaBot/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

ARG RIYABOT_UID=1000
ARG RIYABOT_GID=1000
RUN groupadd --gid "$RIYABOT_GID" riyabot \
    && useradd --uid "$RIYABOT_UID" --gid "$RIYABOT_GID" --home-dir /RiyaBot --shell /usr/sbin/nologin riyabot

COPY --chown=riyabot:riyabot . .
RUN mkdir -p config data logs plugins \
    && chown riyabot:riyabot /RiyaBot \
    && chown -R riyabot:riyabot config data logs plugins

USER riyabot

EXPOSE 8000 8001

ENTRYPOINT ["python", "bot.py"]
