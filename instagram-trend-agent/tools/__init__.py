"""LangChain tools for the Instagram Reels trend agent."""

from tools.budget_tool import check_budget, record_spend
from tools.scrape_tool import scrape_instagram_reels
from tools.analysis_tools import run_local_analysis, deduplicate_and_persist
from tools.llm_analysis_tool import analyze_trends_with_llm
from tools.output_tools import write_trend_outputs

ALL_TOOLS = [
    check_budget,
    scrape_instagram_reels,
    run_local_analysis,
    deduplicate_and_persist,
    analyze_trends_with_llm,
    write_trend_outputs,
    record_spend,
]
