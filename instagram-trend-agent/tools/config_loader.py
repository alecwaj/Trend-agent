"""Shared config loader — loaded once, shared across all tools."""

import os
from pathlib import Path
from typing import Optional

import yaml

_config: Optional[dict] = None


def get_config(config_path: Optional[str] = None) -> dict:
    """Return the loaded config, initialising on first call."""
    global _config
    if _config is not None:
        return _config

    if config_path is None:
        root = Path(__file__).parent.parent
        config_path = str(root / "config.yaml")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    env_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "apify": "APIFY_API_KEY",
        "rapidapi": "RAPIDAPI_KEY",
    }
    for key_name, env_var in env_map.items():
        value = os.environ.get(env_var, "")
        if value:
            config.setdefault("api_keys", {})[key_name] = value

    _config = config
    return _config


def get_data_dir() -> str:
    config = get_config()
    return config.get("output", {}).get("data_directory", "data/")


def get_output_dir() -> str:
    config = get_config()
    return config.get("output", {}).get("csv_directory", "outputs/")
