"""
RapidAPI Instagram Scraper — Freemium API-based scraping.
Free tier: ~500 requests/month (~16/day).

Priority: TERTIARY (fallback when Apify daily quota used)
"""

import logging
import re
from datetime import datetime
from typing import List, Optional

import requests

from scrapers import ReelData

logger = logging.getLogger(__name__)


class RapidAPIScraper:
    """
    Uses RapidAPI Instagram endpoints to collect Reels metadata.
    Multiple endpoint options for resilience.
    """

    def __init__(self, config: dict, api_key: str):
        self.config = config
        self.api_key = api_key
        self.host = config.get("host", "instagram-scraper-api2.p.rapidapi.com")
        self.results_per_request = config.get("results_per_request", 12)
        self.last_cost_cents = 0
        self.headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": self.host,
        }

    def _is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def scrape(self, keywords: List[str], max_results: int = 50) -> List[ReelData]:
        """
        Scrape reels for given hashtags via RapidAPI.

        Args:
            keywords: List of hashtags (without #)
            max_results: Max reels to return

        Returns:
            List of ReelData objects
        """
        if not self._is_configured():
            logger.info("RapidAPI key not configured, skipping")
            return []

        all_reels = []
        per_hashtag = max(5, max_results // max(len(keywords), 1))

        for hashtag in keywords:
            if len(all_reels) >= max_results:
                break

            reels = self._scrape_hashtag(hashtag, per_hashtag)
            all_reels.extend(reels)
            logger.debug(f"RapidAPI #{hashtag}: {len(reels)} reels")

        return all_reels[:max_results]

    def _scrape_hashtag(self, hashtag: str, limit: int) -> List[ReelData]:
        """Fetch top reels for a hashtag via RapidAPI."""
        url = f"https://{self.host}/v1/hashtag"
        params = {"hashtag": hashtag}

        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=30)

            if resp.status_code == 429:
                logger.warning("RapidAPI rate limit hit")
                return []
            elif resp.status_code == 403:
                logger.warning("RapidAPI authentication failed — check API key")
                return []

            resp.raise_for_status()
            data = resp.json()

            # Parse the response structure (varies by API version)
            items = self._extract_items(data)
            reels = []

            for item in items[:limit]:
                reel = self._item_to_reel_data(item, hashtag)
                if reel:
                    reels.append(reel)

            return reels

        except requests.RequestException as e:
            logger.warning(f"RapidAPI request failed for #{hashtag}: {e}")
            return []
        except Exception as e:
            logger.error(f"RapidAPI unexpected error for #{hashtag}: {e}")
            return []

    def _extract_items(self, data: dict) -> list:
        """Extract media items from API response (handles different response formats)."""
        # Try multiple known response structures
        for path in [
            ["data", "items"],
            ["data", "top", "sections"],
            ["data", "medias"],
            ["items"],
            ["medias"],
        ]:
            result = data
            for key in path:
                if isinstance(result, dict):
                    result = result.get(key, {})
                else:
                    result = None
                    break
            if result and isinstance(result, list):
                return result

        # Flatten section-based results
        if "data" in data and isinstance(data["data"], dict):
            sections = data["data"].get("top", {}).get("sections", [])
            items = []
            for section in sections:
                layout_content = section.get("layout_content", {})
                medias = layout_content.get("medias", [])
                for media in medias:
                    if isinstance(media, dict) and "media" in media:
                        items.append(media["media"])
            return items

        return []

    def _item_to_reel_data(self, item: dict, hashtag: str) -> Optional[ReelData]:
        """Convert a RapidAPI item to ReelData."""
        try:
            # RapidAPI response varies; handle both nested and flat structures
            if "media" in item:
                item = item["media"]

            media_type = item.get("media_type", 0)
            # Only process video content (type 2 = video)
            if media_type not in (2, "VIDEO"):
                return None

            # Timestamps
            taken_at = item.get("taken_at") or item.get("timestamp", 0)
            if isinstance(taken_at, (int, float)) and taken_at > 0:
                posted_at = datetime.utcfromtimestamp(taken_at)
            else:
                posted_at = datetime.utcnow()

            # Caption and hashtags
            caption_data = item.get("caption") or {}
            if isinstance(caption_data, dict):
                caption = caption_data.get("text", "")
            else:
                caption = str(caption_data or "")

            hashtags = re.findall(r"#(\w+)", caption.lower())
            if hashtag not in hashtags:
                hashtags.insert(0, hashtag)

            # Owner info
            owner = item.get("user") or item.get("owner") or {}
            username = owner.get("username", "")
            followers = owner.get("follower_count", 0) or 0

            # Audio
            clips_meta = item.get("clips_metadata", {}) or {}
            music_info = clips_meta.get("music_info", {}) or item.get("music_metadata", {}) or {}
            music_track = music_info.get("music_asset_info", {}) or {}
            audio_name = music_track.get("title") or clips_meta.get("original_sound_info", {}).get("original_audio_title")
            audio_artist = music_track.get("display_artist")

            # IDs
            pk = str(item.get("pk") or item.get("id", ""))
            code = item.get("code") or pk

            # Metrics
            like_count = item.get("like_count", 0) or 0
            comment_count = item.get("comment_count", 0) or 0
            play_count = item.get("play_count") or item.get("video_view_count", 0) or 0

            return ReelData(
                reel_id=pk,
                shortcode=str(code),
                url=f"https://www.instagram.com/p/{code}/",
                username=username,
                follower_count=int(followers),
                caption=str(caption)[:1000],
                hashtags=hashtags,
                likes=int(like_count),
                comments=int(comment_count),
                views=int(play_count),
                posted_at=posted_at,
                audio_name=audio_name,
                audio_artist=audio_artist,
                duration_seconds=item.get("video_duration"),
                source="rapidapi",
                raw_metadata={"media_type": media_type},
            )
        except Exception as e:
            logger.debug(f"Failed to parse RapidAPI item: {e}")
            return None
