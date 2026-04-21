"""Centralized filesystem paths used across the project."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
RESULTS_DIR = OUTPUT_DIR / "results"
PROGRESS_DIR = OUTPUT_DIR / "progress"
SESSION_DIR = OUTPUT_DIR / "session"

