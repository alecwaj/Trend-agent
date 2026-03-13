"""
Apify Scraper — Cloud-based Instagram scraping via Apify platform.
Free tier: 30 actor runs/month (~1/day).

Priority: SECONDARY (free quota, higher reliability than instaloader)
"""

import logging
import time
from datetime import datetime
from typing import List, Optional

import requests

from scrapers import ReelData

logger = logging.getLogger(__name__)


class ApifyScraper:
    """
    Uses Apify's Instagram scraper actor to collect Reels data.
    Handles the free tier (30 runs/month) automatically.
    """

    BASE_URL = "https://api.apify.com/v2"

    def __init__(self, config: dict, api_key: str):
        self.config = config
        self.api_key = api_key
        self.actor_id = config.get("actor_id", "apify/instagram-scraper")
        self.results_per_run = config.get("results_per_run", 50)
        self.timeout_seconds = config.get("timeout_seconds", 300)
        self.last_cost_cents = 0

    def _is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def scrape(self, keywords: List[str], max_results: int = 50) -> List[ReelData]:
        """
        Run Apify Instagram scraper actor for given hashtags.

        Args:
            keywords: List of hashtags (without #)
            max_results: Max reels to collect

        Returns:
            List of ReelData objects
        """
        if not self._is_configured():
            logger.info("Apify API key not configured, skipping")
            return []

        # Build input for the Apify Instagram scraper actor
        actor_input = {
            "hashtags": [f"#{kw}" for kw in keywords[:10]],  # Limit hashtags per run
            "resultsLimit": min(max_results, self.results_per_run),
            "scrapeType": "reels",
            "addParentData": True,
        }

        try:
            run_id = self._start_actor_run(actor_input)
            if not run_id:
                return []

            # Wait for run to complete
            success = self._wait_for_run(run_id)
            if not success:
                return []

            # Fetch results
            items = self._get_run_results(run_id)
            reels = [self._item_to_reel_data(item) for item in items]
            reels = [r for r in reels if r is not None]
            logger.info(f"Apify returned {len(reels)} reels")
            return reels

        except Exception as e:
            logger.error(f"Apify scraper failed: {e}")
            return []

    def _start_actor_run(self, actor_input: dict) -> Optional[str]:
        """Start an Apify actor run and return the run ID."""
        url = f"{self.BASE_URL}/acts/{self.actor_id}/runs"
        params = {"token": self.api_key}

        try:
            resp = requests.post(url, json=actor_input, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            run_id = data.get("data", {}).get("id")
            logger.info(f"Started Apify run: {run_id}")
            return run_id
        except requests.RequestException as e:
            logger.error(f"Failed to start Apify actor: {e}")
            return None

    def _wait_for_run(self, run_id: str) -> bool:
        """Poll until the Apify run completes or times out."""
        url = f"{self.BASE_URL}/actor-runs/{run_id}"
        params = {"token": self.api_key}
        deadline = time.time() + self.timeout_seconds

        while time.time() < deadline:
            try:
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                status = resp.json().get("data", {}).get("status", "")

                if status == "SUCCEEDED":
                    logger.info(f"Apify run {run_id} succeeded")
                    return True
                elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
                    logger.error(f"Apify run {run_id} ended with status: {status}")
                    return False

                logger.debug(f"Apify run status: {status}, waiting...")
                time.sleep(10)

            except requests.RequestException as e:
                logger.warning(f"Error polling Apify run: {e}")
                time.sleep(15)

        logger.error(f"Apify run {run_id} timed out after {self.timeout_seconds}s")
        return False

    def _get_run_results(self, run_id: str) -> list:
        """Fetch the output dataset from a completed run."""
        url = f"{self.BASE_URL}/actor-runs/{run_id}/dataset/items"
        params = {"token": self.api_key, "format": "json"}

        try:
            resp = requests.get(url, params=params, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch Apify results: {e}")
            return []

    def _item_to_reel_data(self, item: dict) -> Optional[ReelData]:
        """Convert an Apify result item to ReelData."""
        try:
            # Apify Instagram scraper output format
            timestamp = item.get("timestamp") or item.get("takenAtTimestamp")
            if isinstance(timestamp, (int, float)):
                posted_at = datetime.utcfromtimestamp(timestamp)
            elif isinstance(timestamp, str):
                posted_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).replace(tzinfo=None)
            else:
                posted_at = datetime.utcnow()

            hashtags = item.get("hashtags", [])
            if isinstance(hashtags, list) and hashtags and isinstance(hashtags[0], dict):
                hashtags = [h.get("name", "") for h in hashtags]

            caption = item.get("caption", "") or ""

            owner = item.get("ownerUsername", "") or item.get("username", "")
            followers = item.get("ownerFollowersCount", 0) or item.get("followersCount", 0) or 0

            music = item.get("musicInfo", {}) or {}
            audio_name = music.get("songName") or item.get("audioTrack", {}).get("title")
            audio_artist = music.get("artistName") or item.get("audioTrack", {}).get("subtitle")

            shortcode = item.get("shortCode") or item.get("id", "")
            reel_id = item.get("id") or shortcode

            return ReelData(
                reel_id=str(reel_id),
                shortcode=str(shortcode),
                url=item.get("url", f"https://www.instagram.com/p/{shortcode}/"),
                username=owner,
                follower_count=int(followers),
                caption=str(caption)[:1000],
                hashtags=hashtags,
                likes=item.get("likesCount", 0) or 0,
                comments=item.get("commentsCount", 0) or 0,
                views=item.get("videoViewCount", 0) or item.get("playCount", 0) or 0,
                posted_at=posted_at,
                audio_name=audio_name,
                audio_artist=audio_artist,
                duration_seconds=item.get("videoDuration"),
                source="apify",
                raw_metadata={"type": item.get("type"), "productType": item.get("productType")},
            )
        except Exception as e:
            logger.debug(f"Failed to parse Apify item: {e}")
            return None
