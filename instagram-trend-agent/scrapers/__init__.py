"""
Scraper modules for Instagram Reels data ingestion.
Each scraper implements the same interface:
    scrape(keywords: List[str], max_results: int) -> List[ReelData]
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class ReelData:
    """Unified data model for a single Instagram Reel."""
    reel_id: str
    shortcode: str
    url: str
    username: str
    follower_count: int
    caption: str
    hashtags: list
    likes: int
    comments: int
    views: int
    posted_at: datetime
    audio_name: Optional[str]
    audio_artist: Optional[str]
    duration_seconds: Optional[int]
    source: str                    # Which scraper collected this
    scraped_at: datetime = field(default_factory=datetime.utcnow)
    raw_metadata: dict = field(default_factory=dict)

    def engagement_rate(self) -> float:
        if self.follower_count == 0:
            return 0.0
        return (self.likes + self.comments) / self.follower_count

    def hours_since_posted(self) -> float:
        delta = datetime.utcnow() - self.posted_at
        return max(delta.total_seconds() / 3600, 0.1)  # Avoid division by zero

    def engagement_velocity(self) -> float:
        """(likes + comments) per hour since posting."""
        return (self.likes + self.comments) / self.hours_since_posted()
