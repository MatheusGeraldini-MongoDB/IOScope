import json
import re
import webbrowser
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import pandas as pd
import plotly.graph_objects as go

APP_NAME = "IOScope"
APP_TAGLINE = "Disk I/O analysis from SAR disk logs"

METRIC_COLS = [
    "tps", "rd_sec_s", "wr_sec_s",
    "avrq_sz", "avgqu_sz", "await",
    "svctm", "pct_util",
]

# Field descriptions based on sar(1) (-d) and related sysstat SAR disk docs.
METRIC_INFO = {
    "tps": {
        "menu": "tps — I/O transfers/s",
        "description": (
            "Total transfers per second issued to the device. "
            "A transfer is an I/O request; multiple logical requests may be merged."
        ),
    },
    "rd_sec_s": {
        "menu": "rd_sec_s — Sectors read/s",
        "description": (
            "Sectors read from the device per second. "
            "Sectors are 512 bytes (equivalent to sar bread/s blocks/s)."
        ),
    },
    "wr_sec_s": {
        "menu": "wr_sec_s — Sectors written/s",
        "description": (
            "Sectors written to the device per second. "
            "Sectors are 512 bytes (equivalent to sar bwrtn/s blocks/s)."
        ),
    },
    "avrq_sz": {
        "menu": "avrq_sz — Avg request size",
        "description": (
            "Average size of I/O requests issued to the device, in sectors. "
            "In sar -d this field is now areq-sz (kibibytes); older reports used avgrq-sz."
        ),
    },
    "avgqu_sz": {
        "menu": "avgqu_sz — Avg queue length",
        "description": (
            "Average queue length of requests issued to the device. "
            "In sar -d this field is now aqu-sz; older reports used avgqu-sz."
        ),
    },
    "await": {
        "menu": "await — Avg I/O time (ms)",
        "description": (
            "Average time in milliseconds for I/O requests to be served, "
            "including queue wait and service time."
        ),
    },
    "svctm": {
        "menu": "svctm — Avg service time (ms)",
        "description": (
            "Average service time in milliseconds for I/O requests issued to the device. "
            "Legacy SAR disk metric; not shown in current sar(1) reports."
        ),
    },
    "pct_util": {
        "menu": "pct_util — Device busy %",
        "description": (
            "Percentage of elapsed time during which I/O requests were issued to the device. "
            "Near 100% may indicate saturation on serial devices."
        ),
    },
}

LINE_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#393b79", "#637939", "#8c6d31", "#843c39", "#7b4173",
    "#5254a3", "#6b6ecf", "#9c9ede", "#ad494a", "#b5cf6b",
]

LOWER_LINE_DASHES = ["dot", "dash", "dashdot", "longdash", "longdashdot"]
TOP_DEVICE_FRACTION = 0.25
MIN_TOP_DEVICES = 5
MAX_TOP_DEVICES = 15


def device_color(device_index):
    return LINE_COLORS[device_index % len(LINE_COLORS)]


def metric_device_line_styles(df, metric, devices):
    means = df.groupby("device")[metric].mean().reindex(devices).fillna(0)
    ranked_devices = means.sort_values(ascending=False).index.tolist()
    top_count = max(
        MIN_TOP_DEVICES,
        min(MAX_TOP_DEVICES, int(len(devices) * TOP_DEVICE_FRACTION)),
    )
    top_devices = set(ranked_devices[:top_count])

    styles = {}
    for rank, device in enumerate(ranked_devices):
        color = device_color(devices.index(device))
        if device in top_devices:
            styles[device] = dict(color=color, dash="solid", width=2.0)
        else:
            dash = LOWER_LINE_DASHES[(rank - top_count) % len(LOWER_LINE_DASHES)]
            styles[device] = dict(color=color, dash=dash, width=1.2)
    return styles

PLOTLY_JS = "https://cdn.plot.ly/plotly-2.35.2.min.js"

# sql.js (SQLite compiled to WebAssembly); used in the browser for large file persistence.
SQL_JS_VERSION = "1.12.0"
SQL_JS_DIST = f"https://cdn.jsdelivr.net/npm/sql.js@{SQL_JS_VERSION}/dist/"

