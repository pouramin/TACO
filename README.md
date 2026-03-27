# TACO | Trump Always Chickens Out

A static English-language website that publishes **one automated post per day** using **live public market data**.

The site is designed for GitHub Actions + Cloudflare Pages and includes:

- a dated article page every day
- a unique SEO-friendly description for each post
- automatically generated SVG charts
- an archive page
- RSS, JSON Feed, sitemap, and robots.txt

## Live data inputs

The generator downloads four public daily series from FRED and transforms them into a custom composite pressure score:

- **S&P 500** (`SP500`)
- **2Y Treasury yield** (`DGS2`)
- **5Y breakeven inflation** (`T5YIE`)
- **VIX** (`VIXCLS`)

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

## Deploy with GitHub + Cloudflare Pages

### 1) Push to GitHub
Create a new GitHub repo and push this project.

### 2) Connect to Cloudflare Pages
In Cloudflare Pages:

- connect the GitHub repository
- framework preset: **None**
- build command: leave empty
- output directory: `site`

Because the generated files are committed into the repository, Pages only needs to publish the `site/` folder.

### 3) Daily automation
The workflow file is already included:

`.github/workflows/daily-build.yml`

It runs on **push**, on a **daily schedule**, and on **manual dispatch**. It rebuilds the site with live data, commits the updated output, and pushes the result. Cloudflare Pages redeploys automatically after that push.

## Domain and branding

The project is preconfigured for:

- **Domain:** `https://freeiran.it`
- **Site name:** `TACO | Trump Always Chickens Out`

## Notes

- The score is a **custom framework**, not an official Deutsche Bank formula.
- Descriptions are generated daily and vary by date, score, regime, and top drivers.
- Charts are generated as static SVG files, so the site stays fast and serverless.
