"""The backup engine: downloads footage for the selected cameras.

Preserves the original script's core flow per camera:
  federated token -> getMediaUris template -> fill {START_TIME}/{DURATION} ->
  fetch MPD (starts the camera session) -> seg_init + N two-second segments ->
  FFmpeg merge (video + optional audio) -> cleanup temp files.

Adds on top: retry with backoff, per-camera progress, disk-space guard,
partial-failure isolation, manifest.json, and friendly error reporting.
"""
import json
import logging
import shutil
import threading
import time
import uuid as uuid_mod
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import requests

from . import naming, space
from .api import RhombusClient, media_session
from .config import AppConfig
from .errors import FriendlyError, friendly_exception
from .ffmpeg_utils import merge_av
from .mpd import RhombusMPDInfo, segment_uri

_log = logging.getLogger("rhombus.backup")

SEGMENT_SECONDS = 2
MEDIA_TIMEOUT = 20          # per segment request
MAX_SEGMENT_RETRIES = 3
MAX_CONSECUTIVE_MISSES = 60  # ~2 min of missing footage -> treat camera as failed
SPACE_CHECK_EVERY = 50       # segments


class CancelledError(Exception):
    pass


class CameraJob:
    """Progress + result for one camera in a run."""

    def __init__(self, cam: dict):
        self.uuid = cam["uuid"]
        self.name = cam["name"]
        self.status = "queued"      # queued | downloading | audio | merging | done | failed | skipped
        self.done_segments = 0
        self.total_segments = 0
        self.bytes = 0
        self.error = ""             # friendly message when failed
        self.output = ""            # final file path when done

    def as_dict(self) -> dict:
        return {
            "uuid": self.uuid, "name": self.name, "status": self.status,
            "doneSegments": self.done_segments, "totalSegments": self.total_segments,
            "bytes": self.bytes, "error": self.error, "output": self.output,
            "percent": round(100.0 * self.done_segments / self.total_segments, 1)
            if self.total_segments else 0,
        }


