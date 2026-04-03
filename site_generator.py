#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean
from typing import Dict, List, Tuple
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape as xml_escape

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
SITE_DIR = ROOT / "site"
DATA_DIR = ROOT / "data"
CONTENT_DIR = ROOT / "content" / "posts"

DEFAULT_CONFIG = {
    "site_name": "TACO | Trump Always Chickens Out",
    "site_tagline": "A live-data daily tracker of market pressure, financial stress, and TACO-style retreat conditions.",
    "site_url": "https://freeiran.it",
    "author": "Amin Pour Abdollahi",
    "timezone": "Europe/Rome",
    "language": "en",
    "posts_to_show_on_home": 12,
    "lookback_days": 180,
    "chart_days": 90,
}

PALETTE = {
    "bg": "#0b1020",
    "panel": "#121933",
    "muted": "#93a4c3",
    "text": "#f5f7fb",
    "line": "#69a7ff",
    "grid": "#27314e",
    "good": "#3ad29f",
    "warn": "#f5c451",
    "bad": "#ff6a6a",
    "border": "#223154",
}

DESCRIPTION_OPENERS = [
    "Daily pressure check",
    "New daily signal",
    "Fresh macro pressure read",
    "Automated market-pressure update",
    "Today’s retreat-pressure snapshot",
    "Policy pressure tracker",
]

DESCRIPTION_CLOSERS = [
    "Includes charts, a component breakdown, and a narrative summary.",
    "Read the charts, latest moves, and a concise market interpretation.",
    "Explore the score history, daily post, and the four-factor dashboard.",
    "See the chart pack, score regime, and what drove the latest reading.",
]

ANALYSIS_SENTENCES = [
    "The index is designed to approximate how market stress can build pressure for a softer policy posture.",
    "This custom framework combines equities, front-end rates, inflation expectations, and volatility into one daily score.",
    "It is not a forecast of policy decisions; it is a structured way to monitor pressure building across markets.",
    "The daily signal helps separate noise from persistent multi-factor stress.",
]

MIN_CACHE_ROWS = 20
MAX_CACHE_AGE_DAYS = 10

def load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            user = json.load(f)
        merged = DEFAULT_CONFIG.copy()
        merged.update(user)
        return merged
    return DEFAULT_CONFIG

def ensure_dirs() -> None:
    for p in [SITE_DIR, SITE_DIR / "assets", SITE_DIR / "posts", SITE_DIR / "archive", SITE_DIR / "about", DATA_DIR, CONTENT_DIR]:
        p.mkdir(parents=True, exist_ok=True)

def http_get_text(url: str, retries: int = 2, timeout: int = 25) -> str:
    last_exc = None
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/plain,text/csv,application/csv,application/json,text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout) as r:
                payload = r.read()
                try:
                    return payload.decode("utf-8-sig")
                except UnicodeDecodeError:
                    return payload.decode("latin-1")
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to fetch {url}: {last_exc}")

def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())

def parse_us_date(value: str) -> str:
    return datetime.strptime(value.strip(), "%m/%d/%Y").date().isoformat()

def lookback_start_date(config: dict):
    days = max(config.get("lookback_days", 180) + 40, 260)
    return datetime.now(timezone.utc).date() - timedelta(days=days)

def parse_stooq_csv(raw: str) -> List[dict]:
    rows = list(csv.DictReader(raw.splitlines()))
    points = []
    for row in rows:
        date_raw = (row.get("Date") or row.get("date") or "").strip()
        close_raw = (row.get("Close") or row.get("close") or "").strip()
        if not date_raw or not close_raw or close_raw.lower() in {"null", "n/a", "na", "-"}:
            continue
        try:
            points.append({"date": date_raw, "value": float(close_raw.replace(",", ""))})
        except ValueError:
            pass
    return points

def stooq_csv_url(symbol: str, start_date, end_date) -> str:
    d1 = start_date.strftime("%Y%m%d")
    d2 = end_date.strftime("%Y%m%d")
    return f"https://stooq.com/q/d/l/?s={quote(symbol)}&i=d&d1={d1}&d2={d2}"

def yahoo_chart_url(symbol: str, range_value: str = "2y") -> str:
    return (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}"
        f"?interval=1d&range={range_value}&includePrePost=false&events=div%2Csplits"
    )

def parse_yahoo_chart(raw: str) -> List[dict]:
    data = json.loads(raw)
    result = (((data or {}).get("chart") or {}).get("result") or [None])[0]
    if not result:
        return []
    timestamps = result.get("timestamp") or []
    closes = ((((result.get("indicators") or {}).get("quote") or [None])[0] or {}).get("close") or [])
    points = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        try:
            d = datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
            points.append({"date": d, "value": float(close)})
        except Exception:
            continue
    dedup = {}
    for p in points:
        dedup[p["date"]] = p["value"]
    return [{"date": d, "value": dedup[d]} for d in sorted(dedup)]

