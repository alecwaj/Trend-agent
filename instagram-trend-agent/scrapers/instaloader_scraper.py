"""
Instaloader Scraper — Free, open-source Instagram data collection.
No API key required. Rate-limited by Instagram naturally.

Priority: PRIMARY (free, no quota limits beyond Instagram's own rate limiting)
"""

import logging
import re
import time
from datetime import datetime, timezone
from typing import List, Optional

from scrapers import ReelData

logger = logging.getLogger(__name__)

try:
    import instaloader
    INSTALOADER_AVAILABLE = True
except ImportError:
    INSTALOADER_AVAILABLE = False
    logger.warning("instaloader not installed. Run: pip install instaloader")


class InstaLoaderScraper:
    """
    Scrapes Instagram Reels using the instaloader library.
    Focuses on hashtag-based discovery of music/DJ content.
    """

    def __init__(self, config: dict):
        self.config = config
        self.sleep_between = config.get("sleep_between_requests", 3)
        self.results_per_hashtag = config.get("requests_per_hashtag", 15)
        self.max_retries = config.get("max_retries", 3)
        self.retry_delay = config.get("retry_delay", 10)
        self.last_cost_cents = 0  # Always free

        if INSTALOADER_AVAILABLE:
            self.loader = instaloader.Instaloader(
                download_videos=False,
                download_video_thumbnails=False,
                download_geotags=False,
                download_comments=False,
                save_metadata=False,
                compress_json=False,
                quiet=True,
            )
        else:
            self.loader = None

    def scrape(self, keywords: List[str], max_results: int = 50) -> List[ReelData]:
        """
        Scrape reels for given hashtags.

        Args:
            keywords: List of hashtags (without #)
            max_results: Max reels to return across all hashtags

        Returns:
            List of ReelData objects
        """
        if not INSTALOADER_AVAILABLE or self.loader is None:
            logger.error("Instaloader not available")
            return []

        all_reels = []
        per_hashtag = min(self.results_per_hashtag, max(3, max_results // max(len(keywords), 1)))

        for hashtag in keywords:
            if len(all_reels) >= max_results:
                break

            reels = self._scrape_hashtag(hashtag, per_hashtag)
            all_reels.extend(reels)
            logger.debug(f"#{hashtag}: {len(reels)} reels")

            if len(reels) > 0:
                time.sleep(self.sleep_between)

        return all_reels[:max_results]

    def _scrape_hashtag(self, hashtag: str, limit: int) -> List[ReelData]:
        """Scrape top recent posts from a single hashtag."""
        reels = []

        for attempt in range(self.max_retries):
            try:
                hashtag_obj = instaloader.Hashtag.from_name(self.loader.context, hashtag)
                posts = hashtag_obj.get_top_posts()

                count = 0
                for post in posts:
                    if count >= limit:
                        break

                    # Only grab Reels (video posts)
                    if not post.is_video:
                        continue

                    reel = self._post_to_reel_data(post)
                    if reel:
                        reels.append(reel)
                        count += 1

                    time.sleep(0.5)  # Polite delay per post

                return reels

            except instaloader.exceptions.ConnectionException as e:
                logger.warning(f"Connection error scraping #{hashtag} (attempt {attempt+1}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
            except instaloader.exceptions.TooManyRequestsException:
                logger.warning(f"Rate limited on #{hashtag}, backing off 60s")
                time.sleep(60)
                break
            except Exception as e:
                logger.error(f"Unexpected error scraping #{hashtag}: {e}")
                break

        return reels

    def _post_to_reel_data(self, post) -> Optional[ReelData]:
        """Convert an instaloader Post object to ReelData."""
        try:
            # Extract hashtags from caption
            caption = post.caption or ""
            hashtags = re.findall(r"#(\w+)", caption.lower())

            # Extract audio info if available
            audio_name = None
            audio_artist = None
            if hasattr(post, "music_info") and post.music_info:
                music = post.music_info
                audio_name = getattr(music, "song_name", None)
                audio_artist = getattr(music, "artist_name", None)

            # Normalize posted_at to UTC naive datetime
            posted_at = post.date_utc
            if posted_at.tzinfo is not None:
                posted_at = posted_at.replace(tzinfo=None)

            return ReelData(
                reel_id=str(post.mediaid),
                shortcode=post.shortcode,
                url=f"https://www.instagram.com/p/{post.shortcode}/",
                username=post.owner_username,
                follower_count=post.owner_profile.followers if post.owner_profile else 0,
                caption=caption[:1000],  # Truncate very long captions
                hashtags=hashtags,
                likes=post.likes,
                comments=post.comments,
                views=post.video_view_count or 0,
                posted_at=posted_at,
                audio_name=audio_name,
                audio_artist=audio_artist,
                duration_seconds=post.video_duration,
                source="instaloader",
                raw_metadata={
                    "typename": post.typename,
                    "location": str(post.location) if post.location else None,
                    "is_pinned": getattr(post, "is_pinned", False),
                },
            )
        except Exception as e:
            logger.debug(f"Failed to parse post {getattr(post, 'shortcode', '?')}: {e}")
            return None

    def scrape_account(self, username: str, limit: int = 10) -> List[ReelData]:
        """Scrape recent Reels from a specific account."""
        if not INSTALOADER_AVAILABLE or self.loader is None:
            return []

        reels = []
        try:
            profile = instaloader.Profile.from_username(self.loader.context, username)
            for post in profile.get_posts():
                if len(reels) >= limit:
                    break
                if post.is_video:
                    reel = self._post_to_reel_data(post)
                    if reel:
                        reels.append(reel)
                time.sleep(0.5)
        except Exception as e:
            logger.error(f"Failed to scrape account @{username}: {e}")

        return reels
