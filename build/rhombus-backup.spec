# PyInstaller spec - build with:  pyinstaller build/rhombus-backup.spec
# Produces a single-file executable named "RhombusBackupBuddy".
import os
import sys
from pathlib import Path

project_root = Path(SPECPATH).parent
static_dir = project_root / "rhombus_backup" / "server" / "static"

datas = [(str(static_dir), "rhombus_backup/server/static")]

# If a platform ffmpeg binary was placed in build/bin/, bundle it so users
# never install anything themselves (see build/README-ffmpeg.txt).
ffmpeg_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
bundled_ffmpeg = project_root / "build" / "bin" / ffmpeg_name
binaries = [(str(bundled_ffmpeg), "bin")] if bundled_ffmpeg.exists() else []

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
    icon=None,
    upx=False,
)

# macOS: also produce a proper .app bundle so it looks native in Finder.
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="Rhombus Backup Buddy.app",
        bundle_identifier="com.rhombus.backupbuddy",
        info_plist={"NSHighResolutionCapable": True},
    )