class BackupRun:
    """One backup run over a set of cameras and a time range."""

    def __init__(
        self,
        cfg: AppConfig,
        api_key: str,
        cameras: List[dict],
        start_epoch: int,
        duration_sec: int,
        ffmpeg_path: str,
        audio_map: Optional[Dict[str, str]] = None,
        on_change: Optional[Callable[[], None]] = None,
    ):
        self.cfg = cfg
        self.client = RhombusClient(api_key)
        self._api_key = api_key
        self.cameras = cameras
        self.start_epoch = int(start_epoch)
        self.duration_sec = int(duration_sec)
        self.ffmpeg_path = ffmpeg_path
        self.audio_map = audio_map or {}
        self.on_change = on_change or (lambda: None)

        self.run_id = uuid_mod.uuid4().hex[:12]
        self.jobs = [CameraJob(c) for c in cameras]
        self.started_at = None
        self.finished_at = None
        self.state = "pending"      # pending | running | done | failed | cancelled
        self.error = ""
        self._cancel = threading.Event()
        self._space_lock = threading.Lock()
        self._space_exhausted = False

    # -- public --------------------------------------------------------------
    def cancel(self):
        self._cancel.set()

    def snapshot(self) -> dict:
        total = sum(j.total_segments for j in self.jobs)
        done = sum(j.done_segments for j in self.jobs)
        return {
            "runId": self.run_id,
            "state": self.state,
            "error": self.error,
            "startEpoch": self.start_epoch,
            "durationSec": self.duration_sec,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "overallPercent": round(100.0 * done / total, 1) if total else 0,
            "bytes": sum(j.bytes for j in self.jobs),
            "estimateBytes": space.estimate_bytes(len(self.jobs), self.duration_sec),
            "cameras": [j.as_dict() for j in self.jobs],
        }

    def execute(self) -> dict:
        """Run to completion (blocking). Returns the final snapshot."""
        self.state = "running"
        self.started_at = time.time()
        self.on_change()
        try:
            with ThreadPoolExecutor(max_workers=max(1, self.cfg.threads)) as pool:
                futures = {pool.submit(self._backup_camera, job): job for job in self.jobs}
                for fut in as_completed(futures):
                    job = futures[fut]
                    try:
                        fut.result()
                    except CancelledError:
                        job.status = "skipped"
                        job.error = "Cancelled before this camera finished."
                    except Exception as exc:  # noqa: BLE001 - isolate per camera
                        fe = friendly_exception(exc, self.cfg.use_wan)
                        job.status = "failed"
                        job.error = str(fe)
                        _log.warning("Camera %s failed: %s (%s)", job.name, fe, fe.technical)
                    self.on_change()
        finally:
            self.finished_at = time.time()
            if self._cancel.is_set():
                self.state = "cancelled"
            elif all(j.status == "failed" for j in self.jobs) and self.jobs:
                self.state = "failed"
                self.error = self.jobs[0].error
            else:
                self.state = "done"
            self._write_manifest()
            self.on_change()
        return self.snapshot()

    # -- per-camera ------------------------------------------------------------
    def _check_cancel(self):
        if self._cancel.is_set():
            raise CancelledError()

    def _check_space(self, every_counter: int):
        if every_counter % SPACE_CHECK_EVERY:
            return
        with self._space_lock:
            if self._space_exhausted:
                raise FriendlyError(
                    "The backup drive ran out of space during this run, so "
                    "remaining cameras were stopped safely."
                )
            free = space.free_bytes(self.cfg.destination)
            if free is not None and free < space.MIN_FREE_BYTES:
                self._space_exhausted = True
                self._cancel.set()
                raise FriendlyError(
                    "The backup drive ran out of space mid-run. The backup stopped "
                    "safely; free up space and run it again."
                )

    def _backup_camera(self, job: CameraJob):
        self._check_cancel()
        time.sleep(0.1)  # stagger, matching the original's rate-limit courtesy
        job.status = "downloading"
        job.total_segments = max(1, self.duration_sec // SEGMENT_SECONDS)
        self.on_change()

        start_local = datetime.fromtimestamp(self.start_epoch)
        final_path = naming.dedupe_path(
            naming.clip_path(self.cfg.destination, job.name, start_local)
        )
        tmp_dir = Path(self.cfg.destination) / ".rhombus-tmp" / "{}_{}".format(self.run_id, job.uuid)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        video_tmp = tmp_dir / "video.m4v"
        audio_tmp = tmp_dir / "audio.m4a"

        try:
            token = self.client.generate_session_token(3600)
            media_headers = {"Cookie": "RSESSIONID=RFT:" + token}
            sess = media_session(self._api_key)

            template = self.client.get_camera_mpd_template(job.uuid, self.cfg.use_wan)
            self._download_stream(
                job, sess, media_headers, template, video_tmp, audio=False
            )

            audio_ok = False
            gw = self.audio_map.get(job.uuid)
            if gw:
                job.status = "audio"   # UI: "downloading audio..." so 100% never looks stuck
                self.on_change()
                try:
                    a_template = self.client.get_audio_mpd_template(gw, self.cfg.use_wan)
                    self._download_stream(
                        job, sess, media_headers, a_template, audio_tmp,
                        audio=True, count_progress=False,
                    )
                    audio_ok = True
                except (FriendlyError, requests.RequestException) as exc:
                    _log.warning("Audio for %s failed, keeping video only: %s", job.name, exc)

            job.status = "merging"
            self.on_change()
            final_path.parent.mkdir(parents=True, exist_ok=True)
            merge_av(self.ffmpeg_path, video_tmp, audio_tmp if audio_ok else None, final_path)
            job.bytes = final_path.stat().st_size
            job.output = str(final_path)
            job.status = "done"
        except Exception:
            # Salvage a partial raw download if the merge machinery failed late.
            if video_tmp.exists() and video_tmp.stat().st_size > 0 and not final_path.exists():
                salvage = final_path.with_suffix(".partial.mp4")
                try:
                    final_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(video_tmp), str(salvage))
                    job.output = str(salvage)
                except OSError:
                    pass
            raise
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _download_stream(
        self,
        job: CameraJob,
        sess: requests.Session,
        media_headers: dict,
        mpd_template: str,
        out_path: Path,
        audio: bool,
        count_progress: bool = True,
    ):
        mpd_uri = mpd_template.replace("{START_TIME}", str(self.start_epoch)).replace(
            "{DURATION}", str(self.duration_sec)
        )
        mpd_doc = self._get_with_retry(sess, mpd_uri, media_headers)
        info = RhombusMPDInfo(mpd_doc.content.decode("utf-8"), audio)

        n_segments = self.duration_sec // SEGMENT_SECONDS
        consecutive_misses = 0
        with open(out_path, "wb") as fp:
            init_uri = segment_uri(mpd_uri, info.init_string)
            fp.write(self._get_with_retry(sess, init_uri, media_headers).content)

            for i in range(n_segments):
                self._check_cancel()
                self._check_space(i)
                seg_uri = segment_uri(mpd_uri, info.segment_name(i))
                try:
                    resp = self._get_with_retry(sess, seg_uri, media_headers)
                    fp.write(resp.content)
                    if count_progress:
                        job.bytes += len(resp.content)
                    consecutive_misses = 0
                except FriendlyError:
                    # A single missing segment = a small gap in footage; keep going.
                    consecutive_misses += 1
                    if consecutive_misses >= MAX_CONSECUTIVE_MISSES:
                        raise FriendlyError(
                            "The camera stopped providing footage for this time "
                            "range (it may not have recordings that far back, or "
                            "the connection dropped). A partial file was saved."
                        )
                if count_progress:
                    job.done_segments = i + 1
                    if i % 15 == 0:
                        self.on_change()
        if count_progress:
            job.done_segments = n_segments or 1
            self.on_change()

    def _get_with_retry(self, sess: requests.Session, url: str, headers: dict) -> requests.Response:
        last_exc = None
        for attempt in range(MAX_SEGMENT_RETRIES):
            self._check_cancel()
            try:
                resp = sess.get(url, headers=headers, timeout=MEDIA_TIMEOUT)
                if resp.status_code == 200:
                    return resp
                last_exc = friendly_exception(
                    requests.exceptions.HTTPError(response=resp), self.cfg.use_wan
                )
            except requests.RequestException as exc:
                last_exc = friendly_exception(exc, self.cfg.use_wan)
            time.sleep(0.5 * (2 ** attempt))  # 0.5s, 1s, 2s backoff
        raise last_exc

    # -- manifest ---------------------------------------------------------------
    def _fetch_events(self) -> dict:
        """Activity events per camera for the backed-up window, so the Library
        can overlay them offline later. Best-effort: a failure here never
        fails the backup."""
        events = {}
        if self._cancel.is_set():
            return events
        for j in self.jobs:
            if j.status != "done":
                continue
            try:
                events[j.uuid] = self.client.get_footage_seekpoints(
                    j.uuid, self.start_epoch, self.duration_sec
                )[:5000]
            except Exception as exc:  # noqa: BLE001
                _log.warning("Could not fetch events for %s: %s", j.name, exc)
        return events

    def _write_manifest(self):
        try:
            events = self._fetch_events()
            start_local = datetime.fromtimestamp(self.start_epoch)
            folder = Path(self.cfg.destination) / naming.date_folder(start_local)
            folder.mkdir(parents=True, exist_ok=True)
            manifest = {
                "app": "Rhombus Backup Buddy",
                "runId": self.run_id,
                "state": self.state,
                "timeRange": {
                    "startEpoch": self.start_epoch,
                    "durationSec": self.duration_sec,
                    "startLocal": start_local.isoformat(),
                },
                "cameras": [
                    {
                        "uuid": j.uuid, "name": j.name, "status": j.status,
                        "file": j.output, "bytes": j.bytes, "error": j.error,
                        "events": events.get(j.uuid, []),
                    }
                    for j in self.jobs
                ],
                "totalBytes": sum(j.bytes for j in self.jobs),
            }
            path = folder / "manifest_{}.json".format(self.run_id)
            path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except OSError as exc:
            _log.warning("Could not write manifest: %s", exc)
