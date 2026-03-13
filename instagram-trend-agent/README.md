# Instagram Reels Music Trend Intelligence Agent

A **minimal-cost, maximum-insight** autonomous agent that monitors Instagram Reels daily in the music/DJ/concert/production space and outputs actionable trend intelligence as structured CSV reports.

**Daily cost: $0.01–0.03** (LLM analysis only; scraping is free)

---

## What It Does

Every day at 6:00 AM UTC the agent:

1. Scrapes **50–100 Instagram Reels** across DJ, concert, and music production hashtags
2. Runs **zero-cost local analysis** (engagement velocity, audio tracking, hashtag co-occurrence)
3. Sends the **top 15 highest-signal reels** to Claude Haiku via Anthropic Batch API
4. Outputs a **daily trend CSV** + **running cumulative log** + **markdown brief**
5. Auto-discovers and tracks high-performing accounts over time

---

## Quick Start (Under 5 Minutes)

### 1. Install dependencies

```bash
cd instagram-trend-agent
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Optional: download spaCy model for better keyword extraction
python -m spacy download en_core_web_sm
```

### 2. Configure API keys

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
# (Apify and RapidAPI keys are optional — instaloader works without any key)
```

### 3. Test with a dry run

```bash
python main.py --mode dry-run
```

This shows exactly what the agent would do without making any real API calls. Check `outputs/` for generated files.

### 4. Run for real

```bash
python main.py --mode daily
```

### 5. Schedule daily runs

```bash
crontab -e
# Add this line (runs at 6 AM UTC):
0 6 * * * /path/to/instagram-trend-agent/run_daily.sh
```

---

## Output Files

| File | Description |
|------|-------------|
| `outputs/trends_YYYY-MM-DD.csv` | Daily trend analysis with marketing angles |
| `outputs/trend_log.csv` | Cumulative trend database (all days) |
| `outputs/daily_summary_YYYY-MM-DD.md` | Human-readable daily brief |
| `logs/YYYY-MM-DD.log` | Full run log for debugging |

### Daily CSV columns

```
date, trend_name, category, description, velocity, confidence,
marketing_angle, suggested_hashtags, suggested_audio, content_format,
shelf_life_days, evidence_reel_count, avg_engagement_velocity
```

### Trend velocity values

| Value | Meaning |
|-------|---------|
| `emerging` | Just appearing, weak signal but worth watching |
| `accelerating` | Growing rapidly — act now |
| `peaking` | At maximum popularity — time is short |
| `declining` | Losing steam — don't invest |

---

## Architecture

```
Data Ingestion (scrapers/)
    ├── instaloader_scraper.py   PRIMARY — free, no API key
    ├── apify_scraper.py         SECONDARY — 30 free runs/month
    ├── rapidapi_scraper.py      TERTIARY — 500 free req/month
    └── google_fallback.py       FALLBACK — zero-cost discovery
         ↓
Tier 1 Local Analysis (analysis/)
    ├── tier1_local.py           Engagement velocity, audio tracking,
    │                            hashtag co-occurrence, TF-IDF keywords
    └── virality_scorer.py       Composite score = velocity(40%) +
                                 audio_reuse(30%) + hashtag_trend(30%)
         ↓ (top 15 reels only)
Tier 2 LLM Analysis
    └── tier2_llm.py             Claude Haiku via Anthropic Batch API
                                 ~$0.01/day, 50% discount vs direct API
         ↓
Output Generation (output/)
    ├── csv_writer.py            Daily + cumulative CSV files
    └── summary_writer.py        Markdown daily brief
```

---

## Cost Breakdown

| Component | Method | Daily Cost |
|-----------|--------|------------|
| Scraping | Instaloader (free) | $0.00 |
| Scraping boost | Apify free tier | $0.00 |
| Scraping overflow | RapidAPI free tier | $0.00 |
| LLM Analysis | Claude Haiku Batch API | **$0.01–0.03** |
| **Total** | | **$0.01–0.03/day** |
| *Buffer for paid Apify runs* | *When free tiers exhausted* | *up to $3/day* |

---

## Configuration

All settings in `config.yaml`. Key options:

```yaml
budget:
  daily_ceiling_cents: 500    # $5 hard stop
  daily_target_cents: 300     # $3 target

scrapers:
  daily_target_reels: 75      # Reels to collect per day

analysis:
  virality_weights:
    engagement_velocity: 0.40  # Adjust scoring formula
    audio_reuse_count: 0.30
    hashtag_trend_score: 0.30
  tier2:
    top_reels_to_analyze: 15   # Reels sent to LLM
    model: "claude-haiku-4-5-20251001"
```

---

## Run Modes

```bash
python main.py --mode daily          # Full daily pipeline
python main.py --mode dry-run        # Preview only, no API calls
python main.py --mode analyze-only   # Skip scraping, analyze existing DB data
python main.py --mode scrape-only    # Collect data, skip LLM analysis
```

---

## How the Agent Gets Smarter Over Time

- **`data/monitored_accounts.json`** — Automatically grows as the agent discovers accounts that appear repeatedly in high-velocity posts
- **`data/hashtag_clusters.json`** — Updated daily with new hashtag co-occurrence patterns; uses exponential moving average to weight recent data
- **`outputs/trend_log.csv`** — Historical context fed back into each day's LLM prompt so Claude can detect acceleration and decline
- **Virality scoring weights** — Tunable in `config.yaml` as you learn what signals matter most for your niche

---

## Scraper Details

### Instaloader (Primary — Free)
- No API key required
- Scrapes top posts from hashtag pages
- Rate-limited by Instagram naturally; the agent respects this with configurable delays
- If rate-limited, automatically falls over to next source

### Apify (Secondary — Free tier: 30 runs/month)
- Requires `APIFY_API_KEY` in `.env`
- More reliable than instaloader for bulk collection
- Free tier tracked automatically; won't exceed without explicit budget approval

### RapidAPI (Tertiary — Free tier: ~500 req/month)
- Requires `RAPIDAPI_KEY` in `.env`
- Multiple Instagram API endpoints available on RapidAPI
- Used only when Apify quota is exhausted

### Google Fallback (Last resort — Free)
- No API key needed
- Searches `site:instagram.com/reel` + music keywords
- Provides URL discovery when direct Instagram access is blocked
- Returns less metadata; enriched by subsequent analysis

---

## Troubleshooting

**`instaloader` returns 0 reels**
Instagram rate-limits aggressively. Try: increase `sleep_between_requests` in `config.yaml`, or add your Apify/RapidAPI keys.

**LLM analysis skipped**
Set `ANTHROPIC_API_KEY` in your `.env` file. The agent runs fine without it but produces less insightful output.

**`spacy` model not found**
Run: `python -m spacy download en_core_web_sm`. The agent falls back to basic keyword counting if spaCy isn't available.

**Budget ceiling hit**
Check `data/budget.json` for what's been spent. Reset by deleting the file or waiting until tomorrow (it resets daily automatically).
