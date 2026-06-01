"""Paths and imports for the unmodified official CHESCA submission."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def official_root() -> Path:
    return project_root() / "CHESCA-main"


def schema_path(dataset_name: str) -> Path:
    path = official_root() / "data" / "schemas" / dataset_name / "schema.json"
    if not path.exists():
        names = ", ".join(available_datasets())
        raise FileNotFoundError(f"Unknown CHESCA dataset '{dataset_name}'. Available: {names}")
    return path


def available_datasets() -> list[str]:
    schema_root = official_root() / "data" / "schemas"
    if not schema_root.exists():
        return []
    return sorted(p.name for p in schema_root.iterdir() if (p / "schema.json").exists())


def configure_official_imports() -> None:
    root = str(official_root())
    if root not in sys.path:
        sys.path.insert(0, root)


@contextmanager
def official_working_directory() -> Iterator[None]:
    """Run code where CHESCA can resolve its pretrained model relative paths."""
    previous = Path.cwd()
    configure_official_imports()
    os.chdir(official_root())
    try:
        yield
    finally:
        os.chdir(previous)


def official_agent_class():
    configure_official_imports()
    from agents.user_agent import SubmissionAgent

    return SubmissionAgent


def official_reward_class():
    configure_official_imports()
    from rewards.user_reward import SubmissionReward

    return SubmissionReward
