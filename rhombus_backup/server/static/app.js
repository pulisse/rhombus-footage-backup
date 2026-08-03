/* Rhombus Backup Buddy front-end. Plain JS, no build step. */
"use strict";

const $ = (id) => document.getElementById(id);
const api = async (path, body) => {
  const opts = body !== undefined
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const resp = await fetch(path, opts);
  let data;
  try { data = await resp.json(); }
  catch { data = { ok: false, error: "The app stopped responding. Try reopening it." }; }
  return data;
};
const human = (b) => {
  if (b == null) return "unknown";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (Math.abs(b) >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return b.toFixed(i ? 1 : 0) + " " + u[i];
};
const fmtWhen = (epoch) => new Date(epoch * 1000).toLocaleString([], {
  month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
});

let STATE = null;          // /api/state payload
let cameraGroups = [];     // for wizard + settings
let pollTimer = null;

/* ---------------- view switching ---------------- */
function showView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  $("view-" + name).classList.remove("hidden");
  document.querySelectorAll(".nav-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === name));
  if (name === "history") loadHistory("history-list", false);
  if (name === "settings") initSettings();
  if (name === "main") { loadHistory("recent-list", true); refreshEstimate(); }
}
document.querySelectorAll(".nav-btn").forEach((b) =>
  b.addEventListener("click", () => showView(b.dataset.view)));

/* ---------------- boot ---------------- */
async function boot() {
  STATE = await api("/api/state");
  if (!STATE.ok) return;
  if (STATE.setupComplete && STATE.hasApiKey) {
    $("main-nav").classList.remove("hidden");
    showView("main");
    startPolling();
  } else {
    showView("wizard");
    initWizard();
  }
}

/* ================= WIZARD ================= */
const wiz = { step: 1, total: 5, apiKey: "", keyOk: false, dest: "", cams: new Set() };

function initWizard() {
  const dots = $("wizard-steps");
  dots.innerHTML = "";
  for (let i = 1; i <= wiz.total; i++) {
    const d = document.createElement("div");
    d.className = "dot" + (i === 1 ? " done" : "");
    dots.appendChild(d);
  }
  renderScheduleRadios($("wiz-schedule"), STATE.config.schedule);
  $("wiz-retention").value = STATE.config.retentionDays || 30;
  $("wiz-signin-block").classList.toggle("hidden", !STATE.signinAvailable);
  showWizStep(1);
}

/* -- Sign in with Rhombus (shared by wizard + settings) -- */
async function runSignIn(statusEl, onSuccess) {
  statusEl.className = "inline-status";
  statusEl.textContent = "Opening your browser - sign in there…";
  const start = await api("/api/oauth/start", {});
  if (!start.ok) { statusEl.className = "inline-status bad"; statusEl.textContent = start.error; return; }
  const labels = {
    waiting: "Waiting for you to sign in in the browser…",
    exchanging: "Finishing sign-in…",
    minting: "Setting up this app's access…",
  };
  while (true) {
    await new Promise((r) => setTimeout(r, 1200));
    const s = await api("/api/oauth/status");
    if (!s.ok) continue;
    if (s.state === "done" && s.org) {
      statusEl.className = "inline-status good";
      statusEl.textContent = `✓ Connected to ${s.org.orgName} - ${s.org.cameraCount} camera${s.org.cameraCount === 1 ? "" : "s"} (${s.org.onlineCount} online)`;
      onSuccess(s.org);
      return;
    }
    if (s.state === "failed") {
      statusEl.className = "inline-status bad";
      statusEl.textContent = s.error || "Sign-in didn't complete. Try again.";
      return;
    }
    statusEl.textContent = labels[s.state] || "Working…";
  }
}

$("wiz-signin-btn").addEventListener("click", () =>
  runSignIn($("wiz-signin-status"), () => {
    wiz.keyOk = true;      // key is parked server-side; never sent to this page
    wiz.apiKey = "";
    validateWizStep();
  }));

function showWizStep(n) {
  wiz.step = n;
  document.querySelectorAll(".wizard-pane").forEach((p) =>
    p.classList.toggle("hidden", +p.dataset.step !== n));
  document.querySelectorAll("#wizard-steps .dot").forEach((d, i) =>
    d.classList.toggle("done", i < n));
  $("wiz-back").classList.toggle("hidden", n === 1);
  $("wiz-next").textContent = n === wiz.total ? "Finish Setup" : "Next";
  $("wiz-error").textContent = "";
  validateWizStep();
}

function validateWizStep() {
  let ok = false;
  if (wiz.step === 1) ok = wiz.keyOk;
  else if (wiz.step === 2) ok = !!$("wiz-dest").value.trim();
  else if (wiz.step === 3) ok = wiz.cams.size > 0;
  else ok = true;
  $("wiz-next").disabled = !ok;
}

$("wiz-test-btn").addEventListener("click", async () => {
  const key = $("wiz-apikey").value.trim();
  const out = $("wiz-test-result");
  out.className = "inline-status";
  out.textContent = "Checking…";
  const r = await api("/api/test-key", { apiKey: key });
  if (r.ok) {
    wiz.apiKey = key; wiz.keyOk = true;
    out.className = "inline-status good";
    out.textContent = `✓ Connected to ${r.orgName} - ${r.cameraCount} camera${r.cameraCount === 1 ? "" : "s"} (${r.onlineCount} online)`;
  } else {
    wiz.keyOk = false;
    out.className = "inline-status bad";
    out.textContent = r.error;
  }
  validateWizStep();
});

async function pickFolder(inputEl, statusEl) {
  const r = await api("/api/browse-folder", {});
  if (r.folder) {
    inputEl.value = r.folder;
  } else if (r.cancelled) {
    return; // user closed the native dialog on purpose
  } else {
    // Native dialog unavailable (browser mode or it failed): built-in browser.
    const chosen = await openFolderModal(inputEl.value.trim());
    if (!chosen) return;
    inputEl.value = chosen;
  }
  inputEl.dispatchEvent(new Event("input"));
  if (statusEl) updateFreeSpace(inputEl, statusEl);
}

/* ---------------- built-in folder browser ---------------- */
const fb = { current: null, resolve: null };

function openFolderModal(startPath) {
  $("folder-modal").classList.remove("hidden");
  fbNavigate(startPath || null);
  return new Promise((resolve) => { fb.resolve = resolve; });
}
function closeFolderModal(result) {
  $("folder-modal").classList.add("hidden");
  if (fb.resolve) { fb.resolve(result); fb.resolve = null; }
}

async function fbNavigate(path) {
  const r = await api("/api/list-folders", { path });
  if (!r.ok) return;
  fb.current = r.current;
  fb.parent = r.parent;
  $("fb-current").textContent = r.current;
  $("fb-up").disabled = !r.parent;
  $("fb-info").className = "inline-status" + (r.error ? " warn" : "");
  $("fb-info").textContent = r.error ||
    `Free space here: ${r.freeHuman}` + (r.writable ? "" : " · ⚠ you can't save into this folder");
  $("fb-select").disabled = !r.writable;

  const places = $("fb-places");
  places.innerHTML = "<option value=''>Go to…</option>";
  r.places.forEach((p) => {
    const o = document.createElement("option");
    o.value = p.path; o.textContent = p.name;
    places.appendChild(o);
  });

  const list = $("fb-list");
  list.innerHTML = "";
  if (!r.folders.length) {
    list.innerHTML = "<div class='fb-empty'>No folders inside - you can use this one, or create a new folder.</div>";
  }
  r.folders.forEach((f) => {
    const div = document.createElement("div");
    div.className = "fb-entry";
    div.textContent = "📁 " + f.name;
    div.addEventListener("click", () => fbNavigate(f.path));
    list.appendChild(div);
  });
}

$("fb-up").addEventListener("click", () => fb.parent && fbNavigate(fb.parent));
$("fb-places").addEventListener("change", (e) => { if (e.target.value) fbNavigate(e.target.value); });
$("fb-cancel").addEventListener("click", () => closeFolderModal(null));
$("fb-select").addEventListener("click", () => closeFolderModal(fb.current));
$("fb-newfolder").addEventListener("click", async () => {
  const name = prompt("Name for the new folder:");
  if (!name) return;
  const r = await api("/api/create-folder", { parent: fb.current, name });
  if (!r.ok) { $("fb-info").className = "inline-status bad"; $("fb-info").textContent = r.error; return; }
  fbNavigate(r.path);
});
$("wiz-browse-btn").addEventListener("click", () => pickFolder($("wiz-dest"), $("wiz-freespace")));
$("wiz-dest").addEventListener("input", () => { validateWizStep(); });
$("wiz-dest").addEventListener("change", () => updateFreeSpace($("wiz-dest"), $("wiz-freespace")));

async function updateFreeSpace(inputEl, statusEl) {
  const path = inputEl.value.trim();
  if (!path) { statusEl.textContent = ""; return; }
  const r = await api("/api/freespace", { path });
  statusEl.className = "inline-status" + (r.free == null ? " bad" : "");
  statusEl.textContent = r.free == null
    ? "That folder isn't reachable - is the drive connected?"
    : `Free space on this drive: ${r.freeHuman}`;
}

function renderCameraList(container, selectedSet, onChange) {
  container.innerHTML = "";
  cameraGroups.forEach((g) => {
    const grp = document.createElement("div");
    grp.className = "loc-group";
    const head = document.createElement("label");
    head.className = "loc-header";
    const all = document.createElement("input");
    all.type = "checkbox";
    const camIds = g.cameras.map((c) => c.uuid);
    const sync = () => { all.checked = camIds.every((id) => selectedSet.has(id)); };
    all.addEventListener("change", () => {
      camIds.forEach((id) => all.checked ? selectedSet.add(id) : selectedSet.delete(id));
      renderCameraList(container, selectedSet, onChange);
      onChange();
    });
    head.appendChild(all);
    head.appendChild(document.createTextNode(" " + g.location));
    grp.appendChild(head);
    g.cameras.forEach((c) => {
      const line = document.createElement("label");
      line.className = "cam-line";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = selectedSet.has(c.uuid);
      cb.addEventListener("change", () => {
        cb.checked ? selectedSet.add(c.uuid) : selectedSet.delete(c.uuid);
        sync(); onChange();
      });
      const dot = document.createElement("span");
      dot.className = "status-dot " + (c.online ? "on" : "off");
      line.appendChild(cb);
      line.appendChild(dot);
      line.appendChild(document.createTextNode(" " + c.name + " "));
      if (!c.online) {
        const off = document.createElement("span");
        off.className = "offline-label";
        off.textContent = "(offline)";
        line.appendChild(off);
      }
      grp.appendChild(line);
    });
    sync();
    container.appendChild(grp);
  });
}

async function loadWizCameras() {
  $("wiz-cam-loading").textContent = "Loading your cameras…";
  const r = await api("/api/cameras", { apiKey: wiz.apiKey });
  if (!r.ok) { $("wiz-cam-loading").textContent = r.error; return; }
  cameraGroups = r.groups;
  $("wiz-cam-loading").textContent =
    "Tick the cameras to include. Offline cameras are shown too - they'll be backed up once they're online.";
  // preselect all online cameras
  cameraGroups.forEach((g) => g.cameras.forEach((c) => { if (c.online) wiz.cams.add(c.uuid); }));
  renderCameraList($("wiz-cam-list"), wiz.cams, validateWizStep);
  validateWizStep();
}

function renderScheduleRadios(container, current) {
  container.innerHTML = "";
  STATE.scheduleChoices.forEach((ch) => {
    const l = document.createElement("label");
    const r = document.createElement("input");
    r.type = "radio"; r.name = container.id + "-sched"; r.value = ch.value;
    r.checked = ch.value === current;
    l.appendChild(r);
    l.appendChild(document.createTextNode(" " + ch.label));
    container.appendChild(l);
  });
}
const radioValue = (container) =>
  (container.querySelector("input:checked") || {}).value || "manual";

$("wiz-back").addEventListener("click", () => showWizStep(wiz.step - 1));
$("wiz-next").addEventListener("click", async () => {
  if (wiz.step === 2) {
    wiz.dest = $("wiz-dest").value.trim();
  }
  if (wiz.step < wiz.total) {
    showWizStep(wiz.step + 1);
    if (wiz.step === 3 && !cameraGroups.length) loadWizCameras();
    return;
  }
  // Finish: save everything
  $("wiz-next").disabled = true;
  const r = await api("/api/config", {
    apiKey: wiz.apiKey,
    destination: $("wiz-dest").value.trim(),
    cameraUuids: [...wiz.cams],
    schedule: radioValue($("wiz-schedule")),
    osScheduleEnabled: $("wiz-os-sched").checked,
    retentionDays: +$("wiz-retention").value || 30,
    setupComplete: true,
  });
  if (!r.ok) {
    $("wiz-error").textContent = r.error;
    $("wiz-next").disabled = false;
    return;
  }
  STATE = await api("/api/state");
  $("main-nav").classList.remove("hidden");
  showView("main");
  startPolling();
});

/* ================= MAIN ================= */
$("range-preset").addEventListener("change", () => {
  const custom = $("range-preset").value === "custom";
  $("custom-range").classList.toggle("hidden", !custom);
  if (custom && !$("range-start").value) {
    const now = new Date(), ago = new Date(now - 3600e3);
    const iso = (d) => new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    $("range-start").value = iso(ago);
    $("range-end").value = iso(now);
  }
  refreshEstimate();
});
["range-start", "range-end"].forEach((id) => $(id).addEventListener("change", refreshEstimate));

function rangeBody() {
  const preset = $("range-preset").value;
  if (preset !== "custom") return { preset };
  return { preset, startLocal: $("range-start").value, endLocal: $("range-end").value };
}
function rangeDurationSec() {
  const preset = $("range-preset").value;
  if (preset === "lastHour") return 3600;
  if (preset === "last24h") return 86400;
  const s = new Date($("range-start").value), e = new Date($("range-end").value);
  return Math.max(0, (e - s) / 1000);
}

async function refreshEstimate() {
  const n = (STATE.config.cameraUuids || []).length;
  const dur = rangeDurationSec();
  if (!n || !dur) { $("estimate-line").textContent = ""; return; }
  const r = await api("/api/estimate", { cameraCount: n, durationSec: dur });
  const el = $("estimate-line");
  el.className = "inline-status" + (r.message ? " warn" : "");
  el.textContent = r.message ||
    `${n} camera${n === 1 ? "" : "s"} · estimated size about ${r.estimateHuman} · ${r.freeHuman} free on the backup drive`;
}

$("backup-btn").addEventListener("click", async () => {
  $("main-error").textContent = "";
  $("backup-btn").disabled = true;
  const r = await api("/api/backup", rangeBody());
  if (!r.ok) {
    $("main-error").textContent = r.error;
    $("backup-btn").disabled = false;
    return;
  }
  startPolling();
});
$("cancel-btn").addEventListener("click", () => api("/api/cancel", {}));

function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(pollStatus, 1000);
  pollStatus();
}

