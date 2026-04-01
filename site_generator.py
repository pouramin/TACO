#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Dict, List, Tuple
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
    "series": {
        "sp500": {"id": "SP500", "label": "S&P 500", "note": "Large-cap U.S. equities"},
        "dgs2": {"id": "DGS2", "label": "2Y Treasury yield", "note": "Front-end Treasury yields"},
        "t5yie": {"id": "T5YIE", "label": "5Y breakeven inflation", "note": "Market inflation expectations"},
        "vix": {"id": "VIXCLS", "label": "VIX", "note": "Implied equity volatility"},
    },
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
MAX_CACHE_AGE_DAYS = 3


@dataclass
class Point:
    date: str
    value: float


@dataclass
class DailySnapshot:
    date: str
    score: float
    regime: str
    drivers: Dict[str, dict]
    description: str
    title: str
    hero_summary: str


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            user = json.load(f)
        merged = DEFAULT_CONFIG.copy()
        merged.update(user)
        merged["series"] = DEFAULT_CONFIG["series"].copy()
        merged["series"].update(user.get("series", {}))
        return merged
    return DEFAULT_CONFIG


def ensure_dirs() -> None:
    for p in [SITE_DIR, SITE_DIR / "assets", SITE_DIR / "posts", DATA_DIR, CONTENT_DIR]:
        p.mkdir(parents=True, exist_ok=True)


def fred_csv_url(series_id: str) -> str:
    return f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"


def fetch_csv(url: str, retries: int = 3) -> str:
    last_exc = None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Accept": "text/csv,application/csv,text/plain;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=30) as r:
                payload = r.read()
                try:
                    return payload.decode("utf-8-sig")
                except UnicodeDecodeError:
                    return payload.decode("latin-1")
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(f"Failed to fetch {url}: {last_exc}")


def parse_fred_csv(raw: str) -> List[Point]:
    # FRED CSV responses can occasionally include a UTF-8 BOM, leading blank
    # lines, or slightly different header casing. Parse defensively instead of
    # assuming the first line is exactly: DATE,<SERIES_ID>
    raw = raw.lstrip("\ufeff")
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    if not lines:
        return []

    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    header_idx = None
    date_col = 0
    value_col = 1
    for i, line in enumerate(lines[:10]):
        try:
            row = next(csv.reader([line]))
        except Exception:
            continue
        if not row:
            continue
        lowered = [c.strip().lower() for c in row]
        if "date" in lowered:
            header_idx = i
            date_col = lowered.index("date")
            non_date_cols = [idx for idx, name in enumerate(lowered) if idx != date_col]
            value_col = non_date_cols[0] if non_date_cols else 1
            break

    start_idx = header_idx + 1 if header_idx is not None else 0
    points: List[Point] = []
    for line in lines[start_idx:]:
        try:
            row = next(csv.reader([line]))
        except Exception:
            continue
        if len(row) < 2:
            continue

        d = row[date_col].strip() if date_col < len(row) else row[0].strip()
        v = row[value_col].strip() if value_col < len(row) else row[1].strip()

        if not date_re.match(d):
            continue
        if v in (None, ".", ""):
            continue

        v = v.replace(",", "")
        try:
            points.append(Point(date=d, value=float(v)))
        except ValueError:
            continue
    return points

def fetch_series(config: dict) -> Dict[str, List[Point]]:
    out = {}
    for key, meta in config["series"].items():
        url = fred_csv_url(meta["id"])
        raw = fetch_csv(url)
        points = parse_fred_csv(raw)
        if not points:
            preview = raw[:180].replace("\n", " ").replace("\r", " ").strip()
            raise RuntimeError(
                f"No valid rows parsed for series '{key}' ({meta['id']}). URL={url}. "
                f"Response preview: {preview!r}"
            )
        out[key] = points
    return out

