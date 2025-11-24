#!/usr/bin/env python3
"""
桌面程序入口：提供 GUI 包装的 WebSocket 下载服务。
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
  sys.path.insert(0, str(ROOT_DIR))

from python_app.ui import launch_desktop_app


def main() -> None:
  """启动桌面 GUI。"""
  launch_desktop_app()


if __name__ == '__main__':
  main()
