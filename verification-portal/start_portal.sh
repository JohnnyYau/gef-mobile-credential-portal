#!/usr/bin/env bash
# ============================================================
#  Credential Verification Portal - one-click launcher (macOS/Linux)
#  ------------------------------------------------------------
#  * First run: creates .venv, installs requirements, seeds the
#    demo chain, opens the portal in your browser.
#  * Later runs: just starts the server.
#  * Default mode: PRIVATE (issuing + admin enabled).
#    For public-verifier-only mode set PUBLIC_MODE=1 below.
# ============================================================
set -e
cd "$(dirname "$0")"

PY=python3
# Optional local LLM (unreachable host -> offline fallback)
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export PUBLIC_MODE=0

if [ ! -x ".venv/bin/python" ]; then
  echo "[portal] First run detected - creating virtual environment..."
  $PY -m venv .venv
  echo "[portal] Installing dependencies..."
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt
else
  echo "[portal] Virtual environment ready."
fi

echo "[portal] Starting server on http://127.0.0.1:8000"
echo "[portal] Press Ctrl+C to stop."
( sleep 1.5; open "http://127.0.0.1:8000" 2>/dev/null || xdg-open "http://127.0.0.1:8000" 2>/dev/null || true ) &
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
