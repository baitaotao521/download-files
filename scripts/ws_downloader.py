#!/usr/bin/env python3
"""
基于命令行的 WebSocket 下载服务入口。
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv, find_dotenv


def _resolve_base_dir() -> Path:
  """返回当前运行环境中的项目根目录，兼容 PyInstaller。"""
  if getattr(sys, 'frozen', False):
    return Path(getattr(sys, '_MEIPASS'))  # type: ignore[attr-defined]
  return Path(__file__).resolve().parents[1]


ROOT_DIR = _resolve_base_dir()
if str(ROOT_DIR) not in sys.path:
  sys.path.insert(0, str(ROOT_DIR))

load_dotenv(find_dotenv(), override=False)

from python_app.config import ServerConfig
from python_app.logging_utils import configure_logging
from python_app.websocket_server import run_server_forever


def parse_args() -> argparse.Namespace:
  """解析 CLI 参数，允许自定义 host/port/output。"""
  parser = argparse.ArgumentParser(
    description='通过 WebSocket 接收飞书临时链接并下载到本地。'
  )
  parser.add_argument('--host', default='127.0.0.1', help='监听地址 (默认: 127.0.0.1)')
  parser.add_argument('--port', type=int, default=11548, help='监听端口 (默认: 11548)')
  parser.add_argument('--output', default='downloads', help='文件保存目录 (默认: ./downloads)')
  parser.add_argument(
    '--log-level',
    choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
    default='INFO',
    help='日志级别 (默认: INFO)'
  )
  parser.add_argument(
    '--download-concurrency',
    type=int,
    default=5,
    help='Python 端下载并发数 (默认: 5)'
  )
  parser.add_argument(
    '--personal-base-token',
    default=None,
    help='可选：用于授权码下载模式的 Personal Base Token'
  )
  return parser.parse_args()


def main() -> None:
  """脚本入口：配置日志、构建配置并启动服务。"""
  args = parse_args()
  configure_logging(args.log_level)
  personal_token = args.personal_base_token or os.environ.get('PERSONAL_BASE_TOKEN')
  config = ServerConfig(
    host=args.host,
    port=args.port,
    output_dir=Path(args.output),
    log_level=args.log_level,
    download_concurrency=args.download_concurrency,
    personal_base_token=personal_token
  )
  try:
    asyncio.run(run_server_forever(config))
  except KeyboardInterrupt:
    print('\nserver interrupted by user, exiting...')


if __name__ == '__main__':
  main()