def fetch_equity_series(config: dict) -> List[dict]:
    start_date = lookback_start_date(config)
    end_date = datetime.now(timezone.utc).date() + timedelta(days=1)
    attempts = [
        ("yahoo", yahoo_chart_url("^GSPC", range_value="2y"), parse_yahoo_chart),
        ("stooq", stooq_csv_url("^spx", start_date, end_date), parse_stooq_csv),
    ]
    errors = []
    for name, url, parser in attempts:
        try:
            pts = [p for p in parser(http_get_text(url)) if datetime.fromisoformat(p["date"]).date() >= start_date]
            if pts:
                return pts
            errors.append(f"{name} returned 0 rows")
        except Exception as exc:
            errors.append(f"{name} failed: {exc}")
    raise RuntimeError("SP500 fetch failed. " + " || ".join(errors))

def cboe_vix_url() -> str:
    return "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"

def parse_cboe_vix_csv(raw: str) -> List[dict]:
    rows = list(csv.DictReader(raw.splitlines()))
    points = []
    for row in rows:
        date_raw = (row.get("DATE") or row.get("Date") or "").strip()
        close_raw = (row.get("CLOSE") or row.get("Close") or "").strip()
        if not date_raw or not close_raw:
            continue
        try:
            points.append({"date": parse_us_date(date_raw), "value": float(close_raw.replace(",", ""))})
        except Exception:
            pass
    return points

def fetch_vix_series(config: dict) -> List[dict]:
    start_date = lookback_start_date(config)
    attempts = [
        ("cboe", cboe_vix_url(), parse_cboe_vix_csv),
        ("yahoo", yahoo_chart_url("^VIX", range_value="2y"), parse_yahoo_chart),
    ]
    errors = []
    for name, url, parser in attempts:
        try:
            pts = [p for p in parser(http_get_text(url)) if datetime.fromisoformat(p["date"]).date() >= start_date]
            if pts:
                return pts
            errors.append(f"{name} returned 0 rows")
        except Exception as exc:
            errors.append(f"{name} failed: {exc}")
    raise RuntimeError("VIX fetch failed. " + " || ".join(errors))

def treasury_year_csv_url(year: int, kind: str) -> str:
    return (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        f"daily-treasury-rates.csv/{year}/all?_format=csv&page=&type={kind}"
    )

def parse_treasury_csv_table(raw: str) -> List[Tuple[str, dict]]:
    rows = []
    reader = csv.DictReader(raw.splitlines())
    if not reader.fieldnames:
        return rows
    field_map = {normalize_header(name): name for name in reader.fieldnames if name}
    date_field = field_map.get("date")
    if not date_field:
        return rows
    for row in reader:
        if not row:
            continue
        try:
            iso_date = parse_us_date(row[date_field])
        except Exception:
            continue
        normalized = {}
        for norm, original in field_map.items():
            normalized[norm] = (row.get(original) or "").strip()
        rows.append((iso_date, normalized))
    return rows

def fetch_treasury_core_series(config: dict) -> Tuple[List[dict], List[dict]]:
    start_date = lookback_start_date(config)
    current_year = datetime.now(timezone.utc).date().year
    years = list(range(start_date.year, current_year + 1))

    nominal_map = {}
    real_map = {}
    nominal_errors = []
    real_errors = []

    for year in years:
        try:
            raw = http_get_text(treasury_year_csv_url(year, "daily_treasury_yield_curve"), retries=2, timeout=20)
            for d, row in parse_treasury_csv_table(raw):
                nominal_map[d] = row
        except Exception as exc:
            nominal_errors.append(f"nominal {year}: {exc}")

        try:
            raw = http_get_text(treasury_year_csv_url(year, "daily_treasury_real_yield_curve"), retries=2, timeout=20)
            for d, row in parse_treasury_csv_table(raw):
                real_map[d] = row
        except Exception as exc:
            real_errors.append(f"real {year}: {exc}")

    if not nominal_map:
        raise RuntimeError("Treasury nominal fetch failed. " + " || ".join(nominal_errors))
    if not real_map:
        raise RuntimeError("Treasury real fetch failed. " + " || ".join(real_errors))

    dgs2_points = []
    t5yie_points = []
    common_dates = sorted(set(nominal_map) & set(real_map))
    for d in common_dates:
        if datetime.fromisoformat(d).date() < start_date:
            continue
        nrow = nominal_map[d]
        rrow = real_map[d]
        y2_raw = nrow.get("2yr", "")
        n5_raw = nrow.get("5yr", "")
        r5_raw = rrow.get("5yr", "")
        if y2_raw and y2_raw.upper() != "N/A":
            try:
                dgs2_points.append({"date": d, "value": float(y2_raw.replace(",", ""))})
            except ValueError:
                pass
        if n5_raw and r5_raw and n5_raw.upper() != "N/A" and r5_raw.upper() != "N/A":
            try:
                breakeven = float(n5_raw.replace(",", "")) - float(r5_raw.replace(",", ""))
                t5yie_points.append({"date": d, "value": breakeven})
            except ValueError:
                pass

    if not dgs2_points:
        raise RuntimeError("Treasury nominal data did not yield any 2Y points.")
    if not t5yie_points:
        raise RuntimeError("Treasury nominal/real data did not yield any 5Y breakeven points.")
    return dgs2_points, t5yie_points

def fetch_series(config: dict):
    dgs2_points, t5yie_points = fetch_treasury_core_series(config)
    return {
        "sp500": fetch_equity_series(config),
        "dgs2": dgs2_points,
        "t5yie": t5yie_points,
        "vix": fetch_vix_series(config),
    }

