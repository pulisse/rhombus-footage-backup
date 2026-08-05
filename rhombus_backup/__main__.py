"""Entry point.

  RhombusBackup                # launch the desktop app (pywebview or browser)
  RhombusBackup --run-backup   # headless scheduled backup (used by OS scheduler)
"""
import argparse
import logging
import logging.handlers
import socket
import sys
import threading
import webbrowser

from rhombus_backup import APP_DISPLAY_NAME
from rhombus_backup.core import paths
from rhombus_backup.core.service import AppService


def _setup_logging():
    handler = logging.handlers.RotatingFileHandler(
        paths.log_file(), maxBytes=2_000_000, backupCount=2, encoding="utf-8"
    )
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if not paths.is_frozen():
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_headless() -> int:
    """Scheduled mode: no UI, exit code reflects success for Task Scheduler logs."""
    service = AppService()
    if not service.cfg.setup_complete:
        logging.getLogger("rhombus").error("Setup not complete; skipping scheduled run.")
        return 2
    try:
        snap = service.run_scheduled_backup_blocking()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("rhombus").error("Scheduled backup failed: %s", exc)
        return 1
    return 0 if snap["state"] in ("done",) else 1


def run_gui() -> int:
    from rhombus_backup.server import app as server_mod
    from rhombus_backup.server.app import create_app

    service = AppService()
    service.start_scheduler()
    flask_app = create_app(service)
    port = _free_port()
    url = "http://127.0.0.1:{}/".format(port)

    def serve():
        # Werkzeug dev server is fine for a single local user; threaded for
        # concurrent status polling during downloads.
        flask_app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)

    threading.Thread(target=serve, daemon=True, name="http").start()

    try:
        import webview  # pywebview

        window = webview.create_window(
            APP_DISPLAY_NAME, url, width=1000, height=740, min_size=(860, 600)
        )
        server_mod.webview_window = window
        webview.start()  # blocks until the window closes
        return 0
    except Exception as exc:  # noqa: BLE001 - fall back to the default browser
        logging.getLogger("rhombus").warning(
            "Native window unavailable (%s); opening in your browser instead.", exc
        )
        webbrowser.open(url)
        print("{} is running at {} - close this window to quit.".format(APP_DISPLAY_NAME, url))
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return 0


def main() -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(prog="RhombusBackup", description=APP_DISPLAY_NAME)
    parser.add_argument(
        "--run-backup", action="store_true",
        help="run one scheduled backup without opening the app window",
    )
    args = parser.parse_args()
    return run_headless() if args.run_backup else run_gui()


if __name__ == "__main__":
    sys.exit(main())