async function pollStatus() {
  const s = await api("/api/status");
  if (!s.ok) return;

  const label = $("next-run-label");
  if (s.nextScheduled) {
    label.textContent = "Next automatic backup: " + fmtWhen(s.nextScheduled);
    label.classList.remove("hidden");
  } else label.classList.add("hidden");

  const run = s.run;
  const running = run && run.state === "running";
  $("backup-btn").disabled = !!running;
  $("cancel-btn").classList.toggle("hidden", !running);
  $("progress-card").classList.toggle("hidden", !run);
  if (!run) return;

  $("progress-title").textContent = {
    running: "Backing up…", done: "Backup finished", failed: "Backup failed",
    cancelled: "Backup stopped", pending: "Starting…",
  }[run.state] || run.state;
  $("progress-overall").textContent = run.overallPercent + "%";
  $("progress-overall-bar").style.width = run.overallPercent + "%";
  const doneCams = run.cameras.filter((c) => c.status === "done").length;
  const failedCams = run.cameras.filter((c) => c.status === "failed").length;
  $("progress-sub").textContent =
    `${fmtWhen(run.startEpoch)} → ${fmtWhen(run.startEpoch + run.durationSec)}` +
    ` · ${human(run.bytes)} downloaded · ${doneCams}/${run.cameras.length} cameras done` +
    (failedCams ? ` · ${failedCams} failed` : "");

  const box = $("camera-progress");
  box.innerHTML = "";
  run.cameras.forEach((c) => {
    const div = document.createElement("div");
    div.className = "cam-progress";
    const row = document.createElement("div");
    row.className = "row space-between";
    const nm = document.createElement("span");
    nm.className = "name"; nm.textContent = c.name;
    const st = document.createElement("span");
    st.className = "state " + c.status;
    st.textContent = {
      queued: "waiting…", downloading: `${c.percent}% · ${human(c.bytes)}`,
      merging: "packaging video…", done: "✓ saved " + human(c.bytes),
      failed: c.error, skipped: "skipped",
    }[c.status] || c.status;
    row.appendChild(nm); row.appendChild(st);
    div.appendChild(row);
    if (c.status === "downloading" || c.status === "merging") {
      const track = document.createElement("div");
      track.className = "progress-track";
      const fill = document.createElement("div");
      fill.className = "progress-fill";
      fill.style.width = (c.status === "merging" ? 100 : c.percent) + "%";
      track.appendChild(fill);
      div.appendChild(track);
    }
    box.appendChild(div);
  });

  if (!running && run.state !== "pending") loadHistory("recent-list", true);
}

