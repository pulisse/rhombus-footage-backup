# Rhombus Backup Buddy - server mode (for NAS boxes / always-on machines).
#   docker compose up -d        (see docker-compose.yml)
# UI on http://<host>:8600 - keep it on your LAN; it has no login of its own.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

COPY rhombus_backup ./rhombus_backup

# /config holds settings + credentials (0600) + history; /backups is footage.
ENV XDG_CONFIG_HOME=/config \
    RBB_HOST=0.0.0.0 \
    RBB_PORT=8600 \
    RBB_DESTINATION=/backups
VOLUME ["/config", "/backups"]
EXPOSE 8600

CMD ["python", "-m", "rhombus_backup", "--serve"]
