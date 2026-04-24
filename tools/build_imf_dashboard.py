import csv
import html
import json
from pathlib import Path

from extract_imf_xls import normalize_imf_export


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "out"


def _last_point(series, max_year=None):
    points = [p for p in series if max_year is None or p["year"] <= max_year]
    return max(points, key=lambda p: p["year"]) if points else None


def _fmt(value):
    if value is None:
        return ""
    return f"{value:,.3f}".rstrip("0").rstrip(".")


def category_for(code, title):
    text = f"{code} {title}".lower()
    if code in {"NGDP_RPCH", "NGDPD", "NGDPDPC", "PPPGDP", "PPPPC", "PPPSH", "PPPEX", "PCPIPCH", "PCPIEPCH", "LP", "LUR"}:
        return "Economic Overview"
    if code.startswith("GG") or code in {"rev", "exp", "prim_exp", "ie", "DEBT1", "FC_dummy", "FR_ind"}:
        return "Government Finance"
    if code in {"BCA", "BCA_NGDPD", "DirectAbroad", "DirectIn", "PrivInexDIGDP", "PrivInexDI"}:
        return "External Sector"
    if "openness" in text or code in {"FM_ka", "ka_in", "ka_out", "ka_new", "HH_LS", "NFC_LS", "PVD_LS"}:
        return "Finance and Openness"
    if "export" in text or "margin" in text or code.startswith("SITC"):
        return "Trade Structure"
    if "gender" in text:
        return "Social Indicators"
    return "Other Indicators"


def build_payload():
    exports = {
        "Australia": DATA_DIR / "imf-dm-export-20260423_aus.xls",
        "Canada": DATA_DIR / "imf-dm-export-20260423_can.xls",
    }
    raw = {country: normalize_imf_export(path, country) for country, path in exports.items()}
    by_country = {
        country: {item["code"]: item for item in obj["indicators"]}
        for country, obj in raw.items()
    }
    common_codes = sorted(set(by_country["Australia"]) & set(by_country["Canada"]))
    indicators = []
    for code in common_codes:
        au = by_country["Australia"][code]
        ca = by_country["Canada"][code]
        latest_hist_year = min(
            au.get("estimate_start_after") or 2024,
            ca.get("estimate_start_after") or 2024,
        )
        latest_au = _last_point(au["series"], latest_hist_year)
        latest_ca = _last_point(ca["series"], latest_hist_year)
        indicators.append(
            {
                "code": code,
                "indicator": au["indicator"],
                "unit": au.get("unit") or ca.get("unit") or "",
                "category": category_for(code, au["indicator"]),
                "estimateStartAfter": {
                    "Australia": au.get("estimate_start_after"),
                    "Canada": ca.get("estimate_start_after"),
                },
                "series": {
                    "Australia": au["series"],
                    "Canada": ca["series"],
                },
                "latestHistorical": {
                    "year": latest_hist_year,
                    "Australia": latest_au["value"] if latest_au else None,
                    "Canada": latest_ca["value"] if latest_ca else None,
                    "difference": (
                        latest_au["value"] - latest_ca["value"]
                        if latest_au and latest_ca
                        else None
                    ),
                },
            }
        )
    indicators.sort(key=lambda x: x["indicator"].lower())
    return {
        "generatedFrom": {country: str(path.relative_to(ROOT)) for country, path in exports.items()},
        "countries": ["Australia", "Canada"],
        "indicators": indicators,
    }


def write_csv(payload):
    OUT_DIR.mkdir(exist_ok=True)
    csv_path = OUT_DIR / "aus_can_common_indicators_table.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "Code",
                "Indicator",
                "Unit",
                "Latest historical year used",
                "Australia",
                "Canada",
                "Australia minus Canada",
                "Australia estimates start after",
                "Canada estimates start after",
            ]
        )
        for item in payload["indicators"]:
            latest = item["latestHistorical"]
            writer.writerow(
                [
                    item["code"],
                    item["indicator"],
                    item["unit"],
                    latest["year"],
                    latest["Australia"],
                    latest["Canada"],
                    latest["difference"],
                    item["estimateStartAfter"]["Australia"],
                    item["estimateStartAfter"]["Canada"],
                ]
            )
    long_csv_path = OUT_DIR / "aus_can_full_time_series_table.csv"
    with long_csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Code", "Indicator", "Unit", "Year", "Australia", "Canada", "Australia minus Canada"])
        for item in payload["indicators"]:
            aus_series = {p["year"]: p["value"] for p in item["series"]["Australia"]}
            can_series = {p["year"]: p["value"] for p in item["series"]["Canada"]}
            for year in sorted(set(aus_series) | set(can_series)):
                aus = aus_series.get(year)
                can = can_series.get(year)
                writer.writerow(
                    [
                        item["code"],
                        item["indicator"],
                        item["unit"],
                        year,
                        aus,
                        can,
                        aus - can if aus is not None and can is not None else "",
                    ]
                )
    return csv_path, long_csv_path


