# Running Backup Buddy on a NAS (Docker)

Server mode runs the exact same app with the web UI served over your LAN
instead of a desktop window. The container holds the in-app scheduler, so
backups run as long as the NAS is on — no computer has to stay awake.

Image: `ghcr.io/pulisse/rhombus-backup-buddy:latest` (amd64 + arm64,
published automatically with every release).

## UGREEN NASync (UGOS Pro)

1. **Install Docker** from the UGOS App Center (one time).
2. **Create a shared folder** for footage, e.g. `CameraBackups`.
3. Open the Docker app → **Project** (compose) → create a project named
   `backup-buddy` and paste, adjusting the backups path:

   ```yaml
   services:
     backup-buddy:
       image: ghcr.io/pulisse/rhombus-backup-buddy:latest
       container_name: rhombus-backup-buddy
       ports:
         - "8600:8600"
       volumes:
         - ./config:/config
         - /volume1/CameraBackups:/backups
       restart: unless-stopped
   ```

   (Or use the Images UI: pull the image, map port 8600→8600, and mount
   your shared folder at `/backups` and a config folder at `/config`.)
4. **Deploy**, then open `http://<NAS-IP>:8600` from any browser on the
   same network.
5. Walk through the normal setup wizard:
   - Paste a Rhombus **API key** (Rhombus Console → Settings → API
     Management). "Sign in with Rhombus" is desktop-only.
   - Pick **`/backups`** as the destination folder.
   - Choose a schedule — the container keeps it running.

## Any other Docker host

```bash
docker run -d --name rhombus-backup-buddy \
  -p 8600:8600 \
  -v "$PWD/config:/config" \
  -v /path/to/backups:/backups \
  --restart unless-stopped \
  ghcr.io/pulisse/rhombus-backup-buddy:latest
```

## Deploying remotely? Skip the wizard with environment variables

NAS cloud portals (UGREEN's ug.link, etc.) only carry the NAS's own web
desktop - they won't forward the container's port 8600. If you're
installing from afar and can't reach the wizard, put the settings in the
compose file instead and the container configures itself on first start:

```yaml
    environment:
      RBB_API_KEY: "paste-your-rhombus-api-key"
      RBB_SCHEDULE: hourly          # every4h | daily_midnight | weekdays_business
      RBB_CAMERAS: all              # or comma-separated camera UUIDs
      RBB_RETENTION_DAYS: "30"
      RBB_USE_WAN: "true"           # if the NAS is NOT on the cameras' network
```

- Applied **once**, while setup is incomplete; after that the in-app
  Settings are the source of truth and these are ignored.
- `RBB_CAMERAS: all` selects every camera in the org at first start;
  cameras added to Rhombus later won't join automatically (pick them in
  Settings, like on desktop).
- The container log (Docker → Log) says exactly what happened:
  "Setup completed from environment" or why it declined.
- The API key sits in plain text in the compose file, readable by anyone
  who administers the NAS. Prefer a key scoped to video read access, and
  rotate it if the NAS isn't yours.

## Good to know

- **Keep it on your LAN.** The web UI has no login of its own — anyone who
  can reach port 8600 can manage backups. Don't port-forward it to the
  internet; if you need remote access, use a VPN (e.g. Tailscale on the NAS).
- **Credentials** live in `/config/rhombus-backup/credentials.json` with
  owner-only permissions (there is no OS keychain inside a container).
  Treat the config volume as private.
- **"Also run when the app is closed"** (OS scheduler) is a desktop
  feature — leave it off; the container itself is the always-on scheduler.
- Building locally instead of pulling: `docker build -t backup-buddy .`
  then use `backup-buddy` as the image name.
