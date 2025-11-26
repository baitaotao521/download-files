"""
用户偏好配置，负责将桌面端的常用字段持久化到 JSON 文件。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict

CONFIG_DIR = Path.home() / '.feishu_attachment_downloader'
CONFIG_FILE = CONFIG_DIR / 'user_settings.json'
DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 11548
DEFAULT_OUTPUT_DIR = 'downloads'
DEFAULT_LANGUAGE = 'zh'
DEFAULT_FILE_DISPLAY_LIMIT = 1000


@dataclass
class UserPreferences:
  """记录需要持久化的桌面端配置项。"""

  host: str = DEFAULT_HOST
  port: int = DEFAULT_PORT
  output_dir: str = DEFAULT_OUTPUT_DIR
  language: str = DEFAULT_LANGUAGE
  personal_base_token: str = ''
  file_display_limit: int = DEFAULT_FILE_DISPLAY_LIMIT


def _coerce_port(value: Any) -> int:
  """将 JSON 中的端口值转换为合法整数。"""
  try:
    port = int(value)
  except (TypeError, ValueError):
    return DEFAULT_PORT
  return port if 1 <= port <= 65535 else DEFAULT_PORT


def load_user_config() -> UserPreferences:
  """从 JSON 文件加载用户配置，若不存在则返回默认配置。"""
  try:
    raw = CONFIG_FILE.read_text(encoding='utf-8')
    data: Dict[str, Any] = json.loads(raw)
  except FileNotFoundError:
    return UserPreferences()
  except json.JSONDecodeError:
    return UserPreferences()
  host = str(data.get('host') or DEFAULT_HOST)
  port = _coerce_port(data.get('port'))
  output_dir = str(data.get('output_dir') or DEFAULT_OUTPUT_DIR)
  language = str(data.get('language') or DEFAULT_LANGUAGE)
  personal_base_token = str(data.get('personal_base_token') or '')
  file_display_limit = _coerce_file_limit(data.get('file_display_limit'))
  return UserPreferences(
    host=host,
    port=port,
    output_dir=output_dir,
    language=language,
    personal_base_token=personal_base_token,
    file_display_limit=file_display_limit
  )


def _coerce_file_limit(value: Any) -> int:
  """将文件展示数量限制转换为合理范围。"""
  try:
    parsed = int(value)
  except (TypeError, ValueError):
    return DEFAULT_FILE_DISPLAY_LIMIT
  if parsed < 100:
    return 100
  if parsed > 5000:
    return 5000
  return parsed


def save_user_config(preferences: UserPreferences) -> None:
  """将用户配置写入 JSON 文件。"""
  CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
  payload = asdict(preferences)
  CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
