"""
CSV Writer — Generates daily and cumulative trend CSV reports.

Daily CSV: trends_YYYY-MM-DD.csv
Cumulative log is managed by TrendTracker (analysis/trend_tracker.py).
"""

import csv
import logging
from datetime import date
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


DAILY_CSV_FIELDS = [
    "date",
    "trend_name",
    "category",
    "description",
    "velocity",
    "confidence",
    "marketing_angle",
    "suggested_hashtags",
    "suggested_audio",
    "content_format",
    "shelf_life_days",
    "evidence_reel_count",
    "avg_engagement_velocity",
]


class CSVWriter:
    """Writes structured trend data to daily CSV files."""

    def __init__(self, config: dict, output_dir: str = "outputs/"):
        self.config = config
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.fields = config.get("output", {}).get("daily_csv_columns", DAILY_CSV_FIELDS)

    def write_daily(
        self,
        trends: List[Dict],
        scored_reels: List[Dict],
        analysis_date: Optional[date] = None,
    ) -> Path:
        """
        Write today's trend analysis to a dated CSV file.

        Args:
            trends: List of trend dicts from LLM analysis (with enrichment from TrendTracker)
            scored_reels: Virality-scored reels for computing evidence_reel_count
            analysis_date: Date for the file name (defaults to today)

        Returns:
            Path to the written CSV file
        """
        if analysis_date is None:
            analysis_date = date.today()

        filename = self.output_dir / f"trends_{analysis_date}.csv"

        # Compute per-trend stats from scored reels
        trend_stats = self._compute_trend_stats(trends, scored_reels)

        rows = []
        for trend in trends:
            name = trend.get("trend_name", "")
            stats = trend_stats.get(name.lower(), {})

            row = {
                "date": str(analysis_date),
                "trend_name": name,
                "category": trend.get("trend_category", trend.get("category", "")),
                "description": trend.get("description", ""),
                "velocity": trend.get("velocity", ""),
                "confidence": f"{float(trend.get('confidence', 0)):.2f}",
                "marketing_angle": trend.get("marketing_angle", ""),
                "suggested_hashtags": "|".join(trend.get("suggested_hashtags", [])),
                "suggested_audio": trend.get("suggested_audio", "") or "",
                "content_format": trend.get("content_format", ""),
                "shelf_life_days": trend.get("estimated_shelf_life_days", trend.get("shelf_life_days", "")),
                "evidence_reel_count": stats.get("evidence_reel_count", 0),
                "avg_engagement_velocity": stats.get("avg_engagement_velocity", 0),
            }
            rows.append(row)

        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        logger.info(f"Wrote {len(rows)} trends to {filename}")
        return filename

    def _compute_trend_stats(self, trends: List[Dict], scored_reels: List[Dict]) -> Dict[str, Dict]:
        """
        For each trend, find matching reels and compute aggregate stats
        (evidence count, average engagement velocity).
        """
        stats = {}

        for trend in trends:
            trend_name = trend.get("trend_name", "").lower()
            suggested_hashtags = {tag.lower() for tag in trend.get("suggested_hashtags", [])}
            category = trend.get("trend_category", trend.get("category", "")).lower()

            matching_reels = []
            for item in scored_reels:
                reel = item["reel"]
                reel_tags = {tag.lower() for tag in reel.hashtags}

                # Match if reel shares hashtags with the trend
                overlap = suggested_hashtags & reel_tags
                if overlap or category in reel_tags:
                    matching_reels.append(item)

            if matching_reels:
                avg_vel = sum(r["engagement_velocity"] for r in matching_reels) / len(matching_reels)
                stats[trend_name] = {
                    "evidence_reel_count": len(matching_reels),
                    "avg_engagement_velocity": round(avg_vel, 2),
                }
            else:
                stats[trend_name] = {
                    "evidence_reel_count": len(scored_reels),  # All reels as general evidence
                    "avg_engagement_velocity": 0,
                }

        return stats

    def write_fallback_csv(
        self,
        scored_reels: List[Dict],
        tier1_results: Dict,
        analysis_date: Optional[date] = None,
    ) -> Path:
        """
        Write a fallback CSV from Tier 1 data when LLM analysis is unavailable.
        Uses top hashtags and audio trends as proxy trends.
        """
        if analysis_date is None:
            analysis_date = date.today()

        filename = self.output_dir / f"trends_{analysis_date}.csv"

        rows = []

        # Generate trend rows from top audio tracks
        audio_trends = tier1_results.get("audio_trends", [])[:5]
        for audio in audio_trends:
            rows.append({
                "date": str(analysis_date),
                "trend_name": f"Audio Trend: {audio['audio_name'][:40]}",
                "category": "crossover",
                "description": f"Audio clip '{audio['audio_name']}' by {audio.get('artist', 'unknown')} "
                               f"trending across {audio['reuse_count']} reels",
                "velocity": "accelerating" if audio["reuse_count"] > 3 else "emerging",
                "confidence": min(audio["reuse_count"] / 10, 0.9),
                "marketing_angle": f"Use this audio: '{audio['audio_name']}' in your next reel",
                "suggested_hashtags": "",
                "suggested_audio": audio["audio_name"],
                "content_format": "15-30s with trending audio",
                "shelf_life_days": 7,
                "evidence_reel_count": audio["reuse_count"],
                "avg_engagement_velocity": audio["avg_engagement_velocity"],
            })

        # Generate trend rows from top hashtag clusters
        top_tags = tier1_results.get("hashtag_analysis", {}).get("top_hashtags", [])[:5]
        for tag in top_tags:
            rows.append({
                "date": str(analysis_date),
                "trend_name": f"Hashtag Trend: #{tag['hashtag']}",
                "category": "unknown",
                "description": f"#{tag['hashtag']} trending with {tag['count']} reels and avg velocity {tag['avg_engagement_velocity']}",
                "velocity": "accelerating" if tag["trend_score"] > 100 else "emerging",
                "confidence": min(tag["count"] / 20, 0.85),
                "marketing_angle": f"Include #{tag['hashtag']} in your next reel caption",
                "suggested_hashtags": tag["hashtag"],
                "suggested_audio": "",
                "content_format": "Best performing format today",
                "shelf_life_days": 5,
                "evidence_reel_count": tag["count"],
                "avg_engagement_velocity": tag["avg_engagement_velocity"],
            })

        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        logger.info(f"Wrote {len(rows)} fallback trend rows to {filename}")
        return filename
