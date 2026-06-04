import json
import re
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import pandas as pd
import plotly.graph_objects as go

APP_NAME = "IOScope"
APP_TAGLINE = "Disk I/O analysis from iostat logs"

METRIC_COLS = [
    "tps", "rd_sec_s", "wr_sec_s",
    "avrq_sz", "avgqu_sz", "await",
    "svctm", "pct_util",
]

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

PAGE_STYLE = """
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      padding: 24px;
      background: #f7f7f8;
      color: #1f2933;
    }
    .panel {
      max-width: 2040px;
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
      min-height: __CHART_MIN_HEIGHT__px;
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
"""

PAGE_SCRIPT = """
    const fileInput = document.getElementById("file-input");
    const statusEl = document.getElementById("status");
    const chartEl = document.getElementById("chart");
    const renderEndpoint = "__RENDER_ENDPOINT__";
    const storageKey = "ioscope-file-content";
    const storageNameKey = "ioscope-file-name";

    function setStatus(message, isError = false) {
      statusEl.textContent = message;
      statusEl.classList.toggle("error", isError);
    }

    function showPlaceholder(message = "Select an iostat file to begin.") {
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
      await Plotly.newPlot("chart", payload.data, payload.layout, payload.config || {responsive: true});
      setStatus(`Showing ${fileName}`);
    }

    fileInput.addEventListener("change", async () => {
      const file = fileInput.files[0];
      if (!file) {
        setStatus("No file selected.");
        showPlaceholder();
        return;
      }

      try {
        const fileText = await file.text();
        sessionStorage.setItem(storageKey, fileText);
        sessionStorage.setItem(storageNameKey, file.name);
        await renderChart(fileText, file.name);
      } catch (error) {
        showPlaceholder();
        setStatus(error.message, true);
      }
    });

    window.addEventListener("DOMContentLoaded", async () => {
      const cachedText = sessionStorage.getItem(storageKey);
      const cachedName = sessionStorage.getItem(storageNameKey);
      if (!cachedText || !cachedName) {
        return;
      }

      try {
        await renderChart(cachedText, cachedName);
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
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <script src="{PLOTLY_JS}"></script>
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
    <div id="status">No file selected.</div>
    <div id="chart">
      <div class="placeholder">Select an iostat file to begin.</div>
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
    subtitle="Upload an iostat file to explore per-device metric trends.",
    active_nav="lines",
    render_endpoint="/api/render/lines",
    chart_min_height=900,
)

HEATMAP_PAGE_HTML = page_html(
    title=f"{APP_NAME} — Heatmap",
    page_heading="Device Heatmap",
    subtitle="Upload an iostat file to explore device activity over time.",
    active_nav="heatmap",
    render_endpoint="/api/render/heatmap",
    chart_min_height=1100,
)


def load_iostat_text(text):
    lines = [line.rstrip("\n") for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("File is empty")

    header = lines[0]

    date_match = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", header)
    if not date_match:
        raise ValueError("Could not find date in first line of file")

    machine_match = re.search(r"\(([^)]+)\)", header)
    if not machine_match:
        raise ValueError("Could not find machine name in first line of file")

    machine_name = machine_match.group(1)
    file_date = pd.to_datetime(date_match.group(1), format="%m/%d/%Y").date()

    pattern = re.compile(
        r'^(\d{2}:\d{2}:\d{2}\s+[AP]M)\s+'
        r'(\S+)\s+'
        r'([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+'
        r'([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)$'
    )

    rows = []
    for line in lines[1:]:
        line = line.strip()

        if (
            line.startswith("Linux ")
            or line.startswith("Device")
            or line.startswith("avg-cpu")
        ):
            continue

        m = pattern.match(line)
        if m:
            rows.append(m.groups())

    if not rows:
        raise ValueError("No iostat device rows found in file")

    cols = [
        "time", "device", "tps", "rd_sec/s", "wr_sec/s",
        "avrq-sz", "avgqu-sz", "await", "svctm", "pctutil"
    ]

    df = pd.DataFrame(rows, columns=cols)

    df["timestamp"] = pd.to_datetime(
        str(file_date) + " " + df["time"],
        format="%Y-%m-%d %I:%M:%S %p"
    )

    for c in cols[2:]:
        df[c] = pd.to_numeric(df[c])

    df = df.rename(columns={
        "rd_sec/s": "rd_sec_s",
        "wr_sec/s": "wr_sec_s",
        "avrq-sz": "avrq_sz",
        "avgqu-sz": "avgqu_sz",
        "pctutil": "pct_util",
    })

    return df, machine_name


def load_iostat_file(path):
    with open(path, "r") as f:
        return load_iostat_text(f.read())


def _metric_buttons(total_traces, traces_per_metric, title_for_metric, layout_updates):
    buttons = []
    for i, metric in enumerate(METRIC_COLS):
        visible = [False] * total_traces
        start = i * traces_per_metric
        for j in range(traces_per_metric):
            visible[start + j] = True

        layout_patch = {"title.text": title_for_metric(metric), **layout_updates(metric)}
        buttons.append(
            dict(
                label=metric,
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
    height = max(920, 180 + device_count * 22)
    left_margin = max(120, min(320, 16 + max_label_len * 7))
    return height, left_margin


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
    bottom_margin = 70 + legend_rows * 22

    fig.update_layout(
        title={"text": f"{machine_name} - {initial_metric} by device and time"},
        width=2000,
        height=820 + legend_rows * 18,
        margin=dict(t=120, r=40, b=bottom_margin, l=80),
        xaxis_title="Timestamp",
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
                x=0.5,
                xanchor="center",
                y=1.02,
                yanchor="bottom",
            )
        ],
    )

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
        width=2000,
        height=height,
        margin=dict(t=120, r=120, b=80, l=left_margin),
        xaxis_title="Timestamp",
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
                x=0.5,
                xanchor="center",
                y=1.02,
                yanchor="bottom",
            )
        ],
    )

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
            df, machine_name = load_iostat_text(body)
            fig = builder(df, machine_name)
            payload = json.loads(fig.to_json())
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
