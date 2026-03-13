#!/usr/bin/env python3
"""
Instagram Reels Music Trend Intelligence Agent — Main Orchestrator

Usage:
    python main.py --mode daily          # Full daily run
    python main.py --mode dry-run        # Show what WOULD happen, no API calls
    python main.py --mode analyze-only   # Skip scraping, analyze existing DB data
    python main.py --mode scrape-only    # Scrape only, skip analysis
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Dict

import yaml

# ──────────────────────────────────────────────────────────────
# Logging setup (before anything else)
# ──────────────────────────────────────────────────────────────

def setup_logging(config: dict, log_dir: str = "logs/") -> logging.Logger:
    """Configure logging to both console and daily log file."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_dir) / f"{date.today()}.log"

    log_cfg = config.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO"))
    fmt = log_cfg.get("log_format", "%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    logging.basicConfig(
        level=level,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    return logging.getLogger("trend_agent")


# ──────────────────────────────────────────────────────────────
# Configuration loading
# ──────────────────────────────────────────────────────────────

def load_config(config_path: str = "config.yaml") -> dict:
    """Load YAML configuration, override API keys from environment."""
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Environment variable overrides
    env_keys = {
        "anthropic": "ANTHROPIC_API_KEY",
        "apify": "APIFY_API_KEY",
        "rapidapi": "RAPIDAPI_KEY",
    }
    for key_name, env_var in env_keys.items():
        env_val = os.environ.get(env_var, "")
        if env_val:
            config.setdefault("api_keys", {})[key_name] = env_val

    return config


# ──────────────────────────────────────────────────────────────
# Budget tracker
# ──────────────────────────────────────────────────────────────

class BudgetTracker:
    """Tracks daily API spending and enforces hard ceiling."""

    def __init__(self, config: dict, data_dir: str = "data/"):
        self.config = config
        self.budget_file = Path(data_dir) / "budget.json"
        self.daily_ceiling = config.get("budget", {}).get("daily_ceiling_cents", 500)
        self.data = self._load()

    def _load(self) -> dict:
        today = str(date.today())
        if self.budget_file.exists():
            try:
                with open(self.budget_file) as f:
                    data = json.load(f)
                # Reset if new day
                if data.get("date") != today:
                    data = self._fresh(today)
            except (json.JSONDecodeError, IOError):
                data = self._fresh(today)
        else:
            data = self._fresh(today)
        return data

    def _fresh(self, today: str) -> dict:
        return {
            "date": today,
            "total_cost_cents_today": 0,
            "llm_calls_today": 0,
            "llm_cost_cents_today": 0,
            "scraper_cost_cents_today": 0,
            "events": [],
        }

    def save(self):
        self.budget_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.budget_file, "w") as f:
            json.dump(self.data, f, indent=2)

    def can_spend(self, estimated_cents: int) -> bool:
        return (self.data["total_cost_cents_today"] + estimated_cents) <= self.daily_ceiling

    def record(self, component: str, cost_cents: int, description: str = ""):
        self.data["total_cost_cents_today"] += cost_cents
        if "llm" in component.lower():
            self.data["llm_calls_today"] += 1
            self.data["llm_cost_cents_today"] += cost_cents
        else:
            self.data["scraper_cost_cents_today"] += cost_cents

        self.data["events"].append({
            "time": datetime.utcnow().isoformat(),
            "component": component,
            "cost_cents": cost_cents,
            "description": description,
        })
        self.save()

    def summary(self) -> dict:
        return {
            k: v for k, v in self.data.items() if k != "events"
        }

    def remaining_cents(self) -> int:
        return max(0, self.daily_ceiling - self.data["total_cost_cents_today"])


# ──────────────────────────────────────────────────────────────
# SQLite deduplication database
# ──────────────────────────────────────────────────────────────