/* ================= HISTORY ================= */
async function loadHistory(elId, compact) {
  const r = await api("/api/history");
  const box = $(elId);
  box.innerHTML = "";
  if (!r.ok || !r.entries.length) {
    box.innerHTML = "<p class='inline-status'>No backups yet.</p>";
    return;
  }
  r.entries.slice(0, compact ? 5 : 50).forEach((e) => {
    const div = document.createElement("div");
    div.className = "entry";
    const head = document.createElement("div");
    head.className = "headline";
    const when = document.createElement("span");
    when.textContent = e.finishedAt ? fmtWhen(e.finishedAt) : "";
    const status = document.createElement("span");
    const okN = e.ok || 0, failN = e.failed || 0;
    if (e.state === "done" && !failN) { status.className = "ok"; status.textContent = `✓ ${okN} camera${okN === 1 ? "" : "s"} backed up`; }
    else if (e.state === "done") { status.className = "partial"; status.textContent = `⚠ ${okN} succeeded, ${failN} failed`; }
    else { status.className = "failed"; status.textContent = "✕ " + (e.error || e.state); }
    const size = document.createElement("span");
    size.className = "inline-status";
    if (e.bytes) size.textContent = human(e.bytes);
    head.appendChild(when); head.appendChild(status); head.appendChild(size);
    div.appendChild(head);
    (e.cameras || []).filter((c) => c.status === "failed").forEach((c) => {
      const d = document.createElement("div");
      d.className = "detail";
      d.textContent = `${c.name}: ${c.error}`;
      div.appendChild(d);
    });
    box.appendChild(div);
  });
}

