from __future__ import annotations

import sys
from pathlib import Path


def get_project_root() -> Path:
  """Return project root, compatible with PyInstaller frozen builds."""
  if getattr(sys, 'frozen', False):
    return Path(getattr(sys, '_MEIPASS'))  # type: ignore[attr-defined]
  return Path(__file__).resolve().parents[1]


def get_public_asset(path: str) -> Path:
  """Resolve a file path inside the public/ directory."""
  return get_project_root() / 'public' / path
