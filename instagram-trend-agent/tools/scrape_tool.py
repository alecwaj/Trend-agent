"""LangChain tool — scrape Instagram Reels via the multi-source router."""

import json
import random
from datetime import datetime, timedelta
from typing import Optional

from langchain_core.tools import tool

from tools.config_loader import get_config, get_data_dir
from tools.helpers import reel_to_dict


def _mock_reels() -> list:
    """Mock ReelData list for dry-run / offline testing."""
    from scrapers import ReelData

    mock_data = [
        ("djbeats_pro", 125000, "Mixing it up tonight #djlife #djset #beatmatch #housemusic",
         ["djlife", "djset", "beatmatch", "housemusic"], "Blinding Lights (Remix)", "The Weeknd"),
        ("musicproducer_x", 89000, "New beat just dropped #musicproduction #beatmaking #flstudio #trap",
         ["musicproduction", "beatmaking", "flstudio", "trap"], "Custom Beat 808", None),
        ("festivalvibes", 234000, "What a night at Coachella! #festivalseason #edm #rave #concertvibes",
         ["festivalseason", "edm", "rave", "concertvibes"], "Levels", "Avicii"),
        ("synthwave_daily", 45000, "Analog warmth #synthesizer #producerlife #studiolife #synthwave",
         ["synthesizer", "producerlife", "studiolife", "synthwave"], "Midnight City", "M83"),
        ("turntablist_99", 67000, "Practice makes perfect #turntablism #scratching #djculture #hiphop",
         ["turntablism", "scratching", "djculture", "hiphop"], "Get Lucky (Scratch Edit)", "Daft Punk"),
        ("newmusic_daily", 189000, "This is going viral #newmusic #viralmusic #trending #musicdiscovery",
         ["newmusic", "viralmusic", "trending", "musicdiscovery"], "As It Was", "Harry Styles"),
        ("ableton_wizard", 56000, "Tutorial time: layering synths #ableton #musicproduction #synthesizer",
         ["ableton", "musicproduction", "synthesizer"], None, None),
        ("concertphotos", 312000, "Electric atmosphere! #livemusic #concertphotography #musicfestival",
         ["livemusic", "concertphotography", "musicfestival"], "Blinding Lights (Remix)", "The Weeknd"),
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


@tool
def scrape_instagram_reels(max_results: int = 75, dry_run: bool = False) -> str:
    """
    Scrape Instagram Reels across DJ, concert, and music production hashtags.

    Uses a prioritised source chain:
      1. instaloader (free, no API key)
      2. apify (30 free runs/month)
      3. rapidapi (500 free req/month)
      4. google fallback (zero-cost HTML scraping)

    Set dry_run=True to use mock data without any network calls.

    Returns JSON: {"reels": [...], "count": N, "source_summary": {...}}
    """
    config = get_config()

    if dry_run:
        reels = _mock_reels()
        return json.dumps({
            "reels": [reel_to_dict(r) for r in reels],
            "count": len(reels),
            "source_summary": {"mock": len(reels)},
        })

    from scrapers.router import ScraperRouter

    hashtag_clusters = config.get("hashtags", {})
    all_hashtags = list(dict.fromkeys(
        h for cluster in hashtag_clusters.values() for h in cluster
    ))

    router = ScraperRouter(config, get_data_dir())
    reels = router.scrape_all(all_hashtags, max_total=max_results)
    source_summary = router.get_usage_summary()

    return json.dumps({
        "reels": [reel_to_dict(r) for r in reels],
        "count": len(reels),
        "source_summary": source_summary,
    })
