"""LangChain tools — write CSV reports and markdown summary."""

import json

from langchain_core.tools import tool

from tools.config_loader import get_config, get_data_dir, get_output_dir
from tools.helpers import dict_to_reel, dict_to_scored_reel


def _deserialise_scored_reels(scored_reels_json: str) -> list:
    payload = json.loads(scored_reels_json)
    raw = payload.get("scored_reels", payload) if isinstance(payload, dict) else payload
    return [dict_to_scored_reel(item) for item in raw]


def _deserialise_tier1(tier1_json: str) -> dict:
    payload = json.loads(tier1_json)
    return payload.get("tier1_results", payload) if isinstance(payload, dict) else payload


@tool
def write_trend_outputs(
    trends_json: str,
    scored_reels_json: str,
    tier1_json: str,
    budget_json: str,
    scraper_summary_json: str = "{}",
) -> str:
    """
    Write all output files for today's run:
      - outputs/trends_YYYY-MM-DD.csv   (daily trend CSV)
      - outputs/trend_log.csv           (cumulative trend database)
      - outputs/daily_summary_YYYY-MM-DD.md  (human-readable brief)

    Input trends_json: JSON string of top_trends from analyze_trends_with_llm,
                       or empty string / "{}" to fall back to Tier 1 data.
    Input scored_reels_json: the "scored_reels" array from run_local_analysis.
    Input tier1_json: the "tier1_results" dict from run_local_analysis.
    Input budget_json: JSON from check_budget.
    Input scraper_summary_json: optional JSON from scrape_instagram_reels source_summary.

    Returns JSON: {"csv_path": "...", "summary_path": "...", "trend_count": N}
    """
    from analysis.trend_tracker import TrendTracker
    from output.csv_writer import CSVWriter
    from output.summary_writer import SummaryWriter

    config = get_config()
    output_dir = get_output_dir()

    scored_reels = _deserialise_scored_reels(scored_reels_json)
    tier1_results = _deserialise_tier1(tier1_json)
    budget_summary = json.loads(budget_json) if budget_json else {}
    scraper_summary = json.loads(scraper_summary_json) if scraper_summary_json else {}

    tracker = TrendTracker(config, output_dir)
    csv_writer = CSVWriter(config, output_dir)
    summary_writer = SummaryWriter(config, output_dir)

    # Parse top_trends from LLM output (may be a full TrendReport or just the list)
    llm_analysis = None
    enriched_trends = []
    csv_path = ""

    if trends_json and trends_json not in ("{}", "null", ""):
        parsed = json.loads(trends_json)
        top_trends_raw = (
            parsed.get("top_trends", [])
            if isinstance(parsed, dict)
            else parsed
        )
        if top_trends_raw:
            # Enrich with historical tracking data
            enriched_trends = tracker.update(top_trends_raw)

            # Build llm_analysis in the shape the existing SummaryWriter expects
            llm_analysis = {
                "top_trends": enriched_trends,
                "emerging_signals": parsed.get("emerging_signals", []) if isinstance(parsed, dict) else [],
                "dying_trends": parsed.get("dying_trends", []) if isinstance(parsed, dict) else [],
                "cross_niche_opportunities": parsed.get("cross_niche_opportunities", []) if isinstance(parsed, dict) else [],
            }
            csv_path = csv_writer.write_daily(enriched_trends, scored_reels)

    if not csv_path:
        # Fallback: derive trends from Tier 1 when LLM analysis is unavailable
        csv_path = csv_writer.write_fallback_csv(scored_reels, tier1_results)

    md_path = summary_writer.write(
        trends=enriched_trends,
        tier1_results=tier1_results,
        llm_analysis=llm_analysis,
        budget_summary=budget_summary,
        scraper_summary=scraper_summary,
    )

    return json.dumps({
        "csv_path": str(csv_path),
        "summary_path": str(md_path),
        "trend_count": len(enriched_trends),
    })
