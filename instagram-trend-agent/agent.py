#!/usr/bin/env python3
"""
Instagram Reels Music Trend Intelligence Agent — LangChain Tool-Calling Agent

Uses LangChain 1.x create_agent (backed by LangGraph).  The orchestration LLM
(claude-sonnet-4-6) reasons over the pipeline and calls tools in the right order.
Each tool wraps an existing module — no logic is duplicated, only the wiring changes.

Usage:
    python agent.py                        # Full daily run
    python agent.py --mode dry-run         # Mock data, no real API scraping
    python agent.py --mode analyze-only    # Skip scraping, use today's DB data
    python agent.py --mode scrape-only     # Scrape only, skip LLM analysis
    python agent.py --verbose              # Stream agent reasoning to stdout
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


# ── Bootstrap ─────────────────────────────────────────────────────────────────
# Always run from the directory containing this file so relative paths work.
_ROOT = Path(__file__).parent
os.chdir(_ROOT)
load_dotenv(_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("trend_agent.agent")


# ── System prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the orchestrator for an Instagram Reels music trend intelligence pipeline.
Your job is to call the available tools in the correct order to produce a daily trend report.

PIPELINE ORDER — follow this exactly:
1. check_budget        — verify we have budget headroom before spending anything
2. scrape_instagram_reels — collect raw reel data (pass dry_run as instructed)
3. run_local_analysis  — run Tier 1 zero-cost analysis + virality scoring
4. deduplicate_and_persist — (skip in dry-run) save new reels to SQLite
5. analyze_trends_with_llm — send top reels to Claude Haiku for trend identification
6. record_spend        — log the LLM cost (~1 cent) to the budget tracker
7. write_trend_outputs — write CSV + markdown summary files

RULES:
- If check_budget shows can_continue = false, stop immediately and report the budget state.
- Pass the JSON output of each tool directly into the next tool that needs it.
- In scrape-only mode: stop after step 3 (no LLM analysis, no output writing).
- In analyze-only mode: skip step 2 (scraping); call run_local_analysis with an empty reels list.
- In dry-run mode: pass dry_run=true to scrape_instagram_reels; skip step 4.
- Always call write_trend_outputs last (unless scrape-only mode).
- Be concise in your final response: report files written, trend count, and total cost."""


# ── Mode instructions ──────────────────────────────────────────────────────────

MODE_INSTRUCTIONS = {
    "daily": (
        "Run the full daily Instagram Reels trend analysis pipeline. "
        "Use real scraping (dry_run=false). "
        "Deduplicate and persist new reels. "
        "Run LLM analysis on the top reels. "
        "Write all output files."
    ),
    "dry-run": (
        "Run a complete dry-run of the Instagram Reels trend analysis pipeline. "
        "Use dry_run=true for scraping so mock data is used — no real network calls. "
        "Skip the deduplicate_and_persist step. "
        "Run LLM analysis and write output files normally."
    ),
    "analyze-only": (
        "Run analysis only — do NOT call scrape_instagram_reels. "
        "Proceed directly to run_local_analysis (pass an empty reels JSON: '{\"reels\":[]}')."
        "Then run LLM analysis and write output files."
    ),
    "scrape-only": (
        "Scrape Instagram Reels and run local analysis only. "
        "Do NOT call analyze_trends_with_llm or write_trend_outputs. "
        "Deduplicate and persist new reels to the database. "
        "Report scraping and analysis results only."
    ),
}


# ── Agent construction ─────────────────────────────────────────────────────────

def build_agent(verbose: bool = False):
    """Construct and return a LangChain 1.x agent graph."""
    from langchain.agents import create_agent
    from langchain_anthropic import ChatAnthropic

    from tools import ALL_TOOLS

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY is not set. Copy .env.example → .env and add your key.")
        sys.exit(1)

    # Orchestrator: Sonnet for reasoning quality.
    # The llm_analysis_tool uses Haiku internally (~$0.01/call) to keep costs low.
    orchestrator_llm = ChatAnthropic(
        model="claude-sonnet-4-6",
        anthropic_api_key=api_key,
        temperature=0,          # Deterministic pipeline orchestration
        max_tokens=4096,
    )

    return create_agent(
        model=orchestrator_llm,
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        debug=verbose,
    )


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Instagram Reels Music Trend Intelligence Agent (LangChain)"
    )
    parser.add_argument(
        "--mode",
        choices=list(MODE_INSTRUCTIONS.keys()),
        default="daily",
        help="Run mode (default: daily)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable LangGraph debug tracing",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config YAML (default: config.yaml)",
    )
    args = parser.parse_args()

    if args.config != "config.yaml":
        from tools.config_loader import get_config
        get_config(args.config)

    logger.info(f"=== Instagram Reels Trend Agent (LangChain) — Mode: {args.mode} ===")

    from langchain_core.messages import HumanMessage

    agent = build_agent(verbose=args.verbose)
    instruction = MODE_INSTRUCTIONS[args.mode]

    result = agent.invoke({"messages": [HumanMessage(content=instruction)]})

    # Final message from the agent
    final_message = result["messages"][-1]
    output = (
        final_message.content
        if hasattr(final_message, "content")
        else str(final_message)
    )

    print("\n" + "=" * 60)
    print("AGENT RESULT")
    print("=" * 60)
    print(output)


if __name__ == "__main__":
    main()