class ReelsDatabase:
    """SQLite store for raw reel data — deduplication and historical lookups."""

    def __init__(self, db_path: str = "data/reels_raw.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self._init_schema()

    def _init_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS reels (
                reel_id TEXT PRIMARY KEY,
                shortcode TEXT,
                url TEXT,
                username TEXT,
                follower_count INTEGER,
                caption TEXT,
                hashtags TEXT,
                likes INTEGER,
                comments INTEGER,
                views INTEGER,
                posted_at TEXT,
                audio_name TEXT,
                audio_artist TEXT,
                duration_seconds REAL,
                source TEXT,
                scraped_at TEXT,
                virality_score REAL,
                engagement_velocity REAL
            )
        """)
        self.conn.commit()

    def filter_new(self, reels) -> list:
        """Return only reels not already in the database."""
        if not reels:
            return []
        placeholders = ",".join("?" * len(reels))
        ids = [r.reel_id for r in reels]
        cursor = self.conn.execute(
            f"SELECT reel_id FROM reels WHERE reel_id IN ({placeholders})", ids
        )
        existing_ids = {row[0] for row in cursor.fetchall()}
        return [r for r in reels if r.reel_id not in existing_ids]

    def insert_reels(self, reels, scored_map: dict = None):
        """Insert reels into the database."""
        scored_map = scored_map or {}
        rows = []
        for reel in reels:
            score_data = scored_map.get(reel.reel_id, {})
            rows.append((
                reel.reel_id,
                reel.shortcode,
                reel.url,
                reel.username,
                reel.follower_count,
                reel.caption,
                "|".join(reel.hashtags),
                reel.likes,
                reel.comments,
                reel.views,
                reel.posted_at.isoformat(),
                reel.audio_name,
                reel.audio_artist,
                reel.duration_seconds,
                reel.source,
                reel.scraped_at.isoformat(),
                score_data.get("virality_score"),
                score_data.get("engagement_velocity"),
            ))

        self.conn.executemany(
            """INSERT OR IGNORE INTO reels VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows
        )
        self.conn.commit()
        return len(rows)

    def get_recent_reels(self, days: int = 1) -> list:
        """Retrieve reels scraped in the last N days."""
        from scrapers import ReelData
        cutoff = datetime.utcnow().replace(hour=0, minute=0, second=0).isoformat()
        cursor = self.conn.execute(
            "SELECT * FROM reels WHERE scraped_at >= ? ORDER BY virality_score DESC",
            (cutoff,)
        )
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description]

        reels = []
        for row in rows:
            r = dict(zip(cols, row))
            try:
                reels.append(ReelData(
                    reel_id=r["reel_id"],
                    shortcode=r["shortcode"] or "",
                    url=r["url"] or "",
                    username=r["username"] or "",
                    follower_count=r["follower_count"] or 0,
                    caption=r["caption"] or "",
                    hashtags=(r["hashtags"] or "").split("|"),
                    likes=r["likes"] or 0,
                    comments=r["comments"] or 0,
                    views=r["views"] or 0,
                    posted_at=datetime.fromisoformat(r["posted_at"]),
                    audio_name=r["audio_name"],
                    audio_artist=r["audio_artist"],
                    duration_seconds=r["duration_seconds"],
                    source=r["source"] or "",
                ))
            except Exception:
                continue
        return reels

    def close(self):
        self.conn.close()


# ──────────────────────────────────────────────────────────────
# Account discovery
# ──────────────────────────────────────────────────────────────

