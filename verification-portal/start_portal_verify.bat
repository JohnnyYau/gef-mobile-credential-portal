@echo off
REM ============================================================
REM  GEF-mobile - VERIFY-only side (Windows one-click)
REM  ------------------------------------------------------------
REM  Public-facing verification end: the UI is trimmed to just
REM    * 验证 Verify  (upload PDF / paste hash -> six-check verdict)
REM    * AI 助手 Chat
REM    * 日志 Log
REM  Admin/issue tabs (自制, 签发, 注销, 签发方) and Student/Home
REM  are hidden. Set PUBLIC_MODE=1 below to ALSO disable admin
REM  API endpoints (403) for a true public deployment.
REM  Usage: double-click this file, then open http://127.0.0.1:8000
REM ============================================================
setlocal
cd /d "%~dp0"

set PY=python
set PUBLIC_MODE=0
set UI_VERIFY_ONLY=1

REM  Optional local LLM: set to your Ollama host. Unreachable host = offline fallback.
set OLLAMA_BASE_URL=http://127.0.0.1:11434
if not exist ".venv\Scripts\python.exe" (
  echo [portal] First run detected - creating virtual environment...
  %PY% -m venv .venv || goto :err
  echo [portal] Installing dependencies...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :err
) else (
  echo [portal] Virtual environment ready.
)

echo [portal] VERIFY-ONLY mode - tabs: Verify / AI Chat / Log
echo [portal] Starting on http://127.0.0.1:8000  (Press Ctrl+C to stop)
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
goto :eof

:err
echo [portal] Setup failed. Please install Python 3.11+ and retry.
pause