PLOTLY_CONFIG = {
    "responsive": True,
    "displayModeBar": True,
}

PAGE_STYLE = """
    *, *::before, *::after {
      box-sizing: border-box;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      padding: 24px;
      background: #f7f7f8;
      color: #1f2933;
    }
    .panel {
      width: 100%;
      margin: 0 auto;
      background: #fff;
      border: 1px solid #d9dde3;
      border-radius: 10px;
      padding: 20px 24px 24px;
      box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
    }
    h1 {
      margin: 0 0 4px;
      font-size: 1.35rem;
    }
    .tagline {
      margin: 0 0 6px;
      color: #829ab1;
      font-size: 0.95rem;
    }
    .page-heading {
      margin: 0 0 8px;
      font-size: 1.1rem;
      font-weight: 600;
      color: #243b53;
    }
    .subtitle {
      margin: 0 0 18px;
      color: #52606d;
    }
    .nav {
      display: flex;
      gap: 12px;
      margin-bottom: 18px;
    }
    .nav a {
      color: #334e68;
      text-decoration: none;
      padding: 8px 14px;
      border: 1px solid #d9dde3;
      border-radius: 8px;
      background: #fafbfc;
      font-size: 0.95rem;
    }
    .nav a.active {
      background: #334e68;
      border-color: #334e68;
      color: #fff;
    }
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      margin-bottom: 16px;
    }
    input[type="file"] {
      font-size: 0.95rem;
    }
    #status {
      min-height: 1.25rem;
      margin-bottom: 12px;
      color: #52606d;
    }
    #status.error {
      color: #b42318;
    }
    #chart {
      width: 100%;
      min-height: __CHART_MIN_HEIGHT__px;
      overflow: hidden;
    }
    #chart .plotly-graph-div,
    #chart .js-plotly-plot {
      width: 100% !important;
    }
    .placeholder {
      display: grid;
      place-items: center;
      min-height: 420px;
      border: 1px dashed #cbd2d9;
      border-radius: 8px;
      color: #7b8794;
      background: #fafbfc;
    }
    .local-db-panel {
      margin-top: 8px;
      margin-bottom: 16px;
      padding: 14px 16px;
      border: 1px solid #d9dde3;
      border-radius: 8px;
      background: #fafbfc;
    }
    .local-db-heading {
      margin: 0 0 6px;
      font-size: 1rem;
      font-weight: 600;
      color: #243b53;
    }
    .local-db-hint {
      margin: 0 0 12px;
      font-size: 0.88rem;
      color: #52606d;
    }
    .local-db-row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }
    .local-db-row label {
      font-size: 0.92rem;
      color: #334e68;
    }
    #saved-list {
      flex: 1 1 220px;
      min-width: 200px;
      max-width: 100%;
      padding: 6px 8px;
      font-size: 0.92rem;
      border-radius: 6px;
      border: 1px solid #cbd2d9;
    }
    .local-db-row button {
      padding: 6px 12px;
      font-size: 0.9rem;
      border-radius: 6px;
      border: 1px solid #cbd2d9;
      background: #fff;
      color: #334e68;
      cursor: pointer;
    }
    .local-db-row button:hover {
      background: #f0f4f8;
    }
    .local-db-row button.danger {
      border-color: #e8a4a4;
      color: #b42318;
      background: #fff5f5;
    }
    .local-db-row button.danger:hover {
      background: #fde8e8;
    }
"""

