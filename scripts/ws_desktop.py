#!/usr/bin/env python3
"""
桌面程序入口：提供 GUI 包装的 WebSocket 下载服务。
"""
import sys
from pathlib import Path


def _resolve_base_dir() -> Path:
  """返回当前运行环境中的项目根目录，兼容 PyInstaller。"""
  if getattr(sys, 'frozen', False):
    return Path(getattr(sys, '_MEIPASS'))  # type: ignore[attr-defined]
  return Path(__file__).resolve().parents[1]


ROOT_DIR = _resolve_base_dir()
if str(ROOT_DIR) not in sys.path:
  sys.path.insert(0, str(ROOT_DIR))

from python_app.ui import launch_desktop_app


def main() -> None:
  """启动桌面 GUI。"""
  launch_desktop_app()


if __name__ == '__main__':
  main()
