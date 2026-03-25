# Instagram Reels Music Trend Intelligence Agent

An autonomous agent that monitors Instagram Reels every 2 hours across the music/DJ/concert/production space and outputs actionable trend intelligence as structured CSV reports.

**Daily cost: ~$1.80** (12 runs × ~$0.15/run — Sonnet analysis; scraping is free)

---

## Setup

```bash
# 1. Clone
git clone https://github.com/alecwaj/Trend-agent.git
cd Trend-agent/instagram-trend-agent

# 2. Environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. API keys
cp .env.example .env
# Open .env — set ANTHROPIC_API_KEY (required). Apify/RapidAPI are optional.

# 4. Test — full pipeline, mock data, no API spend
python agent.py --mode dry-run --verbose

# 5. Run for real
python agent.py --mode daily

# 6. Schedule (every 2 hours)
chmod +x run_agent.sh
crontab -e
# Add: 0 */2 * * * /absolute/path/to/instagram-trend-agent/run_agent.sh
```

### Troubleshooting

| Problem | Fix |
|---|---|
| `ANTHROPIC_API_KEY` not set | Add it to `.env` — required for LLM analysis |
| `instaloader` returns 0 reels | Instagram rate-limited. Increase `sleep_between_requests` in `config.yaml`, or add Apify/RapidAPI keys |
| `ModuleNotFoundError: langchain` | Run `pip install -r requirements.txt` inside your active venv |
| `spacy` model not found | Run `python -m spacy download en_core_web_sm`. Agent falls back to basic keyword counting if absent |
| Budget ceiling hit mid-day | Expected — $2 hard ceiling across 12 runs. Check `data/budget.json`, resets automatically at midnight |

---

## What It Does

Every 2 hours the agent:

1. Scrapes **~40 fresh Instagram Reels** across DJ, concert, and music production hashtags
2. Runs **zero-cost local analysis** (engagement velocity, audio tracking, hashtag co-occurrence)
3. Sends the **top 25 highest-signal reels** to Claude Sonnet for deep trend analysis
4. Outputs a **dated trend CSV** + **running cumulative log** + **markdown brief**
5. Auto-discovers and tracks high-performing accounts over time

Running 12 times a day means the agent catches trends as they emerge across time zones — not just what was trending at 6am.

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
    ├── Tool: deduplicate_and_persist    SQLite dedup — each run sees only fresh reels
    │
    ├── Tool: analyze_trends_with_llm   claude-sonnet-4-6, Pydantic structured output
    │                                    top 25 reels, 14 days historical context
    │                                    ~$0.15/run
    │
    └── Tool: write_trend_outputs
            ├── csv_writer.py            Daily + cumulative CSV files
            └── summary_writer.py        Markdown brief
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

## Run Modes

```bash
python agent.py --mode daily          # Full run (default)
python agent.py --mode dry-run        # Mock data — no network calls, no API spend
python agent.py --mode analyze-only   # Skip scraping, reanalyse existing DB data
python agent.py --mode scrape-only    # Collect and persist only, skip LLM analysis
python agent.py --verbose             # Stream LangGraph reasoning to stdout
```

The original `main.py` pipeline still works independently:

```bash
python main.py --mode daily
```

---

## Configuration

All settings in `config.yaml` — no code changes needed.

```yaml
budget:
  daily_ceiling_cents: 200    # $2 hard stop — safe to run every 2 hours

scrapers:
  daily_target_reels: 40      # Per-run target (right-sized for 2-hour fresh window)

analysis:
  tier2:
    model: "claude-sonnet-4-6"
    top_reels_to_analyze: 25       # Reels sent to LLM per run
    max_input_tokens: 15000        # Rich context per analysis
    max_output_tokens: 5000        # Detailed trend output
    historical_context_days: 14    # Two weeks of trend memory per prompt
  virality_weights:
    engagement_velocity: 0.40
    audio_reuse_count: 0.30
    hashtag_trend_score: 0.30
```

### Cost vs quality tradeoff

| Model | Quality | Est. cost/run | Runs/day at $2 |
|---|---|---|---|
| `claude-haiku-4-5-20251001` | Good | ~$0.01 | 200 (overkill) |
| `claude-sonnet-4-6` *(default)* | Medium-high | ~$0.15 | 12 (every 2 hrs) |
| `claude-opus-4-6` | Highest | ~$0.80+ | 2 (morning + evening) |

---

## How the Agent Gets Smarter Over Time

- **`data/monitored_accounts.json`** — Grows automatically as the agent discovers accounts appearing repeatedly in high-velocity posts
- **`data/hashtag_clusters.json`** — Updated each run with new co-occurrence patterns using exponential moving average
- **`outputs/trend_log.csv`** — 14 days of trend history fed back into every LLM prompt — the model can see what's accelerating, peaking, and dying across the full two-week window
- **SQLite deduplication** — Each run only analyzes reels it hasn't seen before, so 12 daily runs produce 12 independent fresh-signal analyses rather than 12 analyses of the same data

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
