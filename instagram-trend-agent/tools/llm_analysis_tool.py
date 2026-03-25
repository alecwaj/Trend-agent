"""
LangChain tool — Tier 2 LLM trend analysis via ChatAnthropic with structured output.

Uses Claude Haiku (cheap model) with Pydantic-enforced structured output — no manual
JSON parsing, no markdown stripping, no regex hacks.
"""

import json
import os
from datetime import date
from typing import List, Literal, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from tools.config_loader import get_config, get_output_dir


# ── Pydantic schema for structured output ────────────────────────────────────

class TrendItem(BaseModel):
    """A single identified trend from today's reel analysis."""

    trend_name: str = Field(description="Short memorable name, 3-5 words")
    trend_category: Literal["dj", "concert", "production", "crossover"] = Field(
        description="Primary category this trend belongs to"
    )
    description: str = Field(description="What the trend is in 1-2 sentences")
    evidence: str = Field(description="Specific reels or data points that support this trend")
    velocity: Literal["emerging", "accelerating", "peaking", "declining"] = Field(
        description="Current momentum direction"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score between 0 and 1")
    marketing_angle: str = Field(
        description="Specific actionable recommendation for creating content around this trend"
    )
    suggested_hashtags: List[str] = Field(description="3-5 hashtags to use with this trend")
    suggested_audio: Optional[str] = Field(
        default=None, description="Specific audio clip to use, or null"
    )
    content_format: str = Field(
        description="Best format: duration, style, hook type (e.g. '15-30s hook-first reel')"
    )
    estimated_shelf_life_days: int = Field(
        description="How many days this trend is likely to remain relevant"
    )


class TrendReport(BaseModel):
    """Full daily trend intelligence report."""

    analysis_date: str = Field(description="Date of this analysis in YYYY-MM-DD format")
    top_trends: List[TrendItem] = Field(
        description="3-7 identified trends, ordered by confidence descending"
    )
    emerging_signals: List[str] = Field(
        description="Weak signals not yet full trends but worth watching"
    )
    dying_trends: List[str] = Field(
        description="Trends from recent days that are losing steam"
    )
    cross_niche_opportunities: List[str] = Field(
        description="Where DJ + production + concert audiences overlap"
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a music industry trend analyst specialising in Instagram Reels viral content.
Your job is to identify actionable trends for music producers, DJs, and concert promoters.
Be specific — generic insights have no value. Every recommendation must be directly applicable
to content creation in the music space."""

USER_PROMPT_TEMPLATE = """Analyse these top-performing Instagram Reels from today's data collection.

<reels_data>
{reels_json}
</reels_data>

<historical_context>
{historical_context}
</historical_context>

<tier1_signals>
{tier1_signals}
</tier1_signals>

Today's date: {today}

Identify 3-7 distinct trends. Prioritise specificity and actionability over breadth."""


def _build_reels_json(scored_reels: list, top_n: int) -> str:
    """Format the top-N scored reels as compact JSON for the LLM prompt."""
    items = []
    for i, item in enumerate(scored_reels[:top_n]):
        reel = item["reel"]
        items.append({
            "rank": i + 1,
            "username": reel.get("username"),
            "followers": reel.get("follower_count"),
            "caption": (reel.get("caption") or "")[:300],
            "hashtags": (reel.get("hashtags") or [])[:15],
            "audio": reel.get("audio_name"),
            "audio_artist": reel.get("audio_artist"),
            "likes": reel.get("likes"),
            "comments": reel.get("comments"),
            "views": reel.get("views"),
            "engagement_velocity": round(item.get("engagement_velocity", 0), 2),
            "virality_score": round(item.get("virality_score", 0), 4),
            "audio_reuse_count": item.get("audio_reuse_count", 0),
            "duration_seconds": reel.get("duration_seconds"),
            "url": reel.get("url"),
        })
    return json.dumps(items, indent=2)


def _summarise_tier1(tier1: dict) -> str:
    """Build compact Tier 1 summary text for the LLM context window."""
    if not tier1:
        return "No Tier 1 analysis available."

    parts = []

    audio_trends = (tier1.get("audio_trends") or [])[:5]
    if audio_trends:
        lines = [
            f"  - '{a['audio_name']}' by {a.get('artist', 'unknown')} "
            f"(used {a['reuse_count']}x, avg vel {a['avg_engagement_velocity']})"
            for a in audio_trends
        ]
        parts.append("TOP AUDIO TRACKS:\n" + "\n".join(lines))

    top_tags = (tier1.get("hashtag_analysis") or {}).get("top_hashtags") or []
    if top_tags:
        tag_str = ", ".join(
            f"#{t['hashtag']} ({t['count']}x)" for t in top_tags[:10]
        )
        parts.append(f"TOP HASHTAGS: {tag_str}")

    emerging = (tier1.get("hashtag_analysis") or {}).get("emerging_clusters") or []
    if emerging:
        lines = [
            f"  - {e['hashtag_pair']} ({e['today_count']}x today)"
            for e in emerging[:5]
        ]
        parts.append("EMERGING CLUSTERS:\n" + "\n".join(lines))

    best_hours = (tier1.get("posting_patterns") or {}).get("best_posting_hours") or []
    if best_hours:
        hours_str = ", ".join(
            f"{h['hour']}:00 UTC (vel: {h['avg_velocity']})" for h in best_hours[:3]
        )
        parts.append(f"BEST POSTING HOURS: {hours_str}")

    best_fmt = (tier1.get("format_analysis") or {}).get("best_performing_format", "unknown")
    parts.append(f"BEST FORMAT: {best_fmt}")

    return "\n\n".join(parts)


def _get_historical_context(days: int) -> str:
    """Pull historical trend context from the cumulative trend log."""
    from analysis.trend_tracker import TrendTracker

    config = get_config()
    tracker = TrendTracker(config, get_output_dir())
    return tracker.get_historical_context(days=days)


# ── LangChain tool ────────────────────────────────────────────────────────────

@tool
def analyze_trends_with_llm(
    scored_reels_json: str,
    tier1_json: str,
    historical_context: str = "",
) -> str:
    """
    Send the top-scoring reels to Claude Haiku for deep trend analysis.

    Uses structured output (Pydantic) — no JSON parsing errors, no hallucinated fields.
    Estimated cost: ~$0.01 per call using claude-haiku-4-5-20251001.

    Input scored_reels_json: the "scored_reels" array from run_local_analysis.
    Input tier1_json: the "tier1_results" dict from run_local_analysis.
    Input historical_context: optional string from previous runs (leave empty on first run).

    Returns the TrendReport as a JSON string.
    """
    from langchain_anthropic import ChatAnthropic

    config = get_config()
    tier2_cfg = config.get("analysis", {}).get("tier2", {})
    top_n = tier2_cfg.get("top_reels_to_analyze", 15)
    temperature = tier2_cfg.get("temperature", 0.3)

    api_key = (
        config.get("api_keys", {}).get("anthropic", "")
        or os.environ.get("ANTHROPIC_API_KEY", "")
    )
    if not api_key:
        return json.dumps({"error": "ANTHROPIC_API_KEY not set — LLM analysis skipped"})

    # Deserialise inputs
    scored_payload = json.loads(scored_reels_json)
    scored_list = (
        scored_payload.get("scored_reels", scored_payload)
        if isinstance(scored_payload, dict)
        else scored_payload
    )
    tier1 = json.loads(tier1_json) if isinstance(tier1_json, str) else tier1_json
    tier1_data = tier1.get("tier1_results", tier1) if isinstance(tier1, dict) else {}

    # Load historical context if not provided
    if not historical_context:
        historical_context = _get_historical_context(
            tier2_cfg.get("historical_context_days", 7)
        )

    reels_json_str = _build_reels_json(scored_list, top_n)
    tier1_summary = _summarise_tier1(tier1_data)

    prompt_text = USER_PROMPT_TEMPLATE.format(
        reels_json=reels_json_str,
        historical_context=historical_context or "No historical data yet.",
        tier1_signals=tier1_summary,
        today=str(date.today()),
    )

    # ChatAnthropic with structured output — model driven by config (tier2.model)
    llm = ChatAnthropic(
        model=tier2_cfg.get("model", "claude-sonnet-4-6"),
        temperature=temperature,
        anthropic_api_key=api_key,
    )
    structured_llm = llm.with_structured_output(TrendReport)

    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=prompt_text),
    ]

    report: TrendReport = structured_llm.invoke(messages)

    # Convert to dict for JSON serialisation
    return report.model_dump_json()
