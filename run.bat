@echo off
REM ARB Studio - tek tik calistirma. Ilk calistirmada venv kurar.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ARB Studio] Sanal ortam olusturuluyor...
    python -m venv .venv || goto :error
    echo [ARB Studio] Bagimliliklar kuruluyor ^(PySide6 ~120 MB, bir kez^)...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)

".venv\Scripts\pythonw.exe" -m arbstudio %*
goto :eof

:error
echo.
echo [ARB Studio] Kurulum basarisiz. Python 3.10+ kurulu mu?
pause
exit /b 1
