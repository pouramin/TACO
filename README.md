# TACO | Trump Always Chickens Out

A static English-language website that publishes **one automated post per day** using **live public market data**.

## What changed in this upgraded repo-native version

The old equity leg only measured **5-session S&P 500 drawdowns**.  
This upgraded version makes the equity component **symmetric**:

- **drawdowns add pressure**
- **rallies add relief**
- equity relief can **partially offset** the composite score

That means a positive market reaction after a soft Trump signal no longer collapses to `0.00` just because there was no drawdown.

## Live data inputs

The generator uses four public daily market inputs:

- **S&P 500** (Yahoo Finance chart endpoint with Stooq fallback)
- **2Y Treasury yield** (U.S. Treasury daily yield curve data)
- **5Y breakeven inflation** (derived from nominal 5Y minus real 5Y Treasury yields)
- **VIX** (Cboe historical VIX data with Yahoo Finance fallback)

## Equity logic

- **equity_pressure** comes from a negative 5-session S&P move
- **equity_relief** comes from a positive 5-session S&P move
- the final equity contribution is:

`equity_net = pressure - 0.5 × relief`

So rallies reduce pressure, but relief is only partially offsetting.

## Composite logic

The site computes:

`composite = clamp((equity_net + rates + inflation + volatility) / 4, 0, 100)`

## Output

Each run refreshes:

- `site/index.html`
- `site/archive/index.html`
- `site/about/index.html`
- `site/posts/YYYY-MM-DD/index.html`
- SVG charts
- `site/rss.xml`
- `site/feed.json`
- `site/sitemap.xml`
- `data/latest.json`
- `data/posts.json`
- `data/history.json`

## Local build

```bash
python site_generator.py
```

## Notes

- This is a **custom framework**, not an official Deutsche Bank formula.
- If live fetch fails, the generator falls back to `data/history.json` if it exists.
- This package is designed to replace the current repo files directly and then rebuild the site.


## GitHub-only usage

You do not need to run anything locally.

1. Replace the contents of your existing `pouramin/TACO` repo with this package.
2. Push to GitHub.
3. Run the existing Action, or use the included `.github/workflows/daily.yml`.

The Action will run `python site_generator.py` on GitHub and refresh `site/`, `data/`, and `content/posts/`.
