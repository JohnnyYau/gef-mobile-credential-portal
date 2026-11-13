@echo off
REM ============================================================
REM  GEF-mobile - ISSUE / ADMIN side (Windows one-click)
REM  ------------------------------------------------------------
REM  Runs the FULL portal: all tabs visible, including
REM    * 自制 Self-issue  (fill your own info -> build PDF/JSON
REM                        AND issue on chain -> upload verifies VALID)
REM    * 签发 Issue / 注销 Revoke / 签发方 Signers / 学生 Student
REM  Files from Self-issue are synced to the main project folder
REM  (自制凭证-outputs/).
REM  Usage: double-click this file, then open http://127.0.0.1:8000
REM ============================================================
setlocal
cd /d "%~dp0"

set PY=python
set PUBLIC_MODE=0
set UI_VERIFY_ONLY=0

if not exist ".venv\Scripts\python.exe" (
  echo [portal] First run detected - creating virtual environment...
  %PY% -m venv .venv || goto :err
  echo [portal] Installing dependencies...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :err
) else (
  echo [portal] Virtual environment ready.
)

echo [portal] ISSUE/ADMIN mode - all tabs enabled (Self-issue, Issue, Revoke, Signers...)
echo [portal] Starting on http://127.0.0.1:8000  (Press Ctrl+C to stop)
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto :eof

:err
echo [portal] Setup failed. Please install Python 3.11+ and retry.
pause
