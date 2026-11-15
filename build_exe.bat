@echo off
REM ArbStudio.exe uretir -> dist\ArbStudio.exe (tek dosya, Python gerektirmez)
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [build] Sanal ortam olusturuluyor...
    python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)

".venv\Scripts\python.exe" -m pip install --quiet pyinstaller || goto :error

echo [build] Derleniyor ^(1-2 dakika surer^)...
".venv\Scripts\python.exe" -m PyInstaller arbstudio.spec --noconfirm --clean || goto :error

echo [build] Dogrulaniyor...
"dist\ArbStudio.exe" --selftest || goto :error

echo.
echo [build] Hazir: %CD%\dist\ArbStudio.exe
dir /b /a-d "dist\ArbStudio.exe"
goto :eof

:error
echo.
echo [build] Derleme basarisiz.
pause
exit /b 1