def update_monitored_accounts(reels, config: dict, data_dir: str = "data/"):
    """
    Auto-discover high-quality accounts from scraped reels and
    add them to monitored_accounts.json if they meet thresholds.
    """
    accounts_file = Path(data_dir) / "monitored_accounts.json"

    # Load existing
    if accounts_file.exists():
        with open(accounts_file) as f:
            monitored = json.load(f)
    else:
        monitored = {"accounts": [], "last_updated": "", "auto_discovered": []}

    existing_usernames = {a["username"] for a in monitored.get("accounts", [])}
    existing_auto = {a["username"] for a in monitored.get("auto_discovered", [])}

    disc_cfg = config.get("account_discovery", {})
    min_followers = disc_cfg.get("min_followers", 10000)
    max_monitored = disc_cfg.get("max_monitored_accounts", 200)

    # Count appearances per account in today's high-velocity reels
    from collections import Counter
    appearance_count = Counter()
    account_info = {}
    for reel in reels:
        vel = reel.engagement_velocity()
        if vel > 10 and reel.follower_count >= min_followers:
            appearance_count[reel.username] += 1
            account_info[reel.username] = {
                "username": reel.username,
                "follower_count": reel.follower_count,
                "discovered_date": str(date.today()),
                "discovery_source": "auto_hashtag_scrape",
            }

    min_appearances = disc_cfg.get("min_appearances_to_add", 3)
    newly_added = 0

    for username, count in appearance_count.most_common():
        if count >= min_appearances and username not in existing_usernames and username not in existing_auto:
            if len(monitored.get("auto_discovered", [])) < max_monitored:
                monitored.setdefault("auto_discovered", []).append(account_info[username])
                newly_added += 1

    if newly_added > 0:
        monitored["last_updated"] = datetime.utcnow().isoformat()
        with open(accounts_file, "w") as f:
            json.dump(monitored, f, indent=2)
        logging.getLogger("trend_agent").info(f"Auto-discovered {newly_added} new accounts")


# ──────────────────────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────────────────────