/* ================= SETTINGS ================= */
const setCams = new Set();

async function initSettings() {
  const c = STATE.config;
  $("set-signin-block").classList.toggle("hidden", !STATE.signinAvailable);
  $("set-dest").value = c.destination;
  $("set-retention").value = c.retentionDays;
  $("set-threads").value = c.threads;
  $("set-lan").checked = !c.useWan;
  $("set-os-sched").checked = c.osScheduleEnabled;
  $("set-os-sched-state").textContent = STATE.osScheduleRegistered
    ? "(currently registered with this computer)" : "";
  renderScheduleRadios($("set-schedule"), c.schedule);
  updateFreeSpace($("set-dest"), $("set-freespace"));

  const ff = $("ffmpeg-status");
  ff.className = "inline-status " + (STATE.ffmpegOk ? "good" : "bad");
  ff.textContent = STATE.ffmpegOk
    ? "✓ Video component (FFmpeg): installed"
    : "✕ Video component (FFmpeg) is missing - backups can't finish without it.";
  $("ffmpeg-install-btn").classList.toggle("hidden", STATE.ffmpegOk);

  setCams.clear();
  (c.cameraUuids || []).forEach((id) => setCams.add(id));
  if (!cameraGroups.length) {
    const r = await api("/api/cameras", {});
    if (r.ok) cameraGroups = r.groups;
    else { $("set-cam-list").innerHTML = `<p class='inline-status bad' style='padding:10px'>${r.error}</p>`; return; }
  }
  renderCameraList($("set-cam-list"), setCams, () => {});
}

