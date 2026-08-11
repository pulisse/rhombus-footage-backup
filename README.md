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

### Connecting to Rhombus

**Easiest: click "Sign in with Rhombus."** Your normal Rhombus login page opens
in your browser; sign in as usual and the app sets up its own access
automatically — nothing to copy or paste. (Your Rhombus account needs
permission to create API keys; if it doesn't, ask your administrator or use
the paste-a-key option below.)

**Or paste an API key:**
1. Sign in to the [Rhombus Console](https://console.rhombussystems.com).
2. Go to **Settings → API Management** and click **Add API Key** (give it video access).
3. Copy the key and paste it into the app when asked. Click **Test Connection** —
   you should see your organization name and camera count.

Either way, access is stored in your computer's secure credential store
(Windows Credential Manager / macOS Keychain). It is never saved in a plain file.

---

## Run it on a NAS instead (Docker)

Have a NAS or an always-on box? Run the same app there as a container —
the web UI is served on your LAN and scheduled backups run around the
clock with no computer left on:

```bash
docker run -d -p 8600:8600 \
  -v "$PWD/config:/config" -v /path/to/backups:/backups \
  --restart unless-stopped ghcr.io/pulisse/rhombus-backup-buddy:latest
```

Full walkthrough (including UGREEN UGOS steps): [docs/DOCKER.md](docs/DOCKER.md).

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
- **Get notified when backups finish** — in Settings → Notifications, paste an
  incoming-webhook URL from Slack, Microsoft Teams, or Google Chat (or add your
  mail server details for email). Choose "After every backup" or "Only when
  something fails", then click **Send Test** to confirm it works.

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

**"Sign in with Rhombus" fails or the button is missing.**
The button appears only in builds where sign-in has been set up by whoever
distributes the app. You can always use the paste-a-key option instead — it
does exactly the same thing. If sign-in says your account can't create keys,
ask your Rhombus administrator.

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
