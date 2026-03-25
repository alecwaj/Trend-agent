"""LangChain tools — Tier 1 local analysis and virality scoring."""

import json

from langchain_core.tools import tool

from tools.config_loader import get_config, get_data_dir
from tools.helpers import dict_to_reel, scored_reel_to_dict


@tool
def run_local_analysis(reels_json: str) -> str:
    """
    Run zero-cost local analysis on scraped reels (no API calls).

    Executes two passes:
      - Tier 1 analysis: engagement velocity, audio tracking, hashtag
        co-occurrence, TF-IDF keyword extraction, format analysis.
      - Virality scoring: composite score = velocity(40%) +
        audio_reuse(30%) + hashtag_trend(30%).

    Input: JSON string from scrape_instagram_reels (the "reels" array, or the
           full payload — both are accepted).

    Returns JSON: {
      "scored_reels": [...],   # sorted by virality_score desc
      "tier1_results": {...},  # full Tier 1 output
      "top_virality_score": float
    }
    """
    from analysis.tier1_local import Tier1Analyzer
    from analysis.virality_scorer import ViralityScorer

    config = get_config()

    payload = json.loads(reels_json)
    raw_list = payload.get("reels", payload) if isinstance(payload, dict) else payload
    reels = [dict_to_reel(r) for r in raw_list]

    tier1 = Tier1Analyzer(config, get_data_dir())
    tier1_results = tier1.analyze(reels)

    scorer = ViralityScorer(config)
    scored_reels = scorer.score_batch(reels)

    top_score = scored_reels[0]["virality_score"] if scored_reels else 0.0

    return json.dumps({
        "scored_reels": [scored_reel_to_dict(item) for item in scored_reels],
        "tier1_results": tier1_results,
        "top_virality_score": top_score,
    }, default=str)


@tool
def deduplicate_and_persist(reels_json: str, scored_reels_json: str) -> str:
    """
    Deduplicate reels against the SQLite database and persist new ones.
    Also triggers auto-discovery of high-performing accounts.

    Input reels_json: the "reels" array from scrape_instagram_reels.
    Input scored_reels_json: the "scored_reels" array from run_local_analysis.

    Returns JSON: {"new_reels_count": N, "total_reels": M}
    """
    from main import ReelsDatabase, update_monitored_accounts

    config = get_config()
    data_dir = get_data_dir()

    payload = json.loads(reels_json)
    raw_list = payload.get("reels", payload) if isinstance(payload, dict) else payload
    reels = [dict_to_reel(r) for r in raw_list]

    scored_payload = json.loads(scored_reels_json)
    scored_list = (
        scored_payload.get("scored_reels", scored_payload)
        if isinstance(scored_payload, dict)
        else scored_payload
    )
    scored_map = {item["reel"]["reel_id"]: item for item in scored_list}

    db = ReelsDatabase(db_path=f"{data_dir}reels_raw.db")
    new_reels = db.filter_new(reels)

    inserted = db.insert_reels(new_reels, scored_map)
    update_monitored_accounts(new_reels, config, data_dir)
    db.close()

    return json.dumps({"new_reels_count": inserted, "total_reels": len(reels)})
