# IOScope

Disk I/O analysis from SAR disk logs. Upload a local SAR disk log file and explore per-device metrics over time and as a heatmap.

## Requirements

- Python 3.10 or newer
- A modern web browser

## Setup

1. Clone this repository and open a terminal in the project directory:

   ```bash
   git clone <your-repo-url>
   cd ioscope
   ```

2. Create a virtual environment:

   ```bash
   python3 -m venv .venv
   ```

3. Activate the virtual environment:

   **macOS / Linux**

   ```bash
   source .venv/bin/activate
   ```

   **Windows**

   ```cmd
   .venv\Scripts\activate
   ```

4. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

## Usage

1. Start IOScope from the project directory:

   ```bash
   python -m ioscope
   ```

   Or run the app module directly:

   ```bash
   python ioscope/app.py
   ```

2. Your browser should open automatically. If it does not, open:

   - Metrics over time: [http://127.0.0.1:8765/](http://127.0.0.1:8765/)
   - Heatmap: [http://127.0.0.1:8765/heatmap](http://127.0.0.1:8765/heatmap)

3. Click **Choose File** and select a SAR disk log text file (`.txt`).

4. Optionally use **Time bucket** to average metrics over **1 minute**, **5 minutes**, **15 minutes**, or **1 hour** (per device). Choose **Original** for raw sample spacing. You can change the bucket after the chart loads; the raw file is still what gets saved under **Saved logs**.

5. Use the **metric dropdown** above the chart to switch between:

   - `tps`
   - `rd_sec_s`
   - `wr_sec_s`
   - `avrq_sz`
   - `avgqu_sz`
   - `await`
   - `svctm`
   - `pct_util`

6. Switch between pages using the navigation links at the top. After a successful upload, the log is stored in the browser (**SQLite via sql.js** + **IndexedDB**). Use **Saved logs** to list every stored copy (hostname, file name, and data time range from first to last sample in the file, then when it was saved), **Load** to open one without re-uploading, or **Discard** to remove it and free space. On reload, the most recent saved log is opened automatically when available.

7. The first time you use IOScope, the app loads **sql.js** (~1 MB WASM) and **Plotly** from a CDN; an internet connection is required unless you host those assets yourself.

8. Stop the server with `Ctrl+C` in the terminal.

## Pages

### Metrics over time

- Line chart showing each device over time
- **Time bucket** control averages all numeric metrics within each interval (per device) for dense samples (for example 1-second data)
- Top devices for the selected metric use **solid** lines
- Lower-value devices use **dotted/dashed** lines
- Device legend is shown at the bottom of the chart for easier export

### Heatmap

- Device-by-time heatmap for the selected metric (same **Time bucket** averaging as the line chart)
- All devices are shown on the y-axis
- Chart height adjusts automatically based on the number of devices

## Input file format

IOScope expects plain-text SAR disk output with:

- A header line containing the machine name in parentheses and a date (`MM/DD/YYYY`)
- Device rows with timestamp, device name, and metric columns

Use **per-device** SAR disk log files (for example, output from `sar -d`).

## Project structure

```text
ioscope/
├── README.md
├── requirements.txt
├── .gitignore
└── ioscope/
    ├── __init__.py
    ├── __main__.py
    └── app.py
```

