# Developer Guide

## What this is

A desktop wrapper around the download flow from Rhombus's
[`NAS-Backup-v2/copy_footage_script_threading.py`](https://github.com/RhombusSystems/api-examples-python/tree/master/NAS-Backup-v2)
example, rebuilt as a friendly app for non-technical users.

## Architecture

```
rhombus_backup/
  __main__.py           entry point: GUI mode (pywebview/browser) or --run-backup (headless)
  core/
    api.py              RhombusClient - the only place that talks to api2.rhombussystems.com
    mpd.py              MPD (MPEG-DASH) playlist parsing (stdlib port of rhombus_mpd_info.py)
    downloader.py       BackupRun/CameraJob - segment downloads, retries, progress, manifest
    ffmpeg_utils.py     find/bundle/install FFmpeg; stream-copy mux of video+audio
    service.py          AppService - owns config, current run, in-app scheduler thread
    config.py           dataclass config; API key via `keyring` (never in JSON)
    schedule_calc.py    pure next-run-time math for the plain-English schedules
    os_sched.py         Task Scheduler / launchd / cron registration for app-closed backups
    retention.py        deletes date folders older than N days (manifest-guarded)
    naming.py           sanitized human-readable paths, no UUIDs in filenames
    errors.py           FriendlyError + mapping raw failures -> actionable messages
    space.py            free-space checks and the 1.5 GB/cam/day estimate
    history.py          JSONL run log in the app data dir
    paths.py            platform data dirs, PyInstaller detection
  server/
    app.py              Flask JSON API (thin shim over AppService) + static hosting
    static/             index.html / style.css / app.js - vanilla JS single page
```

**UI stack rationale:** all logic is behind a localhost JSON API; the "desktop
app" is a pywebview window pointed at it (WKWebView on macOS, WebView2 on
Windows). If pywebview can't start, we fall back to the user's default browser -
the app remains fully usable. This keeps the PyInstaller output small and the
UI layer completely swappable.

### The download flow (per camera)

Identical in spirit to the original script:

1. `POST /api/org/generateFederatedSessionToken` (1 h) - so the API key never
   appears in media URLs; the token rides in a `Cookie: RSESSIONID=RFT:<token>`.
2. `POST /api/camera/getMediaUris` → LAN (`lanVodMpdUrisTemplates[0]`) or WAN
   (`wanVodMpdUriTemplate`) template; fill `{START_TIME}` (epoch sec) and
   `{DURATION}` (sec).
3. GET the MPD document (this starts the camera-side session), parse
   `SegmentTemplate` (media pattern, `seg_init` name, `startNumber` - 0 LAN / 1 WAN).
4. Download `seg_init` + `duration/2` two-second segments, appending in order.
5. If the camera has an audio gateway (`associatedCameras`), repeat against
   `/api/audiogateway/getMediaUris`, then FFmpeg-mux video+audio.

Deliberate differences from the original script:

- **Stream copy, not re-encode**: `ffmpeg -c copy -movflags +faststart` instead
  of the `concat` filter (faster, lossless). Video-only cameras are also
  remuxed for a clean container.
- **Retry with backoff** (3 tries, 0.5/1/2 s) per media request; up to 60
  consecutive missing segments are tolerated as recording gaps.
- **Fixed** the original's copy-paste bug of checking the session response's
  status where the media-URI response was meant.
- TLS verification stays **on** for api2 and **off only** for media requests
  (LAN cameras use self-signed certs), rather than off globally.
- Cameras fail independently; one bad camera never kills the run.

### Threading model

- Flask serves on a random localhost port, `threaded=True`.
- A backup is one `BackupRun` executed on a worker thread; it fans out per
  camera with `ThreadPoolExecutor(max_workers=cfg.threads)` (default 4, same
  as the original, to respect API rate limits).
- The UI polls `/api/status` once a second; no websockets, which keeps
  packaged builds boring and reliable.
- The in-app scheduler is one daemon thread (`service._restart_scheduler`).
  When the OS-level schedule is enabled, the in-app loop stands down so runs
  aren't duplicated.

### Known API assumptions (verify against a real org)

- Org name endpoint: tries `/api/org/getOrgV2` then `/api/org/getUserOrgs`,
  and degrades to "your organization" if both fail. Harmless if wrong.
- Location names from `/api/location/getLocations`; degrades to a single
  "All cameras" group.
- A bad API key returns **403** (observed), not 401; both map to the
  "key rejected" message.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m rhombus_backup          # native window (or browser fallback)
python dev_server.py              # fixed port 8765, browser only - best for UI work
python -m pytest tests/          # unit tests (no network, Rhombus API mocked)
python -m rhombus_backup --run-backup   # what the OS scheduler executes
```

Config/logs live in `~/Library/Application Support/RhombusBackup` (macOS),
`%APPDATA%\RhombusBackup` (Windows), `~/.config/rhombus-backup` (Linux).

## Building distributables

```bash
./build/build.sh      # macOS/Linux -> dist/Rhombus Backup Buddy.app / binary
build\build.bat       # Windows     -> dist\RhombusBackupBuddy.exe
```

The build script drops a static FFmpeg into `build/bin/` (via the
imageio-ffmpeg wheel) and the spec bundles it; `ffmpeg_utils.find_ffmpeg()`
looks there first. For production you may prefer an official static FFmpeg
build in `build/bin/` - just place it there before building. macOS releases
should be codesigned + notarized; Windows releases benefit from Authenticode
signing to avoid SmartScreen friction.

## Extending

- **New schedule choice**: add to `config.SCHEDULE_CHOICES`, implement in
  `schedule_calc.next_run` / `window_for`, add the OS mapping in `os_sched`,
  and a test in `test_schedule_calc.py`.
- **New error mapping**: add a message constant + branch in `errors.py`, test
  it in `test_errors.py`. UI and logs pick it up automatically.
- **Different UI**: everything the UI does goes through the JSON endpoints in
  `server/app.py`; nothing else knows HTML exists.
