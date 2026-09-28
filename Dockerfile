FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# uv для быстрой установки зависимостей
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache

COPY app ./app

# без root — меньше ущерб при компрометации
RUN useradd -m -u 10001 bot && chown -R bot:bot /app
USER bot

# команда задаётся в docker-compose (run_catalog / run_order / uvicorn)
CMD [".venv/bin/python", "-m", "app.run_catalog"]
