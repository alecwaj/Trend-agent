"""Serialisation helpers — convert ReelData ↔ JSON-safe dicts across tool boundaries."""

from datetime import datetime
from typing import Any

from scrapers import ReelData


def reel_to_dict(reel: ReelData) -> dict:
    return {
        "reel_id": reel.reel_id,
        "shortcode": reel.shortcode,
        "url": reel.url,
        "username": reel.username,
        "follower_count": reel.follower_count,
        "caption": reel.caption,
        "hashtags": reel.hashtags,
        "likes": reel.likes,
        "comments": reel.comments,
        "views": reel.views,
        "posted_at": reel.posted_at.isoformat(),
        "audio_name": reel.audio_name,
        "audio_artist": reel.audio_artist,
        "duration_seconds": reel.duration_seconds,
        "source": reel.source,
        "scraped_at": reel.scraped_at.isoformat(),
    }


def dict_to_reel(data: dict) -> ReelData:
    return ReelData(
        reel_id=data["reel_id"],
        shortcode=data.get("shortcode", ""),
        url=data.get("url", ""),
        username=data.get("username", ""),
        follower_count=data.get("follower_count", 0),
        caption=data.get("caption", ""),
        hashtags=data.get("hashtags", []),
        likes=data.get("likes", 0),
        comments=data.get("comments", 0),
        views=data.get("views", 0),
        posted_at=datetime.fromisoformat(data["posted_at"]),
        audio_name=data.get("audio_name"),
        audio_artist=data.get("audio_artist"),
        duration_seconds=data.get("duration_seconds"),
        source=data.get("source", ""),
        scraped_at=datetime.fromisoformat(
            data.get("scraped_at", datetime.utcnow().isoformat())
        ),
    )


def scored_reel_to_dict(item: dict) -> dict:
    """Serialise a ViralityScorer output dict (which embeds a ReelData object)."""
    return {
        "reel": reel_to_dict(item["reel"]),
        "virality_score": item.get("virality_score", 0.0),
        "engagement_velocity": item.get("engagement_velocity", 0.0),
        "audio_reuse_count": item.get("audio_reuse_count", 0),
        "norm_engagement": item.get("norm_engagement", 0.0),
        "audio_score": item.get("audio_score", 0.0),
        "hashtag_score": item.get("hashtag_score", 0.0),
    }


def dict_to_scored_reel(data: dict) -> dict:
    """Deserialise back to the format ViralityScorer would produce."""
    return {
        "reel": dict_to_reel(data["reel"]),
        "virality_score": data.get("virality_score", 0.0),
        "engagement_velocity": data.get("engagement_velocity", 0.0),
        "audio_reuse_count": data.get("audio_reuse_count", 0),
        "norm_engagement": data.get("norm_engagement", 0.0),
        "audio_score": data.get("audio_score", 0.0),
        "hashtag_score": data.get("hashtag_score", 0.0),
    }
