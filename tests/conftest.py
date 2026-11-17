"""Shared test setup: run everything offline (no API calls) with a small cluster."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["LEVELFORGE_OFFLINE"] = "1"          # agents never call the LLM in CI
os.environ.setdefault("LEVELFORGE_WORKERS", "2")  # small cluster for the MCP server tests
os.environ.setdefault("NO_COLOR", "1")
