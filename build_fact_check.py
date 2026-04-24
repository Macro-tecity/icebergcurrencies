import html
import json
import math
import pathlib
import statistics
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "out"
CHARTS = OUT / "charts"


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.load(resp)


def ensure_dirs():
    CHARTS.mkdir(parents=True, exist_ok=True)


def parse_world_bank_gdp_growth():
    url = (
        "https://api.worldbank.org/v2/country/CAN;AUS/"
        "indicator/NY.GDP.MKTP.KD.ZG?format=json&per_page=20000&date=1975:2024"
    )
    payload = fetch_json(url)
    series = {"CAN": {}, "AUS": {}}
    for row in payload[1]:
        c = row["countryiso3code"]
        if c in series and row["value"] is not None:
            series[c][int(row["date"])] = float(row["value"])
    return series


def parse_imf_series(indicator):
    url = f"https://www.imf.org/external/datamapper/api/v2/{indicator}/CAN/AUS"
    payload = fetch_json(url)
    raw = payload["values"][indicator]
    out = {}
    for country in ("CAN", "AUS"):
        years = raw[country]
        out[country] = {int(y): float(v) for y, v in years.items()}
    return out


def mean_for_years(series, years):
    vals = [series[y] for y in years if y in series]
    return sum(vals) / len(vals) if vals else float("nan")


def fmt(x, digits=1):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{x:.{digits}f}"


def pick(series, year):
    return series.get(year)