def align_series(series: Dict[str, List[Point]], lookback_days: int) -> List[dict]:
    maps = {k: {p.date: p.value for p in pts} for k, pts in series.items()}
    if not maps:
        raise RuntimeError("No series were loaded.")
    date_sets = [set(m.keys()) for m in maps.values() if m]
    if len(date_sets) != len(maps):
        empty = [k for k, m in maps.items() if not m]
        raise RuntimeError(f"Some series were empty after parsing: {', '.join(empty)}")
    common_dates = sorted(set.intersection(*date_sets)) if date_sets else []
    if not common_dates:
        lengths = ', '.join(f"{k}={len(v)}" for k, v in maps.items())
        raise RuntimeError(f"No overlapping dates across live series ({lengths}).")
    common_dates = common_dates[-lookback_days:]
    rows = []
    for d in common_dates:
        rows.append({"date": d, **{k: maps[k][d] for k in maps}})
    return rows


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def component_scores(rows: List[dict], idx: int) -> Dict[str, dict]:
    i5 = max(0, idx - 5)
    today = rows[idx]
    prev5 = rows[i5]

    eq_drop_pct = max(0.0, (prev5["sp500"] - today["sp500"]) / prev5["sp500"] * 100.0)
    eq_score = clamp(eq_drop_pct / 5.0 * 100)

    y2_bps = max(0.0, (today["dgs2"] - prev5["dgs2"]) * 100)
    y2_score = clamp(y2_bps / 25.0 * 100)

    inf_bps = max(0.0, (today["t5yie"] - prev5["t5yie"]) * 100)
    inf_score = clamp(inf_bps / 20.0 * 100)

    vix_level_score = clamp((today["vix"] - 12.0) / (35.0 - 12.0) * 70.0)
    vix_jump_score = clamp(max(0.0, today["vix"] - prev5["vix"]) / 8.0 * 30.0)
    vix_score = clamp(vix_level_score + vix_jump_score)

    return {
        "equity": {
            "label": "S&P 500 equity pressure",
            "raw": round(eq_drop_pct, 2),
            "unit": "% 5-session drop",
            "score": round(eq_score, 2),
            "latest_value": today["sp500"],
            "latest_date": today["date"],
            "note": "Bigger equity drawdowns imply more stress.",
        },
        "rates": {
            "label": "2Y Treasury rate pressure",
            "raw": round(y2_bps, 2),
            "unit": "bps 5-session increase",
            "score": round(y2_score, 2),
            "latest_value": today["dgs2"],
            "latest_date": today["date"],
            "note": "A rise in front-end yields can tighten financial conditions.",
        },
        "inflation": {
            "label": "Inflation expectations pressure",
            "raw": round(inf_bps, 2),
            "unit": "bps 5-session increase",
            "score": round(inf_score, 2),
            "latest_value": today["t5yie"],
            "latest_date": today["date"],
            "note": "Higher breakevens imply more inflation pressure.",
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
        score = round(mean(x["score"] for x in drivers.values()), 2)
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


def top_drivers(drivers: Dict[str, dict], n: int = 2) -> List[Tuple[str, dict]]:
    return sorted(drivers.items(), key=lambda kv: kv[1]["score"], reverse=True)[:n]


def human_driver_name(key: str) -> str:
    return {
        "equity": "equity stress",
        "rates": "front-end rate pressure",
        "inflation": "inflation expectations",
        "volatility": "volatility",
    }[key]


def hero_summary(date: str, score: float, regime: str, drivers: Dict[str, dict]) -> str:
    lead = choose_opening(date + "hero", ANALYSIS_SENTENCES)
    tops = top_drivers(drivers, 2)
    names = " and ".join(human_driver_name(k) for k, _ in tops)
    return f"{lead} On {date}, the score printed {score:.2f}/100 in the {regime.lower()} regime, with {names} doing most of the work."


def make_description(date: str, score: float, regime: str, drivers: Dict[str, dict]) -> str:
    opener = choose_opening(date, DESCRIPTION_OPENERS)
    closer = choose_opening(date + "closer", DESCRIPTION_CLOSERS)
    tops = top_drivers(drivers, 2)
    drivers_text = " and ".join(human_driver_name(k) for k, _ in tops)
    return (
        f"{opener} for {date}: the TACO Pressure Index closed at {score:.2f}/100, "
        f"signaling a {regime.lower()} pressure regime as {drivers_text} shaped the daily read. {closer}"
    )


def post_title(date: str, score: float, regime: str) -> str:
    return f"{date} TACO Pressure Index Update: {regime.title()} at {score:.2f}"


def load_cached_history() -> List[dict] | None:
    path = DATA_DIR / "history.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            return data
    except Exception:
        return None
    return None


def cache_recency_days(history: List[dict], tz_name: str) -> int:
    latest = datetime.fromisoformat(history[-1]["date"]).date()
    today = datetime.now(ZoneInfo(tz_name)).date()
    return (today - latest).days


def validate_history(history: List[dict], config: dict | None = None, cache_mode: bool = False) -> None:
    if not history:
        raise RuntimeError("No historical rows available to build the site.")
    required_top = {"date", "score", "regime", "drivers"}
    required_drivers = {"equity", "rates", "inflation", "volatility"}
    seen_dates = []
    for row in history:
        missing = required_top - set(row.keys())
        if missing:
            raise RuntimeError(f"Cached history is missing keys: {sorted(missing)}")
        if set(row["drivers"].keys()) != required_drivers:
            raise RuntimeError("Cached history does not contain the expected driver blocks.")
        seen_dates.append(row["date"])

    if seen_dates != sorted(seen_dates):
        raise RuntimeError("History dates are not sorted ascending.")
    if len(set(seen_dates)) != len(seen_dates):
        raise RuntimeError("History contains duplicate dates.")

    if cache_mode:
        if len(history) < MIN_CACHE_ROWS:
            raise RuntimeError(
                f"Cached history is too short to trust ({len(history)} rows; need at least {MIN_CACHE_ROWS})."
            )
        if config is not None:
            age_days = cache_recency_days(history, config.get("timezone", "UTC"))
            if age_days > MAX_CACHE_AGE_DAYS:
                raise RuntimeError(
                    f"Cached history is stale ({age_days} days behind today; max allowed is {MAX_CACHE_AGE_DAYS})."
                )


def json_dump(path: Path, data) -> None:

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_raw_snapshot(day: dict) -> None:
    json_dump(CONTENT_DIR / f"{day['date']}.json", day)


def format_num(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def svg_line_chart(points: List[Tuple[str, float]], title: str, subtitle: str, width: int = 960, height: int = 430) -> str:
    margin = {"l": 70, "r": 25, "t": 60, "b": 55}
    xs = list(range(len(points)))
    ys = [p[1] for p in points]
    if not ys:
        ys = [0.0]
    ymin = min(ys)
    ymax = max(ys)
    if math.isclose(ymin, ymax):
        ymax = ymin + 1.0
    chart_w = width - margin["l"] - margin["r"]
    chart_h = height - margin["t"] - margin["b"]

    def sx(i: int) -> float:
        if len(xs) == 1:
            return margin["l"] + chart_w / 2
        return margin["l"] + (i / (len(xs) - 1)) * chart_w

    def sy(v: float) -> float:
        return margin["t"] + (1 - (v - ymin) / (ymax - ymin)) * chart_h

    path = " ".join(
        ("M" if i == 0 else "L") + f" {sx(i):.2f} {sy(v):.2f}" for i, v in enumerate(ys)
    )

    ticks = 5
    y_grid = []
    for t in range(ticks + 1):
        val = ymin + (ymax - ymin) * t / ticks
        yy = sy(val)
        y_grid.append((yy, val))

    label_idx = sorted(set([0, len(points) // 2, len(points) - 1])) if points else [0]
    x_labels = [(sx(i), points[i][0]) for i in label_idx]

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{xml_escape(title)}">',
        f'<rect width="100%" height="100%" fill="{PALETTE["bg"]}" rx="20"/>',
        f'<text x="{margin["l"]}" y="32" fill="{PALETTE["text"]}" font-family="Inter, Arial, sans-serif" font-size="24" font-weight="700">{xml_escape(title)}</text>',
        f'<text x="{margin["l"]}" y="52" fill="{PALETTE["muted"]}" font-family="Inter, Arial, sans-serif" font-size="13">{xml_escape(subtitle)}</text>',
    ]
    for yy, val in y_grid:
        svg.append(f'<line x1="{margin["l"]}" x2="{width - margin["r"]}" y1="{yy:.2f}" y2="{yy:.2f}" stroke="{PALETTE["grid"]}" stroke-width="1"/>')
        svg.append(f'<text x="{margin["l"] - 12}" y="{yy + 4:.2f}" text-anchor="end" fill="{PALETTE["muted"]}" font-family="Inter, Arial, sans-serif" font-size="12">{val:.0f}</text>')
    for xx, label in x_labels:
        svg.append(f'<text x="{xx:.2f}" y="{height - 18}" text-anchor="middle" fill="{PALETTE["muted"]}" font-family="Inter, Arial, sans-serif" font-size="12">{xml_escape(label)}</text>')
    svg.append(f'<path d="{path}" fill="none" stroke="{PALETTE["line"]}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')
    if points:
        lx, ly = sx(len(points) - 1), sy(ys[-1])
        svg.append(f'<circle cx="{lx:.2f}" cy="{ly:.2f}" r="6" fill="{PALETTE["line"]}"/>')
        svg.append(f'<text x="{lx - 8:.2f}" y="{ly - 12:.2f}" text-anchor="end" fill="{PALETTE["text"]}" font-family="Inter, Arial, sans-serif" font-size="12" font-weight="600">{ys[-1]:.2f}</text>')
    svg.append('</svg>')
    return "\n".join(svg)


def svg_bar_chart(items: List[Tuple[str, float]], title: str, subtitle: str, width: int = 960, height: int = 430) -> str:
    max_label_len = max((len(label) for label, _ in items), default=18)
    left_margin = min(340, max(220, int(max_label_len * 8.0)))
    margin = {"l": left_margin, "r": 25, "t": 60, "b": 40}
    chart_w = width - margin["l"] - margin["r"]
    chart_h = height - margin["t"] - margin["b"]
    bar_gap = 18
    bar_h = (chart_h - bar_gap * (len(items) - 1)) / max(1, len(items))

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{xml_escape(title)}">',
        f'<rect width="100%" height="100%" fill="{PALETTE["bg"]}" rx="20"/>',
        f'<text x="{margin["l"]}" y="32" fill="{PALETTE["text"]}" font-family="Inter, Arial, sans-serif" font-size="24" font-weight="700">{xml_escape(title)}</text>',
        f'<text x="{margin["l"]}" y="52" fill="{PALETTE["muted"]}" font-family="Inter, Arial, sans-serif" font-size="13">{xml_escape(subtitle)}</text>',
    ]
    for i in range(6):
        x = margin["l"] + chart_w * i / 5
        svg.append(f'<line x1="{x:.2f}" x2="{x:.2f}" y1="{margin["t"]}" y2="{height - margin["b"]}" stroke="{PALETTE["grid"]}" stroke-width="1"/>')
        svg.append(f'<text x="{x:.2f}" y="{height - 12}" text-anchor="middle" fill="{PALETTE["muted"]}" font-family="Inter, Arial, sans-serif" font-size="12">{i*20}</text>')
    for idx, (label, val) in enumerate(items):
        y = margin["t"] + idx * (bar_h + bar_gap)
        bar_w = chart_w * clamp(val) / 100.0
        color = PALETTE["good"] if val < 25 else PALETTE["warn"] if val < 60 else PALETTE["bad"]
        label_x = margin["l"] - 16
        value_x = min(width - margin["r"] - 6, margin["l"] + bar_w + 8)
        svg.append(f'<text x="{label_x}" y="{y + bar_h/2 + 5:.2f}" text-anchor="end" fill="{PALETTE["text"]}" font-family="Inter, Arial, sans-serif" font-size="14">{xml_escape(label)}</text>')
        svg.append(f'<rect x="{margin["l"]}" y="{y:.2f}" width="{chart_w:.2f}" height="{bar_h:.2f}" rx="10" fill="{PALETTE["panel"]}" stroke="{PALETTE["border"]}"/>')
        svg.append(f'<rect x="{margin["l"]}" y="{y:.2f}" width="{bar_w:.2f}" height="{bar_h:.2f}" rx="10" fill="{color}"/>')
        svg.append(f'<text x="{value_x:.2f}" y="{y + bar_h/2 + 5:.2f}" fill="{PALETTE["text"]}" font-family="Inter, Arial, sans-serif" font-size="13" font-weight="600">{val:.2f}</text>')
    svg.append('</svg>')
    return "\n".join(svg)


def svg_og_card(title: str, subtitle: str, score: float, regime: str, width: int = 1200, height: int = 630) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0%" stop-color="#0b1020"/>
      <stop offset="100%" stop-color="#18254a"/>
    </linearGradient>
  </defs>
  <rect width="100%" height="100%" fill="url(#bg)" rx="32"/>
  <text x="80" y="120" fill="#a5b4d6" font-family="Inter, Arial, sans-serif" font-size="30">TACO | Trump Always Chickens Out</text>
  <text x="80" y="220" fill="#ffffff" font-family="Inter, Arial, sans-serif" font-size="54" font-weight="700">{xml_escape(title)}</text>
  <text x="80" y="300" fill="#d6def2" font-family="Inter, Arial, sans-serif" font-size="28">{xml_escape(subtitle)}</text>
  <rect x="80" y="380" width="360" height="150" rx="24" fill="#121933" stroke="#27314e"/>
  <text x="120" y="445" fill="#93a4c3" font-family="Inter, Arial, sans-serif" font-size="24">Composite score</text>
  <text x="120" y="505" fill="#ffffff" font-family="Inter, Arial, sans-serif" font-size="64" font-weight="700">{score:.2f}</text>
  <rect x="490" y="410" width="220" height="80" rx="40" fill="#223154"/>
  <text x="600" y="462" text-anchor="middle" fill="#ffffff" font-family="Inter, Arial, sans-serif" font-size="32" font-weight="700">{xml_escape(regime)}</text>
</svg>'''


def root_url(path: str) -> str:
    path = path.lstrip("/")
    return f"/{path}" if path else "/"


def abs_url(config: dict, path: str) -> str:
    return f"{config['site_url'].rstrip('/')}/{path.lstrip('/')}"


def html_page(*, config: dict, title: str, description: str, body: str, canonical: str, og_image: str, extra_head: str = "") -> str:
    return f'''<!doctype html>
<html lang="{config['language']}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{xml_escape(title)}</title>
  <meta name="description" content="{xml_escape(description)}">
  <link rel="canonical" href="{xml_escape(canonical)}">
  <meta property="og:type" content="article">
  <meta property="og:title" content="{xml_escape(title)}">
  <meta property="og:description" content="{xml_escape(description)}">
  <meta property="og:url" content="{xml_escape(canonical)}">
  <meta property="og:image" content="{xml_escape(og_image)}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{xml_escape(title)}">
  <meta name="twitter:description" content="{xml_escape(description)}">
  <meta name="twitter:image" content="{xml_escape(og_image)}">
  <link rel="alternate" type="application/rss+xml" title="{xml_escape(config['site_name'])}" href="{xml_escape(root_url('rss.xml'))}">
  <link rel="stylesheet" href="{xml_escape(root_url('assets/style.css'))}">
  {extra_head}
</head>
<body>
{body}
</body>
</html>'''


def site_nav(config: dict) -> str:
    return f'''
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
'''


def footer(config: dict) -> str:
    return f'''
<footer class="site-footer">
  <div class="wrap footer-inner footer-centered">
    <a class="x-logo-link" href="https://x.com/pouraminam" target="_blank" rel="noopener noreferrer" aria-label="Follow on X">
      <img class="x-logo" src="{root_url('assets/x-mark.svg')}" alt="">
    </a>
  </div>
</footer>
'''


def make_post_page(config: dict, post: dict, recent_history: List[dict]) -> str:
    post_url = abs_url(config, f"posts/{post['date']}/")
    og_url = abs_url(config, f"posts/{post['date']}/og.svg")
    json_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post["title"],
        "description": post["description"],
        "datePublished": post["date"],
        "dateModified": post["date"],
        "inLanguage": config["language"],
        "author": {"@type": "Person", "name": config["author"]},
        "mainEntityOfPage": post_url,
        "publisher": {"@type": "Organization", "name": config["site_name"]},
        "image": og_url,
    }, ensure_ascii=False)

    driver_cards = []
    for item in sorted(post["drivers"].values(), key=lambda x: x["score"], reverse=True):
        driver_cards.append(f'''
          <article class="metric-card">
            <h3>{xml_escape(item['label'])}</h3>
            <p class="metric-score">{item['score']:.2f}<span>/100</span></p>
            <p class="metric-meta">{xml_escape(str(item['raw']))} {xml_escape(item['unit'])}</p>
            <p class="metric-meta">Latest: {xml_escape(format_num(item['latest_value']))} on {xml_escape(item['latest_date'])}</p>
            <p>{xml_escape(item['note'])}</p>
          </article>
        ''')

    body = f'''
{site_nav(config)}
<main class="wrap post-layout">
  <article class="post-card">
    <h1>{xml_escape(post['title'])}</h1>
    <p class="lede">{xml_escape(post['hero_summary'])}</p>

    <div class="hero-grid">
      <div class="hero-stat">
        <span>Composite score</span>
        <strong>{post['score']:.2f}</strong>
      </div>
      <div class="hero-stat">
        <span>Regime</span>
        <strong>{xml_escape(post['regime'])}</strong>
      </div>
      <div class="hero-stat">
        <span>Published</span>
        <strong>{xml_escape(post['date'])}</strong>
      </div>
    </div>

    <p>{xml_escape(post['description'])}</p>

    <section class="chart-section">
      <h2>Pressure history</h2>
      <img src="./score-history.svg" alt="Score history chart for the last 90 sessions">
    </section>

    <section class="chart-section">
      <h2>Latest component scores</h2>
      <img src="./component-scores.svg" alt="Bar chart of the latest component scores">
    </section>

    <section>
      <h2>Today’s component breakdown</h2>
      <div class="metrics-grid">
        {''.join(driver_cards)}
      </div>
    </section>

    <section>
      <h2>Method in one paragraph</h2>
      <p>The TACO Pressure Index converts four live market inputs into 0–100 pressure scores and averages them into a composite reading. The framework penalizes S&amp;P 500 drawdowns, rising 2-year Treasury yields, higher 5-year breakeven inflation, and elevated VIX readings, then groups the result into LOW, ELEVATED, HIGH, and EXTREME regimes.</p>
    </section>
  </article>
</main>
{footer(config)}
'''
    return html_page(
        config=config,
        title=post["title"],
        description=post["description"],
        body=body,
        canonical=post_url,
        og_image=og_url,
        extra_head=f'<script type="application/ld+json">{json_ld}</script>',
    )


def make_index_page(config: dict, posts: List[dict]) -> str:
    latest = posts[0]
    items = []
    for post in posts[: config["posts_to_show_on_home"]]:
        items.append(f'''
        <article class="post-list-item">
          <p class="post-list-date">{xml_escape(post['date'])}</p>
          <h3><a href="{root_url(f"posts/{post['date']}/")}">{xml_escape(post['title'])}</a></h3>
          <p>{xml_escape(post['description'])}</p>
        </article>
        ''')

    body = f'''
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
    <p><a class="button" href="{root_url(f"posts/{latest['date']}/")}">Read today’s post</a></p>
  </section>

  <section class="chart-section">
    <h2>Latest 90-session score history</h2>
    <img src="{root_url('assets/latest-score-history.svg')}" alt="Composite score history chart">
  </section>

  <section class="grid-two">
    <div class="panel">
      <h2>What the site publishes</h2>
      <p>One new post per day with a dated headline, a unique SEO-friendly description, a market summary, and freshly generated charts based on live public data.</p>
    </div>
    <div class="panel">
      <h2>How to read it</h2>
      <p>The composite score ranges from 0 to 100 and is grouped into LOW, ELEVATED, HIGH, and EXTREME regimes. Higher readings mean broader pressure across equities, front-end rates, inflation expectations, and volatility.</p>
    </div>
  </section>

  <section>
    <h2>Recent posts</h2>
    <div class="post-list">{''.join(items)}</div>
  </section>
</main>
{footer(config)}
'''
    desc = f"{config['site_name']} publishes one automated English post per day with charts, a unique SEO description, and a four-factor live-data pressure index."
    return html_page(
        config=config,
        title=config["site_name"],
        description=desc,
        body=body,
        canonical=abs_url(config, '/'),
        og_image=abs_url(config, 'assets/home-og.svg'),
    )


def make_archive_page(config: dict, posts: List[dict]) -> str:
    items = []
    for post in posts:
        items.append(f'''
        <article class="post-list-item">
          <p class="post-list-date">{xml_escape(post['date'])} • {xml_escape(post['regime'])}</p>
          <h3><a href="{root_url(f"posts/{post['date']}/")}">{xml_escape(post['title'])}</a></h3>
          <p>{xml_escape(post['description'])}</p>
        </article>
        ''')
    body = f'''
{site_nav(config)}
<main class="wrap archive-layout">
  <section class="panel">
    <h1>Archive</h1>
    <p>Every automatically generated daily post built from live public data lives here.</p>
  </section>
  <section class="post-list">{''.join(items)}</section>
</main>
{footer(config)}
'''
    return html_page(
        config=config,
        title=f"Archive | {config['site_name']}",
        description=f"Archive of automated daily posts from {config['site_name']}.",
        body=body,
        canonical=abs_url(config, 'archive/'),
        og_image=abs_url(config, 'assets/home-og.svg'),
    )


def make_about_page(config: dict) -> str:
    title = f"About | {config['site_name']}"
    description = (
        "How the TACO Pressure Index works: live inputs, daily scoring logic, regime thresholds, "
        "and what the composite score is designed to measure."
    )
    body = f'''
{site_nav(config)}
<main class="wrap about-layout">
  <section class="post-card">
    <p class="eyebrow">Methodology</p>
    <h1>About the TACO Pressure Index</h1>
    <p class="lede">This site publishes one daily reading built from real market data. The goal is not to predict policy decisions with certainty. The goal is to track how much multi-factor market pressure is building at any given moment.</p>

    <section class="grid-two">
      <div class="panel">
        <h2>What data goes into the index</h2>
        <p>The model pulls four public series: the S&amp;P 500, the U.S. 2-year Treasury yield, 5-year breakeven inflation, and the VIX. The site keeps only dates where all four series are available together, then computes one daily score from that aligned history.</p>
      </div>
      <div class="panel">
        <h2>What the score is trying to capture</h2>
        <p>The framework treats falling equities, rising front-end rates, rising inflation expectations, and higher volatility as signs of growing market stress. When more of those signals worsen at the same time, the composite score rises.</p>
      </div>
    </section>

    <section class="panel">
      <h2>How scoring works</h2>
      <div class="metrics-grid methodology-grid">
        <article class="metric-card">
          <h3>1) Equity pressure</h3>
          <p>The model looks at the 5-session drop in the S&amp;P 500.</p>
          <p class="metric-meta">A 5% drop maps to 100. A 2.5% drop maps to 50. Little or no drawdown keeps this component low.</p>
        </article>
        <article class="metric-card">
          <h3>2) Rates pressure</h3>
          <p>The model looks at the 5-session increase in the U.S. 2-year Treasury yield, measured in basis points.</p>
          <p class="metric-meta">A 25 bp rise maps to 100. A 12.5 bp rise maps to 50.</p>
        </article>
        <article class="metric-card">
          <h3>3) Inflation pressure</h3>
          <p>The model looks at the 5-session increase in 5-year breakeven inflation.</p>
          <p class="metric-meta">A 20 bp rise maps to 100. A 10 bp rise maps to 50.</p>
        </article>
        <article class="metric-card">
          <h3>4) Volatility pressure</h3>
          <p>The VIX component combines two ideas: the current VIX level and the change versus 5 sessions ago.</p>
          <p class="metric-meta">That means volatility pressure can rise because volatility is already high, because it jumped suddenly, or because both happened together.</p>
        </article>
      </div>
    </section>

    <section class="grid-two">
      <div class="panel">
        <h2>Composite score</h2>
        <p>Each component is converted to a 0-100 score. The final daily reading is the simple average of the four component scores.</p>
        <div class="formula-box">Composite Score = average(equity, rates, inflation, volatility)</div>
      </div>
      <div class="panel">
        <h2>Regime labels</h2>
        <ul class="regime-list">
          <li><strong>LOW</strong>: 0 to below 25</li>
          <li><strong>ELEVATED</strong>: 25 to below 50</li>
          <li><strong>HIGH</strong>: 50 to below 75</li>
          <li><strong>EXTREME</strong>: 75 to 100</li>
        </ul>
      </div>
    </section>

    <section class="panel">
      <h2>How to interpret the site</h2>
      <p>A higher score does not mean a policy reversal must happen. It means the market backdrop is putting more stress on the system across several channels at once. This is a custom heuristic model designed for monitoring pressure, not an official Deutsche Bank model and not a guaranteed forecast of political behavior.</p>
    </section>
  </section>