def run_pipeline(config: dict, mode: str = "daily", logger: logging.Logger = None):
    """Execute the full daily pipeline."""
    if logger is None:
        logger = logging.getLogger("trend_agent")

    data_dir = config.get("output", {}).get("data_directory", "data/")
    output_dir = config.get("output", {}).get("csv_directory", "outputs/")
    dry_run = (mode == "dry-run")

    logger.info(f"=== Instagram Reels Trend Agent — Mode: {mode} ===")

    # Initialize components
    budget = BudgetTracker(config, data_dir)
    db = ReelsDatabase(db_path=f"{data_dir}reels_raw.db")

    # ── Step 1: Budget check ──────────────────────────────────
    if not budget.can_spend(10):  # 10 cents minimum to continue
        logger.error(f"Daily budget ceiling hit (${budget.daily_ceiling/100:.2f}). Aborting.")
        return False

    logger.info(f"Budget: ${budget.data['total_cost_cents_today']/100:.3f} spent today, "
                f"${budget.remaining_cents()/100:.2f} remaining")

    # ── Step 2: Scraping ─────────────────────────────────────
    raw_reels = []
    if mode in ("daily", "dry-run", "scrape-only"):
        if dry_run:
            logger.info("[DRY RUN] Would scrape Instagram for music reels")
            raw_reels = _generate_mock_reels()
        else:
            logger.info("Starting scrape pipeline...")
            from scrapers.router import ScraperRouter
            router = ScraperRouter(config, data_dir)

            # Build flat hashtag list from config
            hashtag_clusters = config.get("hashtags", {})
            all_hashtags = []
            for cluster in hashtag_clusters.values():
                all_hashtags.extend(cluster)
            # Deduplicate and shuffle for variety
            all_hashtags = list(dict.fromkeys(all_hashtags))

            target = config.get("scrapers", {}).get("daily_target_reels", 75)
            raw_reels = router.scrape_all(all_hashtags, max_total=target)
            scraper_summary = router.get_usage_summary()
            budget.record("scraper", scraper_summary.get("total_cost_cents", 0), "Daily scrape")

    if not raw_reels:
        logger.warning("No reels collected. Checking DB for today's data...")
        raw_reels = db.get_recent_reels(days=1)

    if not raw_reels:
        min_acceptable = config.get("scrapers", {}).get("min_reels_acceptable", 20)
        logger.error(f"Collected 0 reels (minimum: {min_acceptable}). Cannot proceed with analysis.")
        return False

    logger.info(f"Collected {len(raw_reels)} raw reels")

    # ── Step 3: Deduplication ────────────────────────────────
    if not dry_run and mode != "analyze-only":
        new_reels = db.filter_new(raw_reels)
        logger.info(f"New reels (not in DB): {len(new_reels)} / {len(raw_reels)}")
        reels_to_analyze = new_reels if new_reels else raw_reels
    else:
        reels_to_analyze = raw_reels

    # ── Step 4: Tier 1 local analysis ───────────────────────
    logger.info("Running Tier 1 local analysis...")
    from analysis.tier1_local import Tier1Analyzer
    from analysis.virality_scorer import ViralityScorer

    tier1 = Tier1Analyzer(config, data_dir)
    tier1_results = tier1.analyze(reels_to_analyze)

    scorer = ViralityScorer(config)
    scored_reels = scorer.score_batch(reels_to_analyze)

    logger.info(f"Tier 1 complete. Top virality score: {scored_reels[0]['virality_score'] if scored_reels else 0}")

    # ── Step 5: Persist to DB ────────────────────────────────
    if not dry_run:
        scored_map = {item["reel"].reel_id: item for item in scored_reels}
        inserted = db.insert_reels(reels_to_analyze, scored_map)
        logger.info(f"Inserted {inserted} reels into DB")
        update_monitored_accounts(reels_to_analyze, config, data_dir)

    # ── Step 6: Tier 2 LLM analysis ─────────────────────────
    llm_analysis = None
    if mode not in ("scrape-only",) and budget.can_spend(5):  # ~$0.05 headroom
        logger.info("Running Tier 2 LLM analysis...")
        from analysis.tier2_llm import Tier2LLMAnalyzer
        from analysis.trend_tracker import TrendTracker

        tracker = TrendTracker(config, output_dir)
        historical_ctx = tracker.get_historical_context(
            days=config.get("analysis", {}).get("tier2", {}).get("historical_context_days", 7)
        )

        llm_analyzer = Tier2LLMAnalyzer(config)
        llm_analysis = llm_analyzer.analyze(
            scored_reels=scored_reels,
            tier1_results=tier1_results,
            historical_context=historical_ctx,
            dry_run=dry_run,
        )

        if llm_analysis:
            # Rough cost estimate: 5000 tokens input + 2000 output at Haiku pricing
            estimated_cost = 1  # ~$0.01 per batch call
            budget.record("llm_batch", estimated_cost, f"Daily LLM analysis — {len(llm_analysis.get('top_trends', []))} trends")
            logger.info(f"LLM identified {len(llm_analysis.get('top_trends', []))} trends")
        else:
            logger.warning("LLM analysis returned no results")
    else:
        logger.info("LLM analysis skipped (scrape-only mode or budget)")

    # ── Step 7: Generate outputs ─────────────────────────────
    logger.info("Generating output files...")
    from analysis.trend_tracker import TrendTracker
    from output.csv_writer import CSVWriter
    from output.summary_writer import SummaryWriter

    tracker = TrendTracker(config, output_dir)
    csv_writer = CSVWriter(config, output_dir)
    summary_writer = SummaryWriter(config, output_dir)

    if llm_analysis and llm_analysis.get("top_trends"):
        # Enrich trends with historical data
        enriched_trends = tracker.update(llm_analysis["top_trends"])
        csv_path = csv_writer.write_daily(enriched_trends, scored_reels)
    else:
        # Fallback: generate CSV from Tier 1 data
        logger.info("Using Tier 1 fallback for CSV generation")
        enriched_trends = []
        csv_path = csv_writer.write_fallback_csv(scored_reels, tier1_results)

    # Determine scraper summary
    try:
        scraper_summary
    except NameError:
        scraper_summary = {"sources": {}, "total_reels": len(raw_reels)}

    md_path = summary_writer.write(
        trends=enriched_trends,
        tier1_results=tier1_results,
        llm_analysis=llm_analysis,
        budget_summary=budget.summary(),
        scraper_summary=scraper_summary,
    )

    logger.info(f"Daily CSV: {csv_path}")
    logger.info(f"Summary: {md_path}")

    # ── Step 8: Final budget save ────────────────────────────
    budget.save()

    logger.info(
        f"=== Pipeline complete === "
        f"Reels: {len(reels_to_analyze)} | "
        f"Trends: {len(enriched_trends)} | "
        f"Cost: ${budget.data['total_cost_cents_today']/100:.3f}"
    )

    db.close()
    return True


