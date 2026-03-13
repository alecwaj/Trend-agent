"""
Tier 2 LLM Analysis — Batched Claude Haiku trend analysis.
Uses Anthropic Batch API for 50% cost reduction.

Only the top 10-15 highest-signal reels are sent here daily.
Estimated cost: $0.01-0.03/day.
"""

import json
import logging
import os
import time
from datetime import date, datetime
from typing import List, Dict, Optional

from scrapers import ReelData

logger = logging.getLogger(__name__)

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    logger.warning("anthropic package not installed. Run: pip install anthropic")


TREND_ANALYSIS_PROMPT = """You are a music industry trend analyst specializing in Instagram Reels viral content.

Analyze these top-performing Instagram Reels from today's data collection.

For each reel, I'm providing: caption, hashtags, audio_name, engagement_metrics, account_info.

<reels_data>
{reels_json}
</reels_data>

<historical_context>
{historical_context}
</historical_context>

<tier1_signals>
{tier1_signals}
</tier1_signals>

Respond in ONLY valid JSON with this exact structure (no markdown, no extra text):
{{
  "date": "{date}",
  "top_trends": [
    {{
      "trend_name": "short memorable name (3-5 words)",
      "trend_category": "dj|concert|production|crossover",
      "description": "what the trend is in 1-2 sentences",
      "evidence": "specific reels/data points supporting this",
      "velocity": "emerging|accelerating|peaking|declining",
      "confidence": 0.0,
      "marketing_angle": "specific actionable recommendation for how to create content that taps into this trend",
      "suggested_hashtags": ["hashtag1", "hashtag2", "hashtag3"],
      "suggested_audio": "specific audio clip to use if applicable, or null",
      "content_format": "what format works best (duration, style, hook type)",
      "estimated_shelf_life_days": 7
    }}
  ],
  "emerging_signals": ["weak signal 1 not yet a trend but worth watching"],
  "dying_trends": ["trend from previous days that is losing steam"],
  "cross_niche_opportunities": ["where DJ + production + concert audiences overlap"]
}}

Identify 3-7 trends. Be specific and actionable. Focus on music industry applicability."""