</main>
{footer(config)}
'''
    return html_page(
        config=config,
        title=title,
        description=description,
        body=body,
        canonical=abs_url(config, 'about/'),
        og_image=abs_url(config, 'assets/home-og.svg'),
    )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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
        save_raw_snapshot(post)
        posts.append(post)

    posts = list(reversed(posts))
    recent_history = list(reversed(history[-config["chart_days"] :]))

    json_dump(DATA_DIR / "latest.json", posts[0])
    json_dump(DATA_DIR / "posts.json", posts)
    json_dump(DATA_DIR / "history.json", history)

    latest_score_svg = svg_line_chart(
        [(x["date"], x["score"]) for x in recent_history],
        title="Composite score history",
        subtitle=f"Last {len(recent_history)} common sessions",
    )
    write_text(SITE_DIR / "assets" / "latest-score-history.svg", latest_score_svg)
    write_text(
        SITE_DIR / "assets" / "home-og.svg",
        svg_og_card(config["site_name"], config["site_tagline"], posts[0]["score"], posts[0]["regime"]),
    )

    for post in posts:
        post_dir = SITE_DIR / "posts" / post["date"]
        post_dir.mkdir(parents=True, exist_ok=True)
        # history up to post date
        upto = [x for x in history if x["date"] <= post["date"]][-config["chart_days"] :]
        score_svg = svg_line_chart(
            [(x["date"], x["score"]) for x in upto],
            title="Composite score history",
            subtitle=f"Trailing {len(upto)} sessions through {post['date']}",
        )
        component_svg = svg_bar_chart(
            [(v["label"], v["score"]) for v in sorted(post["drivers"].values(), key=lambda x: x["score"], reverse=True)],
            title="Latest component scores",
            subtitle=f"How each factor contributed on {post['date']}",
        )
        write_text(post_dir / "score-history.svg", score_svg)
        write_text(post_dir / "component-scores.svg", component_svg)
        write_text(post_dir / "og.svg", svg_og_card(post["title"], post["description"], post["score"], post["regime"]))
        write_text(post_dir / "index.html", make_post_page(config, post, recent_history))

    (SITE_DIR / "archive").mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "about").mkdir(parents=True, exist_ok=True)
    write_text(SITE_DIR / "index.html", make_index_page(config, posts))
    write_text(SITE_DIR / "archive" / "index.html", make_archive_page(config, posts))
    write_text(SITE_DIR / "about" / "index.html", make_about_page(config))
    write_text(SITE_DIR / "assets" / "style.css", STYLE_CSS)
    write_text(SITE_DIR / "assets" / "x-mark.svg", X_MARK_SVG)
    write_text(SITE_DIR / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {config['site_url']}/sitemap.xml\n")
    write_text(SITE_DIR / "_headers", "/*\n  Cache-Control: public, max-age=300\n")
    write_text(SITE_DIR / "rss.xml", make_rss(config, posts[:30]))
    write_text(SITE_DIR / "feed.json", json.dumps(make_feed_json(config, posts[:30]), ensure_ascii=False, indent=2))
    write_text(SITE_DIR / "sitemap.xml", make_sitemap(config, posts))


def make_rss(config: dict, posts: List[dict]) -> str:
    items = []
    for post in posts:
        url = f"{config['site_url']}/posts/{post['date']}/"
        items.append(f'''
