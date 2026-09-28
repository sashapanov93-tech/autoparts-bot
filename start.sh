#!/bin/bash
# Один контейнер Render free: веб (держит сервис awake) + оба бота.
# Каждый процесс под супервизором: падение одного не роняет контейнер.

run_forever() {
  local name="$1"; shift
  while true; do
    echo "[supervisor] starting $name"
    "$@" || echo "[supervisor] $name exited with code $?, restarting in 5s"
    sleep 5
  done
}

run_forever web .venv/bin/uvicorn app.web_admin:app --host 0.0.0.0 --port "${PORT:-8000}" &
run_forever catalog .venv/bin/python -m app.run_catalog &
run_forever order .venv/bin/python -m app.run_order &
wait