def _generate_mock_reels():
    """Generate mock ReelData for dry-run testing."""
    from scrapers import ReelData
    from datetime import datetime, timedelta
    import random

    mock_data = [
        ("djbeats_pro", 125000, "Mixing it up tonight #djlife #djset #beatmatch #housemusic", ["djlife", "djset", "beatmatch", "housemusic"], "Blinding Lights (Remix)", "The Weeknd"),
        ("musicproducer_x", 89000, "New beat just dropped #musicproduction #beatmaking #flstudio #trap", ["musicproduction", "beatmaking", "flstudio", "trap"], "Custom Beat 808", None),
        ("festivalvibes", 234000, "What a night at Coachella! #festivalseason #edm #rave #concertvibes", ["festivalseason", "edm", "rave", "concertvibes"], "Levels", "Avicii"),
        ("synthwave_daily", 45000, "Analog warmth #synthesizer #producerlife #studiolife #synthwave", ["synthesizer", "producerlife", "studiolife", "synthwave"], "Midnight City", "M83"),
        ("turntablist_99", 67000, "Practice makes perfect #turntablism #scratching #djculture #hiphop", ["turntablism", "scratching", "djculture", "hiphop"], "Get Lucky (Scratch Edit)", "Daft Punk"),
        ("newmusic_daily", 189000, "This is going viral #newmusic #viralmusic #trending #musicdiscovery", ["newmusic", "viralmusic", "trending", "musicdiscovery"], "As It Was", "Harry Styles"),
        ("ableton_wizard", 56000, "Tutorial time: layering synths #ableton #musicproduction #synthesizer", ["ableton", "musicproduction", "synthesizer"], None, None),
        ("concertphotos", 312000, "Electric atmosphere! #livemusic #concertphotography #musicfestival", ["livemusic", "concertphotography", "musicfestival"], "Blinding Lights (Remix)", "The Weeknd"),
    ]

    reels = []
    for i, (username, followers, caption, hashtags, audio, artist) in enumerate(mock_data):
        hours_ago = random.uniform(1, 48)
        posted_at = datetime.utcnow() - timedelta(hours=hours_ago)
        reels.append(ReelData(
            reel_id=f"mock_{i:04d}",
            shortcode=f"MOCK{i:04d}",
            url=f"https://www.instagram.com/p/MOCK{i:04d}/",
            username=username,
            follower_count=followers,
            caption=caption,
            hashtags=hashtags,
            likes=random.randint(1000, 50000),
            comments=random.randint(50, 2000),
            views=random.randint(10000, 500000),
            posted_at=posted_at,
            audio_name=audio,
            audio_artist=artist,
            duration_seconds=random.choice([15, 30, 60]),
            source="mock",
        ))
    return reels


# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Instagram Reels Music Trend Intelligence Agent"
    )
    parser.add_argument(
        "--mode",
        choices=["daily", "dry-run", "analyze-only", "scrape-only"],
        default="daily",
        help="Run mode (default: daily)",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    args = parser.parse_args()

    # Change to script directory so relative paths work
    script_dir = Path(__file__).parent
    os.chdir(script_dir)

    try:
        config = load_config(args.config)
    except FileNotFoundError:
        print(f"ERROR: Config file not found: {args.config}")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"ERROR: Invalid config YAML: {e}")
        sys.exit(1)

    logger = setup_logging(config)

    if args.mode == "dry-run":
        logger.info("DRY RUN MODE: No real API calls will be made")

    success = run_pipeline(config, mode=args.mode, logger=logger)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
