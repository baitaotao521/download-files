"""提供 Python 端展示版本号的工具：优先外部注入，缺失则读取 _version.txt 或默认版本。"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from .paths import get_project_root

VERSION_FILE = get_project_root() / 'python_app' / '_version.txt'


def _read_version_file() -> Optional[str]:
  if VERSION_FILE.exists():
    value = VERSION_FILE.read_text(encoding='utf-8').strip()
    return value or None
  return None


@lru_cache()
def get_app_version() -> str:
  """优先返回 APP_VERSION；若不存在则读取 _version.txt，再回退默认版本。"""
  env_version = os.environ.get('APP_VERSION')
  if env_version and env_version.strip():
    return env_version.strip()
  file_version = _read_version_file()
  if file_version:
    return file_version
  return '0.0.0'


APP_VERSION = get_app_version()
