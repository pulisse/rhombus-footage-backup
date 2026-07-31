"""Dev-only: run the UI on a fixed port in the browser (no pywebview window)."""
from rhombus_backup.core.service import AppService
from rhombus_backup.server.app import create_app

if __name__ == "__main__":
    service = AppService()
    service.start_scheduler()
    create_app(service).run(host="127.0.0.1", port=8765, threaded=True, use_reloader=False)