def svg_chart(title, subtitle, years, series_map, y_label, split_year=None, note=None):
    width, height = 1100, 520
    left, right, top, bottom = 90, 30, 55, 80
    plot_w = width - left - right
    plot_h = height - top - bottom

    all_vals = []
    for s in series_map.values():
        for y in years:
            if y in s:
                all_vals.append(s[y])
    lo = min(all_vals)
    hi = max(all_vals)
    pad = (hi - lo) * 0.12 if hi != lo else 1.0
    lo -= pad
    hi += pad

    def x_for_year(y):
        return left + (y - years[0]) * plot_w / (years[-1] - years[0] if years[-1] != years[0] else 1)

    def y_for_val(v):
        return top + (hi - v) * plot_h / (hi - lo if hi != lo else 1)

    def line_points(series, filtered_years):
        pts = []
        for y in filtered_years:
            if y in series:
                pts.append((x_for_year(y), y_for_val(series[y])))
        return pts

    def polyline(pts):
        if not pts:
            return ""
        d = [f"M {pts[0][0]:.2f} {pts[0][1]:.2f}"]
        for x, y in pts[1:]:
            d.append(f"L {x:.2f} {y:.2f}")
        return " ".join(d)

    def fmt_val(v):
        if abs(v) >= 10:
            return f"{v:.0f}"
        return f"{v:.1f}"

    # Grid lines
    y_ticks = 5
    grid = []
    for i in range(y_ticks + 1):
        v = lo + (hi - lo) * i / y_ticks
        y = y_for_val(v)
        grid.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" '
            f'stroke="#e5e7eb" stroke-width="1" />'
        )
        grid.append(
            f'<text x="{left-12}" y="{y+4:.2f}" text-anchor="end" '
            f'font-size="13" fill="#6b7280">{fmt_val(v)}</text>'
        )

    x_labels = []
    year_step = max(5, round((years[-1] - years[0]) / 10))
    start_year = years[0] + (year_step - (years[0] % year_step)) % year_step
    for y in range(start_year, years[-1] + 1, year_step):
        x = x_for_year(y)
        x_labels.append(
            f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{height-bottom}" stroke="#eef2f7" stroke-width="1" />'
        )
        x_labels.append(
            f'<text x="{x:.2f}" y="{height-bottom+24}" text-anchor="middle" '
            f'font-size="13" fill="#6b7280">{y}</text>'
        )

    colors = {
        "Canada": "#2563eb",
        "Australia": "#f97316",
    }
    styles = []
    legend = []
    for name, series in series_map.items():
        color = colors[name]
        actual_years = [y for y in years if y in series and (split_year is None or y <= split_year)]
        future_years = [y for y in years if y in series and split_year is not None and y > split_year]
        if actual_years:
            styles.append(
                f'<path d="{polyline(line_points(series, actual_years))}" fill="none" '
                f'stroke="{color}" stroke-width="3.5" stroke-linejoin="round" stroke-linecap="round" />'
            )
        if future_years:
            styles.append(
                f'<path d="{polyline(line_points(series, future_years))}" fill="none" '
                f'stroke="{color}" stroke-width="3.5" stroke-dasharray="8 6" stroke-linejoin="round" stroke-linecap="round" />'
            )
        # highlight final year
        final_year = max([y for y in years if y in series])
        fx, fy = x_for_year(final_year), y_for_val(series[final_year])
        styles.append(f'<circle cx="{fx:.2f}" cy="{fy:.2f}" r="4.5" fill="{color}" />')
        styles.append(
            f'<text x="{fx+8:.2f}" y="{fy-8:.2f}" font-size="13" fill="{color}">{fmt_val(series[final_year])}</text>'
        )
        legend.append(
            f'<g transform="translate({left + (0 if name == "Canada" else 165)}, {height-36})">'
            f'<line x1="0" y1="0" x2="28" y2="0" stroke="{color}" stroke-width="4" '
            f'{"stroke-dasharray=\"8 6\"" if future_years else ""} />'
            f'<text x="36" y="4" font-size="13" fill="#111827">{html.escape(name)}</text>'
            f'</g>'
        )

    forecast_key = ""
    if split_year is not None:
        forecast_key = (
            f'<g transform="translate({left + 355}, {height-36})">'
            f'<line x1="0" y1="0" x2="28" y2="0" stroke="#6b7280" stroke-width="3" stroke-dasharray="8 6" />'
            f'<text x="36" y="4" font-size="13" fill="#111827">IMF projection</text>'
            f'</g>'
        )

    note_block = ""
    if note:
        note_block = f'<text x="{left}" y="{height-16}" font-size="12" fill="#6b7280">{html.escape(note)}</text>'

    return f"""
<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{html.escape(title)}">
  <rect x="0" y="0" width="{width}" height="{height}" fill="white" rx="10" />
  <text x="{left}" y="24" font-size="22" font-weight="700" fill="#111827">{html.escape(title)}</text>
  <text x="{left}" y="43" font-size="13" fill="#6b7280">{html.escape(subtitle)}</text>
  {''.join(grid)}
  {''.join(x_labels)}
  <line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#9ca3af" stroke-width="1.2" />
  <line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#9ca3af" stroke-width="1.2" />
  {''.join(styles)}
  {''.join(legend)}
  {forecast_key}
  <text x="18" y="{top + plot_h/2:.2f}" transform="rotate(-90 18,{top + plot_h/2:.2f})" font-size="13" fill="#6b7280">{html.escape(y_label)}</text>
  {note_block}
</svg>
"""


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_report():
    ensure_dirs()

    wb_gdp = parse_world_bank_gdp_growth()
    imf = {ind: parse_imf_series(ind) for ind in ["NGDP_RPCH", "LUR", "GGXWDG_NGDP", "GGXCNL_NGDP", "BCA_NGDPD"]}

    # Summary stats
    stats = {
        "can": {
            "gdp_avg_1975_2024": mean_for_years(wb_gdp["CAN"], range(1975, 2025)),
            "gdp_2024": wb_gdp["CAN"][2024],
            "gdp_avg_2015_2024": mean_for_years(imf["NGDP_RPCH"]["CAN"], range(2015, 2025)),
            "unemp_2024": imf["LUR"]["CAN"][2024],
            "debt_2024": imf["GGXWDG_NGDP"]["CAN"][2024],
            "fiscal_2024": imf["GGXCNL_NGDP"]["CAN"][2024],
            "ca_2024": imf["BCA_NGDPD"]["CAN"][2024],
            "fiscal_2025": imf["GGXCNL_NGDP"]["CAN"][2025],
            "debt_2025": imf["GGXWDG_NGDP"]["CAN"][2025],
            "fertility": 1.25,
        },
        "aus": {
            "gdp_avg_1975_2024": mean_for_years(wb_gdp["AUS"], range(1975, 2025)),
            "gdp_2024": wb_gdp["AUS"][2024],
            "gdp_avg_2015_2024": mean_for_years(imf["NGDP_RPCH"]["AUS"], range(2015, 2025)),
            "unemp_2024": imf["LUR"]["AUS"][2024],
            "debt_2024": imf["GGXWDG_NGDP"]["AUS"][2024],
            "fiscal_2024": imf["GGXCNL_NGDP"]["AUS"][2024],
            "ca_2024": imf["BCA_NGDPD"]["AUS"][2024],
            "fiscal_2025": imf["GGXCNL_NGDP"]["AUS"][2025],
            "debt_2025": imf["GGXWDG_NGDP"]["AUS"][2025],
            "fertility": 1.481,
        },
    }

    # Fact-check matrix
    findings = [
        {
            "claim": "Canada had the stronger fiscal position than Australia.",
            "verdict": "Incorrect on gross-debt terms.",
            "correction": "Australia's gross debt was 50.6% of GDP in 2024, versus Canada's 110.0% in IMF data. Canada does have a much lower debt ratio in net-debt terms in Budget 2025, but my earlier wording was too loose.",
            "source": "IMF DataMapper; Budget Canada 2025; Budget Paper No. 1 2025-26",
        },
        {
            "claim": "Australia has the cleaner demographic profile.",
            "verdict": "Supported.",
            "correction": "Australia's 2024 fertility rate was 1.481 births per woman versus Canada's 1.25, which is ultra-low fertility.",
            "source": "ABS Births, Australia 2024; Statistics Canada fertility release",
        },
        {
            "claim": "Canada has stronger water security.",
            "verdict": "Supported.",
            "correction": "Canada's official water indicator says it holds about 20% of the world's freshwater reserves and nearly 7% of annual renewable freshwater.",
            "source": "Canada.ca Water use in Canada",
        },
        {
            "claim": "Australia's water stress is a real structural risk.",
            "verdict": "Supported.",
            "correction": "BoM says south-west rainfall has declined around 16% since 1970 and more than 28% of hydrologic reference stations show significant streamflow declines.",
            "source": "Bureau of Meteorology State of the Climate 2024",
        },
        {
            "claim": "Australia is more exposed to imported liquid fuels.",
            "verdict": "Supported.",
            "correction": "Energy.gov.au says 79% of refined product consumption was met by imports in 2023-24.",
            "source": "energy.gov.au Energy trade",
        },
        {
            "claim": "Canada is a large food exporter.",
            "verdict": "Supported.",
            "correction": "CFIA says Canada was the world's fifth-largest exporter of agriculture and seafood products in 2024, with $100.3 billion of exports.",
            "source": "CFIA 2026-27 Departmental Plan",
        },
    ]

    charts = [
        (
            "GDP growth, 1975-2024",
            "World Bank annual real GDP growth (actual history only).",
            range(1975, 2025),
            {"Canada": wb_gdp["CAN"], "Australia": wb_gdp["AUS"]},
            "Real GDP growth, %",
            None,
            "World Bank series gives the cleanest 50-year comparison window.",
            "gdp_growth.svg",
        ),
        (
            "Unemployment rate, 1980-2031",
            "IMF DataMapper. Solid line is actual data through 2024; dashed segment is IMF projection.",
            range(1980, 2032),
            {"Canada": imf["LUR"]["CAN"], "Australia": imf["LUR"]["AUS"]},
            "Unemployment rate, %",
            2024,
            None,
            "unemployment.svg",
        ),
        (
            "General government gross debt, 1980-2031",
            "IMF DataMapper. This is gross debt, not net debt.",
            range(1980, 2032),
            {"Canada": imf["GGXWDG_NGDP"]["CAN"], "Australia": imf["GGXWDG_NGDP"]["AUS"]},
            "Gross debt, % of GDP",
            2024,
            None,
            "gross_debt.svg",
        ),
        (
            "Current account balance, 1980-2031",
            "IMF DataMapper. Negative numbers are deficits.",
            range(1980, 2032),
            {"Canada": imf["BCA_NGDPD"]["CAN"], "Australia": imf["BCA_NGDPD"]["AUS"]},
            "Current account, % of GDP",
            2024,
            None,
            "current_account.svg",
        ),
    ]

    chart_tags = []
    for title, subtitle, years, series_map, y_label, split_year, note, filename in charts:
        svg = svg_chart(title, subtitle, list(years), series_map, y_label, split_year=split_year, note=note)
        write(CHARTS / filename, svg)
        chart_tags.append((title, filename))

    report = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Canada vs Australia fact-check</title>
  <style>
    :root {{
      --ink: #111827;
      --muted: #6b7280;
      --line: #e5e7eb;
      --panel: #ffffff;
      --bg: #f8fafc;
      --blue: #2563eb;
      --orange: #f97316;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    }}
    .wrap {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 28px 22px 48px;
    }}
    h1, h2, h3 {{ margin: 0 0 10px; line-height: 1.2; }}
    h1 {{ font-size: 32px; }}
    h2 {{ font-size: 22px; margin-top: 34px; }}
    p {{ margin: 10px 0; }}
    .lede {{ color: var(--muted); max-width: 1000px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin: 18px 0 8px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 16px 16px 14px;
      box-shadow: 0 1px 2px rgba(15,23,42,.04);
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      background: white;
      border: 1px solid var(--line);
      border-radius: 10px;
      overflow: hidden;
      margin-top: 12px;
    }}
    th, td {{
      text-align: left;
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      vertical-align: top;
    }}
    th {{ background: #f9fafb; }}
    .small {{ color: var(--muted); font-size: 13px; }}
    .charts img {{
      width: 100%;
      display: block;
      background: white;
      border: 1px solid var(--line);
      border-radius: 10px;
      margin: 10px 0 18px;
    }}
    ul {{
      margin: 8px 0 0 18px;
      padding: 0;
    }}
    li {{ margin: 4px 0; }}
    .tag {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 999px;
      background: #eef2ff;
      color: #3730a3;
      font-size: 12px;
      margin-right: 6px;
    }}
    .sources a {{ color: var(--blue); text-decoration: none; }}
    .sources a:hover {{ text-decoration: underline; }}
    @media (max-width: 900px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<div class="wrap">
  <h1>Canada vs Australia, fact-checked</h1>
  <p class="lede">
    This is a correction and quantification pass on the earlier long-run currency outlook.
    The main fix is simple: Canada is still the stronger resilience story in several strategic areas,
    but Australia is clearly the cleaner fiscal story on gross debt and the cleaner demographic story on fertility.
  </p>

  <div class="grid">
    <div class="card"><span class="tag">Canada</span><strong>Resilience advantages</strong><p>Water, energy endowment, food output, and North American market access are the structural positives.</p></div>
    <div class="card"><span class="tag">Australia</span><strong>Fiscal and demographic advantages</strong><p>Lower gross debt and better fertility make Australia look cleaner on orthodox sovereign metrics.</p></div>
  </div>

  <h2>Fact-check matrix</h2>
  <table>
    <thead>
      <tr><th style="width:22%">Claim</th><th style="width:18%">Verdict</th><th>Correction</th><th style="width:18%">Source</th></tr>
    </thead>
    <tbody>
      {''.join(f'<tr><td>{html.escape(f["claim"])}</td><td>{html.escape(f["verdict"])}</td><td>{html.escape(f["correction"])}</td><td>{html.escape(f["source"])}</td></tr>' for f in findings)}
    </tbody>
  </table>

  <h2>Quantified comparison</h2>
  <table>
    <thead>
      <tr><th>Indicator</th><th>Canada</th><th>Australia</th><th>Read</th></tr>
    </thead>
    <tbody>
      <tr><td>Average real GDP growth, 1975-2024</td><td>{fmt(stats["can"]["gdp_avg_1975_2024"], 2)}%</td><td>{fmt(stats["aus"]["gdp_avg_1975_2024"], 2)}%</td><td>Australia has grown faster over the very long run.</td></tr>
      <tr><td>Real GDP growth, 2024</td><td>{fmt(stats["can"]["gdp_2024"], 2)}%</td><td>{fmt(stats["aus"]["gdp_2024"], 2)}%</td><td>Both slowed sharply, Australia a little more.</td></tr>
      <tr><td>Average real GDP growth, 2015-2024</td><td>{fmt(stats["can"]["gdp_avg_2015_2024"], 2)}%</td><td>{fmt(stats["aus"]["gdp_avg_2015_2024"], 2)}%</td><td>Australia still leads.</td></tr>
      <tr><td>Unemployment, 2024</td><td>{fmt(stats["can"]["unemp_2024"], 1)}%</td><td>{fmt(stats["aus"]["unemp_2024"], 1)}%</td><td>Australia is lower.</td></tr>
      <tr><td>General government gross debt, 2024</td><td>{fmt(stats["can"]["debt_2024"], 1)}%</td><td>{fmt(stats["aus"]["debt_2024"], 1)}%</td><td>Australia is far stronger on gross debt.</td></tr>
      <tr><td>Government fiscal balance, 2024</td><td>{fmt(stats["can"]["fiscal_2024"], 1)}%</td><td>{fmt(stats["aus"]["fiscal_2024"], 1)}%</td><td>Both are in deficit, Canada slightly less negative.</td></tr>
      <tr><td>Current account balance, 2024</td><td>{fmt(stats["can"]["ca_2024"], 1)}%</td><td>{fmt(stats["aus"]["ca_2024"], 1)}%</td><td>Canada is closer to balance.</td></tr>
      <tr><td>Total fertility rate, 2024</td><td>{fmt(stats["can"]["fertility"], 2)}</td><td>{fmt(stats["aus"]["fertility"], 3)}</td><td>Australia has the cleaner demographic base.</td></tr>
    </tbody>
  </table>

  <h2>Charts</h2>
  <div class="charts">
    {''.join(f'<img src="charts/{html.escape(filename)}" alt="{html.escape(title)}" />' for title, filename in chart_tags)}
  </div>

  <h2>Sources</h2>
  <div class="sources">
    <ul>
      <li><a href="https://api.worldbank.org/v2/country/CAN;AUS/indicator/NY.GDP.MKTP.KD.ZG?format=json&per_page=20000&date=1975:2024">World Bank GDP growth API</a></li>
      <li><a href="https://www.imf.org/external/datamapper/api/v2/NGDP_RPCH/CAN/AUS">IMF DataMapper NGDP_RPCH</a></li>
      <li><a href="https://www.imf.org/external/datamapper/api/v2/LUR/CAN/AUS">IMF DataMapper LUR</a></li>
      <li><a href="https://www.imf.org/external/datamapper/api/v2/GGXWDG_NGDP/CAN/AUS">IMF DataMapper GGXWDG_NGDP</a></li>
      <li><a href="https://www.imf.org/external/datamapper/api/v2/GGXCNL_NGDP/CAN/AUS">IMF DataMapper GGXCNL_NGDP</a></li>
      <li><a href="https://www.imf.org/external/datamapper/api/v2/BCA_NGDPD/CAN/AUS">IMF DataMapper BCA_NGDPD</a></li>
      <li><a href="https://www.canada.ca/en/environment-climate-change/services/environmental-indicators/water-use.html">Canada water use indicator</a></li>
      <li><a href="https://www.bom.gov.au/weather-and-climate/past-weather-and-climate/state-of-the-climate-2024/australias-changing-climate">BoM State of the Climate 2024</a></li>
      <li><a href="https://www.energy.gov.au/data/energy-trade">Australia energy trade</a></li>
      <li><a href="https://www.cer-rec.gc.ca/en/data-analysis/energy-markets/market-snapshots/2025/market-snapshot-overview-of-2024-canada-us-energy-trade.html?undefined=undefined&wbdisable=true">CER Canada-U.S. energy trade</a></li>
      <li><a href="https://www.abs.gov.au/statistics/people/population/births-australia/2024">ABS Births, Australia 2024</a></li>
      <li><a href="https://www.statcan.gc.ca/o1/en/plus/9140-canadas-total-fertility-rate-reaches-new-low-2024">Statistics Canada fertility release</a></li>
      <li><a href="https://budget.canada.ca/2025/report-rapport/anx1-en.html">Canada Budget 2025 Annex 1</a></li>
      <li><a href="https://budget.gov.au/content/bp1/download/bp1_bs-1.pdf">Australia Budget Paper No. 1, 2025-26</a></li>
      <li><a href="https://www.agriculture.gov.au/abares/products/insights/snapshot-of-australian-agriculture">Snapshot of Australian Agriculture 2026</a></li>
      <li><a href="https://inspection.canada.ca/en/about-cfia/transparency/corporate-management-reporting/reports-parliament/2026-2027-departmental-plan-0">CFIA 2026-27 Departmental Plan</a></li>
    </ul>
  </div>

  <h2>Conclusion</h2>
  <p>
    After correcting the fiscal claim, my conclusion is more balanced:
    <strong>Australia is stronger on conventional fiscal metrics and demographics;</strong>
    <strong>Canada is stronger on long-run strategic resilience</strong> because of water abundance, energy endowment, food capacity, and tighter North American integration.
  </p>
  <p>
    If the question is which currency is likelier to be steadier through a resource-constrained, geopolitically noisy world,
    I still lean <strong>Canada</strong> by a narrow margin.
    If the question is which sovereign looks cleaner on gross public finance and population replacement, it is <strong>Australia</strong>.
  </p>
  <p class="small">
    Coverage note: the 50-year comparison uses World Bank GDP growth for 1975-2024.
    The fiscal and external charts use IMF DataMapper series, which begin in 1980 for these countries.
  </p>
</div>
</body>
</html>
"""

    write(OUT / "fact_check_canada_australia.html", report)


if __name__ == "__main__":
    build_report()
