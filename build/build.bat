@echo off
REM Build a distributable RhombusBackupBuddy.exe for Windows.
REM Usage:  build\build.bat
cd /d "%~dp0\.."

python -m venv .venv-build
call .venv-build\Scripts\activate.bat
pip install --quiet -r requirements-dev.txt

if not exist build\bin\ffmpeg.exe (
  echo Fetching a static FFmpeg to bundle...
  mkdir build\bin 2>nul
  python -c "import subprocess,sys,shutil; subprocess.check_call([sys.executable,'-m','pip','install','--quiet','imageio-ffmpeg']); import imageio_ffmpeg; shutil.copy(imageio_ffmpeg.get_ffmpeg_exe(), r'build\bin\ffmpeg.exe')"
)

pyinstaller --noconfirm --distpath dist --workpath build\tmp build\rhombus-backup.spec
echo.
echo Done. Find RhombusBackupBuddy.exe in .\dist\
