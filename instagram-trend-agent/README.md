# Instagram Reels Music Trend Intelligence Agent

An autonomous agent that monitors Instagram Reels daily in the music/DJ/concert/production space and outputs actionable trend intelligence as structured CSV reports.

**Daily cost: ~$0.07–0.10** (one Claude Sonnet call; scraping is free)

---

## What It Does

Every day at 6:00 AM UTC the agent:

1. Scrapes **50–100 Instagram Reels** across DJ, concert, and music production hashtags
2. Runs **zero-cost local analysis** (engagement velocity, audio tracking, hashtag co-occurrence)
3. Sends the **top 15 highest-signal reels** to Claude Sonnet for deep trend analysis
4. Outputs a **daily trend CSV** + **running cumulative log** + **markdown brief**
5. Auto-discovers and tracks high-performing accounts over time

---

## Architecture

```
LangChain Agent (claude-sonnet-4-6 orchestrator)
    │
    ├── Tool: check_budget
    ├── Tool: scrape_instagram_reels
    │       ├── instaloader_scraper.py   PRIMARY  — free, no API key
    │       ├── apify_scraper.py         SECONDARY — 30 free runs/month
    │       ├── rapidapi_scraper.py      TERTIARY  — 500 free req/month
    │       └── google_fallback.py       FALLBACK  — zero-cost discovery
    │
    ├── Tool: run_local_analysis
    │       ├── tier1_local.py           Engagement velocity, audio tracking,
    │       │                            hashtag co-occurrence, TF-IDF keywords
    │       └── virality_scorer.py       Score = velocity(40%) +
    │                                    audio_reuse(30%) + hashtag_trend(30%)
    │
    ├── Tool: deduplicate_and_persist    SQLite deduplication + account discovery
    │
    ├── Tool: analyze_trends_with_llm   claude-sonnet-4-6, structured Pydantic output
    │                                    ~$0.07–0.10/day
    │
    └── Tool: write_trend_outputs
            ├── csv_writer.py            Daily + cumulative CSV files
            └── summary_writer.py        Markdown daily brief
```

---

## Local Setup with Claude Code

These instructions are written for Claude Code to follow directly.

### Prerequisites

- Python 3.9+
- An Anthropic API key (get one at console.anthropic.com)
- Git

### Step 1 — Clone and navigate

```bash
git clone https://github.com/alecwaj/Trend-agent.git
cd Trend-agent/instagram-trend-agent
```

### Step 2 — Create a virtual environment and install dependencies

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Optional but recommended — improves caption keyword extraction:

```bash
python -m spacy download en_core_web_sm
```

### Step 3 — Configure API keys

```bash
cp .env.example .env
```

Open `.env` and set your keys:

```
ANTHROPIC_API_KEY=sk-ant-...   # Required
APIFY_API_KEY=                 # Optional — 30 free scrape runs/month
RAPIDAPI_KEY=                  # Optional — 500 free requests/month
```

Only `ANTHROPIC_API_KEY` is required. The agent scrapes via instaloader (free) by default.

### Step 4 — Verify setup with a dry run

```bash
python agent.py --mode dry-run --verbose
```

This runs the full pipeline using mock reel data — no real network calls, no API spend. Check `outputs/` for generated CSV and markdown files. If files appear, the setup is working correctly.

### Step 5 — Run for real

```bash
python agent.py --mode daily
```

### Step 6 — Schedule daily runs

```bash
crontab -e
# Add this line (runs at 6 AM UTC):
0 6 * * * /absolute/path/to/instagram-trend-agent/run_daily.sh
```

Update the path in `run_daily.sh` to match your actual install location.

### Troubleshooting

