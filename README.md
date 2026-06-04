# IOScope

Disk I/O analysis from iostat logs. Upload a local iostat text file and explore per-device metrics over time and as a heatmap.

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

3. Click **Choose File** and select an iostat text file (`.txt`).

4. Use the **metric dropdown** above the chart to switch between:

   - `tps`
   - `rd_sec_s`
   - `wr_sec_s`
   - `avrq_sz`
   - `avgqu_sz`
   - `await`
   - `svctm`
   - `pct_util`

5. Switch between pages using the navigation links at the top. The selected file is kept in the browser session, so you do not need to re-upload it when moving between views.

6. Stop the server with `Ctrl+C` in the terminal.

## Pages

### Metrics over time

- Line chart showing each device over time
- Top devices for the selected metric use **solid** lines
- Lower-value devices use **dotted/dashed** lines
- Device legend is shown at the bottom of the chart for easier export

### Heatmap

- Device-by-time heatmap for the selected metric
- All devices are shown on the y-axis
- Chart height adjusts automatically based on the number of devices

## Input file format

IOScope expects plain-text iostat output with:

- A header line containing the machine name in parentheses and a date (`MM/DD/YYYY`)
- Device rows with timestamp, device name, and metric columns

Use iostat **by-disk** output files (for example, files generated with `sar -d` or `iostat -x`).

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

## Notes

- IOScope runs a local web server on port `8765` by default.
- Data is processed locally in your browser session; files are not uploaded anywhere else.
- Use the Plotly toolbar on the chart to zoom, pan, or export an image.

## Publishing to GitHub

From the `ioscope` directory:

```bash
git init
git add .
git commit -m "Initial commit: IOScope"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```
