"""
Summary Writer — Generates the daily markdown briefing.

Output: daily_summary_YYYY-MM-DD.md

Contents:
- Top 3 trends to act on TODAY
- 1 emerging trend to prepare content for
- 1 trend to stop investing in
- Cost report
"""

import logging
from datetime import date
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class SummaryWriter:
    """Generates human-readable daily trend summaries in Markdown format."""

    def __init__(self, config: dict, output_dir: str = "outputs/"):
        self.config = config
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        trends: List[Dict],
        tier1_results: Dict,
        llm_analysis: Optional[Dict],
        budget_summary: Dict,
        scraper_summary: Dict,
        analysis_date: Optional[date] = None,
    ) -> Path:
        """
        Write the daily summary markdown file.

        Returns:
            Path to the written markdown file
        """
        if analysis_date is None:
            analysis_date = date.today()

        filename = self.output_dir / f"daily_summary_{analysis_date}.md"

        content = self._build_summary(
            trends, tier1_results, llm_analysis,
            budget_summary, scraper_summary, analysis_date
        )

        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Wrote daily summary to {filename}")
        return filename

    def _build_summary(
        self,
        trends: List[Dict],
        tier1_results: Dict,
        llm_analysis: Optional[Dict],
        budget_summary: Dict,
        scraper_summary: Dict,
        analysis_date: date,
    ) -> str:
        sections = [
            self._header(analysis_date, tier1_results),
            self._top_action_trends(trends),
            self._emerging_trend(trends, llm_analysis),
            self._declining_trend(trends, llm_analysis),
            self._audio_signals(tier1_results),
            self._hashtag_signals(tier1_results),
            self._posting_insights(tier1_results),
            self._cost_report(budget_summary, scraper_summary),
            self._footer(analysis_date),
        ]
        return "\n\n".join(s for s in sections if s)

    def _header(self, analysis_date: date, tier1_results: Dict) -> str:
        reel_count = tier1_results.get("reel_count", 0)
        engagement_stats = tier1_results.get("engagement_stats", {})
        avg_vel = engagement_stats.get("avg_engagement_velocity", 0)

        return f"""# Instagram Reels Music Trend Brief — {analysis_date}

> **Daily intelligence report for music industry content creators and marketers**

**Data snapshot:** {reel_count} reels analyzed | Avg engagement velocity: {avg_vel:.1f}/hr"""

    def _top_action_trends(self, trends: List[Dict]) -> str:
        if not trends:
            return "## Act On These TODAY\n\n_No trend data available._"

        # Sort by confidence, prioritize accelerating/peaking
        priority_order = {"peaking": 0, "accelerating": 1, "emerging": 2, "declining": 3}
        sorted_trends = sorted(
            trends,
            key=lambda t: (
                priority_order.get(t.get("velocity", "emerging"), 2),
                -float(t.get("confidence", 0)),
            )
        )
        top_3 = sorted_trends[:3]

        lines = ["## Act On These TODAY\n"]
        for i, trend in enumerate(top_3, 1):
            confidence_pct = int(float(trend.get("confidence", 0)) * 100)
            shelf_life = trend.get("estimated_shelf_life_days", trend.get("shelf_life_days", "?"))
            hashtags = trend.get("suggested_hashtags", [])
            if isinstance(hashtags, str):
                hashtags = [h for h in hashtags.split("|") if h]
            hashtag_str = " ".join(f"#{tag}" for tag in hashtags[:5]) if hashtags else "_none_"
            audio = trend.get("suggested_audio") or "_no specific audio_"

            lines.append(f"### {i}. {trend.get('trend_name', 'Unknown Trend')}")
            lines.append(f"**Category:** {trend.get('trend_category', trend.get('category', '?'))} | "
                        f"**Confidence:** {confidence_pct}% | "
                        f"**Velocity:** {trend.get('velocity', '?')} | "
                        f"**Shelf life:** ~{shelf_life} days\n")
            lines.append(f"{trend.get('description', '')}\n")
            lines.append(f"**What to do:** {trend.get('marketing_angle', '')}\n")
            lines.append(f"**Use hashtags:** {hashtag_str}")
            lines.append(f"**Use audio:** {audio}")
            lines.append(f"**Format:** {trend.get('content_format', '?')}")
            lines.append("")

        return "\n".join(lines)

    def _emerging_trend(self, trends: List[Dict], llm_analysis: Optional[Dict]) -> str:
        # Find an emerging trend (low confidence but worth watching)
        emerging = [t for t in trends if t.get("velocity") == "emerging"]

        lines = ["## Emerging Signal: Prepare Content Now\n"]

        if llm_analysis:
            signals = llm_analysis.get("emerging_signals", [])
            if signals:
                lines.append("**Weak signals worth watching:**")
                for sig in signals[:3]:
                    lines.append(f"- {sig}")
                lines.append("")

        if emerging:
            trend = emerging[0]
            lines.append(f"**Trend to prepare for:** {trend.get('trend_name', '?')}")
            lines.append(f"{trend.get('description', '')}")
            lines.append(f"**Prepare:** {trend.get('marketing_angle', '')}")
        else:
            lines.append("_No clear emerging trends identified today._")

        return "\n".join(lines)

    def _declining_trend(self, trends: List[Dict], llm_analysis: Optional[Dict]) -> str:
        declining = [t for t in trends if t.get("velocity") == "declining"]
        dying = llm_analysis.get("dying_trends", []) if llm_analysis else []

        if not declining and not dying:
            return ""

        lines = ["## Stop Investing In These\n"]

        if dying:
            for trend_name in dying[:2]:
                lines.append(f"- **{trend_name}** — losing momentum, shift resources elsewhere")

        if declining:
            for trend in declining[:2]:
                lines.append(f"- **{trend.get('trend_name', '?')}** — {trend.get('description', '')[:100]}")

        return "\n".join(lines)

    def _audio_signals(self, tier1_results: Dict) -> str:
        audio_trends = tier1_results.get("audio_trends", [])[:5]
        if not audio_trends:
            return ""

        lines = ["## Trending Audio Tracks\n"]
        lines.append("| Audio | Artist | Reels Using It | Avg Velocity |")
        lines.append("|-------|--------|---------------|--------------|")
        for a in audio_trends:
            artist = a.get("artist") or "unknown"
            lines.append(
                f"| {a['audio_name'][:40]} | {artist[:25]} | "
                f"{a['reuse_count']} | {a['avg_engagement_velocity']}/hr |"
            )

        return "\n".join(lines)

    def _hashtag_signals(self, tier1_results: Dict) -> str:
        top_tags = tier1_results.get("hashtag_analysis", {}).get("top_hashtags", [])[:10]
        emerging_clusters = tier1_results.get("hashtag_analysis", {}).get("emerging_clusters", [])[:5]

        if not top_tags:
            return ""

        lines = ["## Hashtag Intelligence\n"]

        lines.append("**Top performing hashtags today:**")
        tag_str = " ".join(f"`#{t['hashtag']}`" for t in top_tags[:8])
        lines.append(tag_str)
        lines.append("")

        if emerging_clusters:
            lines.append("**Emerging hashtag combos (new or accelerating):**")
            for cluster in emerging_clusters[:5]:
                new_flag = " _(NEW)_" if cluster.get("is_new") else ""
                lines.append(f"- {cluster['hashtag_pair']}: {cluster['today_count']}x today{new_flag}")

        return "\n".join(lines)

    def _posting_insights(self, tier1_results: Dict) -> str:
        patterns = tier1_results.get("posting_patterns", {})
        best_hours = patterns.get("best_posting_hours", [])[:3]
        best_days = patterns.get("best_posting_days", [])[:3]
        fmt = tier1_results.get("format_analysis", {})

        if not best_hours and not best_days:
            return ""

        lines = ["## Optimal Posting Strategy\n"]

        if best_hours:
            hours_str = ", ".join(f"{h['hour']}:00 UTC" for h in best_hours)
            lines.append(f"**Best posting times:** {hours_str}")

        if best_days:
            days_str = ", ".join(d["day"] for d in best_days)
            lines.append(f"**Best days:** {days_str}")

        best_format = fmt.get("best_performing_format", "unknown")
        lines.append(f"**Best reel length:** {best_format}")

        return "\n".join(lines)

    def _cost_report(self, budget_summary: Dict, scraper_summary: Dict) -> str:
        total_cost_cents = budget_summary.get("total_cost_cents_today", 0)
        daily_ceiling = self.config.get("budget", {}).get("daily_ceiling_cents", 500)
        budget_remaining = daily_ceiling - total_cost_cents

        lines = ["## Cost Report\n"]
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Total cost today | ${total_cost_cents/100:.3f} |")
        lines.append(f"| Daily budget remaining | ${budget_remaining/100:.2f} |")
        lines.append(f"| Daily ceiling | ${daily_ceiling/100:.2f} |")

        # Per-source breakdown
        sources = scraper_summary.get("sources", {})
        if sources:
            lines.append("")
            lines.append("**Scraper usage:**")
            for source, data in sources.items():
                lines.append(
                    f"- {source}: {data.get('reels', 0)} reels, "
                    f"{data.get('requests', 0)} requests, "
                    f"${data.get('cost_cents', 0)/100:.3f}"
                )

        api_calls = budget_summary.get("llm_calls_today", 0)
        llm_cost = budget_summary.get("llm_cost_cents_today", 0)
        lines.append(f"\n**LLM usage:** {api_calls} batch calls | Cost: ${llm_cost/100:.3f}")

        return "\n".join(lines)

    def _footer(self, analysis_date: date) -> str:
        return f"""---
_Generated by Instagram Reels Music Trend Agent | {analysis_date}_
_Next run: tomorrow at 06:00 UTC_"""