| Problem | Fix |
|---|---|
| `instaloader` returns 0 reels | Instagram rate-limits aggressively. Increase `sleep_between_requests` in `config.yaml`, or add Apify/RapidAPI keys. |
| LLM analysis skipped | Verify `ANTHROPIC_API_KEY` is set in `.env` |
| `spacy` model not found | Run `python -m spacy download en_core_web_sm`. Agent falls back to basic keyword counting if unavailable. |
| Budget ceiling hit | Check `data/budget.json`. Resets automatically each day, or delete the file to reset immediately. |
| `ModuleNotFoundError` on langchain | Run `pip install -r requirements.txt` inside your active venv |

---

## Run Modes

```bash
python agent.py --mode daily          # Full daily pipeline
python agent.py --mode dry-run        # Mock data — no network calls, no API spend
python agent.py --mode analyze-only   # Skip scraping, reanalyse existing DB data
python agent.py --mode scrape-only    # Collect and persist only, skip LLM analysis
python agent.py --verbose             # Stream LangGraph reasoning to stdout
```

The original `main.py` pipeline still works alongside the agent:

```bash
python main.py --mode daily
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
| `emerging` | Just appearing — weak signal but worth watching |
| `accelerating` | Growing rapidly — act now |
| `peaking` | At maximum popularity — time is short |
| `declining` | Losing steam — don't invest |

---

## Configuration

All settings in `config.yaml`. No code changes needed to tune behaviour.

```yaml
budget:
  daily_ceiling_cents: 200    # $2 hard stop
  daily_target_cents: 200     # $2 target

scrapers:
  daily_target_reels: 75      # Reels to collect per day

analysis:
  tier2:
    model: "claude-sonnet-4-6"     # Analysis model — change here to adjust quality/cost
    top_reels_to_analyze: 15       # Reels sent to LLM
    historical_context_days: 7     # Days of trend memory fed into each prompt
  virality_weights:
    engagement_velocity: 0.40
    audio_reuse_count: 0.30
    hashtag_trend_score: 0.30
```

### Model options

| Model | Quality | Est. cost/day |
|---|---|---|
| `claude-haiku-4-5-20251001` | Good | ~$0.01 |
| `claude-sonnet-4-6` *(default)* | Medium-high | ~$0.07–0.10 |
| `claude-opus-4-6` | Highest | ~$0.50+ |

---

## How the Agent Gets Smarter Over Time

- **`data/monitored_accounts.json`** — Grows automatically as the agent discovers accounts appearing repeatedly in high-velocity posts
- **`data/hashtag_clusters.json`** — Updated daily with new hashtag co-occurrence patterns using exponential moving average
- **`outputs/trend_log.csv`** — Fed back into each day's LLM prompt as historical context so the model can detect acceleration and decline across days
- **Virality weights** — Tunable in `config.yaml` as you learn which signals matter most for your niche

---

## Cost Breakdown

| Component | Method | Daily Cost |
|-----------|--------|------------|
| Scraping | Instaloader (free) | $0.00 |
| Scraping boost | Apify free tier | $0.00 |
| Scraping overflow | RapidAPI free tier | $0.00 |
| LLM Analysis | Claude Sonnet | **~$0.07–0.10** |
| **Total** | | **~$0.07–0.10/day** |
| *Hard ceiling* | *Configurable in config.yaml* | *$2.00/day* |

---

## V2 Roadmap

**CSV-driven account targeting**

In V2, you will be able to drop a CSV of example accounts into the project and the agent will use them as the primary scraping targets rather than (or in addition to) hashtag-based discovery.

Planned interface:

```bash
python agent.py --mode daily --accounts my_accounts.csv
```

Where `my_accounts.csv` contains one account per row with optional metadata:

```
username,reason,priority
defected,top UK house label,high
toolroom,underground techno,high
beatport,broad discovery,medium
```

The agent would scrape these accounts directly via `instaloader_scraper.scrape_account()`, weight their reels in virality scoring by priority, and surface them explicitly in the daily summary. This makes the tool useful for competitive monitoring, label tracking, or artist research — not just hashtag discovery.
