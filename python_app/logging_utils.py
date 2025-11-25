"""
统一的日志配置工具，供 CLI 与桌面端共同调用。
"""
import logging


def configure_logging(level: str) -> None:
  """使用统一格式配置日志输出。"""
  logging.basicConfig(
    level=getattr(logging, level.upper(), logging.INFO),
    format='%(asctime)s | %(levelname)s | %(message)s'
  )


__all__ = ['configure_logging']
