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
  if (name === "library") initLibrary();
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

/* Camera picker: search, All/None, foldable location groups, counts. */
const camPickerState = new Map(); // container id -> {query, folded:Set<location>}

function renderCameraList(container, selectedSet, onChange) {
  const st = camPickerState.get(container.id) || { query: "", folded: new Set() };
  camPickerState.set(container.id, st);
  const rerender = () => renderCameraList(container, selectedSet, onChange);
  const q = st.query.trim().toLowerCase();
  const allCams = cameraGroups.flatMap((g) => g.cameras);
  const matches = (g, c) =>
    !q || c.name.toLowerCase().includes(q) || g.location.toLowerCase().includes(q);
  const visible = cameraGroups
    .map((g) => ({ ...g, cameras: g.cameras.filter((c) => matches(g, c)) }))
    .filter((g) => g.cameras.length);
  const visibleIds = visible.flatMap((g) => g.cameras.map((c) => c.uuid));

  container.classList.remove("camera-list");
  container.innerHTML = "";

  // toolbar: search + All/None + count
  const bar = document.createElement("div");
  bar.className = "cam-toolbar";
  const search = document.createElement("input");
  search.type = "text";
  search.placeholder = "Search cameras or locations…";
  search.value = st.query;
  search.addEventListener("input", () => {
    st.query = search.value;
    const pos = search.selectionStart;
    rerender();
    const s2 = container.querySelector(".cam-toolbar input");
    s2.focus(); s2.setSelectionRange(pos, pos);
  });
  const btnAll = document.createElement("button");
  btnAll.className = "btn"; btnAll.type = "button";
  btnAll.textContent = q ? "All shown" : "All";
  btnAll.addEventListener("click", () => {
    visibleIds.forEach((id) => selectedSet.add(id)); rerender(); onChange();
  });
  const btnNone = document.createElement("button");
  btnNone.className = "btn"; btnNone.type = "button";
  btnNone.textContent = q ? "None shown" : "None";
  btnNone.addEventListener("click", () => {
    visibleIds.forEach((id) => selectedSet.delete(id)); rerender(); onChange();
  });
  const count = document.createElement("span");
  count.className = "cam-count";
  count.textContent = `${[...selectedSet].filter((id) => allCams.some((c) => c.uuid === id)).length} of ${allCams.length} selected`;
  bar.append(search, btnAll, btnNone, count);
  container.appendChild(bar);

  const listEl = document.createElement("div");
  listEl.className = "camera-list";
  container.appendChild(listEl);

  const highlight = (text) => {
    if (!q) return document.createTextNode(" " + text + " ");
    const i = text.toLowerCase().indexOf(q);
    if (i < 0) return document.createTextNode(" " + text + " ");
    const frag = document.createDocumentFragment();
    frag.append(" " + text.slice(0, i));
    const m = document.createElement("mark");
    m.textContent = text.slice(i, i + q.length);
    frag.append(m, text.slice(i + q.length) + " ");
    return frag;
  };

  if (!visible.length) {
    listEl.innerHTML = "<div class='cam-no-results'>No cameras match that search.</div>";
    return;
  }

  visible.forEach((g) => {
    const folded = !q && st.folded.has(g.location); // searching auto-unfolds
    const grp = document.createElement("div");
    grp.className = "loc-group" + (folded ? " folded" : "");

    const head = document.createElement("div");
    head.className = "loc-header";
    const arrow = document.createElement("span");
    arrow.className = "fold-arrow";
    arrow.textContent = "▼";
    const all = document.createElement("input");
    all.type = "checkbox";
    const camIds = g.cameras.map((c) => c.uuid);
    const selCount = camIds.filter((id) => selectedSet.has(id)).length;
    all.checked = selCount === camIds.length;
    all.indeterminate = selCount > 0 && selCount < camIds.length;
    all.addEventListener("click", (e) => e.stopPropagation());
    all.addEventListener("change", () => {
      camIds.forEach((id) => all.checked ? selectedSet.add(id) : selectedSet.delete(id));
      rerender(); onChange();
    });
    const locCount = document.createElement("span");
    locCount.className = "loc-count";
    locCount.textContent = `${selCount}/${camIds.length} selected`;
    head.append(arrow, all, highlight(g.location), locCount);
    head.addEventListener("click", (e) => {
      if (e.target === all) return;
      st.folded.has(g.location) ? st.folded.delete(g.location) : st.folded.add(g.location);
      rerender();
    });
    grp.appendChild(head);

    g.cameras.forEach((c) => {
      const line = document.createElement("label");
      line.className = "cam-line";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = selectedSet.has(c.uuid);
      cb.addEventListener("change", () => {
        cb.checked ? selectedSet.add(c.uuid) : selectedSet.delete(c.uuid);
        rerender(); onChange();
      });
      const dot = document.createElement("span");
      dot.className = "status-dot " + (c.online ? "on" : "off");
      line.append(cb, dot, highlight(c.name));
      if (!c.online) {
        const off = document.createElement("span");
        off.className = "offline-label";
        off.textContent = "(offline)";
        line.appendChild(off);
      }
      grp.appendChild(line);
    });
    listEl.appendChild(grp);
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

  // The spinner element persists across polls - recreating it every second
  // restarts its CSS animation and makes it stutter.
  $("progress-spinner").classList.toggle("hidden", !running);
  const titleText = {
    running: "Backing up…", done: "Backup finished", failed: "Backup failed",
    cancelled: "Backup stopped", pending: "Starting…",
  }[run.state] || run.state;
  const titleEl = $("progress-title-text");
  if (titleEl.textContent !== titleText) titleEl.textContent = titleText;
  $("progress-overall").textContent = run.overallPercent + "%";
  const overallBar = $("progress-overall-bar");
  overallBar.style.width = run.overallPercent + "%";
  overallBar.classList.toggle("active", !!running);
  const doneCams = run.cameras.filter((c) => c.status === "done").length;
  const failedCams = run.cameras.filter((c) => c.status === "failed").length;
  let eta = "";
  if (running && run.startedAt && run.overallPercent > 2) {
    const elapsed = Date.now() / 1000 - run.startedAt;
    const remaining = elapsed * (100 - run.overallPercent) / run.overallPercent;
    eta = remaining > 90
      ? ` · about ${Math.round(remaining / 60)} min left`
      : ` · under 2 min left`;
  }
  $("progress-sub").textContent =
    `${fmtWhen(run.startEpoch)} → ${fmtWhen(run.startEpoch + run.durationSec)}` +
    ` · ${human(run.bytes)} downloaded · ${doneCams}/${run.cameras.length} cameras done` +
    (failedCams ? ` · ${failedCams} failed` : "") + eta;

  renderCameraProgress(run);

  if (!running && run.state !== "pending") loadHistory("recent-list", true);
}

/* Per-camera progress rows are updated IN PLACE (keyed by camera uuid) so the
   CSS animations - striped fills, indeterminate sweeps - run continuously
   instead of restarting on every 1-second poll. */
function renderCameraProgress(run) {
  const box = $("camera-progress");
  const seen = new Set();
  run.cameras.forEach((c) => {
    seen.add(c.uuid);
    let div = box.querySelector(`[data-uuid="${CSS.escape(c.uuid)}"]`);
    if (!div) {
      div = document.createElement("div");
      div.className = "cam-progress";
      div.dataset.uuid = c.uuid;
      const row = document.createElement("div");
      row.className = "row space-between";
      const nm = document.createElement("span");
      nm.className = "name"; nm.textContent = c.name;
      const st = document.createElement("span");
      st.className = "state";
      row.append(nm, st);
      const track = document.createElement("div");
      track.className = "progress-track";
      const fill = document.createElement("div");
      fill.className = "progress-fill";
      track.appendChild(fill);
      div.append(row, track);
      box.appendChild(div);
    }
    const st = div.querySelector(".state");
    const stateClass = "state " + c.status;
    if (st.className !== stateClass) st.className = stateClass;
    const text = {
      queued: "waiting…", downloading: `${c.percent}% · ${human(c.bytes)}`,
      audio: "downloading audio…", merging: "packaging video…",
      done: "✓ saved " + human(c.bytes),
      failed: c.error, skipped: "skipped",
    }[c.status] || c.status;
    if (st.textContent !== text) st.textContent = text;

    const track = div.querySelector(".progress-track");
    const fill = div.querySelector(".progress-fill");
    const showBar = ["downloading", "audio", "merging", "queued"].includes(c.status);
    track.classList.toggle("hidden", !showBar);
    let fillClass = "progress-fill";
    if (c.status === "downloading") fillClass += " active";
    else if (showBar) fillClass += " indeterminate"; // queued/audio/merging sweep
    if (fill.className !== fillClass) fill.className = fillClass;
    if (c.status === "downloading") fill.style.width = c.percent + "%";
  });
  [...box.children].forEach((el) => {
    if (!seen.has(el.dataset.uuid)) el.remove(); // rows from a previous run
  });
}

/* ================= LIBRARY ================= */
/* Browse backed-up footage: pick camera + day, click the 24h timeline to play
   that moment. Clip = one backed-up file; the timeline shows where footage
   exists (coverage) and a playhead that follows the video. */
const LIB = { days: [], cameras: [], camera: null, date: null, clip: null, midnight: 0 };

async function initLibrary() {
  const r = await api("/api/library");
  const empty = !r.ok || !r.days.length;
  $("lib-empty").classList.toggle("hidden", !empty);
  $("lib-viewer").classList.toggle("hidden", empty);
  if (empty) return;
  LIB.days = r.days;
  LIB.cameras = r.cameras;
  if (!LIB.cameras.includes(LIB.camera)) LIB.camera = LIB.cameras[0];

  const camSel = $("lib-camera");
  camSel.innerHTML = "";
  LIB.cameras.forEach((name) => {
    const o = document.createElement("option");
    o.value = name; o.textContent = "📷 " + name;
    camSel.appendChild(o);
  });
  camSel.value = LIB.camera;
  renderLibDates();
}

function libDatesForCamera() {
  return LIB.days.filter((d) => d.clips.some((c) => c.camera === LIB.camera));
}

function renderLibDates() {
  const dates = libDatesForCamera();
  const dateSel = $("lib-date");
  dateSel.innerHTML = "";
  dates.forEach((d) => {
    const o = document.createElement("option");
    o.value = d.date;
    o.textContent = new Date(d.date + "T00:00").toLocaleDateString([], {
      weekday: "short", month: "short", day: "numeric", year: "numeric",
    });
    dateSel.appendChild(o);
  });
  if (!dates.some((d) => d.date === LIB.date)) LIB.date = dates.length ? dates[0].date : null;
  if (LIB.date) dateSel.value = LIB.date;
  renderLibDay();
}

function libClips() {
  const day = LIB.days.find((d) => d.date === LIB.date);
  return day ? day.clips.filter((c) => c.camera === LIB.camera) : [];
}

function renderLibDay() {
  const clips = libClips();
  LIB.midnight = LIB.date ? new Date(LIB.date + "T00:00").getTime() / 1000 : 0;
  const rail = $("lib-rail");
  rail.innerHTML = "";

  // hour ticks
  for (let h = 1; h < 24; h++) {
    const t = document.createElement("span");
    t.className = "lib-tick" + (h % 4 === 0 ? " major" : "");
    t.style.left = (100 * h / 24) + "%";
    rail.appendChild(t);
  }
  // footage coverage
  clips.forEach((c) => {
    const left = Math.max(0, 100 * (c.startEpoch - LIB.midnight) / 86400);
    const width = Math.min(100 - left, 100 * c.durationSec / 86400);
    const seg = document.createElement("div");
    seg.className = "lib-cov";
    seg.style.left = left + "%";
    seg.style.width = Math.max(width, 0.4) + "%";
    rail.appendChild(seg);
  });
  const ph = document.createElement("div");
  ph.className = "lib-playhead hidden";
  ph.id = "lib-playhead";
  rail.appendChild(ph);

  // clip list
  const list = $("lib-clip-list");
  list.innerHTML = "";
  clips.forEach((c) => {
    const div = document.createElement("div");
    div.className = "entry lib-entry";
    const from = new Date(c.startEpoch * 1000);
    const to = new Date((c.startEpoch + c.durationSec) * 1000);
    const fmt = (d) => d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    div.innerHTML = `<span class="lib-play">▶</span> ${fmt(from)} – ${fmt(to)}`
      + ` <span class="inline-status">· ${human(c.bytes)}</span>`;
    div.addEventListener("click", () => loadClip(c, 0, true));
    list.appendChild(div);
  });

  // reset player
  const video = $("lib-video");
  video.removeAttribute("src");
  video.load();
  LIB.clip = null;
  $("lib-clip-label").textContent = clips.length
    ? "Pick a moment on the timeline, or press ▶ on a clip below."
    : "No footage from this camera on this day.";
  $("lib-clip-size").textContent = "";
  $("lib-video-error").classList.add("hidden");
}

function loadClip(clip, offsetSec, autoplay) {
  LIB.clip = clip;
  const video = $("lib-video");
  $("lib-video-error").classList.add("hidden");
  video.src = "/api/library/media?path=" + encodeURIComponent(clip.file);
  const seek = () => {
    if (offsetSec > 0 && offsetSec < (video.duration || clip.durationSec)) {
      video.currentTime = offsetSec;
    }
    if (autoplay) video.play().catch(() => {});
    video.removeEventListener("loadedmetadata", seek);
  };
  video.addEventListener("loadedmetadata", seek);
  const name = clip.file.split("/").pop();
  $("lib-clip-label").textContent = "Clip: " + name;
  $("lib-clip-size").textContent = human(clip.bytes);
}

$("lib-rail").addEventListener("click", (e) => {
  const rect = $("lib-rail").getBoundingClientRect();
  const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
  const t = LIB.midnight + frac * 86400;
  const clips = libClips();
  let clip = clips.find((c) => t >= c.startEpoch && t < c.startEpoch + c.durationSec);
  let offset = clip ? t - clip.startEpoch : 0;
  if (!clip) {
    // clicked a gap: jump to the start of the next clip that day
    clip = clips.find((c) => c.startEpoch > t);
    offset = 0;
  }
  if (clip) loadClip(clip, offset, true);
});

$("lib-video").addEventListener("timeupdate", () => {
  const ph = $("lib-playhead");
  if (!ph || !LIB.clip) return;
  const t = LIB.clip.startEpoch + $("lib-video").currentTime;
  ph.classList.remove("hidden");
  ph.style.left = Math.min(100, Math.max(0, 100 * (t - LIB.midnight) / 86400)) + "%";
});

$("lib-video").addEventListener("error", () => {
  if (!LIB.clip) return;
  const err = $("lib-video-error");
  err.textContent = "This clip can't be played here. It may use a video format "
    + "(like H.265) this window doesn't support - the file itself is fine and "
    + "plays in VLC or your system video player.";
  err.classList.remove("hidden");
});

$("lib-camera").addEventListener("change", () => {
  LIB.camera = $("lib-camera").value;
  renderLibDates();
});
$("lib-date").addEventListener("change", () => {
  LIB.date = $("lib-date").value;
  renderLibDay();
});

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

  $("set-notify-mode").value = c.notifyMode || "never";
  $("set-slack").value = c.slackWebhook || "";
  $("set-teams").value = c.teamsWebhook || "";
  $("set-gchat").value = c.gchatWebhook || "";
  $("set-email-to").value = c.emailTo || "";
  $("set-smtp-host").value = c.smtpHost || "";
  $("set-smtp-port").value = c.smtpPort || 587;
  $("set-smtp-user").value = c.smtpUser || "";
  $("email-details").open = !!(c.emailTo || c.smtpHost);

  const ff = $("ffmpeg-status");
  ff.className = "inline-status " + (STATE.ffmpegOk ? "good" : "bad");
  ff.textContent = STATE.ffmpegOk
    ? "✓ Video component (FFmpeg): installed"
    : "✕ Video component (FFmpeg) is missing - backups can't finish without it.";
  $("ffmpeg-install-btn").classList.toggle("hidden", STATE.ffmpegOk);
  $("signin-config-status").textContent = STATE.signinAvailable
    ? "✓ 'Sign in with Rhombus' is set up for this build."
    : "'Sign in with Rhombus' isn't set up for this build (needs oauth_client.json "
      + "from scripts/register_oauth_app.py), so only the paste-a-key option is shown.";

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

$("notify-test-btn").addEventListener("click", async () => {
  const out = $("notify-test-result");
  out.className = "inline-status";
  out.textContent = "Sending… (save settings first if you just added a channel)";
  const r = await api("/api/test-notification", {});
  out.className = "inline-status " + (r.ok ? "good" : "bad");
  out.textContent = r.ok ? `✓ Sent to ${r.channels.join(", ")}` : r.error;
});

$("ffmpeg-install-btn").addEventListener("click", async () => {
  const ff = $("ffmpeg-status");
  ff.className = "inline-status"; ff.textContent = "Installing… this can take a minute.";
  const r = await api("/api/install-ffmpeg", {});
  ff.className = "inline-status " + (r.ok ? "good" : "bad");
  ff.textContent = r.ok ? "✓ Installed!" : r.error;
  if (r.ok) $("ffmpeg-install-btn").classList.add("hidden");
});

async function saveSettings() {
  $("set-error").textContent = "";
  const outs = [$("set-save-result"), $("set-save-result-top")];
  const out = {
    set className(v) { outs.forEach((o) => { o.className = v; }); },
    set textContent(v) { outs.forEach((o) => { o.textContent = v; }); },
  };
  out.textContent = "Saving…";
  const body = {
    destination: $("set-dest").value.trim(),
    cameraUuids: [...setCams],
    schedule: radioValue($("set-schedule")),
    retentionDays: +$("set-retention").value,
    threads: +$("set-threads").value,
    useWan: !$("set-lan").checked,
    osScheduleEnabled: $("set-os-sched").checked,
    notifyMode: $("set-notify-mode").value,
    slackWebhook: $("set-slack").value.trim(),
    teamsWebhook: $("set-teams").value.trim(),
    gchatWebhook: $("set-gchat").value.trim(),
    emailTo: $("set-email-to").value.trim(),
    smtpHost: $("set-smtp-host").value.trim(),
    smtpPort: +$("set-smtp-port").value || 587,
    smtpUser: $("set-smtp-user").value.trim(),
  };
  const key = $("set-apikey").value.trim();
  if (key) body.apiKey = key;
  const smtpPass = $("set-smtp-pass").value;
  if (smtpPass) body.smtpPassword = smtpPass;
  const r = await api("/api/config", body);
  if (!r.ok) { out.textContent = ""; $("set-error").textContent = r.error; return; }
  out.className = "inline-status good";
  out.textContent = "✓ Saved";
  $("set-apikey").value = "";
  $("set-smtp-pass").value = "";
  STATE = await api("/api/state");
  setTimeout(() => { out.textContent = ""; }, 2500);
}
$("set-save-btn").addEventListener("click", saveSettings);
$("set-save-btn-top").addEventListener("click", saveSettings);

boot();