def align_series(series: Dict[str, List[dict]], lookback_days: int) -> List[dict]:
    maps = {k: {p["date"]: p["value"] for p in pts} for k, pts in series.items()}
    common_dates = sorted(set.intersection(*[set(m.keys()) for m in maps.values()]))
    common_dates = common_dates[-lookback_days:]
    return [{"date": d, **{k: maps[k][d] for k in maps}} for d in common_dates]

def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))

def component_scores(rows: List[dict], idx: int) -> Dict[str, dict]:
    i5 = max(0, idx - 5)
    today = rows[idx]
    prev5 = rows[i5]

    spx_move_pct = (today["sp500"] - prev5["sp500"]) / prev5["sp500"] * 100.0 if prev5["sp500"] else 0.0
    eq_pressure = clamp(max(0.0, -spx_move_pct) / 5.0 * 100.0)
    eq_relief = clamp(max(0.0, spx_move_pct) / 5.0 * 100.0)
    eq_net = round(eq_pressure - 0.5 * eq_relief, 2)

    y2_delta_bps = (today["dgs2"] - prev5["dgs2"]) * 100
    y2_level_score = clamp((today["dgs2"] - 3.0) / (5.25 - 3.0) * 60.0)
    y2_change_score = clamp(max(0.0, y2_delta_bps) / 25.0 * 40.0)
    y2_score = clamp(y2_level_score + y2_change_score)

    inf_delta_bps = (today["t5yie"] - prev5["t5yie"]) * 100
    inf_level_score = clamp((today["t5yie"] - 2.0) / (3.0 - 2.0) * 60.0)
    inf_change_score = clamp(max(0.0, inf_delta_bps) / 20.0 * 40.0)
    inf_score = clamp(inf_level_score + inf_change_score)

    vix_level_score = clamp((today["vix"] - 12.0) / (35.0 - 12.0) * 70.0)
    vix_jump_score = clamp(max(0.0, today["vix"] - prev5["vix"]) / 8.0 * 30.0)
    vix_score = clamp(vix_level_score + vix_jump_score)

    return {
        "equity": {
            "label": "S&P 500 equity signal",
            "raw": f"{spx_move_pct:+.2f}% vs 5 sessions | pressure {eq_pressure:.2f} | relief {eq_relief:.2f}",
            "unit": "signed 5-session move",
            "score": eq_net,
            "pressure_score": round(eq_pressure, 2),
            "relief_score": round(eq_relief, 2),
            "latest_value": today["sp500"],
            "latest_date": today["date"],
            "note": "A 5-session drawdown adds pressure. A 5-session rally adds relief and can partially offset the composite score.",
        },
        "rates": {
            "label": "2Y Treasury rate pressure",
            "raw": f"{today['dgs2']:.2f}% level, {y2_delta_bps:+.2f} bp vs 5 sessions",
            "unit": "60% level + 40% change",
            "score": round(y2_score, 2),
            "latest_value": today["dgs2"],
            "latest_date": today["date"],
            "note": "Rates pressure reflects both the current 2Y level and any fresh 5-session rise.",
        },
        "inflation": {
            "label": "Inflation expectations pressure",
            "raw": f"{today['t5yie']:.2f}% level, {inf_delta_bps:+.2f} bp vs 5 sessions",
            "unit": "60% level + 40% change",
            "score": round(inf_score, 2),
            "latest_value": today["t5yie"],
            "latest_date": today["date"],
            "note": "Inflation pressure reflects both the breakeven level and any fresh 5-session rise.",
        },
        "volatility": {
            "label": "VIX volatility pressure",
            "raw": round(today["vix"], 2),
            "unit": "index level",
            "score": round(vix_score, 2),
            "latest_value": today["vix"],
            "latest_date": today["date"],
            "note": "Higher implied volatility usually means greater market stress.",
        },
    }

def classify_regime(score: float) -> str:
    if score < 25:
        return "LOW"
    if score < 50:
        return "ELEVATED"
    if score < 75:
        return "HIGH"
    return "EXTREME"

def compute_history(rows: List[dict]) -> List[dict]:
    history = []
    for idx in range(len(rows)):
        drivers = component_scores(rows, idx)
        eq_pressure = float(drivers["equity"].get("pressure_score", 0.0))
        eq_relief = float(drivers["equity"].get("relief_score", 0.0))
        score = round(clamp((
            eq_pressure - 0.5 * eq_relief + drivers["rates"]["score"] + drivers["inflation"]["score"] + drivers["volatility"]["score"]
        ) / 4.0), 2)
        history.append({
            "date": rows[idx]["date"],
            "score": score,
            "regime": classify_regime(score),
            "drivers": drivers,
            "inputs": {
                "sp500": rows[idx]["sp500"],
                "dgs2": rows[idx]["dgs2"],
                "t5yie": rows[idx]["t5yie"],
                "vix": rows[idx]["vix"],
            },
        })
    return history

def choose_opening(date: str, pool: List[str]) -> str:
    seed = int(hashlib.sha256(date.encode()).hexdigest(), 16)
    return pool[seed % len(pool)]

