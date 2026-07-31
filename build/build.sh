#!/usr/bin/env bash
# Build a distributable app for macOS or Linux.
# Usage:  ./build/build.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .venv-build
source .venv-build/bin/activate
pip install --quiet -r requirements-dev.txt

# Bundle a static ffmpeg so users never install it themselves.
if [ ! -f build/bin/ffmpeg ]; then
  echo "Fetching a static FFmpeg to bundle..."
  mkdir -p build/bin
  python - <<'EOF'
import shutil, subprocess, sys
subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "imageio-ffmpeg"])
import imageio_ffmpeg
shutil.copy(imageio_ffmpeg.get_ffmpeg_exe(), "build/bin/ffmpeg")
EOF
  chmod +x build/bin/ffmpeg
fi

pyinstaller --noconfirm --distpath dist --workpath build/tmp build/rhombus-backup.spec
echo
echo "Done. Find the app in ./dist/"
