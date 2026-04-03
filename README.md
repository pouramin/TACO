# TACO | Trump Always Chickens Out

A static English-language website that publishes **one automated post per day** using **live public market data**.

This restored package keeps the richer site structure:
- interactive hoverable score charts
- X logo footer link
- richer About page and SEO metadata
- archive, RSS, JSON Feed, sitemap, robots.txt
- GitHub Actions workflow for daily rebuilds

## Scoring logic

- **Equity** = symmetric 5-session S&P 500 signal
  - drawdowns add pressure
  - rallies add relief
  - relief partially offsets the composite
- **Rates** = 60% current 2Y level + 40% positive 5-session rise
- **Inflation** = 60% current 5Y breakeven level + 40% positive 5-session rise
- **Volatility** = current VIX level + positive 5-session jump

Composite formula:

`clamp((equity pressure − 0.5 × equity relief + rates + inflation + volatility) / 4, 0, 100)`

## Deploy

Upload the files to the repo and run the GitHub Action.