def write_html(payload):
    OUT_DIR.mkdir(exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False)
    html_path = OUT_DIR / "aus_can_imf_time_series_dashboard.html"
    html_path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Australia and Canada IMF Indicator Dashboard</title>
  <style>
    :root {{
      --ink: #17202a;
      --muted: #5f6b75;
      --line: #d9e0e6;
      --panel: #ffffff;
      --page: #f5f7f8;
      --aus: #0f8b8d;
      --can: #c43e36;
      --gold: #b98722;
      --focus: #2156a5;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: var(--page);
      font-family: Arial, Helvetica, sans-serif;
      letter-spacing: 0;
    }}
    header {{
      background: #ffffff;
      border-bottom: 1px solid var(--line);
    }}
    .shell {{
      max-width: 1240px;
      margin: 0 auto;
      padding: 22px 22px 28px;
    }}
    .eyebrow {{
      color: var(--focus);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .08em;
    }}
    h1 {{
      margin: 8px 0 8px;
      font-size: clamp(30px, 4vw, 54px);
      line-height: 1.02;
      letter-spacing: 0;
    }}
    .lede {{
      max-width: 820px;
      margin: 0;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.45;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: 22px;
    }}
    .stat {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-height: 92px;
    }}
    .stat span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      font-weight: 700;
    }}
    .stat strong {{
      display: block;
      margin-top: 8px;
      font-size: 24px;
    }}
    main.shell {{
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      gap: 18px;
      padding-top: 18px;
    }}
    aside, section.panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    aside {{
      max-height: calc(100vh - 34px);
      position: sticky;
      top: 16px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }}
    .toolbar {{
      display: grid;
      gap: 10px;
      padding: 14px;
      border-bottom: 1px solid var(--line);
    }}
    input, select, button {{
      font: inherit;
    }}
    .search, select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      background: #fff;
      color: var(--ink);
    }}
    .segmented {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 4px;
      background: #eef2f4;
      padding: 4px;
      border-radius: 7px;
    }}
    .segmented button {{
      border: 0;
      border-radius: 5px;
      padding: 8px;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      font-size: 13px;
    }}
    .segmented button.active {{
      background: #fff;
      color: var(--ink);
      box-shadow: 0 1px 2px rgba(23, 32, 42, .08);
    }}
    .indicator-list {{
      overflow: auto;
      padding: 8px;
    }}
    .indicator-button {{
      width: 100%;
      text-align: left;
      border: 0;
      border-radius: 6px;
      background: transparent;
      padding: 10px;
      cursor: pointer;
      color: var(--ink);
    }}
    .indicator-button strong {{
      display: block;
      font-size: 13px;
      line-height: 1.25;
    }}
    .indicator-button span {{
      display: block;
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
    }}
    .indicator-button.active {{
      background: #e8f4f4;
      outline: 1px solid rgba(15,139,141,.22);
    }}
    .content {{
      display: grid;
      gap: 18px;
      min-width: 0;
    }}
    .panel {{
      padding: 18px;
    }}
    .chart-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: start;
      margin-bottom: 12px;
    }}
    .chart-title h2 {{
      margin: 0;
      font-size: 24px;
      line-height: 1.2;
    }}
    .chart-title p {{
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .axis-controls {{
      display: grid;
      grid-template-columns: repeat(4, minmax(90px, 1fr));
      gap: 10px;
      margin: 10px 0 14px;
      padding: 12px;
      background: #f8fafb;
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .axis-controls label {{
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .axis-controls input {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 9px;
      color: var(--ink);
      background: #fff;
      font-size: 13px;
    }}
    .axis-controls button {{
      align-self: end;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      background: #fff;
      color: var(--focus);
      cursor: pointer;
      font-size: 13px;
      font-weight: 700;
    }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      color: var(--muted);
      font-size: 13px;
    }}
    .dot {{
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      margin-right: 6px;
    }}
    .chart-wrap {{
      position: relative;
      min-height: 430px;
    }}
    svg {{
      width: 100%;
      height: 430px;
      display: block;
      overflow: visible;
    }}
    .axis text {{
      fill: var(--muted);
      font-size: 11px;
    }}
    .grid line {{
      stroke: #edf1f4;
    }}
    .axis path, .axis line {{
      stroke: var(--line);
    }}
    .tooltip {{
      position: absolute;
      pointer-events: none;
      transform: translate(-50%, -100%);
      background: #17202a;
      color: white;
      border-radius: 6px;
      padding: 8px 10px;
      font-size: 12px;
      min-width: 170px;
      opacity: 0;
      transition: opacity .12s ease;
      box-shadow: 0 8px 24px rgba(0,0,0,.18);
    }}
    .metric-row {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 12px;
    }}
    .metric {{
      border-top: 3px solid var(--line);
      padding-top: 10px;
    }}
    .metric.aus {{ border-color: var(--aus); }}
    .metric.can {{ border-color: var(--can); }}
    .metric.diff {{ border-color: var(--gold); }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .metric strong {{
      display: block;
      margin-top: 5px;
      font-size: 22px;
    }}
    .table-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }}
    .table-head h2 {{
      margin: 0;
      font-size: 22px;
    }}
    .gallery-intro {{
      margin-bottom: 14px;
    }}
    .gallery-intro h2 {{
      margin: 0;
      font-size: 22px;
    }}
    .gallery-intro p {{
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.4;
    }}
    .category-block {{
      border-top: 1px solid var(--line);
      padding-top: 16px;
      margin-top: 18px;
    }}
    .category-block:first-of-type {{
      margin-top: 0;
    }}
    .category-title {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin: 0 0 12px;
    }}
    .category-title h3 {{
      margin: 0;
      font-size: 18px;
    }}
    .category-title span {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      font-weight: 700;
    }}
    .mini-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .mini-chart {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 12px;
      cursor: pointer;
      text-align: left;
      color: var(--ink);
      min-width: 0;
    }}
    .mini-chart:hover {{
      border-color: rgba(15,139,141,.5);
      box-shadow: 0 8px 22px rgba(23,32,42,.08);
    }}
    .mini-chart strong {{
      display: block;
      font-size: 13px;
      line-height: 1.25;
      min-height: 32px;
    }}
    .mini-chart span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-top: 4px;
    }}
    .mini-legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 8px;
      color: var(--muted);
      font-size: 11px;
    }}
    .mini-legend i {{
      display: inline-block;
      width: 9px;
      height: 9px;
      border-radius: 50%;
      margin-right: 5px;
      vertical-align: -1px;
    }}
    .mini-chart svg {{
      height: 150px;
      margin-top: 8px;
    }}
    .mini-chart text {{
      pointer-events: none;
    }}
    .mini-crosshair {{
      pointer-events: none;
      opacity: 0;
      transition: opacity .1s ease;
    }}
    .mini-chart:hover .mini-crosshair,
    .mini-chart:focus .mini-crosshair,
    .mini-chart:focus-within .mini-crosshair {{
      opacity: 1;
    }}
    .mini-note {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      margin: 8px 0 0;
      min-height: 48px;
    }}
    .mini-tip {{
      margin-top: 8px;
      min-height: 48px;
      border-top: 1px solid var(--line);
      padding-top: 8px;
      color: var(--ink);
      font-size: 12px;
      line-height: 1.35;
    }}
    .mini-tip strong {{
      display: inline;
      min-height: 0;
      font-size: 12px;
    }}
    .table-box {{
      overflow: auto;
      max-height: 620px;
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 960px;
      background: #fff;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      text-align: right;
      vertical-align: top;
      font-size: 13px;
      white-space: nowrap;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #f8fafb;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      z-index: 1;
    }}
    th:first-child, td:first-child, th:nth-child(2), td:nth-child(2), th:nth-child(3), td:nth-child(3) {{
      text-align: left;
      white-space: normal;
    }}
    tbody tr {{
      cursor: pointer;
    }}
    tbody tr:hover {{
      background: #f6fbfb;
    }}
    .source {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 12px;
      line-height: 1.4;
    }}
    @media (max-width: 920px) {{
      .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      main.shell {{ grid-template-columns: 1fr; }}
      aside {{ position: static; max-height: 430px; }}
      .chart-head, .table-head {{ flex-direction: column; align-items: stretch; }}
      .metric-row {{ grid-template-columns: 1fr; }}
      .axis-controls {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .mini-grid {{ grid-template-columns: 1fr; }}
      svg {{ height: 360px; }}
      .chart-wrap {{ min-height: 360px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="shell">
      <div class="eyebrow">IMF DataMapper local export</div>
      <h1>Australia and Canada</h1>
      <p class="lede">Interactive time-series comparison for the indicators shared by the local IMF country profile exports. The table uses the latest historical year common to both countries for each indicator.</p>
      <div class="stats">
        <div class="stat"><span>Countries</span><strong>2</strong></div>
        <div class="stat"><span>Common indicators</span><strong id="statIndicators"></strong></div>
        <div class="stat"><span>Years covered</span><strong id="statYears"></strong></div>
        <div class="stat"><span>Source</span><strong>Local XLS</strong></div>
      </div>
    </div>
  </header>

  <main class="shell">
    <aside>
      <div class="toolbar">
        <input id="search" class="search" type="search" placeholder="Search indicators" />
        <select id="indicatorSelect" aria-label="Indicator"></select>
        <div class="segmented" aria-label="Chart scale">
          <button id="scaleValue" class="active" type="button">Value</button>
          <button id="scaleIndex" type="button">Index</button>
          <button id="scaleDiff" type="button">Spread</button>
        </div>
      </div>
      <div id="indicatorList" class="indicator-list"></div>
    </aside>

    <div class="content">
      <section class="panel">
        <div class="chart-head">
          <div class="chart-title">
            <h2 id="chartTitle"></h2>
            <p id="chartMeta"></p>
          </div>
          <div class="legend">
            <span><i class="dot" style="background:var(--aus)"></i>Australia</span>
            <span><i class="dot" style="background:var(--can)"></i>Canada</span>
            <span><i class="dot" style="background:var(--gold)"></i>Forecast boundary</span>
          </div>
        </div>
        <div class="axis-controls">
          <label>Start year<input id="xMinInput" type="number" step="1" /></label>
          <label>End year<input id="xMaxInput" type="number" step="1" /></label>
          <label>Y min<input id="yMinInput" type="number" step="any" placeholder="Auto" /></label>
          <label>Y max<input id="yMaxInput" type="number" step="any" placeholder="Auto" /></label>
          <button id="axisReset" type="button">Reset Axes</button>
        </div>
        <div class="chart-wrap">
          <svg id="chart" role="img"></svg>
          <div id="tooltip" class="tooltip"></div>
        </div>
        <div class="metric-row">
          <div class="metric aus"><span id="ausMetricLabel"></span><strong id="ausMetric"></strong></div>
          <div class="metric can"><span id="canMetricLabel"></span><strong id="canMetric"></strong></div>
          <div class="metric diff"><span>Australia minus Canada</span><strong id="diffMetric"></strong></div>
        </div>
      </section>

      <section class="panel">
        <div class="gallery-intro">
          <h2>Indicator Groups</h2>
          <p>Each panel plots Australia and Canada together for an identical IMF indicator, grouped in the same profile-style flow: overview, government finance, external sector, finance, trade, and social measures.</p>
        </div>
        <div id="chartGallery"></div>
      </section>

      <section class="panel">
        <div class="table-head">
          <h2>Common Indicator Table</h2>
          <input id="tableSearch" class="search" type="search" placeholder="Filter table" />
        </div>
        <div class="table-box">
          <table>
            <thead>
              <tr>
                <th>Code</th>
                <th>Indicator</th>
                <th>Unit</th>
                <th>Year</th>
                <th>Australia</th>
                <th>Canada</th>
                <th>Spread</th>
                <th>AUS est. after</th>
                <th>CAN est. after</th>
              </tr>
            </thead>
            <tbody id="tableBody"></tbody>
          </table>
        </div>
        <p class="source">Source files: {html.escape(payload["generatedFrom"]["Australia"])} and {html.escape(payload["generatedFrom"]["Canada"])}. Export vintage shown in the workbooks: IMF, 2026.</p>
      </section>
    </div>
  </main>

  <script>
    const DATA = {data};
    const state = {{ selected: 0, scale: "value", search: "", tableSearch: "", axes: {{ xMin: null, xMax: null, yMin: null, yMax: null }} }};
    const $ = (id) => document.getElementById(id);
    const fmt = (v) => v === null || v === undefined || Number.isNaN(v) ? "" : new Intl.NumberFormat("en-US", {{ maximumFractionDigits: Math.abs(v) >= 100 ? 1 : 3 }}).format(v);
    const years = DATA.indicators.flatMap(d => Object.values(d.series).flat().map(p => p.year));
    const dataMinYear = Math.min(...years);
    const dataMaxYear = Math.max(...years);
    $("statIndicators").textContent = DATA.indicators.length;
    $("statYears").textContent = dataMinYear + "-" + dataMaxYear;

    function pointMap(series) {{
      return new Map(series.map(p => [p.year, p.value]));
    }}

    function transformedSeries(item) {{
      const au = item.series.Australia;
      const ca = item.series.Canada;
      if (state.scale === "value") return {{ Australia: au, Canada: ca }};
      if (state.scale === "index") {{
        const baseYear = Math.max(au[0].year, ca[0].year);
        const auBase = pointMap(au).get(baseYear);
        const caBase = pointMap(ca).get(baseYear);
        return {{
          Australia: au.filter(p => p.year >= baseYear).map(p => ({{ year: p.year, value: p.value / auBase * 100 }})),
          Canada: ca.filter(p => p.year >= baseYear).map(p => ({{ year: p.year, value: p.value / caBase * 100 }})),
        }};
      }}
      const am = pointMap(au), cm = pointMap(ca);
      const spread = [...new Set([...am.keys(), ...cm.keys()])].sort((a,b)=>a-b)
        .filter(y => am.has(y) && cm.has(y))
        .map(y => ({{ year: y, value: am.get(y) - cm.get(y) }}));
      return {{ "Australia minus Canada": spread }};
    }}

    function niceStep(range, targetTicks = 6) {{
      if (!Number.isFinite(range) || range <= 0) return 1;
      const rough = range / targetTicks;
      const pow = Math.pow(10, Math.floor(Math.log10(rough)));
      const scaled = rough / pow;
      const nice = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10;
      return nice * pow;
    }}

    function niceTicks(min, max, targetTicks = 6) {{
      const step = niceStep(max - min, targetTicks);
      const start = Math.ceil(min / step) * step;
      const ticks = [];
      for (let v = start; v <= max + step * 0.5; v += step) ticks.push(Number(v.toPrecision(12)));
      if (!ticks.length) ticks.push(min, max);
      return ticks;
    }}

    function yearTicks(minYear, maxYear) {{
      const span = maxYear - minYear;
      const step = span <= 12 ? 2 : span <= 25 ? 5 : span <= 60 ? 10 : 20;
      const start = Math.ceil(minYear / step) * step;
      const ticks = [];
      for (let y = start; y <= maxYear; y += step) ticks.push(y);
      if (!ticks.includes(minYear)) ticks.unshift(minYear);
      if (!ticks.includes(maxYear)) ticks.push(maxYear);
      return ticks;
    }}

    function syncAxisInputs() {{
      $("xMinInput").value = state.axes.xMin ?? dataMinYear;
      $("xMaxInput").value = state.axes.xMax ?? dataMaxYear;
      $("yMinInput").value = state.axes.yMin ?? "";
      $("yMaxInput").value = state.axes.yMax ?? "";
    }}

    function pathFor(points, x, y) {{
      return points.map((p, i) => `${{i ? "L" : "M"}} ${{x(p.year)}} ${{y(p.value)}}`).join(" ");
    }}

    function renderChart() {{
      const item = DATA.indicators[state.selected];
      const svg = $("chart");
      const box = svg.getBoundingClientRect();
      const width = Math.max(620, box.width || 900);
      const height = svg.clientHeight || 430;
      const margin = {{ top: 22, right: 24, bottom: 42, left: 68 }};
      const plotW = width - margin.left - margin.right;
      const plotH = height - margin.top - margin.bottom;
      const sets = transformedSeries(item);
      const allRaw = Object.values(sets).flat();
      const rawMinYear = Math.min(...allRaw.map(p => p.year));
      const rawMaxYear = Math.max(...allRaw.map(p => p.year));
      let minYear = Math.max(rawMinYear, Number(state.axes.xMin ?? rawMinYear));
      let maxYear = Math.min(rawMaxYear, Number(state.axes.xMax ?? rawMaxYear));
      if (minYear >= maxYear) {{ minYear = rawMinYear; maxYear = rawMaxYear; }}
      const filteredSets = Object.fromEntries(Object.entries(sets).map(([name, pts]) => [name, pts.filter(p => p.year >= minYear && p.year <= maxYear)]).filter(([, pts]) => pts.length));
      const all = Object.values(filteredSets).flat();
      let minVal = Math.min(...all.map(p => p.value));
      let maxVal = Math.max(...all.map(p => p.value));
      if (minVal === maxVal) {{ minVal -= 1; maxVal += 1; }}
      const pad = (maxVal - minVal) * 0.08;
      minVal -= pad; maxVal += pad;
      if (state.axes.yMin !== null && Number.isFinite(Number(state.axes.yMin))) minVal = Number(state.axes.yMin);
      if (state.axes.yMax !== null && Number.isFinite(Number(state.axes.yMax))) maxVal = Number(state.axes.yMax);
      if (minVal >= maxVal) {{
        const center = minVal;
        minVal = center - 1;
        maxVal = center + 1;
      }}
      const x = yr => margin.left + (yr - minYear) / (maxYear - minYear) * plotW;
      const y = val => margin.top + (maxVal - val) / (maxVal - minVal) * plotH;
      const yTicks = niceTicks(minVal, maxVal, 6);
      const xTicks = yearTicks(minYear, maxYear);
      const colors = {{ Australia: "var(--aus)", Canada: "var(--can)", "Australia minus Canada": "var(--gold)" }};
      const paths = Object.entries(filteredSets).map(([name, pts]) => `<path d="${{pathFor(pts, x, y)}}" fill="none" stroke="${{colors[name]}}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"></path>`).join("");
      const estYear = Math.min(item.estimateStartAfter.Australia || maxYear, item.estimateStartAfter.Canada || maxYear);
      const estLine = estYear && estYear >= minYear && estYear <= maxYear ? `<line x1="${{x(estYear)}}" x2="${{x(estYear)}}" y1="${{margin.top}}" y2="${{height - margin.bottom}}" stroke="var(--gold)" stroke-width="1.5" stroke-dasharray="5 5"></line>` : "";
      svg.setAttribute("viewBox", `0 0 ${{width}} ${{height}}`);
      svg.innerHTML = `
        <g class="grid">${{yTicks.map(t => `<line x1="${{margin.left}}" x2="${{width-margin.right}}" y1="${{y(t)}}" y2="${{y(t)}}"></line>`).join("")}}</g>
        ${{estLine}}
        ${{paths}}
        <g class="axis">${{yTicks.map(t => `<text x="${{margin.left-10}}" y="${{y(t)+4}}" text-anchor="end">${{fmt(t)}}</text>`).join("")}}</g>
        <g class="axis">${{xTicks.map(t => `<text x="${{x(t)}}" y="${{height-14}}" text-anchor="middle">${{t}}</text>`).join("")}}</g>
        <text x="${{margin.left + plotW / 2}}" y="${{height - 2}}" text-anchor="middle" fill="var(--muted)" font-size="11">Year</text>
        <text x="14" y="${{margin.top + plotH / 2}}" text-anchor="middle" fill="var(--muted)" font-size="11" transform="rotate(-90 14 ${{margin.top + plotH / 2}})">${{state.scale === "index" ? "Index (first common year = 100)" : state.scale === "diff" ? "Australia minus Canada" : item.unit || "Value"}}</text>
        <line x1="${{margin.left}}" x2="${{width-margin.right}}" y1="${{height-margin.bottom}}" y2="${{height-margin.bottom}}" stroke="var(--line)"></line>
      `;
      const overlay = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      overlay.setAttribute("x", margin.left);
      overlay.setAttribute("y", margin.top);
      overlay.setAttribute("width", plotW);
      overlay.setAttribute("height", plotH);
      overlay.setAttribute("fill", "transparent");
      overlay.addEventListener("mousemove", (ev) => {{
        const rect = svg.getBoundingClientRect();
        const mx = ev.clientX - rect.left;
        const yr = Math.round(minYear + (mx - margin.left) / plotW * (maxYear - minYear));
        const lines = Object.entries(filteredSets).map(([name, pts]) => {{
          const p = pts.reduce((best, cur) => Math.abs(cur.year - yr) < Math.abs(best.year - yr) ? cur : best, pts[0]);
          return `<div><strong>${{name}}</strong>: ${{fmt(p.value)}} (${{p.year}})</div>`;
        }}).join("");
        const tip = $("tooltip");
        tip.innerHTML = lines;
        tip.style.left = Math.min(Math.max(mx, 100), rect.width - 100) + "px";
        tip.style.top = Math.max(ev.clientY - rect.top - 12, 60) + "px";
        tip.style.opacity = 1;
      }});
      overlay.addEventListener("mouseleave", () => $("tooltip").style.opacity = 0);
      svg.appendChild(overlay);
    }}

    function miniSvg(item, idx) {{
      const au = item.series.Australia;
      const ca = item.series.Canada;
      const all = au.concat(ca);
      const width = 420, height = 150;
      const margin = {{ top: 12, right: 8, bottom: 22, left: 38 }};
      const plotW = width - margin.left - margin.right;
      const plotH = height - margin.top - margin.bottom;
      const minYear = Math.min(...all.map(p => p.year));
      const maxYear = Math.max(...all.map(p => p.year));
      let minVal = Math.min(...all.map(p => p.value));
      let maxVal = Math.max(...all.map(p => p.value));
      if (minVal === maxVal) {{ minVal -= 1; maxVal += 1; }}
      const pad = (maxVal - minVal) * 0.08;
      minVal -= pad; maxVal += pad;
      const x = yr => margin.left + (yr - minYear) / (maxYear - minYear) * plotW;
      const y = val => margin.top + (maxVal - val) / (maxVal - minVal) * plotH;
      const yearTickVals = [minYear, maxYear];
      const valueTicks = niceTicks(minVal, maxVal, 3).slice(0, 3);
      const line = pts => pts.map((p, i) => `${{i ? "L" : "M"}} ${{x(p.year).toFixed(1)}} ${{y(p.value).toFixed(1)}}`).join(" ");
      const est = Math.min(item.estimateStartAfter.Australia || maxYear, item.estimateStartAfter.Canada || maxYear);
      const estLine = est && est >= minYear && est <= maxYear ? `<line x1="${{x(est).toFixed(1)}}" x2="${{x(est).toFixed(1)}}" y1="${{margin.top}}" y2="${{height - margin.bottom}}" stroke="var(--gold)" stroke-dasharray="4 4"></line>` : "";
      const latest = item.latestHistorical;
      const markerYear = latest.year;
      const auMarker = latest.Australia;
      const caMarker = latest.Canada;
      return `
        <svg viewBox="0 0 ${{width}} ${{height}}" role="img" aria-label="${{item.indicator}}" data-idx="${{idx}}" data-min-year="${{minYear}}" data-max-year="${{maxYear}}" data-left="${{margin.left}}" data-right="${{width - margin.right}}">
          <line x1="${{margin.left}}" x2="${{width - margin.right}}" y1="${{height - margin.bottom}}" y2="${{height - margin.bottom}}" stroke="var(--line)"></line>
          ${{valueTicks.map(t => `<line x1="${{margin.left}}" x2="${{width - margin.right}}" y1="${{y(t).toFixed(1)}}" y2="${{y(t).toFixed(1)}}" stroke="#edf1f4"></line>`).join("")}}
          ${{estLine}}
          <path d="${{line(au)}}" fill="none" stroke="var(--aus)" stroke-width="2.5" stroke-linecap="round"></path>
          <path d="${{line(ca)}}" fill="none" stroke="var(--can)" stroke-width="2.5" stroke-linecap="round"></path>
          <g class="mini-crosshair">
            <line class="mini-xline" x1="${{x(markerYear).toFixed(1)}}" x2="${{x(markerYear).toFixed(1)}}" y1="${{margin.top}}" y2="${{height - margin.bottom}}" stroke="#51606b" stroke-dasharray="3 3"></line>
            <circle class="mini-aus-dot" cx="${{x(markerYear).toFixed(1)}}" cy="${{y(auMarker).toFixed(1)}}" r="4" fill="var(--aus)" stroke="#fff" stroke-width="1.5"></circle>
            <circle class="mini-can-dot" cx="${{x(markerYear).toFixed(1)}}" cy="${{y(caMarker).toFixed(1)}}" r="4" fill="var(--can)" stroke="#fff" stroke-width="1.5"></circle>
          </g>
          ${{yearTickVals.map(t => `<text x="${{x(t).toFixed(1)}}" y="${{height - 5}}" text-anchor="middle" fill="var(--muted)" font-size="10">${{t}}</text>`).join("")}}
          ${{valueTicks.map(t => `<text x="${{margin.left - 5}}" y="${{y(t).toFixed(1)}}" text-anchor="end" dominant-baseline="middle" fill="var(--muted)" font-size="9">${{fmt(t)}}</text>`).join("")}}
        </svg>
      `;
    }}

    function latestAtOrBefore(series, year) {{
      return series.filter(p => p.year <= year).sort((a, b) => b.year - a.year)[0] || null;
    }}

    function changeOverWindow(series, endYear, yearsBack = 5) {{
      const end = latestAtOrBefore(series, endYear);
      const start = latestAtOrBefore(series, endYear - yearsBack);
      if (!end || !start) return null;
      return end.value - start.value;
    }}

    function commentary(item) {{
      const latest = item.latestHistorical;
      const aus = latest.Australia;
      const can = latest.Canada;
      const diff = latest.difference;
      const unit = item.unit || "units";
      if (aus === null || can === null || diff === null) return "Latest common values are not available for both countries.";
      const leader = diff > 0 ? "Australia is above Canada" : diff < 0 ? "Canada is above Australia" : "Australia and Canada are level";
      const absDiff = Math.abs(diff);
      const auMove = changeOverWindow(item.series.Australia, latest.year);
      const caMove = changeOverWindow(item.series.Canada, latest.year);
      let trend = "";
      if (auMove !== null && caMove !== null) {{
        const auWord = auMove > 0 ? "rose" : auMove < 0 ? "fell" : "was flat";
        const caWord = caMove > 0 ? "rose" : caMove < 0 ? "fell" : "was flat";
        trend = ` Over the prior five years, Australia ${{auWord}} by ${{fmt(Math.abs(auMove))}} and Canada ${{caWord}} by ${{fmt(Math.abs(caMove))}}.`;
      }}
      return `${{leader}} by ${{fmt(absDiff)}} ${{unit}} in ${{latest.year}}.${{trend}}`;
    }}

    function renderGallery() {{
      const order = ["Economic Overview", "Government Finance", "External Sector", "Finance and Openness", "Trade Structure", "Social Indicators", "Other Indicators"];
      const groups = new Map();
      DATA.indicators.forEach((item, idx) => {{
        const category = item.category || "Other Indicators";
        if (!groups.has(category)) groups.set(category, []);
        groups.get(category).push({{ item, idx }});
      }});
      $("chartGallery").innerHTML = order.filter(name => groups.has(name)).map(name => {{
        const items = groups.get(name);
        return `
          <div class="category-block" id="${{name.toLowerCase().replaceAll(" ", "-")}}">
            <div class="category-title"><h3>${{name}}</h3><span>${{items.length}} indicators</span></div>
            <div class="mini-grid">
              ${{items.map(({{ item, idx }}) => `
                <button class="mini-chart" type="button" data-idx="${{idx}}">
                  <strong>${{item.indicator}}</strong>
                  <span>${{item.code}} · ${{item.unit || "Value"}}</span>
                  <div class="mini-legend">
                    <span><i style="background:var(--aus)"></i>Australia</span>
                    <span><i style="background:var(--can)"></i>Canada</span>
                    <span><i style="background:var(--gold)"></i>Forecast</span>
                  </div>
                  ${{miniSvg(item, idx)}}
                  <div class="mini-tip" data-tip-idx="${{idx}}"></div>
                  <p class="mini-note">${{commentary(item)}}</p>
                </button>
              `).join("")}}
            </div>
          </div>
        `;
      }}).join("");
      document.querySelectorAll(".mini-chart").forEach(card => card.addEventListener("click", () => {{
        state.selected = Number(card.dataset.idx);
        document.querySelector("main").scrollIntoView({{ behavior: "smooth", block: "start" }});
        renderAll();
      }}));
      document.querySelectorAll(".mini-chart").forEach(card => {{
        const idx = Number(card.dataset.idx);
        const item = DATA.indicators[idx];
        const svg = card.querySelector("svg");
        const tip = card.querySelector(".mini-tip");
        const updateMini = (clientX = null, explicitYear = null) => {{
          const minYear = Number(svg.dataset.minYear);
          const maxYear = Number(svg.dataset.maxYear);
          const left = Number(svg.dataset.left);
          const right = Number(svg.dataset.right);
          let year = explicitYear;
          if (year === null) {{
            const rect = svg.getBoundingClientRect();
            const viewX = (clientX - rect.left) / rect.width * 420;
            year = Math.round(minYear + (Math.min(Math.max(viewX, left), right) - left) / (right - left) * (maxYear - minYear));
          }}
          const au = item.series.Australia.reduce((best, cur) => Math.abs(cur.year - year) < Math.abs(best.year - year) ? cur : best, item.series.Australia[0]);
          const ca = item.series.Canada.reduce((best, cur) => Math.abs(cur.year - year) < Math.abs(best.year - year) ? cur : best, item.series.Canada[0]);
          const chosenYear = Math.abs(au.year - year) <= Math.abs(ca.year - year) ? au.year : ca.year;
          const auPoint = item.series.Australia.find(p => p.year === chosenYear) || au;
          const caPoint = item.series.Canada.find(p => p.year === chosenYear) || ca;
          const x = left + (chosenYear - minYear) / (maxYear - minYear) * (right - left);
          const yScale = (seriesValue) => {{
            const points = item.series.Australia.concat(item.series.Canada);
            let mn = Math.min(...points.map(p => p.value));
            let mx = Math.max(...points.map(p => p.value));
            if (mn === mx) {{ mn -= 1; mx += 1; }}
            const pad = (mx - mn) * 0.08;
            mn -= pad; mx += pad;
            return 12 + (mx - seriesValue) / (mx - mn) * (150 - 12 - 22);
          }};
          svg.querySelector(".mini-xline").setAttribute("x1", x);
          svg.querySelector(".mini-xline").setAttribute("x2", x);
          svg.querySelector(".mini-aus-dot").setAttribute("cx", x);
          svg.querySelector(".mini-aus-dot").setAttribute("cy", yScale(auPoint.value));
          svg.querySelector(".mini-can-dot").setAttribute("cx", x);
          svg.querySelector(".mini-can-dot").setAttribute("cy", yScale(caPoint.value));
          tip.innerHTML = `<strong>${{chosenYear}}</strong><br><span style="color:var(--aus)">Australia</span>: ${{fmt(auPoint.value)}}<br><span style="color:var(--can)">Canada</span>: ${{fmt(caPoint.value)}}<br>Spread: ${{fmt(auPoint.value - caPoint.value)}}`;
        }};
        updateMini(null, item.latestHistorical.year);
        card.addEventListener("mousemove", ev => updateMini(ev.clientX, null));
        card.addEventListener("focus", () => updateMini(null, item.latestHistorical.year));
        card.addEventListener("keydown", ev => {{
          if (ev.key === "Enter" || ev.key === " ") {{
            ev.preventDefault();
            state.selected = idx;
            document.querySelector("main").scrollIntoView({{ behavior: "smooth", block: "start" }});
            renderAll();
          }}
        }});
      }});
    }}

    function renderPicker() {{
      const q = state.search.toLowerCase();
      const filtered = DATA.indicators
        .map((item, idx) => ({{ item, idx }}))
        .filter(x => (x.item.indicator + " " + x.item.code).toLowerCase().includes(q));
      $("indicatorSelect").innerHTML = DATA.indicators.map((item, idx) => `<option value="${{idx}}">${{item.code}} - ${{item.indicator}}</option>`).join("");
      $("indicatorSelect").value = state.selected;
      $("indicatorList").innerHTML = filtered.map(x => `
        <button type="button" class="indicator-button ${{x.idx === state.selected ? "active" : ""}}" data-idx="${{x.idx}}">
          <strong>${{x.item.indicator}}</strong><span>${{x.item.code}} · ${{x.item.unit || "Index"}}</span>
        </button>
      `).join("");
      document.querySelectorAll(".indicator-button").forEach(btn => btn.addEventListener("click", () => {{
        state.selected = Number(btn.dataset.idx);
        renderAll();
      }}));
    }}

    function renderTable() {{
      const q = state.tableSearch.toLowerCase();
      const rows = DATA.indicators.filter(item => (item.indicator + " " + item.code + " " + item.unit).toLowerCase().includes(q));
      $("tableBody").innerHTML = rows.map(item => `
        <tr data-idx="${{DATA.indicators.indexOf(item)}}">
          <td>${{item.code}}</td>
          <td>${{item.indicator}}</td>
          <td>${{item.unit}}</td>
          <td>${{item.latestHistorical.year}}</td>
          <td>${{fmt(item.latestHistorical.Australia)}}</td>
          <td>${{fmt(item.latestHistorical.Canada)}}</td>
          <td>${{fmt(item.latestHistorical.difference)}}</td>
          <td>${{item.estimateStartAfter.Australia || ""}}</td>
          <td>${{item.estimateStartAfter.Canada || ""}}</td>
        </tr>
      `).join("");
      document.querySelectorAll("tbody tr").forEach(row => row.addEventListener("click", () => {{
        state.selected = Number(row.dataset.idx);
        window.scrollTo({{ top: document.querySelector("main").offsetTop, behavior: "smooth" }});
        renderAll();
      }}));
    }}

    function renderSummary() {{
      const item = DATA.indicators[state.selected];
      const latest = item.latestHistorical;
      $("chartTitle").textContent = item.indicator;
      $("chartMeta").textContent = `${{item.code}} · ${{state.scale === "index" ? "Indexed to first common year = 100" : state.scale === "diff" ? "Australia minus Canada" : item.unit || "Value"}}`;
      $("ausMetricLabel").textContent = `Australia, ${{latest.year}}`;
      $("canMetricLabel").textContent = `Canada, ${{latest.year}}`;
      $("ausMetric").textContent = fmt(latest.Australia);
      $("canMetric").textContent = fmt(latest.Canada);
      $("diffMetric").textContent = fmt(latest.difference);
    }}

    function renderAll() {{
      syncAxisInputs();
      renderPicker();
      renderSummary();
      renderChart();
      renderGallery();
      renderTable();
    }}

    $("search").addEventListener("input", e => {{ state.search = e.target.value; renderPicker(); }});
    $("tableSearch").addEventListener("input", e => {{ state.tableSearch = e.target.value; renderTable(); }});
    $("indicatorSelect").addEventListener("change", e => {{ state.selected = Number(e.target.value); renderAll(); }});
    [["xMinInput","xMin"],["xMaxInput","xMax"],["yMinInput","yMin"],["yMaxInput","yMax"]].forEach(([id, key]) => {{
      $(id).addEventListener("change", e => {{
        const value = e.target.value === "" ? null : Number(e.target.value);
        state.axes[key] = Number.isFinite(value) ? value : null;
        renderChart();
      }});
    }});
    $("axisReset").addEventListener("click", () => {{
      state.axes = {{ xMin: null, xMax: null, yMin: null, yMax: null }};
      renderAll();
    }});
    [["scaleValue","value"],["scaleIndex","index"],["scaleDiff","diff"]].forEach(([id, scale]) => {{
      $(id).addEventListener("click", () => {{
        state.scale = scale;
        document.querySelectorAll(".segmented button").forEach(b => b.classList.remove("active"));
        $(id).classList.add("active");
        renderAll();
      }});
    }});
    window.addEventListener("resize", renderChart);
    renderAll();
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )
    return html_path


def main():
    payload = build_payload()
    OUT_DIR.mkdir(exist_ok=True)
    json_path = OUT_DIR / "aus_can_common_indicators.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path, long_csv_path = write_csv(payload)
    html_path = write_html(payload)
    print(f"indicators={len(payload['indicators'])}")
    print(html_path)
    print(csv_path)
    print(long_csv_path)


if __name__ == "__main__":
    main()
