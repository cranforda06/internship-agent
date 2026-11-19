import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config(path=PROJECT_ROOT / "config.yaml"):
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    config["resume_path"] = PROJECT_ROOT / config["resume_path"]
    config["tracker_path"] = PROJECT_ROOT / config["tracker_path"]
    config["output_dir"] = PROJECT_ROOT / config.get("output_dir", "output/resumes")
    return config


def get_api_key():
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key or key == "your-key-here":
        raise RuntimeError(
            "No API key found. Copy .env.example to .env and paste your key in."
        )
    return key