def top_drivers(drivers: Dict[str, dict], n: int = 2):
    return sorted(drivers.items(), key=lambda kv: kv[1]["score"], reverse=True)[:n]

def human_driver_name(key: str) -> str:
    return {
        "equity": "equity signal",
        "rates": "front-end rate pressure",
        "inflation": "inflation expectations",
        "volatility": "volatility",
    }[key]

def hero_summary(date: str, score: float, regime: str, drivers: Dict[str, dict]) -> str:
    lead = choose_opening(date + "hero", ANALYSIS_SENTENCES)
    tops = top_drivers(drivers, 2)
    names = " and ".join(human_driver_name(k) for k, _ in tops)
    eq = drivers.get("equity", {})
    relief_clause = ""
    if float(eq.get("relief_score", 0.0)) >= 8 and float(eq.get("score", 0.0)) < 0:
        relief_clause = " Equities also provided visible relief through a positive 5-session move."
    return f"{lead} On {date}, the score printed {score:.2f}/100 in the {regime.lower()} regime, with {names} doing most of the work.{relief_clause}"

def make_description(date: str, score: float, regime: str, drivers: Dict[str, dict]) -> str:
    opener = choose_opening(date, DESCRIPTION_OPENERS)
    closer = choose_opening(date + "closer", DESCRIPTION_CLOSERS)
    tops = top_drivers(drivers, 2)
    drivers_text = " and ".join(human_driver_name(k) for k, _ in tops)
    eq = drivers.get("equity", {})
    relief_text = ""
    if float(eq.get("relief_score", 0.0)) >= 8 and float(eq.get("score", 0.0)) < 0:
        relief_text = " A positive 5-session S&P move also added equity relief."
    return (
        f"{opener} for {date}: the TACO Pressure Index closed at {score:.2f}/100, "
        f"signaling a {regime.lower()} pressure regime as {drivers_text} shaped the daily read.{relief_text} {closer}"
    )

def post_title(date: str, score: float, regime: str) -> str:
    return f"{date} TACO Pressure Index Update: {regime.title()} at {score:.2f}"

def load_cached_history() -> List[dict] | None:
    path = DATA_DIR / "history.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def validate_cache(history: List[dict], config: dict) -> bool:
    if not history or len(history) < MIN_CACHE_ROWS:
        return False
    try:
        latest = datetime.fromisoformat(history[-1]["date"]).date()
        today = datetime.now(ZoneInfo(config.get("timezone", "UTC"))).date()
        return (today - latest).days <= MAX_CACHE_AGE_DAYS
    except Exception:
        return False

