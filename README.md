# TACO | Trump Always Chickens Out

A static English-language website that publishes **one automated post per day** using **live public market data**.

The site is designed for scheduled static publishing and includes:

- a dated article page every day
- a unique SEO-friendly description for each post
- automatically generated SVG charts
- an archive page
- RSS, JSON Feed, sitemap, and robots.txt

## Live data inputs

The generator downloads four public daily market inputs from multiple public sources and transforms them into a custom composite pressure score:

- **S&P 500** (Yahoo Finance chart endpoint with Stooq fallback)
- **2Y Treasury yield** (U.S. Treasury daily yield curve data)
- **5Y breakeven inflation** (derived from U.S. Treasury nominal 5Y minus real 5Y yields)
- **VIX** (Cboe historical VIX data with Yahoo Finance fallback)

The algorithm converts each input into a 0–100 component score and averages them into a composite reading.

## Output

Each run creates or refreshes:

- `site/index.html`
- `site/archive/index.html`
- `site/posts/YYYY-MM-DD/index.html`
- fresh SVG charts for each post
- `site/rss.xml`, `site/feed.json`, `site/sitemap.xml`
- `data/latest.json`, `data/history.json`, `data/posts.json`
- raw daily snapshots under `content/posts/`

## Local build

This project is **live-data only**.

```bash
python site_generator.py
```

## Deploy

Publish the generated `site` directory on your preferred static hosting setup.

The included workflow can rebuild the site on a daily schedule and refresh the generated output automatically.

## Domain and branding

The project is preconfigured for:

- **Domain:** `https://freeiran.it`
- **Site name:** `TACO | Trump Always Chickens Out`

## Notes

- The score is a **custom framework**, not an official Deutsche Bank formula.
- Descriptions are generated daily and vary by date, score, regime, and top drivers.
- Charts are generated as static SVG files, so the site stays fast and serverless.


## Freshness and cache safety

This project will only fall back to cached history if the cache is both recent and substantial. Tiny or stale seed caches are rejected so the site does not silently publish outdated posts.


Scoring logic:
- **Equity** = 5-session S&P 500 drawdown only
- **Rates** = 60% current 2Y level + 40% positive 5-session rise
- **Inflation** = 60% current 5Y breakeven level + 40% positive 5-session rise
- **Volatility** = current VIX level + positive 5-session jump
