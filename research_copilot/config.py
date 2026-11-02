"""Settings for the Research Copilot (models, chunking, retrieval, sources)."""

import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

BASE_DIR = Path(__file__).resolve().parent.parent
INDEX_DIR = BASE_DIR / "copilot_index"
SOURCES_FILE = BASE_DIR / "copilot_sources.json"
EVAL_FILE = Path(__file__).resolve().parent / "eval_questions.json"


@dataclass
class Source:
    """One documentation source: a root folder plus include / exclude glob patterns."""
    label: str
    root: str
    include: List[str] = field(default_factory=lambda: ["**/*.md"])
    exclude: List[str] = field(default_factory=list)


@dataclass
class Settings:
    ollama_url: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    chat_model: str = os.getenv("COPILOT_CHAT_MODEL", "qwen2.5:1.5b")
    embed_model: str = os.getenv("COPILOT_EMBED_MODEL", "nomic-embed-text")
    chunk_chars: int = 1200
    chunk_overlap: int = 150
    top_k: int = 5
    candidates: int = 30
    rrf_k: int = 60
    temperature: float = 0.1
    num_ctx: int = 4096
    max_answer_tokens: int = 350


# Paths that never enter the index, whatever the source config says
ALWAYS_EXCLUDE = [
    "**/.env*", "**/*secret*", "**/*credential*", "**/.git/**", "**/.venv/**", "**/node_modules/**",
    "**/.claude/**", "**/.codex/**", "**/.agents/**", "**/AGENTS.md", "**/MEMORY.md",
]


def load_sources() -> List[Source]:
    """Reads copilot_sources.json (kept out of git because it points at private folders)."""
    if not SOURCES_FILE.exists():
        raise FileNotFoundError(
            f"{SOURCES_FILE.name} not found. Copy copilot_sources.example.json and point it at your docs."
        )
    raw = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    return [Source(**s) for s in raw["sources"]]
