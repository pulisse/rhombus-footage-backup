# Manual Test Checklist (against a real Rhombus org)

Run these in order on each platform you ship (Windows + macOS at minimum).
Items marked ⚠ verify assumptions that could not be tested without a real org.

## Setup wizard
- [ ] Launch app fresh (delete the config dir first) → wizard appears.
- [ ] ⚠ **Sign in with Rhombus** (needs `oauth_client.json` from
      `scripts/register_oauth_app.py`): button opens the default browser at the
      Rhombus consent page; after approving, the tab says "You're signed in",
      the wizard shows org name + camera count, and a new API key named
      "Rhombus Backup Buddy (<hostname>)" appears in Console → API Management.
- [ ] Sign-in with an account that lacks API-key permission → friendly
      "ask your Rhombus administrator" message; paste-a-key path still works.
- [ ] Cancel the consent page / let it time out (5 min) → app shows a friendly
      timeout, not a hang; retry works without restarting.
- [ ] Choose Folder in the **native window**: OS folder dialog opens; Cancel
      does nothing; choosing fills the path + free space.
- [ ] Choose Folder in **browser mode** (`python dev_server.py`): built-in
      folder browser opens; Go to… shortcuts, Up, New Folder…, and
      "Use This Folder" all work; read-only folders disable the select button.
- [ ] Paste a **bad** key → Test Connection shows the "key was rejected /
      no permission" message, Next stays disabled.
- [ ] Paste a **good** key → shows org name ⚠ and camera count; Next enables.
      (⚠ if org name shows "your organization", note it: the getOrgV2/getUserOrgs
      assumption needs adjusting in `core/api.py`.)
- [ ] Choose Folder opens a native picker (pywebview mode); free space shown.
- [ ] Camera list is grouped by location ⚠ with per-location "select all";
      offline cameras marked. (⚠ if all cameras appear under "All cameras",
      the getLocations assumption needs adjusting.)
- [ ] Pick "Every hour" + tick "run when app is closed" + finish → main screen.
- [ ] Verify the API key is NOT in `config.json`; it IS in
      Keychain/Credential Manager under "RhombusBackup".

## Manual backup
- [ ] "Last hour" → Back Up Now: per-camera progress bars advance, overall %
      and MB counts move, estimated size shown before starting.
- [ ] Resulting files exist at `<dest>/<YYYY-MM-DD>/<CameraName>/Name_date_time.mp4`
      and play in QuickTime/VLC/Windows Media Player. Timestamps are local time.
- [ ] A camera **with** an audio gateway produces a file with sound.
- [ ] `manifest_<runid>.json` exists in the date folder and lists every camera,
      file, byte size, and the time range.
- [ ] Custom range picker: end before start is rejected with a clear message;
      a >7-day range is rejected with a clear message.
- [ ] Cancel mid-run → run stops within a few seconds, status "Backup stopped",
      partially-downloaded temp files are cleaned up (no `.rhombus-tmp` left).

## Failure handling
- [ ] Unplug one camera (or pick an offline one) → other cameras complete;
      History shows exactly which camera failed and a readable reason.
- [ ] LAN mode from a network that can't reach the cameras → error suggests
      toggling the "same network" setting. Toggle it OFF → WAN backup works.
- [ ] Fill (or nearly fill) the destination drive → preflight refuses to start
      with a size comparison; free space, retry → works.
- [ ] Revoke the API key in the Console mid-use → next action shows the
      key-rejected message; pasting a new key in Settings fixes it without restart.
- [ ] Kill the network mid-run → retries happen (watch app.log), then a friendly
      timeout message; no crash, no stack trace shown to the user.

## Scheduling
- [ ] Schedule "Every hour" with app open → "Next automatic backup" pill shows
      the top of the next hour; leave it open past the hour → backup runs and
      appears in History.
- [ ] Enable "run when app is closed" → `schtasks /Query /TN RhombusBackupBuddy`
      (Win) or `launchctl list | grep rhombus` (Mac) shows the task. Quit the
      app, wait for the schedule → new date folder + manifest appear.
- [ ] Disable the toggle → the OS task is gone.
- [ ] With OS schedule ON and the app open, confirm runs are NOT duplicated.

## Retention
- [ ] Set retention to 1 day, create a fake old folder `2020-01-01` **with** a
      `manifest_x.json` inside → after the next run it is deleted.
- [ ] A date-named folder **without** a manifest is left untouched.

## Packaging
- [ ] Built app launches on a machine with **no Python and no FFmpeg installed**;
      a full backup (including audio merge) succeeds.
- [ ] macOS: app opens via right-click → Open without terminal windows.
- [ ] Windows: no console window appears; app survives SmartScreen "Run anyway".
- [ ] App data lands in the right per-user folder; `app.log` contains no API key
      (search the log for the key string!).