def json_dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def format_num(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"

def svg_line_chart(points: List[Tuple[str, float]], title: str, subtitle: str, width: int = 960, height: int = 430) -> str:
    points = sorted(points, key=lambda item: item[0])
    margin = {"l": 70, "r": 25, "t": 60, "b": 55}
    ys = [p[1] for p in points] or [0.0]
    ymin = min(ys)
    ymax = max(ys)
    if math.isclose(ymin, ymax):
        ymax = ymin + 1.0
    chart_w = width - margin["l"] - margin["r"]
    chart_h = height - margin["t"] - margin["b"]

    def sx(i):
        if len(points) == 1:
            return margin["l"] + chart_w / 2
        return margin["l"] + (i / (len(points) - 1)) * chart_w

    def sy(v):
        return margin["t"] + (1 - (v - ymin) / (ymax - ymin)) * chart_h

    path = " ".join(("M" if i == 0 else "L") + f" {sx(i):.2f} {sy(v):.2f}" for i, (_, v) in enumerate(points))
    ticks = 5
    y_grid = [(sy(ymin + (ymax - ymin) * t / ticks), ymin + (ymax - ymin) * t / ticks) for t in range(ticks + 1)]
    label_idx = sorted(set([0, len(points) // 2, len(points) - 1])) if points else [0]
    x_labels = [(sx(i), points[i][0]) for i in label_idx]

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="100%" height="100%" fill="{PALETTE["bg"]}" rx="20"/>',
        f'<text x="{margin["l"]}" y="32" fill="{PALETTE["text"]}" font-size="24" font-family="Inter, Arial, sans-serif" font-weight="700">{xml_escape(title)}</text>',
        f'<text x="{margin["l"]}" y="52" fill="{PALETTE["muted"]}" font-size="13" font-family="Inter, Arial, sans-serif">{xml_escape(subtitle)}</text>',
    ]
    for yy, val in y_grid:
        svg.append(f'<line x1="{margin["l"]}" x2="{width - margin["r"]}" y1="{yy:.2f}" y2="{yy:.2f}" stroke="{PALETTE["grid"]}" stroke-width="1"/>')
        svg.append(f'<text x="{margin["l"] - 12}" y="{yy + 4:.2f}" text-anchor="end" fill="{PALETTE["muted"]}" font-size="12" font-family="Inter, Arial, sans-serif">{val:.0f}</text>')
    for xx, label in x_labels:
        svg.append(f'<text x="{xx:.2f}" y="{height - 18}" text-anchor="middle" fill="{PALETTE["muted"]}" font-size="12" font-family="Inter, Arial, sans-serif">{xml_escape(label)}</text>')
    svg.append(f'<path d="{path}" fill="none" stroke="{PALETTE["line"]}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')
    if points:
        lx, ly = sx(len(points) - 1), sy(points[-1][1])
        svg.append(f'<circle cx="{lx:.2f}" cy="{ly:.2f}" r="6" fill="{PALETTE["line"]}"/>')
    svg.append("</svg>")
    return "\n".join(svg)

def svg_bar_chart(items: List[Tuple[str, float]], title: str, subtitle: str, width: int = 960, height: int = 430) -> str:
    signed = any(val < 0 for _, val in items)
    max_label_len = max((len(label) for label, _ in items), default=18)
    left_margin = min(340, max(220, int(max_label_len * 8.0)))
    margin = {"l": left_margin, "r": 25, "t": 60, "b": 40}
    chart_w = width - margin["l"] - margin["r"]
    chart_h = height - margin["t"] - margin["b"]
    bar_gap = 18
    bar_h = (chart_h - bar_gap * (len(items) - 1)) / max(1, len(items))
    min_axis = -100 if signed else 0
    max_axis = 100
    zero_x = margin["l"] + ((0 - min_axis) / (max_axis - min_axis)) * chart_w

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="100%" height="100%" fill="{PALETTE["bg"]}" rx="20"/>',
        f'<text x="{margin["l"]}" y="32" fill="{PALETTE["text"]}" font-size="24" font-family="Inter, Arial, sans-serif" font-weight="700">{xml_escape(title)}</text>',
        f'<text x="{margin["l"]}" y="52" fill="{PALETTE["muted"]}" font-size="13" font-family="Inter, Arial, sans-serif">{xml_escape(subtitle)}</text>',
    ]
    ticks = [-100, -50, 0, 50, 100] if signed else [0, 20, 40, 60, 80, 100]
    for tick in ticks:
        x = margin["l"] + ((tick - min_axis) / (max_axis - min_axis)) * chart_w
        svg.append(f'<line x1="{x:.2f}" x2="{x:.2f}" y1="{margin["t"]}" y2="{height - margin["b"]}" stroke="{PALETTE["grid"]}" stroke-width="1"/>')
        svg.append(f'<text x="{x:.2f}" y="{height - 12}" text-anchor="middle" fill="{PALETTE["muted"]}" font-size="12" font-family="Inter, Arial, sans-serif">{tick}</text>')
    if signed:
        svg.append(f'<line x1="{zero_x:.2f}" x2="{zero_x:.2f}" y1="{margin["t"]}" y2="{height - margin["b"]}" stroke="{PALETTE["text"]}" stroke-width="1.5" opacity="0.7"/>')
    for idx, (label, val) in enumerate(items):
        y = margin["t"] + idx * (bar_h + bar_gap)
        svg.append(f'<text x="{margin["l"] - 16}" y="{y + bar_h/2 + 5:.2f}" text-anchor="end" fill="{PALETTE["text"]}" font-size="14" font-family="Inter, Arial, sans-serif">{xml_escape(label)}</text>')
        svg.append(f'<rect x="{margin["l"]}" y="{y:.2f}" width="{chart_w:.2f}" height="{bar_h:.2f}" rx="10" fill="{PALETTE["panel"]}" stroke="{PALETTE["border"]}"/>')
        if signed:
            val = max(-100.0, min(100.0, float(val)))
            end_x = margin["l"] + ((val - min_axis) / (max_axis - min_axis)) * chart_w
            x = min(zero_x, end_x)
            w = abs(end_x - zero_x)
            color = PALETTE["bad"] if val > 0 else PALETTE["good"] if val < 0 else PALETTE["muted"]
            svg.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{bar_h:.2f}" rx="10" fill="{color}" opacity="0.95"/>')
            value_x = end_x + 8 if val >= 0 else end_x - 8
            anchor = "start" if val >= 0 else "end"
        else:
            val = max(0.0, min(100.0, float(val)))
            bar_w = chart_w * val / 100.0
            color = PALETTE["good"] if val < 25 else PALETTE["warn"] if val < 60 else PALETTE["bad"]
            svg.append(f'<rect x="{margin["l"]}" y="{y:.2f}" width="{bar_w:.2f}" height="{bar_h:.2f}" rx="10" fill="{color}"/>')
            value_x = min(width - margin["r"] - 6, margin["l"] + bar_w + 8)
            anchor = "start"
        svg.append(f'<text x="{value_x:.2f}" y="{y + bar_h/2 + 5:.2f}" text-anchor="{anchor}" fill="{PALETTE["text"]}" font-size="13" font-family="Inter, Arial, sans-serif" font-weight="600">{val:.2f}</text>')
    svg.append("</svg>")
    return "\n".join(svg)

def root_url(path: str) -> str:
    path = path.lstrip("/")
    return f"/{path}" if path else "/"

def abs_url(config: dict, path: str) -> str:
    return f"{config['site_url'].rstrip('/')}/{path.lstrip('/')}"

def cache_bust_token(obj) -> str:
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.md5(payload).hexdigest()[:10]

def html_page(config: dict, title: str, description: str, body: str, canonical: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{xml_escape(title)}</title>
<meta name="description" content="{xml_escape(description)}">
<link rel="canonical" href="{xml_escape(canonical)}">
<link rel="stylesheet" href="{xml_escape(root_url('assets/style.css'))}">
</head>
<body>
{body}
</body>
</html>"""

def site_nav(config: dict) -> str:
    return f"""
<header class="site-header">
  <div class="wrap nav-row">
    <a class="brand" href="{root_url('')}">{xml_escape(config['site_name'])}</a>
    <nav>
      <a href="{root_url('')}">Home</a>
      <a href="{root_url('archive/')}">Archive</a>
      <a href="{root_url('about/')}">About</a>
      <a href="{root_url('rss.xml')}">RSS</a>
    </nav>
  </div>
</header>
"""

def footer() -> str:
    return """
<footer class="site-footer">
  <div class="wrap footer-inner">
    <span>Automated static publishing</span>
    <span>TACO upgraded equity logic</span>
  </div>
</footer>
"""

def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

def save_post_snapshot(post: dict) -> None:
    json_dump(CONTENT_DIR / f"{post['date']}.json", post)

def make_post_page(config: dict, post: dict, upto: List[dict]) -> str:
    driver_cards = []
    for item in sorted(post["drivers"].values(), key=lambda x: x["score"], reverse=True):
        driver_cards.append(f"""
          <article class="metric-card">
            <h3>{xml_escape(item['label'])}</h3>
            <p class="metric-score">{item['score']:.2f}<span>/100</span></p>
            <p class="metric-meta">{xml_escape(str(item['raw']))} {xml_escape(item['unit'])}</p>
            <p class="metric-meta">Latest: {xml_escape(format_num(item['latest_value']))} on {xml_escape(item['latest_date'])}</p>
            <p>{xml_escape(item['note'])}</p>
          </article>
        """)

    body = f"""
{site_nav(config)}
<main class="wrap post-layout">
  <article class="post-card">
    <h1>{xml_escape(post['title'])}</h1>
    <p class="lede">{xml_escape(post['hero_summary'])}</p>
    <div class="hero-grid">
      <div class="hero-stat"><span>Composite score</span><strong>{post['score']:.2f}</strong></div>
      <div class="hero-stat"><span>Regime</span><strong>{xml_escape(post['regime'])}</strong></div>
      <div class="hero-stat"><span>Published</span><strong>{xml_escape(post['date'])}</strong></div>
    </div>
    <p>{xml_escape(post['description'])}</p>
    <section class="chart-section">
      <h2>Pressure history</h2>
      <img src="./score-history.svg?v={post['score_history_token']}" alt="Composite score history">
    </section>
    <section class="chart-section">
      <h2>Latest component scores</h2>
      <img src="./component-scores.svg?v={post['component_chart_token']}" alt="Latest component scores">
    </section>
    <section>
      <h2>Today’s component breakdown</h2>
      <div class="metrics-grid">
        {''.join(driver_cards)}
      </div>
    </section>
    <section>
      <h2>Method in one paragraph</h2>
      <p>The TACO Pressure Index converts four live market inputs into comparable component scores and combines them into one composite reading. The equity leg is symmetric: 5-session drawdowns add pressure, while 5-session rallies add relief and can partially offset the total score. Rates, inflation, and volatility still combine a level component with a 5-session change component before the final result is grouped into LOW, ELEVATED, HIGH, and EXTREME regimes.</p>
    </section>
  </article>
</main>
{footer()}
"""
    return html_page(config, post["title"], post["description"], body, abs_url(config, f"posts/{post['date']}/"))

def make_index_page(config: dict, posts: List[dict]) -> str:
    latest = posts[0]
    items = []
    for post in posts[:config["posts_to_show_on_home"]]:
        items.append(f"""
        <article class="post-list-item">
          <p class="post-list-date">{xml_escape(post['date'])}</p>
          <h3><a href="{root_url(f'posts/{post["date"]}/')}">{xml_escape(post['title'])}</a></h3>
          <p>{xml_escape(post['description'])}</p>
        </article>
        """)
    body = f"""
{site_nav(config)}
<main class="wrap home-layout">
  <section class="hero-home">
    <h1>{xml_escape(config['site_name'])}</h1>
    <p class="lede">{xml_escape(config['site_tagline'])}</p>
    <div class="hero-grid">
      <div class="hero-stat"><span>Latest score</span><strong>{latest['score']:.2f}</strong></div>
      <div class="hero-stat"><span>Regime</span><strong>{xml_escape(latest['regime'])}</strong></div>
      <div class="hero-stat"><span>Latest post</span><strong>{xml_escape(latest['date'])}</strong></div>
    </div>
    <p><a class="button" href="{root_url(f'posts/{latest["date"]}/')}">Read today’s post</a></p>
  </section>
  <section class="chart-section">
    <h2>Latest 90-session score history</h2>
    <img src="{root_url('assets/latest-score-history.svg')}?v={latest['latest_score_history_token']}" alt="Latest score history">
  </section>
  <section>
    <h2>Recent posts</h2>
    <div class="post-list">{''.join(items)}</div>
  </section>
</main>
{footer()}
"""
    desc = f"{config['site_name']} publishes one automated English post per day with charts, a unique SEO description, and a four-factor live-data pressure index."
    return html_page(config, config["site_name"], desc, body, abs_url(config, "/"))

def make_archive_page(config: dict, posts: List[dict]) -> str:
    items = []
    for post in posts:
        items.append(f"""
        <article class="post-list-item">
          <p class="post-list-date">{xml_escape(post['date'])} • {xml_escape(post['regime'])}</p>
          <h3><a href="{root_url(f'posts/{post["date"]}/')}">{xml_escape(post['title'])}</a></h3>
          <p>{xml_escape(post['description'])}</p>
        </article>
        """)
    body = f"""
{site_nav(config)}
<main class="wrap archive-layout">
  <section class="post-card">
    <h1>Archive</h1>
    <p>Every automatically generated daily post built from live public data lives here.</p>
  </section>
  <section class="post-list">{''.join(items)}</section>
</main>
{footer()}
"""
    return html_page(config, f"Archive | {config['site_name']}", f"Archive of automated daily posts from {config['site_name']}.", body, abs_url(config, "archive/"))

def make_about_page(config: dict) -> str:
    body = f"""
{site_nav(config)}
<main class="wrap about-layout">
  <section class="post-card">
    <h1>About the TACO Pressure Index</h1>
    <p class="lede">This upgraded build uses a symmetric equity leg instead of a drawdown-only equity leg.</p>
    <div class="metrics-grid">
      <article class="metric-card">
        <h3>Equity</h3>
        <p>The model now uses the signed 5-session S&amp;P 500 move.</p>
        <p class="metric-meta">Drawdowns add pressure. Rallies add relief. Relief partially offsets the composite score.</p>
      </article>
      <article class="metric-card">
        <h3>Rates</h3>
        <p>60% current 2Y level + 40% positive 5-session rise.</p>
      </article>
      <article class="metric-card">
        <h3>Inflation</h3>
        <p>60% current 5Y breakeven level + 40% positive 5-session rise.</p>
      </article>
      <article class="metric-card">
        <h3>Volatility</h3>
        <p>Current VIX level plus any positive 5-session jump.</p>
      </article>
    </div>
  </section>
</main>
{footer()}
"""
    return html_page(config, f"About | {config['site_name']}", "Methodology and scoring logic for the TACO Pressure Index.", body, abs_url(config, "about/"))

def make_rss(config: dict, posts: List[dict]) -> str:
    items = []
    for post in posts:
        url = f"{config['site_url']}/posts/{post['date']}/"
        items.append(f"""
<item>
  <title>{xml_escape(post['title'])}</title>
  <link>{xml_escape(url)}</link>
  <guid>{xml_escape(url)}</guid>
  <description>{xml_escape(post['description'])}</description>
  <pubDate>{datetime.fromisoformat(post['date']).strftime('%a, %d %b %Y 00:00:00 +0000')}</pubDate>
</item>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>{xml_escape(config['site_name'])}</title>
  <link>{xml_escape(config['site_url'])}</link>
  <description>{xml_escape(config['site_tagline'])}</description>
  {''.join(items)}
</channel>
</rss>
"""

def make_feed_json(config: dict, posts: List[dict]) -> dict:
    return {
        "version": "https://jsonfeed.org/version/1.1",
        "title": config["site_name"],
        "home_page_url": config["site_url"],
        "feed_url": f"{config['site_url']}/feed.json",
        "description": config["site_tagline"],
        "items": [
            {
                "id": f"{config['site_url']}/posts/{p['date']}/",
                "url": f"{config['site_url']}/posts/{p['date']}/",
                "title": p["title"],
                "summary": p["description"],
                "date_published": f"{p['date']}T00:00:00Z",
            }
            for p in posts
        ],
    }

def make_sitemap(config: dict, posts: List[dict]) -> str:
    urls = [f"{config['site_url']}/", f"{config['site_url']}/archive/", f"{config['site_url']}/about/"]
    urls.extend(f"{config['site_url']}/posts/{p['date']}/" for p in posts)
    nodes = "\n".join(f"  <url><loc>{xml_escape(u)}</loc></url>" for u in urls)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{nodes}
</urlset>
"""

STYLE_CSS = """
:root {
  --bg: #08101f;
  --panel: #101935;
  --text: #f4f7fb;
  --muted: #a6b4d6;
  --border: #23345a;
  --accent: #7fb1ff;
  --shadow: 0 18px 50px rgba(0,0,0,.28);
}
* { box-sizing: border-box; }
body { margin: 0; background: radial-gradient(circle at top, #12204a 0%, var(--bg) 42%); color: var(--text); font: 16px/1.65 Inter, system-ui, sans-serif; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
img { max-width: 100%; display: block; border-radius: 22px; border: 1px solid var(--border); }
.wrap { width: min(1120px, calc(100% - 32px)); margin: 0 auto; }
.site-header { position: sticky; top: 0; backdrop-filter: blur(14px); background: rgba(8,16,31,.75); border-bottom: 1px solid rgba(255,255,255,.06); z-index: 20; }
.nav-row { display: flex; justify-content: space-between; align-items: center; padding: 16px 0; }
.nav-row nav { display: flex; gap: 20px; }
.brand { color: var(--text); font-weight: 800; }
main { padding: 36px 0 60px; }
.hero-home, .post-card { background: linear-gradient(180deg, rgba(19,32,65,.95), rgba(11,17,34,.95)); border: 1px solid var(--border); border-radius: 28px; box-shadow: var(--shadow); padding: 30px; }
.lede { color: var(--muted); font-size: 1.08rem; max-width: 75ch; }
.hero-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin: 22px 0; }
.hero-stat, .metric-card, .post-list-item { background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.06); border-radius: 22px; padding: 18px; }
.hero-stat span { display: block; color: var(--muted); font-size: 14px; }
.hero-stat strong { display: block; font-size: 1.7rem; margin-top: 6px; }
.home-layout, .archive-layout, .post-layout, .about-layout { display: grid; gap: 24px; }
.post-list { display: grid; gap: 18px; }
.metrics-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 18px; }
.metric-score { font-size: 2rem; font-weight: 800; margin: 0 0 10px; }
.metric-score span { font-size: 1rem; color: var(--muted); margin-left: 6px; }
.metric-meta { color: var(--muted); margin: 6px 0; }
.post-list-date { margin: 0 0 8px; color: #8ef0c1; font-size: 13px; text-transform: uppercase; letter-spacing: .12em; }
.button { display: inline-block; padding: 12px 18px; border-radius: 999px; background: linear-gradient(90deg, var(--accent), #9ec6ff); color: #06101f; font-weight: 800; }
.site-footer { border-top: 1px solid rgba(255,255,255,.08); padding: 28px 0 36px; color: var(--muted); }
.footer-inner { display: flex; justify-content: space-between; gap: 20px; }
@media (max-width: 840px) {
  .hero-grid, .metrics-grid { grid-template-columns: 1fr; }
  .footer-inner, .nav-row { flex-direction: column; align-items: flex-start; }
}
"""

def build_site(config: dict, history: List[dict]) -> None:
    ensure_dirs()
    posts = []
    for day in history:
        post = {
            "date": day["date"],
            "score": day["score"],
            "regime": day["regime"],
            "drivers": day["drivers"],
            "title": post_title(day["date"], day["score"], day["regime"]),
            "description": make_description(day["date"], day["score"], day["regime"], day["drivers"]),
            "hero_summary": hero_summary(day["date"], day["score"], day["regime"], day["drivers"]),
        }
        save_post_snapshot(post)
        posts.append(post)

    posts = list(reversed(posts))
    recent_history = history[-config["chart_days"]:]
    latest_score_history_token = cache_bust_token([(x["date"], x["score"]) for x in recent_history])
    if posts:
        posts[0]["latest_score_history_token"] = latest_score_history_token

    json_dump(DATA_DIR / "latest.json", posts[0])
    json_dump(DATA_DIR / "posts.json", posts)
    json_dump(DATA_DIR / "history.json", history)

    write_text(SITE_DIR / "assets" / "style.css", STYLE_CSS)
    write_text(SITE_DIR / "assets" / "latest-score-history.svg", svg_line_chart([(x["date"], x["score"]) for x in recent_history], "Composite score history", f"Last {len(recent_history)} common sessions"))

    for post in posts:
        post_dir = SITE_DIR / "posts" / post["date"]
        upto = [x for x in history if x["date"] <= post["date"]][-config["chart_days"]:]
        score_svg = svg_line_chart([(x["date"], x["score"]) for x in upto], "Composite score history", f"Trailing {len(upto)} sessions through {post['date']}")
        component_items = [(v["label"], v["score"]) for v in sorted(post["drivers"].values(), key=lambda x: x["score"], reverse=True)]
        component_svg = svg_bar_chart(component_items, "Latest component scores", f"How each factor contributed on {post['date']}")
        post["score_history_token"] = cache_bust_token([(x["date"], x["score"]) for x in upto])
        post["component_chart_token"] = cache_bust_token(component_items)
        write_text(post_dir / "score-history.svg", score_svg)
        write_text(post_dir / "component-scores.svg", component_svg)
        write_text(post_dir / "index.html", make_post_page(config, post, upto))

    write_text(SITE_DIR / "index.html", make_index_page(config, posts))
    write_text(SITE_DIR / "archive" / "index.html", make_archive_page(config, posts))
    write_text(SITE_DIR / "about" / "index.html", make_about_page(config))
    write_text(SITE_DIR / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {config['site_url']}/sitemap.xml\n")
    write_text(SITE_DIR / "rss.xml", make_rss(config, posts[:30]))
    write_text(SITE_DIR / "feed.json", json.dumps(make_feed_json(config, posts[:30]), ensure_ascii=False, indent=2))
    write_text(SITE_DIR / "sitemap.xml", make_sitemap(config, posts))

def main() -> int:
    config = load_config()
    ensure_dirs()

    history = None
    used_cache = False
    try:
        rows = align_series(fetch_series(config), config["lookback_days"])
        history = compute_history(rows)
    except Exception as exc:
        cached = load_cached_history()
        if cached and validate_cache(cached, config):
            history = cached
            used_cache = True
            print(f"WARNING: live fetch failed; using cached history instead. Cause: {exc}", file=sys.stderr)
        else:
            print(f"ERROR: live fetch failed and no valid cached history exists. Cause: {exc}", file=sys.stderr)
            return 1

    build_site(config, history)
    source_label = "cached history" if used_cache else "live data"
    print(f"Built {config['site_name']} with {len(history)} daily posts from {source_label}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
