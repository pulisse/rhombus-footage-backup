# Rhombus Backup Buddy

Back up your Rhombus camera footage to your own drive — no technical skills needed.

Rhombus Backup Buddy downloads footage from your Rhombus cameras and saves it as
normal video files on any folder you choose: an external drive, a NAS (network
drive), or this computer. It can run on a schedule so backups happen automatically.

---

## Install in 3 steps

1. **Download** the app for your computer:
   - Windows: `RhombusBackupBuddy.exe`
   - Mac: `Rhombus Backup Buddy.app`
2. **Open it.** (Mac: right-click → Open the first time. Windows: click
   "More info → Run anyway" if SmartScreen asks.)
3. **Follow the setup wizard** — it takes about 2 minutes. You'll need your
   Rhombus API key (see below).

> *[screenshot placeholder: setup wizard, step 1]*

### Getting your API key

1. Sign in to the [Rhombus Console](https://console.rhombussystems.com).
2. Go to **Settings → API Management** and click **Add API Key** (give it video access).
3. Copy the key and paste it into the app when asked. Click **Test Connection** —
   you should see your organization name and camera count.

Your key is stored in your computer's secure credential store (Windows
Credential Manager / macOS Keychain). It is never saved in a plain file.

---

## Everyday use

> *[screenshot placeholder: main screen with progress bars]*

- **Back Up Now** — pick "Last hour", "Last 24 hours", or a custom range, and
  click the big button. You'll see a progress bar per camera.
- **Automatic backups** — choose a schedule in Settings ("Every hour", "Daily at
  midnight", …). Turn on *"Also run backups when this app is closed"* to have
  your computer run backups even when the app isn't open.
- **Old footage cleans itself up** — files older than your retention setting
  (default 30 days) are deleted automatically so the drive never silently fills.

### Where do my videos go?

Inside the folder you chose, organized by date and camera:

```
Backups/
  2026-07-31/
    Front Door/
      FrontDoor_2026-07-31_14-00.mp4
    Loading Dock/
      LoadingDock_2026-07-31_14-00.mp4
    manifest_a1b2c3.json   ← a small receipt of what was backed up
```

Every file plays in any normal video player.

---

## FAQ / Troubleshooting

**"Your API key was rejected."**
The key was deleted, expired, or copied incorrectly. Create a fresh key in the
Rhombus Console (Settings → API Management) and paste it in the app's Settings.

**"No cameras are reachable."**
Open the Rhombus Console and check your cameras show **Online**. Offline cameras
can't provide footage.

**"Not enough space" warnings.**
Footage is big — plan for roughly **1.5 GB per camera per day**. The app checks
before every backup and refuses to start if the drive would fill up. Free up
space, use a bigger drive, or reduce the retention days in Settings.

**Backups are slow or time out.**
If this computer is in the **same building/network** as the cameras, keep
*"This computer is on the same network as the cameras"* checked in Settings —
downloads come straight from the cameras and are much faster. If you're backing
up from somewhere else (home, another office), **uncheck it** so footage comes
via the Rhombus cloud instead.

**"A required video component (FFmpeg) is missing."**
The packaged app includes it, so you shouldn't see this. If you do, open
**Settings → Advanced** and click **Install video component** — one click, no
PATH editing, no downloads from random websites.

**One camera failed but the others worked.**
That's by design — a problem with one camera never stops the rest. The History
tab shows exactly which camera failed and why.

**Does the app need to stay open?**
Only for in-app schedules. If you enable *"Also run backups when this app is
closed"*, the backup is registered with Windows Task Scheduler / macOS launchd
and runs on its own.

**Where are the app's own logs?**
- Mac: `~/Library/Application Support/RhombusBackup/app.log`
- Windows: `%APPDATA%\RhombusBackup\app.log`

---

*Built on the Rhombus public API. Not an official Rhombus Systems product.*
