"""LangChain tool — check and record API budget spend."""

import json

from langchain_core.tools import tool

from tools.config_loader import get_config, get_data_dir


@tool
def check_budget() -> str:
    """
    Check today's API budget: how much has been spent and how much remains.
    Always call this first before scraping or running LLM analysis.
    Returns a JSON summary with keys: date, total_cost_cents_today,
    remaining_cents, daily_ceiling_cents, can_continue.
    """
    from main import BudgetTracker

    config = get_config()
    budget = BudgetTracker(config, get_data_dir())
    summary = budget.summary()
    summary["remaining_cents"] = budget.remaining_cents()
    summary["can_continue"] = budget.can_spend(20)  # ~$0.15/Sonnet call + buffer
    return json.dumps(summary)


@tool
def record_spend(component: str, cost_cents: int, description: str = "") -> str:
    """
    Record an API cost event in the daily budget tracker.
    component: e.g. 'llm_batch', 'scraper'
    cost_cents: integer cost in US cents
    description: short human-readable label
    Returns updated budget summary JSON.
    """
    from main import BudgetTracker

    config = get_config()
    budget = BudgetTracker(config, get_data_dir())
    budget.record(component, cost_cents, description)
    summary = budget.summary()
    summary["remaining_cents"] = budget.remaining_cents()
    return json.dumps(summary)