class Tier2LLMAnalyzer:
    """
    Sends top reels to Claude Haiku for deep trend analysis.
    Uses Anthropic Batch API when possible for cost savings.
    """

    def __init__(self, config: dict):
        self.config = config
        tier2_cfg = config.get("analysis", {}).get("tier2", {})
        self.model = tier2_cfg.get("model", "claude-haiku-4-5-20251001")
        self.top_n = tier2_cfg.get("top_reels_to_analyze", 15)
        self.max_input_tokens = tier2_cfg.get("max_input_tokens", 8000)
        self.max_output_tokens = tier2_cfg.get("max_output_tokens", 3000)
        self.use_batch = tier2_cfg.get("use_batch_api", True)
        self.historical_days = tier2_cfg.get("historical_context_days", 7)
        self.temperature = tier2_cfg.get("temperature", 0.3)

        api_key = (
            config.get("api_keys", {}).get("anthropic", "")
            or os.environ.get("ANTHROPIC_API_KEY", "")
        )

        if ANTHROPIC_AVAILABLE and api_key:
            self.client = anthropic.Anthropic(api_key=api_key)
        else:
            self.client = None
            if not api_key:
                logger.warning("ANTHROPIC_API_KEY not set; LLM analysis will be skipped")

    def _is_configured(self) -> bool:
        return self.client is not None and ANTHROPIC_AVAILABLE

    def analyze(
        self,
        scored_reels: List[Dict],
        tier1_results: Dict,
        historical_context: str = "",
        dry_run: bool = False,
    ) -> Optional[Dict]:
        """
        Run LLM analysis on top scored reels.

        Args:
            scored_reels: Output from ViralityScorer.score_batch()
            tier1_results: Output from Tier1Analyzer.analyze()
            historical_context: Summary of last N days of trends
            dry_run: If True, return mock data without API calls

        Returns:
            Parsed trend analysis dict, or None on failure
        """
        if dry_run:
            return self._mock_analysis()

        if not self._is_configured():
            logger.warning("LLM analysis skipped — not configured")
            return None

        # Select top N reels for analysis
        top_reels = scored_reels[:self.top_n]
        if not top_reels:
            logger.warning("No reels to analyze")
            return None

        # Build the prompt
        reels_json = self._format_reels_for_prompt(top_reels)
        tier1_summary = self._summarize_tier1(tier1_results)
        today = str(date.today())

        prompt = TREND_ANALYSIS_PROMPT.format(
            reels_json=reels_json,
            historical_context=historical_context or "No historical data available yet.",
            tier1_signals=tier1_summary,
            date=today,
        )

        # Use batch API if enabled, else direct API
        if self.use_batch:
            result = self._run_batch_analysis(prompt)
        else:
            result = self._run_direct_analysis(prompt)

        return result

    def _format_reels_for_prompt(self, scored_reels: List[Dict]) -> str:
        """Format reel data for LLM consumption (compact but informative)."""
        reels_data = []
        for i, item in enumerate(scored_reels):
            reel: ReelData = item["reel"]
            reels_data.append({
                "rank": i + 1,
                "username": reel.username,
                "followers": reel.follower_count,
                "caption": reel.caption[:300],
                "hashtags": reel.hashtags[:15],
                "audio": reel.audio_name,
                "audio_artist": reel.audio_artist,
                "likes": reel.likes,
                "comments": reel.comments,
                "views": reel.views,
                "engagement_velocity": item["engagement_velocity"],
                "virality_score": item["virality_score"],
                "audio_reuse_count": item["audio_reuse_count"],
                "posted_hours_ago": round(reel.hours_since_posted(), 1),
                "duration_seconds": reel.duration_seconds,
                "url": reel.url,
            })
        return json.dumps(reels_data, indent=2, default=str)

    def _summarize_tier1(self, tier1: Dict) -> str:
        """Create a compact summary of Tier 1 findings for the LLM context."""
        if not tier1:
            return "No Tier 1 analysis available."

        parts = []

        # Top audio tracks
        audio_trends = tier1.get("audio_trends", [])[:5]
        if audio_trends:
            audio_list = [
                f"'{a['audio_name']}' by {a.get('artist', 'unknown')} (used {a['reuse_count']}x, avg vel {a['avg_engagement_velocity']})"
                for a in audio_trends
            ]
            parts.append("TOP AUDIO TRACKS:\n" + "\n".join(f"  - {a}" for a in audio_list))

        # Top hashtags
        top_tags = tier1.get("hashtag_analysis", {}).get("top_hashtags", [])[:10]
        if top_tags:
            tag_list = [f"#{t['hashtag']} ({t['count']}x, score {t['trend_score']})" for t in top_tags]
            parts.append("TOP HASHTAGS:\n  " + ", ".join(tag_list))

        # Emerging clusters
        emerging = tier1.get("hashtag_analysis", {}).get("emerging_clusters", [])[:5]
        if emerging:
            em_list = [f"{e['hashtag_pair']} ({e['today_count']}x today, {e['historical_count']} historical)" for e in emerging]
            parts.append("EMERGING HASHTAG CLUSTERS:\n" + "\n".join(f"  - {e}" for e in em_list))

        # Best posting times
        best_hours = tier1.get("posting_patterns", {}).get("best_posting_hours", [])[:3]
        if best_hours:
            hours_str = ", ".join(f"{h['hour']}:00 UTC (vel: {h['avg_velocity']})" for h in best_hours)
            parts.append(f"BEST POSTING HOURS: {hours_str}")

        # Format analysis
        fmt = tier1.get("format_analysis", {})
        best_fmt = fmt.get("best_performing_format", "unknown")
        parts.append(f"BEST PERFORMING FORMAT: {best_fmt}")

        return "\n\n".join(parts) if parts else "Tier 1 analysis produced no signals."

    def _run_direct_analysis(self, prompt: str) -> Optional[Dict]:
        """Send prompt directly to Claude API."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_output_tokens,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.content[0].text
            return self._parse_llm_response(content)
        except Exception as e:
            logger.error(f"Direct LLM analysis failed: {e}")
            return None

    def _run_batch_analysis(self, prompt: str) -> Optional[Dict]:
        """Submit to Anthropic Batch API for 50% cost reduction."""
        try:
            # Create batch with single request
            batch = self.client.messages.batches.create(
                requests=[
                    {
                        "custom_id": f"trend-analysis-{date.today()}",
                        "params": {
                            "model": self.model,
                            "max_tokens": self.max_output_tokens,
                            "temperature": self.temperature,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                    }
                ]
            )

            batch_id = batch.id
            logger.info(f"Submitted batch job: {batch_id}")

            # Poll for completion (batch API can take minutes)
            return self._wait_for_batch(batch_id)

        except anthropic.BadRequestError as e:
            logger.warning(f"Batch API not available, falling back to direct: {e}")
            return self._run_direct_analysis(prompt)
        except Exception as e:
            logger.error(f"Batch LLM analysis failed: {e}")
            return None

    def _wait_for_batch(self, batch_id: str, max_wait: int = 600) -> Optional[Dict]:
        """Poll Anthropic batch until complete."""
        deadline = time.time() + max_wait
        wait = 10

        while time.time() < deadline:
            try:
                batch = self.client.messages.batches.retrieve(batch_id)
                status = batch.processing_status

                if status == "ended":
                    # Retrieve results
                    for result in self.client.messages.batches.results(batch_id):
                        if result.result.type == "succeeded":
                            content = result.result.message.content[0].text
                            return self._parse_llm_response(content)
                        else:
                            logger.error(f"Batch request failed: {result.result}")
                            return None

                logger.debug(f"Batch {batch_id} status: {status}, waiting {wait}s...")
                time.sleep(wait)
                wait = min(wait * 1.5, 60)  # Exponential backoff, cap at 60s

            except Exception as e:
                logger.warning(f"Error polling batch {batch_id}: {e}")
                time.sleep(wait)

        logger.error(f"Batch {batch_id} timed out after {max_wait}s")
        return None

    def _parse_llm_response(self, content: str) -> Optional[Dict]:
        """Parse and validate the LLM JSON response."""
        # Strip any markdown code blocks if present
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
            content = content.strip()

        try:
            data = json.loads(content)

            # Basic validation
            if "top_trends" not in data:
                logger.error("LLM response missing 'top_trends' field")
                return None

            # Ensure confidence values are floats in [0, 1]
            for trend in data.get("top_trends", []):
                conf = trend.get("confidence", 0.5)
                trend["confidence"] = max(0.0, min(1.0, float(conf)))

            logger.info(f"Parsed {len(data.get('top_trends', []))} trends from LLM response")
            return data

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Raw response: {content[:500]}")
            return None

    def _mock_analysis(self) -> Dict:
        """Return mock analysis for dry-run mode."""
        return {
            "date": str(date.today()),
            "top_trends": [
                {
                    "trend_name": "DRY RUN - Sample Trend",
                    "trend_category": "dj",
                    "description": "This is mock data from a dry run. No API calls were made.",
                    "evidence": "N/A — dry run mode",
                    "velocity": "emerging",
                    "confidence": 0.99,
                    "marketing_angle": "Configure ANTHROPIC_API_KEY to get real insights",
                    "suggested_hashtags": ["djlife", "musictrends"],
                    "suggested_audio": None,
                    "content_format": "15-30s hook-driven reel",
                    "estimated_shelf_life_days": 7,
                }
            ],
            "emerging_signals": ["Dry run mode — real signals require API configuration"],
            "dying_trends": [],
            "cross_niche_opportunities": [],
        }


# Fix missing import
import re