$("set-browse-btn").addEventListener("click", () => pickFolder($("set-dest"), $("set-freespace")));
$("set-dest").addEventListener("change", () => updateFreeSpace($("set-dest"), $("set-freespace")));

$("set-signin-btn").addEventListener("click", () =>
  runSignIn($("set-signin-status"), async () => {
    // Persist the freshly minted key right away (empty update adopts it).
    await api("/api/config", {});
  }));

$("set-test-btn").addEventListener("click", async () => {
  const key = $("set-apikey").value.trim();
  const out = $("set-test-result");
  if (!key) { out.textContent = "Paste a key first."; return; }
  out.className = "inline-status"; out.textContent = "Checking…";
  const r = await api("/api/test-key", { apiKey: key });
  out.className = "inline-status " + (r.ok ? "good" : "bad");
  out.textContent = r.ok ? `✓ Connected to ${r.orgName}` : r.error;
});

$("ffmpeg-install-btn").addEventListener("click", async () => {
  const ff = $("ffmpeg-status");
  ff.className = "inline-status"; ff.textContent = "Installing… this can take a minute.";
  const r = await api("/api/install-ffmpeg", {});
  ff.className = "inline-status " + (r.ok ? "good" : "bad");
  ff.textContent = r.ok ? "✓ Installed!" : r.error;
  if (r.ok) $("ffmpeg-install-btn").classList.add("hidden");
});

$("set-save-btn").addEventListener("click", async () => {
  $("set-error").textContent = "";
  const out = $("set-save-result");
  out.textContent = "Saving…";
  const body = {
    destination: $("set-dest").value.trim(),
    cameraUuids: [...setCams],
    schedule: radioValue($("set-schedule")),
    retentionDays: +$("set-retention").value,
    threads: +$("set-threads").value,
    useWan: !$("set-lan").checked,
    osScheduleEnabled: $("set-os-sched").checked,
  };
  const key = $("set-apikey").value.trim();
  if (key) body.apiKey = key;
  const r = await api("/api/config", body);
  if (!r.ok) { out.textContent = ""; $("set-error").textContent = r.error; return; }
  out.className = "inline-status good";
  out.textContent = "✓ Saved";
  $("set-apikey").value = "";
  STATE = await api("/api/state");
  setTimeout(() => { out.textContent = ""; }, 2500);
});

boot();
