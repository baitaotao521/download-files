"""
WebSocket 服务运行时模块，封装 CLI 与桌面端的共用服务管理逻辑。
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from pathlib import Path
from typing import Optional

import websockets

from .config import ServerConfig
from .downloader import AttachmentDownloader
from .monitor import DownloadMonitor


async def run_server_forever(config: ServerConfig, monitor: Optional[DownloadMonitor] = None) -> None:
  """以 CLI 方式运行 WebSocket 服务，直到用户终止。"""
  downloader = AttachmentDownloader(config, monitor=monitor)
  logging.info('starting CLI server at ws://%s:%s', config.host, config.port)
  try:
    async with websockets.serve(downloader.handle_connection, config.host, config.port):
      await asyncio.Future()
  except asyncio.CancelledError:
    logging.info('server coroutine cancelled, shutting down')
  finally:
    logging.info('server exited')


class WebSocketDownloadServer:
  """在桌面应用中托管 WebSocket 服务的封装类。"""

  def __init__(self, config: ServerConfig, monitor: Optional[DownloadMonitor] = None) -> None:
    """记录配置并初始化内部状态。"""
    self.config = config
    self.monitor = monitor
    self._loop: Optional[asyncio.AbstractEventLoop] = None
    self._thread: Optional[threading.Thread] = None
    self._stop_event: Optional[asyncio.Event] = None
    self._task: Optional[asyncio.Task] = None
    self._downloader: Optional[AttachmentDownloader] = None

  @property
  def is_running(self) -> bool:
    """返回当前服务是否处于运行状态。"""
    return bool(self._thread and self._thread.is_alive())

  def start(self) -> None:
    """在后台线程中启动 WebSocket 服务。"""
    if self.is_running:
      raise RuntimeError('server is already running')

    def runner() -> None:
      """在线程中启动事件循环。"""
      self._loop = asyncio.new_event_loop()
      asyncio.set_event_loop(self._loop)
      self._stop_event = asyncio.Event()
      downloader = AttachmentDownloader(self.config, monitor=self.monitor)
      self._downloader = downloader
      server_coro = self._serve_until_stopped(downloader, self._stop_event)
      self._task = self._loop.create_task(server_coro)
      try:
        self._loop.run_until_complete(self._task)
      finally:
        pending = asyncio.all_tasks(loop=self._loop)
        for task in pending:
          task.cancel()
        with contextlib.suppress(Exception):
          self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self._loop.close()
        self._downloader = None

    self._thread = threading.Thread(target=runner, daemon=True)
    self._thread.start()

  async def _serve_until_stopped(self, downloader: AttachmentDownloader, stop_event: asyncio.Event) -> None:
    """运行 WebSocket 服务直到 stop_event 被设置。"""
    logging.info('desktop server listening at ws://%s:%s', self.config.host, self.config.port)
    async with websockets.serve(downloader.handle_connection, self.config.host, self.config.port):
      await stop_event.wait()
    logging.info('desktop server stopped')

  def stop(self) -> None:
    """请求后台线程停止，并等待其退出。"""
    if not self.is_running or not self._loop or not self._stop_event:
      return
    future = asyncio.run_coroutine_threadsafe(self._signal_stop(), self._loop)
    future.result(timeout=5)
    self._thread.join(timeout=5)
    self._thread = None
    self._loop = None
    self._stop_event = None
    self._task = None

  async def _signal_stop(self) -> None:
    """在事件循环中设置停止事件。"""
    if self._stop_event and not self._stop_event.is_set():
      self._stop_event.set()

  def update_output_dir(self, new_dir: str | Path) -> Path:
    """更新当前运行服务的保存目录，必要时通知下载器。"""
    if not new_dir:
      raise ValueError('output directory cannot be empty')
    self.config.output_dir = Path(new_dir)
    normalized = self.config.ensure_output_dir()
    if not self.is_running or not self._loop or not self._downloader:
      return normalized

    async def _apply_update() -> Path:
      """在事件循环中调用下载器更新目录。"""
      if not self._downloader:
        return normalized
      return self._downloader.update_output_dir(normalized)

    future = asyncio.run_coroutine_threadsafe(_apply_update(), self._loop)
    return future.result(timeout=5)

  def update_personal_token(self, token: Optional[str]) -> None:
    """更新授权码并同步给运行中的下载器。"""
    normalized = (token or '').strip() or None
    self.config.personal_base_token = normalized
    if not self.is_running or not self._loop or not self._downloader:
      return

    async def _apply_update() -> None:
      """在事件循环中调用下载器更新授权信息。"""
      if self._downloader:
        self._downloader.update_personal_token(normalized)

    future = asyncio.run_coroutine_threadsafe(_apply_update(), self._loop)
    future.result(timeout=5)


__all__ = ['run_server_forever', 'WebSocketDownloadServer']
