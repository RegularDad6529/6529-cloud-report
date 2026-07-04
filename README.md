# 6529 Cloud Report

Daily sentiment-driven word cloud generated from 6529.io wave drops.

## How it works

- Fetches recent drops from the 6529.io API (dive bar + top 5 most active waves)
- Runs VADER sentiment analysis on aggregated text
- Generates a cloud-shaped word cloud with weather-themed background
- Weather condition (sunny → stormy) reflects overall community sentiment
- Deep saturated seasonal color palettes (spring for positive, Halloween for negative)

## Schedule

GitHub Actions runs the pipeline at **06:00 and 18:00 UTC** daily. The latest PNG is committed to the repo and served via GitHub Pages.

## Local development

```bash
pip install wordcloud vaderSentiment pillow numpy
export TOKEN_6529="your-6529-api-token"
python cloud_report.py --daily --output output.png
```

## Flags

- `--daily` — Fetch last 24h of drops (vs. all-time cache)
- `--output PATH` — Custom output path
- `--cached` — Use cached word frequency data
- `--sentiment SCORE` — Override sentiment score