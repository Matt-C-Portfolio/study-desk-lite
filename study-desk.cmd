@echo off
setlocal
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -m study_desk %*
) else (
  python -m study_desk %*
)