PAGE_SCRIPT = """
    const fileInput = document.getElementById("file-input");
    const statusEl = document.getElementById("status");
    const chartEl = document.getElementById("chart");
    const renderEndpoint = "__RENDER_ENDPOINT__";
    const sqlJsDist = "__SQL_JS_DIST__";
    /** Clear legacy sessionStorage keys from older IOScope versions. */
    const legacyContentKey = "ioscope-file-content";
    const legacyNameKey = "ioscope-file-name";

    const idbName = "ioscope-sql-wasm";
    const idbStore = "snapshots";
    const idbKey = "file-db";

    const plotConfig = { responsive: true, displayModeBar: true };
    let resizeTimer = null;
    let sqlDb = null;
    let sqlDbOpenPromise = null;

    function idbOpen() {
      return new Promise((resolve, reject) => {
        const req = indexedDB.open(idbName, 1);
        req.onupgradeneeded = () => {
          const db = req.result;
          if (!db.objectStoreNames.contains(idbStore)) {
            db.createObjectStore(idbStore);
          }
        };
        req.onerror = () => reject(req.error);
        req.onsuccess = () => resolve(req.result);
      });
    }

    async function idbGetSnapshot() {
      const db = await idbOpen();
      return new Promise((resolve, reject) => {
        let result = null;
        const tx = db.transaction(idbStore, "readonly");
        const getReq = tx.objectStore(idbStore).get(idbKey);
        getReq.onsuccess = () => {
          result = getReq.result || null;
        };
        getReq.onerror = () => reject(getReq.error);
        tx.oncomplete = () => {
          db.close();
          resolve(result);
        };
        tx.onerror = () => reject(tx.error);
      });
    }

    async function idbPutSnapshot(data) {
      const db = await idbOpen();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(idbStore, "readwrite");
        tx.objectStore(idbStore).put(data, idbKey);
        tx.oncomplete = () => {
          db.close();
          resolve();
        };
        tx.onerror = () => reject(tx.error);
      });
    }

    async function migrateSchemaIfNeeded(db) {
      db.run(`CREATE TABLE IF NOT EXISTS saved_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_name TEXT NOT NULL,
        file_content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        host_name TEXT NOT NULL DEFAULT ''
      );`);
      const legacy = db.exec(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='current_file'",
      );
      let migrated = false;
      if (legacy.length > 0 && legacy[0].values.length > 0) {
        const rows = db.exec("SELECT file_name, file_content FROM current_file WHERE id = 1");
        if (rows.length > 0 && rows[0].values.length > 0) {
          const fn = rows[0].values[0][0];
          const fc = rows[0].values[0][1];
          db.run(
            "INSERT INTO saved_files (file_name, file_content, created_at, host_name) VALUES (?, ?, datetime('now'), '')",
            [fn, fc],
          );
        }
        db.run("DROP TABLE IF EXISTS current_file");
        migrated = true;
      }
      let needsPersist = migrated;
      const info = db.exec("PRAGMA table_info(saved_files)");
      if (info.length > 0 && info[0].values) {
        const colNames = info[0].values.map((row) => row[1]);
        if (!colNames.includes("host_name")) {
          db.run("ALTER TABLE saved_files ADD COLUMN host_name TEXT NOT NULL DEFAULT ''");
          needsPersist = true;
        }
      }
      if (needsPersist) {
        await idbPutSnapshot(db.export());
      }
    }

    async function ensureSqlDatabase() {
      if (sqlDb) {
        return sqlDb;
      }
      if (!sqlDbOpenPromise) {
        sqlDbOpenPromise = (async () => {
          try {
            const SQL = await initSqlJs({ locateFile: (file) => sqlJsDist + file });
            const bytes = await idbGetSnapshot();
            const db = bytes && bytes.byteLength ? new SQL.Database(bytes) : new SQL.Database();
            await migrateSchemaIfNeeded(db);
            sqlDb = db;
            return db;
          } catch (err) {
            sqlDbOpenPromise = null;
            sqlDb = null;
            throw err;
          }
        })();
      }
      return sqlDbOpenPromise;
    }

    async function persistDbToIdb() {
      const exported = sqlDb.export();
      await idbPutSnapshot(exported);
    }

    async function insertSavedFile(name, text, hostName) {
      await ensureSqlDatabase();
      const host = hostName && String(hostName).trim() ? String(hostName).trim() : "";
      sqlDb.run(
        "INSERT INTO saved_files (file_name, file_content, created_at, host_name) VALUES (?, ?, datetime('now'), ?)",
        [name, text, host],
      );
      await persistDbToIdb();
    }

    async function deleteSavedFile(id) {
      await ensureSqlDatabase();
      sqlDb.run("DELETE FROM saved_files WHERE id = ?", [id]);
      await persistDbToIdb();
    }

    async function getSavedFileById(id) {
      await ensureSqlDatabase();
      const stmt = sqlDb.prepare(
        "SELECT file_name AS n, file_content AS t FROM saved_files WHERE id = ?",
      );
      stmt.bind([id]);
      if (!stmt.step()) {
        stmt.free();
        return null;
      }
      const row = stmt.getAsObject();
      stmt.free();
      if (!row.t) {
        return null;
      }
      return { name: row.n, text: row.t };
    }

    async function refreshSavedList() {
      const sel = document.getElementById("saved-list");
      if (!sel) {
        return;
      }
      await ensureSqlDatabase();
      sel.innerHTML = '<option value="">— Select a saved log —</option>';
      const stmt = sqlDb.prepare(
        "SELECT id, file_name, host_name, created_at, length(file_content) AS nbytes FROM saved_files ORDER BY id DESC",
      );
      while (stmt.step()) {
        const r = stmt.getAsObject();
        const mib = (r.nbytes / (1024 * 1024)).toFixed(2);
        const hostPart =
          r.host_name && String(r.host_name).trim()
            ? String(r.host_name).trim() + " · "
            : "";
        const opt = document.createElement("option");
        opt.value = String(r.id);
        opt.textContent = hostPart + r.file_name + " · " + r.created_at + " · " + mib + " MiB";
        sel.appendChild(opt);
      }
      stmt.free();
    }

    function resizeChart() {
      const chart = document.getElementById("chart");
      if (chart && chart.data) {
        Plotly.Plots.resize(chart);
      }
    }

    function setStatus(message, isError = false) {
      statusEl.textContent = message;
      statusEl.classList.toggle("error", isError);
    }

    function showPlaceholder(message = "Select a SAR disk log file to begin.") {
      chartEl.innerHTML = `<div class="placeholder">${message}</div>`;
    }

    async function renderChart(fileText, fileName) {
      setStatus(`Loading ${fileName}...`);

      const response = await fetch(renderEndpoint, {
        method: "POST",
        headers: {"Content-Type": "text/plain; charset=utf-8"},
        body: fileText,
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Failed to render chart.");
      }

      chartEl.innerHTML = "";
      await Plotly.newPlot("chart", payload.data, payload.layout, plotConfig);
      resizeChart();
      const machineName =
        typeof payload.machine_name === "string" ? payload.machine_name.trim() : "";
      setStatus(
        machineName
          ? `Showing ${fileName} (${machineName})`
          : `Showing ${fileName}`,
      );
      return machineName;
    }

    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(resizeChart, 150);
    });

    fileInput.addEventListener("change", async () => {
      const file = fileInput.files[0];
      if (!file) {
        setStatus("No file selected.");
        showPlaceholder();
        return;
      }

      try {
        const fileText = await file.text();
        const machineName = await renderChart(fileText, file.name);
        try {
          await insertSavedFile(file.name, fileText, machineName);
          await refreshSavedList();
          const sel = document.getElementById("saved-list");
          if (sel && sel.options.length > 1) {
            sel.selectedIndex = 1;
          }
        } catch (persistErr) {
          setStatus(
            `Showing ${file.name} (could not save offline copy: ${persistErr.message})`,
            false,
          );
        }
      } catch (error) {
        showPlaceholder();
        setStatus(error.message, true);
      }
    });

    document.getElementById("load-saved-btn").addEventListener("click", async () => {
      const sel = document.getElementById("saved-list");
      const id = sel && sel.value ? Number(sel.value) : NaN;
      if (!id) {
        setStatus("Choose a saved log from the list first.", true);
        return;
      }
      try {
        const snap = await getSavedFileById(id);
        if (!snap) {
          setStatus("That saved log is missing; try Refresh list.", true);
          await refreshSavedList();
          return;
        }
        await renderChart(snap.text, snap.name);
      } catch (error) {
        showPlaceholder();
        setStatus(error.message, true);
      }
    });

    document.getElementById("discard-saved-btn").addEventListener("click", async () => {
      const sel = document.getElementById("saved-list");
      const id = sel && sel.value ? Number(sel.value) : NaN;
      if (!id) {
        setStatus("Choose a saved log to discard.", true);
        return;
      }
      if (!confirm("Remove this saved log from the browser database?")) {
        return;
      }
      try {
        await deleteSavedFile(id);
        await refreshSavedList();
        sel.value = "";
        setStatus("Saved log removed.");
        showPlaceholder("Select a SAR disk log file or load a saved log.");
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    document.getElementById("refresh-saved-btn").addEventListener("click", async () => {
      try {
        await refreshSavedList();
        setStatus("Saved logs list updated.");
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    window.addEventListener("DOMContentLoaded", async () => {
      try {
        sessionStorage.removeItem(legacyContentKey);
        sessionStorage.removeItem(legacyNameKey);
        await refreshSavedList();
        const sel = document.getElementById("saved-list");
        if (sel && sel.options.length > 1) {
          sel.selectedIndex = 1;
          const snap = await getSavedFileById(Number(sel.value));
          if (snap) {
            await renderChart(snap.text, snap.name);
          }
        }
      } catch (error) {
        showPlaceholder();
        setStatus(error.message, true);
      }
    });
"""


