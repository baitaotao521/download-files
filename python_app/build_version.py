from __future__ import annotations

import os
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent / '_version.txt'


def write_version_file(version: str) -> None:
  """将版本号写入 _version.txt 供运行时读取。"""
  VERSION_FILE.write_text(version, encoding='utf-8')


if __name__ == '__main__':
  target_version = os.environ.get('APP_VERSION', '').strip()
  if not target_version:
    raise SystemExit('APP_VERSION env is required when writing version file')
  write_version_file(target_version)
