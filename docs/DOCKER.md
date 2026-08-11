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