<item>
  <title>{xml_escape(post['title'])}</title>
  <link>{xml_escape(url)}</link>
  <guid>{xml_escape(url)}</guid>
  <description>{xml_escape(post['description'])}</description>
  <pubDate>{datetime.fromisoformat(post['date']).strftime('%a, %d %b %Y 00:00:00 +0000')}</pubDate>
</item>''')
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>{xml_escape(config['site_name'])}</title>
  <link>{xml_escape(config['site_url'])}</link>
  <description>{xml_escape(config['site_tagline'])}</description>
  {''.join(items)}
</channel>
</rss>
'''


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
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{nodes}
</urlset>
'''


X_MARK_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">
  <defs>
    <linearGradient id="g" x1="12" y1="10" x2="52" y2="54" gradientUnits="userSpaceOnUse">
      <stop stop-color="#9ec6ff"/>
      <stop offset="1" stop-color="#8ef0c1"/>
    </linearGradient>
  </defs>
  <path d="M13 12h11.6l11.1 15.4L48 12h4L37.5 28.5 53 52H41.4L29.1 34.7 13.8 52H9.7l17.5-19.9L13 12Zm14.1 4.1h-6l21.8 31.8h6L27.1 16.1Z" fill="url(#g)"/>
</svg>
"""


STYLE_CSS = """
:root {
  --bg: #08101f;
  --panel: #101935;
  --panel-2: #132041;
  --text: #f4f7fb;
  --muted: #a6b4d6;
  --border: #23345a;
  --accent: #7fb1ff;
  --accent-2: #8ef0c1;
  --shadow: 0 18px 50px rgba(0,0,0,.28);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: radial-gradient(circle at top, #12204a 0%, var(--bg) 42%);
  color: var(--text);
  font: 16px/1.65 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
img { max-width: 100%; height: auto; display: block; border-radius: 22px; border: 1px solid var(--border); }
.wrap { width: min(1120px, calc(100% - 32px)); margin: 0 auto; }
.site-header { position: sticky; top: 0; backdrop-filter: blur(14px); background: rgba(8,16,31,.75); border-bottom: 1px solid rgba(255,255,255,.06); z-index: 20; }
.nav-row { display: flex; justify-content: space-between; align-items: center; padding: 16px 0; }
.nav-row nav { display: flex; gap: 20px; }
.brand { color: var(--text); font-weight: 800; letter-spacing: .2px; }
main { padding: 36px 0 60px; }
.hero-home, .post-card, .panel { background: linear-gradient(180deg, rgba(19,32,65,.95), rgba(11,17,34,.95)); border: 1px solid var(--border); border-radius: 28px; box-shadow: var(--shadow); }
.hero-home, .post-card { padding: 30px; }
.panel { padding: 24px; }
.eyebrow { color: var(--accent-2); text-transform: uppercase; letter-spacing: .14em; font-size: 12px; font-weight: 700; }
.lede { color: var(--muted); font-size: 1.12rem; max-width: 75ch; }
.hero-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin: 22px 0; }
.hero-stat { background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.06); border-radius: 20px; padding: 18px; }
.hero-stat span { display: block; color: var(--muted); font-size: 14px; }
.hero-stat strong { display: block; font-size: clamp(1.4rem, 2vw, 2rem); margin-top: 6px; }
.button { display: inline-block; padding: 12px 18px; border-radius: 999px; background: linear-gradient(90deg, var(--accent), #9ec6ff); color: #06101f; font-weight: 800; }
.home-layout, .archive-layout, .post-layout { display: grid; gap: 24px; }
.grid-two { display: grid; grid-template-columns: repeat(2, 1fr); gap: 24px; }
.chart-section { margin-top: 20px; }
.post-list { display: grid; gap: 18px; }
.about-layout { display: grid; gap: 24px; }
.methodology-grid { grid-template-columns: repeat(2, 1fr); }
.formula-box { margin-top: 16px; padding: 16px 18px; border-radius: 18px; background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08); color: var(--text); font-weight: 700; }
.regime-list { margin: 0; padding-left: 20px; color: var(--muted); }
.regime-list li { margin: 8px 0; }
.post-list-item { padding: 22px; background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.06); border-radius: 22px; }
.post-list-date { margin: 0 0 8px; color: var(--accent-2); font-size: 13px; text-transform: uppercase; letter-spacing: .12em; }
.metrics-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 18px; }
.metric-card { padding: 20px; background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.07); border-radius: 22px; }
.metric-card h3 { margin: 0 0 8px; font-size: 1rem; }
.metric-score { font-size: 2rem; font-weight: 800; margin: 0 0 10px; }
.metric-score span { font-size: 1rem; color: var(--muted); margin-left: 6px; }
.metric-meta { color: var(--muted); margin: 6px 0; }
.site-footer { border-top: 1px solid rgba(255,255,255,.08); padding: 28px 0 36px; color: var(--muted); }
.footer-inner { display: flex; justify-content: space-between; gap: 20px; }
.footer-centered { justify-content: center; align-items: center; }
.x-logo-link { display: inline-flex; align-items: center; justify-content: center; width: 58px; height: 58px; border-radius: 999px; background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.08); box-shadow: var(--shadow); transition: transform .15s ease, border-color .15s ease, background .15s ease; }
.x-logo-link:hover { text-decoration: none; transform: translateY(-2px); border-color: rgba(127,177,255,.55); background: rgba(127,177,255,.08); }
.x-logo { width: 22px; height: 22px; display: block; border: 0; border-radius: 0; }
@media (max-width: 840px) {
  .hero-grid, .grid-two, .metrics-grid { grid-template-columns: 1fr; }
  .footer-inner, .nav-row { flex-direction: column; align-items: flex-start; }
  .footer-centered { align-items: center; }
}
"""


def main(argv: List[str]) -> int:
    config = load_config()
    ensure_dirs()

    history = None
    used_cache = False
    try:
        series = fetch_series(config)
        rows = align_series(series, config["lookback_days"])
        history = compute_history(rows)
        validate_history(history, config=config, cache_mode=False)
    except Exception as exc:
        cached = load_cached_history()
        if cached:
            try:
                validate_history(cached, config=config, cache_mode=True)
                history = cached
                used_cache = True
                print(f"WARNING: live fetch/build input failed; using cached real history instead. Cause: {exc}", file=sys.stderr)
            except Exception as cache_exc:
                print(f"ERROR: live fetch failed ({exc}) and cache was invalid ({cache_exc})", file=sys.stderr)
                return 1
        else:
            print(f"ERROR: live fetch failed and no cached history exists. Cause: {exc}", file=sys.stderr)
            return 1

    try:
        build_site(config, history)
    except Exception as exc:
        print(f"ERROR: site build failed: {exc}", file=sys.stderr)
        return 1

    tz = ZoneInfo(config.get("timezone", "UTC"))
    now = datetime.now(tz)
    source_label = "cached history" if used_cache else "live data"
    print(f"Built {config['site_name']} with {len(history)} daily posts from {source_label} at {now.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