def page_html(title, page_heading, subtitle, active_nav, render_endpoint, chart_min_height):
    nav_lines = ""
    for href, label, key in [
        ("/", "Metrics over time", "lines"),
        ("/heatmap", "Heatmap", "heatmap"),
    ]:
        css_class = "active" if key == active_nav else ""
        nav_lines += f'      <a href="{href}" class="{css_class}">{label}</a>\n'

    style = PAGE_STYLE.replace("__CHART_MIN_HEIGHT__", str(chart_min_height))
    script = (
        PAGE_SCRIPT
        .replace("__RENDER_ENDPOINT__", render_endpoint)
        .replace("__SQL_JS_DIST__", SQL_JS_DIST)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <script src="{PLOTLY_JS}"></script>
  <script src="{SQL_JS_DIST}sql-wasm.js"></script>
  <style>{style}
  </style>
</head>
<body>
  <div class="panel">
    <h1>{APP_NAME}</h1>
    <p class="tagline">{APP_TAGLINE}</p>
    <p class="page-heading">{page_heading}</p>
    <p class="subtitle">{subtitle}</p>
    <nav class="nav">
{nav_lines}    </nav>
    <div class="controls">
      <input id="file-input" type="file" accept=".txt,text/plain">
    </div>
    <div class="local-db-panel">
      <h2 class="local-db-heading">Saved logs (browser database)</h2>
      <p class="local-db-hint">Each successful upload is stored locally. Pick one to reload it, or discard it to free space.</p>
      <div class="local-db-row">
        <label for="saved-list">Saved</label>
        <select id="saved-list" aria-label="Saved SAR disk logs">
          <option value="">— Select a saved log —</option>
        </select>
        <button type="button" id="load-saved-btn">Load</button>
        <button type="button" id="discard-saved-btn" class="danger">Discard</button>
        <button type="button" id="refresh-saved-btn">Refresh list</button>
      </div>
    </div>
    <div id="status">No file selected.</div>
    <div id="chart">
      <div class="placeholder">Select a SAR disk log file to begin.</div>
    </div>
  </div>
  <script>{script}
  </script>
</body>
</html>
"""

LINES_PAGE_HTML = page_html(
    title=f"{APP_NAME} — Metrics Over Time",
    page_heading="Metrics Over Time by Device",
    subtitle="Upload a SAR disk log file to explore per-device metric trends.",
    active_nav="lines",
    render_endpoint="/api/render/lines",
    chart_min_height=900,
)

HEATMAP_PAGE_HTML = page_html(
    title=f"{APP_NAME} — Heatmap",
    page_heading="Device Heatmap",
    subtitle="Upload a SAR disk log file to explore device activity over time.",
    active_nav="heatmap",
    render_endpoint="/api/render/heatmap",
    chart_min_height=1100,
)


HEADER_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b")
DEVICE_ROW_RE = re.compile(
    r"^(\d{1,2}:\d{2}:\d{2}(?:\s+(?:AM|PM))?)\s+(\S+)\s+(.+)$",
    re.IGNORECASE,
)
COLUMN_HEADER_RE = re.compile(r"\b(DEV|Device:?)\b", re.IGNORECASE)

# Map header tokens from SAR disk reports to internal metric columns.
METRIC_ALIASES = {
    "tps": "tps",
    "rd_sec/s": "rd_sec_s",
    "wr_sec/s": "wr_sec_s",
    "rkB/s": "rd_sec_s",
    "wkB/s": "wr_sec_s",
    "dkB/s": None,
    "avrq-sz": "avrq_sz",
    "areq-sz": "avrq_sz",
    "avgqu-sz": "avgqu_sz",
    "aqu-sz": "avgqu_sz",
    "await": "await",
    "svctm": "svctm",
    "pctutil": "pct_util",
    "%util": "pct_util",
}

# Backward time jump larger than this (seconds) starts the next calendar day.
MIDNIGHT_ROLLOVER_SECONDS = 3600

# Fallback column order when no header row is present (value count after device).
POSITIONAL_LAYOUTS = {
    8: ["tps", "rd_sec_s", "wr_sec_s", "avrq_sz", "avgqu_sz", "await", "svctm", "pct_util"],
    9: ["tps", "rd_sec_s", "wr_sec_s", None, "avrq_sz", "avgqu_sz", "await", "pct_util"],
}


def _normalize_metric_name(name):
    key = name.strip()
    return METRIC_ALIASES.get(key, METRIC_ALIASES.get(key.lower()))


def _parse_file_date(header_text):
    match = HEADER_DATE_RE.search(header_text)
    if not match:
        raise ValueError("Could not find date in file header")

    date_str = match.group(1)
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return pd.to_datetime(date_str, format=fmt).date()
        except (ValueError, pd.errors.ParserError):
            continue
    raise ValueError(f"Could not parse date: {date_str}")


def _parse_machine_name(lines):
    for line in lines[:5]:
        match = re.search(r"\(([^)]+)\)", line)
        if match:
            return match.group(1)
    raise ValueError("Could not find machine name in file header")


def _is_column_header_line(line):
    return bool(COLUMN_HEADER_RE.search(line)) and re.search(r"\btps\b", line, re.I)


def _parse_column_header(line):
    if not _is_column_header_line(line):
        return None

    parts = line.split()
    dev_index = None
    for index, part in enumerate(parts):
        if re.fullmatch(r"dev|device:?", part, re.I):
            dev_index = index
            break
    if dev_index is None:
        return None

    layout = [_normalize_metric_name(name) for name in parts[dev_index + 1:]]
    return layout if layout else None


def _layout_for_values(values, column_layout):
    if column_layout is not None and len(values) == len(column_layout):
        return column_layout
    return POSITIONAL_LAYOUTS.get(len(values))


def _parse_device_row(line, column_layout):
    match = DEVICE_ROW_RE.match(line)
    if not match:
        return None

    time_str = re.sub(r"\s+", " ", match.group(1).strip().upper())
    device = match.group(2)
    try:
        values = [float(value) for value in match.group(3).split()]
    except ValueError:
        return None

    layout = _layout_for_values(values, column_layout)
    if layout is None:
        return None

    metrics = {col: float("nan") for col in METRIC_COLS}
    for value, col in zip(values, layout):
        if col:
            metrics[col] = value

    return {"time": time_str, "device": device, **metrics}


def _time_of_day_seconds(time_str):
    clock = pd.to_datetime(time_str.strip(), format="mixed").time()
    return clock.hour * 3600 + clock.minute * 60 + clock.second


def _try_parse_file_date(line):
    try:
        return _parse_file_date(line)
    except ValueError:
        return None


def _advance_date_on_rollover(current_date, time_str, last_time_str, last_seconds):
    seconds = _time_of_day_seconds(time_str)
    if time_str != last_time_str and last_seconds is not None:
        if seconds + MIDNIGHT_ROLLOVER_SECONDS < last_seconds:
            current_date = current_date + timedelta(days=1)
    if time_str != last_time_str:
        last_seconds = seconds
        last_time_str = time_str
    return current_date, last_time_str, last_seconds


def load_sar_disk_text(text):
    lines = [line.rstrip("\n") for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("File is empty")

    file_date = _parse_file_date(lines[0])
    machine_name = _parse_machine_name(lines)

    column_layout = None
    for line in lines[1:]:
        layout = _parse_column_header(line.strip())
        if layout:
            column_layout = layout
            break

    current_date = file_date
    last_time_str = None
    last_seconds = None
    rows = []

    for line in lines[1:]:
        stripped = line.strip()

        if stripped.startswith("Linux "):
            header_date = _try_parse_file_date(stripped)
            if header_date is not None:
                current_date = header_date
                last_time_str = None
                last_seconds = None
            continue

        if (
            stripped.startswith("avg-cpu")
            or _is_column_header_line(stripped)
        ):
            continue
        if stripped.startswith("Device") and not _is_column_header_line(stripped):
            continue

        parsed = _parse_device_row(stripped, column_layout)
        if not parsed:
            continue

        time_str = parsed["time"]
        current_date, last_time_str, last_seconds = _advance_date_on_rollover(
            current_date, time_str, last_time_str, last_seconds,
        )
        parsed["date"] = current_date
        rows.append(parsed)

    if not rows:
        raise ValueError("No SAR disk device rows found in file")

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(
        df["date"].astype(str) + " " + df["time"],
        format="mixed",
    )
    df = df.drop(columns=["time", "date"])

    for col in METRIC_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df, machine_name


def load_sar_disk_file(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return load_sar_disk_text(f.read())


def metric_menu_label(metric):
    return METRIC_INFO[metric]["menu"]


def metric_description_annotation(metric):
    return dict(
        text=METRIC_INFO[metric]["description"],
        xref="paper",
        yref="paper",
        x=0.5,
        y=1.05,
        showarrow=False,
        font=dict(size=11, color="#52606d"),
        xanchor="center",
        yanchor="bottom",
    )


def _metric_buttons(total_traces, traces_per_metric, title_for_metric, layout_updates):
    buttons = []
    for i, metric in enumerate(METRIC_COLS):
        visible = [False] * total_traces
        start = i * traces_per_metric
        for j in range(traces_per_metric):
            visible[start + j] = True

        layout_patch = {
            "title.text": title_for_metric(metric),
            "annotations": [metric_description_annotation(metric)],
            **layout_updates(metric),
        }
        buttons.append(
            dict(
                label=metric_menu_label(metric),
                method="update",
                args=[{"visible": visible}, layout_patch],
            )
        )
    return buttons


def sorted_devices(df):
    return sorted(df["device"].unique())


def build_heatmap_pivot(df, metric, devices):
    return (
        df.pivot_table(
            index="device",
            columns="timestamp",
            values=metric,
            aggfunc="mean",
        )
        .reindex(devices)
        .fillna(0)
        .sort_index()
    )


def heatmap_layout_size(devices):
    device_count = len(devices)
    max_label_len = max((len(device) for device in devices), default=6)
    height = max(720, 180 + device_count * 22)
    left_margin = max(120, min(320, 16 + max_label_len * 7))
    return height, left_margin


def apply_line_chart_xaxis(fig):
    fig.update_xaxes(
        title="Timestamp",
        tickformat="%b %d %H:%M",
        tickangle=-45,
        automargin=True,
        nticks=12,
    )


def apply_heatmap_xaxis(fig):
    fig.update_xaxes(
        title="Timestamp",
        tickangle=-45,
        automargin=True,
        nticks=12,
    )


def build_line_chart(df, machine_name):
    devices = sorted_devices(df)
    traces_per_metric = len(devices)
    total_traces = len(METRIC_COLS) * traces_per_metric
    initial_metric = METRIC_COLS[0]

    fig = go.Figure()

    for i, metric in enumerate(METRIC_COLS):
        show_metric = i == 0
        device_styles = metric_device_line_styles(df, metric, devices)
        for device in devices:
            device_df = df[df["device"] == device].sort_values("timestamp")
            style = device_styles[device]
            fig.add_trace(
                go.Scatter(
                    x=device_df["timestamp"],
                    y=device_df[metric],
                    mode="lines",
                    name=device,
                    legendgroup=device,
                    visible=show_metric,
                    line=dict(color=style["color"], dash=style["dash"], width=style["width"]),
                    hovertemplate=(
                        "Device: %{fullData.name}<br>"
                        "Time: %{x}<br>"
                        f"{metric}: %{{y:.4f}}<extra></extra>"
                    ),
                )
            )

    device_count = len(devices)
    legend_rows = max(1, (device_count + 11) // 12)
    bottom_margin = 110 + legend_rows * 22
    chart_height = 720 + legend_rows * 18

    fig.update_layout(
        title={"text": f"{machine_name} - {initial_metric} by device and time"},
        autosize=True,
        height=chart_height,
        margin=dict(t=145, r=24, b=bottom_margin, l=80),
        annotations=[metric_description_annotation(initial_metric)],
        yaxis_title=initial_metric,
        legend=dict(
            title="Device",
            orientation="h",
            yanchor="top",
            y=-0.08 - (legend_rows - 1) * 0.035,
            xanchor="center",
            x=0.5,
            traceorder="normal",
            itemsizing="constant",
            itemwidth=30,
            font=dict(size=10),
        ),
        updatemenus=[
            dict(
                buttons=_metric_buttons(
                    total_traces,
                    traces_per_metric,
                    lambda metric: f"{machine_name} - {metric} by device and time",
                    lambda metric: {"yaxis.title.text": metric},
                ),
                direction="down",
                showactive=True,
                x=0,
                xanchor="left",
                y=1.02,
                yanchor="bottom",
            )
        ],
    )
    apply_line_chart_xaxis(fig)

    return fig


def build_heatmap_chart(df, machine_name):
    initial_metric = METRIC_COLS[0]
    devices = sorted_devices(df)
    height, left_margin = heatmap_layout_size(devices)
    device_labels = devices

    fig = go.Figure()

    for i, metric in enumerate(METRIC_COLS):
        pivot = build_heatmap_pivot(df, metric, devices)

        fig.add_trace(
            go.Heatmap(
                z=pivot.values.tolist(),
                x=[ts.strftime("%Y-%m-%d %H:%M:%S") for ts in pivot.columns],
                y=device_labels,
                colorscale="YlOrRd",
                visible=(i == 0),
                colorbar=dict(title=metric),
                name=metric,
                hovertemplate=(
                    "Device: %{y}<br>"
                    "Time: %{x}<br>"
                    f"{metric}: %{{z:.4f}}<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        title={"text": f"{machine_name} - Heatmap of {initial_metric} by device and time"},
        autosize=True,
        height=height,
        margin=dict(t=145, r=24, b=80, l=left_margin),
        annotations=[metric_description_annotation(initial_metric)],
        yaxis=dict(
            title="Device",
            type="category",
            categoryorder="array",
            categoryarray=device_labels,
            tickmode="array",
            tickvals=device_labels,
            ticktext=device_labels,
            automargin=True,
            tickfont=dict(size=10),
        ),
        updatemenus=[
            dict(
                buttons=_metric_buttons(
                    len(METRIC_COLS),
                    1,
                    lambda metric: f"{machine_name} - Heatmap of {metric} by device and time",
                    lambda metric: {},
                ),
                direction="down",
                showactive=True,
                x=0,
                xanchor="left",
                y=1.02,
                yanchor="bottom",
            )
        ],
    )
    apply_heatmap_xaxis(fig)

    return fig


class ViewerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send_html(LINES_PAGE_HTML)
            return
        if path == "/heatmap":
            self._send_html(HEATMAP_PAGE_HTML)
            return

        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8", errors="replace")

        builders = {
            "/api/render/lines": build_line_chart,
            "/api/render/heatmap": build_heatmap_chart,
        }

        builder = builders.get(path)
        if builder is None:
            self.send_error(404)
            return

        try:
            df, machine_name = load_sar_disk_text(body)
            fig = builder(df, machine_name)
            payload = json.loads(fig.to_json())
            payload["config"] = PLOTLY_CONFIG
            payload["machine_name"] = machine_name
            self._send_json(payload)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)

    def _send_html(self, html):
        encoded = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, payload, status=200):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main(host="127.0.0.1", port=8765):
    server = HTTPServer((host, port), ViewerHandler)
    url = f"http://{host}:{port}/"
    print(f"{APP_NAME} — {APP_TAGLINE}")
    print(f"Metrics over time: {url}")
    print(f"Heatmap:          http://{host}:{port}/heatmap")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
        server.server_close()


if __name__ == "__main__":
    main()
