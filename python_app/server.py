"""
兼容层模块，聚合下载器、日志与运行时接口，便于旧代码继续使用。
"""
from .downloader import (
  ACK_MESSAGE_TYPE,
  WEBSOCKET_COMPLETE_TYPE,
  WEBSOCKET_CONFIG_TYPE,
  WEBSOCKET_LINK_TYPE,
  AttachmentDownloader,
  DownloadJobState
)
from .logging_utils import configure_logging
from .websocket_server import WebSocketDownloadServer, run_server_forever

__all__ = [
  'ACK_MESSAGE_TYPE',
  'WEBSOCKET_COMPLETE_TYPE',
  'WEBSOCKET_CONFIG_TYPE',
  'WEBSOCKET_LINK_TYPE',
  'AttachmentDownloader',
  'DownloadJobState',
  'WebSocketDownloadServer',
  'configure_logging',
  'run_server_forever'
]
