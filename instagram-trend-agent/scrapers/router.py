"""
Scraper Router — Smart source rotation and budget tracking.

Rotates between scraper sources to stay within free tiers.
Falls back gracefully if a source is rate-limited or unavailable.
"""

import json
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from scrapers import ReelData

logger = logging.getLogger(__name__)


class ScraperRouter:
    """
    Routes scraping requests across multiple sources, tracking
    daily usage per source and respecting budget/quota limits.
    """

    def __init__(self, config: dict, data_dir: str = "data/"):
        self.config = config
        self.data_dir = Path(data_dir)
        self.budget_file = self.data_dir / "budget.json"
        self.usage_file = self.data_dir / "scraper_usage.json"
        self.scrapers = {}
        self._load_usage()
        self._init_scrapers()

    def _init_scrapers(self):
        """Lazy-initialize scrapers based on config."""
        scraper_config = self.config.get("scrapers", {})
        priority = scraper_config.get("source_priority", [])

        for source_name in priority:
            source_cfg = scraper_config.get(source_name, {})
            if not source_cfg.get("enabled", True):
                logger.info(f"Scraper {source_name} disabled in config, skipping.")
                continue

            try:
                if source_name == "instaloader":
                    from scrapers.instaloader_scraper import InstaLoaderScraper
                    self.scrapers[source_name] = InstaLoaderScraper(source_cfg)
                elif source_name == "apify":
                    from scrapers.apify_scraper import ApifyScraper
                    api_key = (
                        self.config.get("api_keys", {}).get("apify", "")
                        or __import__("os").environ.get("APIFY_API_KEY", "")
                    )
                    self.scrapers[source_name] = ApifyScraper(source_cfg, api_key)
                elif source_name == "rapidapi":
                    from scrapers.rapidapi_scraper import RapidAPIScraper
                    api_key = (
                        self.config.get("api_keys", {}).get("rapidapi", "")
                        or __import__("os").environ.get("RAPIDAPI_KEY", "")
                    )
                    self.scrapers[source_name] = RapidAPIScraper(source_cfg, api_key)
                elif source_name == "google_fallback":
                    from scrapers.google_fallback import GoogleFallbackScraper
                    self.scrapers[source_name] = GoogleFallbackScraper(source_cfg)
                logger.info(f"Initialized scraper: {source_name}")
            except Exception as e:
                logger.warning(f"Failed to initialize scraper {source_name}: {e}")

    def _load_usage(self):
        """Load today's usage stats from disk."""
        today = str(date.today())
        if self.usage_file.exists():
            with open(self.usage_file) as f:
                all_usage = json.load(f)
            self.usage = all_usage.get(today, {})
        else:
            self.usage = {}
        self.usage_date = today

    def _save_usage(self):
        """Persist today's usage stats."""
        today = str(date.today())
        if self.usage_file.exists():
            with open(self.usage_file) as f:
                all_usage = json.load(f)
        else:
            all_usage = {}

        all_usage[today] = self.usage
        # Keep only last 30 days
        cutoff = sorted(all_usage.keys())[-30:]
        all_usage = {k: all_usage[k] for k in cutoff}

        self.usage_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.usage_file, "w") as f:
            json.dump(all_usage, f, indent=2)

    def _get_source_usage(self, source_name: str) -> dict:
        """Get today's usage for a source."""
        if str(date.today()) != self.usage_date:
            # Day rolled over, reset usage
            self.usage = {}
            self.usage_date = str(date.today())
        return self.usage.get(source_name, {"requests": 0, "reels": 0, "errors": 0, "cost_cents": 0})

    def _update_source_usage(self, source_name: str, reels: int, cost_cents: int, errors: int = 0):
        """Update usage counter for a source."""
        current = self._get_source_usage(source_name)
        self.usage[source_name] = {
            "requests": current["requests"] + 1,
            "reels": current["reels"] + reels,
            "errors": current["errors"] + errors,
            "cost_cents": current["cost_cents"] + cost_cents,
        }
        self._save_usage()

    def _can_use_source(self, source_name: str) -> bool:
        """Check if a source still has quota remaining for today."""
        scraper_config = self.config.get("scrapers", {})
        source_cfg = scraper_config.get(source_name, {})
        usage = self._get_source_usage(source_name)

        # Check monthly quotas (approximate as daily fractions)
        if source_name == "apify":
            monthly_free = source_cfg.get("free_runs_per_month", 30)
            # Track monthly separately
            if usage["requests"] >= max(1, monthly_free // 30):
                logger.info(f"Apify daily quota reached ({usage['requests']} runs today)")
                return False

        if source_name == "rapidapi":
            monthly_free = source_cfg.get("free_requests_per_month", 500)
            daily_budget = max(1, monthly_free // 30)
            if usage["requests"] >= daily_budget:
                logger.info(f"RapidAPI daily quota reached ({usage['requests']} requests today)")
                return False

        if source_name == "google_fallback":
            daily_limit = source_cfg.get("requests_per_day", 100)
            if usage["requests"] >= daily_limit:
                logger.info(f"Google fallback daily quota reached")
                return False

        # Check if too many errors (source may be blocked)
        if usage["errors"] >= 5:
            logger.warning(f"Source {source_name} has {usage['errors']} errors today, skipping")
            return False

        return True

    def scrape_all(self, hashtags: List[str], max_total: int = 75) -> List[ReelData]:
        """
        Main entry point. Scrapes hashtags across available sources,
        rotating to stay within free tiers. Returns deduplicated ReelData list.
        """
        all_reels = []
        remaining = max_total
        priority = self.config.get("scrapers", {}).get("source_priority", [])

        for source_name in priority:
            if remaining <= 0:
                break

            if source_name not in self.scrapers:
                continue

            if not self._can_use_source(source_name):
                logger.info(f"Skipping {source_name} — quota exhausted or too many errors")
                continue

            scraper = self.scrapers[source_name]
            logger.info(f"Using scraper: {source_name} (need {remaining} more reels)")

            try:
                reels = scraper.scrape(hashtags, max_results=min(remaining + 20, 50))
                cost_cents = getattr(scraper, "last_cost_cents", 0)
                self._update_source_usage(source_name, len(reels), cost_cents)
                all_reels.extend(reels)
                remaining -= len(reels)
                logger.info(f"Got {len(reels)} reels from {source_name}")

                if len(reels) > 0:
                    # Give primary source time to avoid hammering
                    time.sleep(2)

            except Exception as e:
                logger.error(f"Scraper {source_name} failed: {e}")
                self._update_source_usage(source_name, 0, 0, errors=1)
                continue

        # Deduplicate by reel_id
        seen = set()
        unique_reels = []
        for reel in all_reels:
            if reel.reel_id not in seen:
                seen.add(reel.reel_id)
                unique_reels.append(reel)

        logger.info(f"Total unique reels collected: {len(unique_reels)}")
        return unique_reels

    def get_usage_summary(self) -> dict:
        """Return today's usage summary across all sources."""
        return {
            "date": self.usage_date,
            "sources": self.usage,
            "total_reels": sum(v.get("reels", 0) for v in self.usage.values()),
            "total_cost_cents": sum(v.get("cost_cents", 0) for v in self.usage.values()),
        }
