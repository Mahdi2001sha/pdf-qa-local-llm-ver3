@echo off
setlocal
title PDF Reading Test
cd /d "%~dp0"

set "PY=%~dp0backend\venv\Scripts\python.exe"
set "PYTHONIOENCODING=utf-8"

rem ---- Check requirements ----
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10+ and tick "Add to PATH".
  pause
  exit /b 1
)

rem ---- Python environment (shared with Start.bat) ----
if not exist "%PY%" (
  echo Creating virtual environment...
  python -m venv backend\venv
  if errorlevel 1 (
    echo Could not create the virtual environment.
    pause
    exit /b 1
  )
)
if not exist "backend\venv\.deps_installed" (
  echo Installing Python packages...
  "%PY%" -m pip install -r backend\requirements.txt
  if errorlevel 1 (
    echo Package installation failed.
    pause
    exit /b 1
  )
  echo ok> backend\venv\.deps_installed
)

rem ---- OCR packages for scanned PDFs (Tesseract itself is installed separately) ----
if not exist "backend\venv\.ocr_tesseract_installed" (
  echo Installing OCR packages for scanned PDFs...
  "%PY%" -m pip install -r backend\requirements-ocr.txt
  if errorlevel 1 (
    echo.
    echo WARNING: OCR packages could not be installed. Typed PDFs still work.
    echo Run this file again to retry.
    echo.
  ) else (
    echo ok> backend\venv\.ocr_tesseract_installed
  )
)
set "TESS_FOUND="
if exist "models\tesseract\tesseract.exe" set "TESS_FOUND=1"
if exist "%ProgramFiles%\Tesseract-OCR\tesseract.exe" set "TESS_FOUND=1"
if exist "%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe" set "TESS_FOUND=1"
where tesseract >nul 2>nul && set "TESS_FOUND=1"
if not defined TESS_FOUND (
  echo.
  echo NOTE: Tesseract OCR was not found. Typed PDFs work, but scanned PDFs need it.
  echo Install it from https://github.com/UB-Mannheim/tesseract/wiki and tick Persian.
  echo.
)

rem ---- Run the reading test (no LLM needed) ----
echo.
echo Drop a PDF onto this file, or choose one in the window that opens.
"%PY%" backend\test_reader.py %*
echo.
pause
