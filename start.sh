#!/bin/bash
# Один контейнер Render free: веб (держит сервис awake) + оба бота.
set -e
.venv/bin/uvicorn app.web_admin:app --host 0.0.0.0 --port "${PORT:-8000}" &
.venv/bin/python -m app.run_catalog &
.venv/bin/python -m app.run_order &
wait -n
