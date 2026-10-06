@echo off
REM Builds a single-file GCShuffler.exe (no Python needed to run it).
REM Requires Python 3.8+ on PATH. Output: dist\GCShuffler.exe

python -m pip install -r requirements.txt pyinstaller || goto :error
python -m PyInstaller --onefile --windowed --name GCShuffler gc_shuffler_gui.py || goto :error

echo.
echo Done: dist\GCShuffler.exe
exit /b 0

:error
echo Build failed.
exit /b 1
