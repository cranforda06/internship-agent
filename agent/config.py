"""Loads settings from config.yaml and secrets from .env."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# The project folder (the one containing main.py). Using this instead of the
# "current directory" means the agent works no matter where you run it from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config(path=PROJECT_ROOT / "config.yaml"):
    """Read config.yaml and return it as a Python dictionary."""
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Turn the file paths into full paths inside the project folder.
    config["resume_path"] = PROJECT_ROOT / config["resume_path"]
    config["tracker_path"] = PROJECT_ROOT / config["tracker_path"]
    return config


def get_api_key():
    """Read the Anthropic API key from .env. Only needed from Phase 2 on."""
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key or key == "your-key-here":
        raise RuntimeError(
            "No API key found. Copy .env.example to .env and paste your key in."
        )
    return key
