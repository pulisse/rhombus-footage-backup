# PyInstaller spec - build with:  pyinstaller build/rhombus-backup.spec
# Produces a single-file executable named "RhombusBackupBuddy".
import os
import sys
from pathlib import Path

project_root = Path(SPECPATH).parent
static_dir = project_root / "rhombus_backup" / "server" / "static"

datas = [(str(static_dir), "rhombus_backup/server/static")]

# "Sign in with Rhombus" client credentials (created once by
# scripts/register_oauth_app.py). Optional: without it the app still works
# via the paste-an-API-key flow.
oauth_file = project_root / "oauth_client.json"
if oauth_file.exists():
    datas.append((str(oauth_file), "."))

# If a platform ffmpeg binary was placed in build/bin/, bundle it so users
# never install anything themselves (see build/README-ffmpeg.txt).
ffmpeg_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
bundled_ffmpeg = project_root / "build" / "bin" / ffmpeg_name
binaries = [(str(bundled_ffmpeg), "bin")] if bundled_ffmpeg.exists() else []

# App icon (Backup Buddy mascot) — .ico for Windows, .icns for macOS.
icon_file = project_root / "build" / ("icon.ico" if os.name == "nt" else "icon.icns")
app_icon = str(icon_file) if icon_file.exists() else None

hiddenimports = [
    "keyring.backends.macOS",
    "keyring.backends.Windows",
    "keyring.backends.SecretService",
    "keyring.backends.chainer",
]

a = Analysis(
    [str(project_root / "rhombus_backup" / "__main__.py")],
    pathex=[str(project_root)],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="RhombusBackupBuddy",
    console=False,          # no scary terminal window for end users
    icon=app_icon,
    upx=False,
)

# macOS: also produce a proper .app bundle so it looks native in Finder.
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="Rhombus Backup Buddy.app",
        icon=app_icon,
        bundle_identifier="com.rhombus.backupbuddy",
        info_plist={"NSHighResolutionCapable": True},
    )
