"""
Trend Tracker — Tracks trends across multiple days, detecting velocity changes.

Maintains the cumulative trend log and computes:
- When trends first appeared
- How long they've been active
- Whether they're accelerating, peaking, or declining
- Historical context for LLM prompts
"""

import csv
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class TrendTracker:
    """
    Maintains a persistent record of trends over time and detects
    velocity changes by comparing current trends to historical data.
    """

    def __init__(self, config: dict, output_dir: str = "outputs/"):
        self.config = config
        self.output_dir = Path(output_dir)
        self.cumulative_log = self.output_dir / "trend_log.csv"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_log_exists()

    def _ensure_log_exists(self):
        """Create the cumulative log with headers if it doesn't exist."""
        if not self.cumulative_log.exists():
            headers = (
                self.config.get("output", {}).get("daily_csv_columns", [])
                + self.config.get("output", {}).get("cumulative_log_extra_columns", [])
            )
            if not headers:
                headers = [
                    "date", "trend_name", "category", "description", "velocity",
                    "confidence", "marketing_angle", "suggested_hashtags",
                    "suggested_audio", "content_format", "shelf_life_days",
                    "evidence_reel_count", "avg_engagement_velocity",
                    "first_detected", "last_seen", "days_active",
                    "peak_confidence", "peak_velocity", "current_status",
                ]
            with open(self.cumulative_log, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
            logger.info(f"Created cumulative trend log: {self.cumulative_log}")

    def update(self, daily_trends: List[Dict], analysis_date: Optional[date] = None) -> List[Dict]:
        """
        Update cumulative log with today's trends.
        Returns enriched trends with historical context added.

        Args:
            daily_trends: List of trend dicts from LLM analysis
            analysis_date: Date to record (defaults to today)

        Returns:
            List of trends with first_detected, days_active, etc.
        """
        if analysis_date is None:
            analysis_date = date.today()

        # Load existing log for historical context
        existing = self._load_existing_trends()

        enriched = []
        for trend in daily_trends:
            trend_name = trend.get("trend_name", "").lower().strip()
            historical = existing.get(trend_name)

            if historical:
                first_detected = historical.get("first_detected", str(analysis_date))
                try:
                    first_dt = datetime.strptime(first_detected, "%Y-%m-%d").date()
                    days_active = (analysis_date - first_dt).days + 1
                except (ValueError, TypeError):
                    days_active = 1
                    first_detected = str(analysis_date)

                peak_confidence = max(
                    float(historical.get("peak_confidence", 0)),
                    float(trend.get("confidence", 0)),
                )
                peak_velocity = historical.get("peak_velocity", trend.get("velocity", "emerging"))
            else:
                first_detected = str(analysis_date)
                days_active = 1
                peak_confidence = float(trend.get("confidence", 0))
                peak_velocity = trend.get("velocity", "emerging")

            # Determine current status
            velocity = trend.get("velocity", "emerging")
            if velocity == "declining":
                current_status = "declining"
            elif days_active > trend.get("estimated_shelf_life_days", 14):
                current_status = "expired"
            else:
                current_status = "active"

            enriched.append({
                **trend,
                "first_detected": first_detected,
                "last_seen": str(analysis_date),
                "days_active": days_active,
                "peak_confidence": round(peak_confidence, 4),
                "peak_velocity": peak_velocity,
                "current_status": current_status,
            })

        # Write to cumulative log
        self._append_to_log(enriched, analysis_date)

        # Mark expired trends in log
        self._mark_expired_trends(existing, {t["trend_name"].lower() for t in daily_trends}, analysis_date)

        return enriched

    def _load_existing_trends(self) -> Dict[str, Dict]:
        """Load all existing trends from the cumulative log, keyed by lowercase trend name."""
        if not self.cumulative_log.exists():
            return {}

        trends = {}
        try:
            with open(self.cumulative_log, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get("trend_name", "").lower().strip()
                    if name:
                        # Keep the most recent entry for each trend
                        if name not in trends or row.get("last_seen", "") > trends[name].get("last_seen", ""):
                            trends[name] = row
        except Exception as e:
            logger.error(f"Failed to load existing trends: {e}")

        return trends

    def _append_to_log(self, trends: List[Dict], analysis_date: date):
        """Append today's trends to the cumulative log."""
        if not trends:
            return

        fieldnames = []
        if self.cumulative_log.exists():
            with open(self.cumulative_log, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                fieldnames = next(reader, [])

        if not fieldnames:
            fieldnames = [
                "date", "trend_name", "category", "description", "velocity",
                "confidence", "marketing_angle", "suggested_hashtags",
                "suggested_audio", "content_format", "shelf_life_days",
                "evidence_reel_count", "avg_engagement_velocity",
                "first_detected", "last_seen", "days_active",
                "peak_confidence", "peak_velocity", "current_status",
            ]

        with open(self.cumulative_log, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            for trend in trends:
                row = {
                    "date": str(analysis_date),
                    "trend_name": trend.get("trend_name", ""),
                    "category": trend.get("trend_category", ""),
                    "description": trend.get("description", ""),
                    "velocity": trend.get("velocity", ""),
                    "confidence": trend.get("confidence", 0),
                    "marketing_angle": trend.get("marketing_angle", ""),
                    "suggested_hashtags": "|".join(trend.get("suggested_hashtags", [])),
                    "suggested_audio": trend.get("suggested_audio", ""),
                    "content_format": trend.get("content_format", ""),
                    "shelf_life_days": trend.get("estimated_shelf_life_days", ""),
                    "evidence_reel_count": trend.get("evidence_reel_count", 0),
                    "avg_engagement_velocity": trend.get("avg_engagement_velocity", 0),
                    "first_detected": trend.get("first_detected", str(analysis_date)),
                    "last_seen": trend.get("last_seen", str(analysis_date)),
                    "days_active": trend.get("days_active", 1),
                    "peak_confidence": trend.get("peak_confidence", trend.get("confidence", 0)),
                    "peak_velocity": trend.get("peak_velocity", trend.get("velocity", "")),
                    "current_status": trend.get("current_status", "active"),
                }
                writer.writerow(row)

        logger.info(f"Appended {len(trends)} trends to cumulative log")

    def _mark_expired_trends(
        self,
        existing: Dict[str, Dict],
        todays_trend_names: set,
        analysis_date: date,
    ):
        """
        Detect trends that were active before but not seen today —
        they may be declining. This is logged but doesn't modify the CSV
        (we'd need a full rewrite for that; instead, absence indicates end).
        """
        previously_active = {
            name: data for name, data in existing.items()
            if data.get("current_status") == "active"
        }
        not_seen_today = set(previously_active.keys()) - todays_trend_names
        if not_seen_today:
            logger.info(f"Trends not seen today (may be declining): {not_seen_today}")

    def get_historical_context(self, days: int = 7) -> str:
        """
        Build a historical context string for the LLM prompt
        summarizing the last N days of trends.
        """
        if not self.cumulative_log.exists():
            return "No historical trend data available yet."

        cutoff = date.today() - timedelta(days=days)
        recent_trends = []

        try:
            with open(self.cumulative_log, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        row_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
                        if row_date >= cutoff:
                            recent_trends.append(row)
                    except (ValueError, KeyError):
                        continue
        except Exception as e:
            logger.error(f"Failed to load historical context: {e}")
            return "Error loading historical data."

        if not recent_trends:
            return "No trend data from the past 7 days."

        # Build a compact summary
        lines = [f"TREND HISTORY (last {days} days):"]
        by_name = {}
        for t in recent_trends:
            name = t.get("trend_name", "")
            if name not in by_name:
                by_name[name] = t
            else:
                # Keep latest
                if t.get("date", "") > by_name[name].get("date", ""):
                    by_name[name] = t

        for name, t in sorted(by_name.items(), key=lambda x: x[1].get("confidence", 0), reverse=True):
            lines.append(
                f"- {name} [{t.get('category', '?')}]: "
                f"velocity={t.get('velocity', '?')}, "
                f"confidence={t.get('confidence', '?')}, "
                f"days_active={t.get('days_active', '?')}, "
                f"status={t.get('current_status', '?')}"
            )

        return "\n".join(lines[:50])  # Cap at 50 lines for token efficiency

    def get_summary_stats(self) -> Dict:
        """Return summary statistics about the trend database."""
        if not self.cumulative_log.exists():
            return {"total_trends_tracked": 0, "active_trends": 0}

        all_trends = []
        try:
            with open(self.cumulative_log, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                all_trends = list(reader)
        except Exception:
            pass

        active = sum(1 for t in all_trends if t.get("current_status") == "active")
        by_category = {}
        for t in all_trends:
            cat = t.get("category", "unknown")
            by_category[cat] = by_category.get(cat, 0) + 1

        return {
            "total_trends_tracked": len(all_trends),
            "active_trends": active,
            "by_category": by_category,
        }
