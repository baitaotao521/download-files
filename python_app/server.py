"""
WebSocket 附件下载服务与桌面后台控制逻辑。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional, Set

import aiohttp
import websockets

from .config import ServerConfig
from .monitor import DownloadMonitor

WEBSOCKET_LINK_TYPE = 'feishu_attachment_link'
WEBSOCKET_CONFIG_TYPE = 'feishu_attachment_config'
WEBSOCKET_COMPLETE_TYPE = 'feishu_attachment_complete'
ACK_MESSAGE_TYPE = 'feishu_attachment_ack'


class DownloadJobState:
  """维护当前 WebSocket 会话的下载状态。"""

  def __init__(self, handler: 'AttachmentDownloader', session: aiohttp.ClientSession) -> None:
    self.handler = handler
    self.http_session = session
    self.semaphore: Optional[asyncio.Semaphore] = None
    self.tasks: Set[asyncio.Task] = set()
    self.configured = False
    self.zip_after = False
    self.job_dir: Optional[Path] = None
    self.job_id: Optional[str] = None
    self.job_name: Optional[str] = None
    self.total: int = 0
    self.completed = False

  async def configure(self, data: Dict[str, Any], websocket) -> bool:
    """应用前端传来的配置，若缺失则通知前端并阻止下载。"""
    if self.configured:
      return True
    try:
      concurrent_raw = data.get('concurrent')
      if concurrent_raw is None:
        concurrent = self.handler.default_concurrency
      else:
        concurrent = int(concurrent_raw)
        if concurrent <= 0:
          raise ValueError('concurrent must be > 0')
      zip_after = bool(data.get('zipAfterDownload'))
      job_id = str(data.get('jobId') or int(time.time()))
      job_name = data.get('zipName') or data.get('jobName') or f'download_{job_id}'
      total = int(data.get('total') or 0)
    except (KeyError, ValueError, TypeError) as exc:
      await self.handler._send_ack(
        websocket,
        status='error',
        message=f'invalid config payload: {exc}',
        order=None
      )
      return False

    self.semaphore = asyncio.Semaphore(concurrent)
    self.zip_after = zip_after
    self.job_id = job_id
    self.job_name = self.handler._sanitize_component(job_name) or f'download_{job_id}'
    self.job_dir = self.handler._create_job_directory(self.job_name, self.job_id)
    self.total = max(total, 0)
    self.configured = True
    self.handler._monitor_job_started(self.total)
    logging.info('job configured: job_id=%s concurrent=%s zip=%s', self.job_id, concurrent, zip_after)
    return True

  async def enqueue_download(self, data: Dict[str, Any], websocket) -> None:
    """按配置并发下载文件。"""
    if not self.configured or not self.job_dir or not self.semaphore:
      await self.handler._send_ack(
        websocket,
        status='error',
        message='job configuration not received; cannot download.',
        order=data.get('order')
      )
      return
    task = asyncio.create_task(self._download_worker(dict(data), websocket))
    self.tasks.add(task)
    task.add_done_callback(lambda fut: self.tasks.discard(fut))

  async def finalize(self, websocket) -> None:
    """等待所有下载完成，并根据配置执行打包。"""
    if self.completed:
      return
    if self.tasks:
      await asyncio.gather(*self.tasks, return_exceptions=True)
    if self.zip_after and self.job_dir:
      zip_path = await asyncio.to_thread(self._create_zip_archive, self.job_dir)
      await self.handler._send_ack(
        websocket,
        status='success',
        message=str(zip_path),
        order=None,
        extra={'stage': 'zip', 'path': str(zip_path)}
      )
    await self.handler._send_ack(
      websocket,
      status='success',
      message='job completed',
      order=None,
      extra={'stage': 'job_complete', 'jobId': self.job_id}
    )
    self.completed = True
    self.handler._monitor_job_finished()

  async def shutdown(self) -> None:
    """在连接异常结束时取消挂起任务。"""
    if not self.tasks:
      self.handler._monitor_job_finished()
      return
    tasks = list(self.tasks)
    self.tasks.clear()
    for task in tasks:
      task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    self.handler._monitor_job_finished()

  async def _download_worker(self, file_info: Dict[str, Any], websocket) -> None:
    """受限的下载任务，负责单个文件处理。"""
    async with self.semaphore:
      download_url = file_info.get('downloadUrl')
      file_name = file_info.get('name')
      relative_path = file_info.get('path', '')
      order = file_info.get('order')
      if not download_url or not file_name:
        await self.handler._send_ack(
          websocket,
          status='error',
          message='missing downloadUrl or name',
          order=order
        )
        return
      success = False
      self.handler._monitor_download_started()
      try:
        target_path = self.handler._build_target_path(relative_path, file_name, base_dir=self.job_dir)
        saved_path = await self.handler._download_file(self.http_session, download_url, target_path)
        success = True
      except ValueError as exc:
        await self.handler._send_ack(
          websocket,
          status='error',
          message=str(exc),
          order=order
        )
        return
      except Exception as exc:  # noqa: BLE001
        logging.exception('download failed for %s', file_name)
        await self.handler._send_ack(
          websocket,
          status='error',
          message=str(exc),
          order=order
        )
        return
      finally:
        self.handler._monitor_download_finished(success=success)
      await self.handler._send_ack(
        websocket,
        status='success',
        message=str(saved_path),
        order=order,
        extra={
          'size': file_info.get('size'),
          'name': file_name,
          'path': str(saved_path.relative_to(self.job_dir)),
          'stage': 'file'
        }
      )

  def _create_zip_archive(self, job_dir: Path) -> Path:
    """同步创建 ZIP 包，供 finalize 调用。"""
    zip_path = job_dir.with_suffix('.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
      for file_path in job_dir.rglob('*'):
        if file_path.is_file():
          zipf.write(file_path, arcname=file_path.relative_to(job_dir))
    return zip_path


def configure_logging(level: str) -> None:
  """使用统一格式配置日志输出。"""
  logging.basicConfig(
    level=getattr(logging, level.upper(), logging.INFO),
    format='%(asctime)s | %(levelname)s | %(message)s'
  )


class AttachmentDownloader:
  """处理 WebSocket 消息并负责飞书附件下载。"""

  def __init__(self, config: ServerConfig, monitor: Optional[DownloadMonitor] = None) -> None:
    """记录输出目录并保存默认配置。"""
    self.config = config
    self.output_dir = config.ensure_output_dir()
    self.default_concurrency = config.normalized_concurrency()
    self.monitor = monitor

  async def handle_connection(self, websocket, path=None) -> None:
    """处理单个客户端连接，并监听其消息流。"""
    peer = getattr(websocket, 'remote_address', ('unknown', ''))
    logging.info('client connected %s:%s', peer[0], peer[1])
    self._monitor_connection(True)
    async with aiohttp.ClientSession() as session:
      job_state = DownloadJobState(self, session)
      try:
        async for message in websocket:
          await self._process_message(message, websocket, job_state)
      except websockets.ConnectionClosedOK:
        logging.info('client closed the connection normally')
      except websockets.ConnectionClosedError as exc:
        logging.warning('connection closed with error: %s', exc)
      finally:
        await job_state.shutdown()
        self._monitor_connection(False)

  async def _process_message(self, message: str, websocket, job_state: DownloadJobState) -> None:
    """解析前端消息并调度下载流程。"""
    try:
      payload = json.loads(message)
    except json.JSONDecodeError as exc:
      logging.error('invalid json payload: %s', exc)
      return

    msg_type = payload.get('type')
    data = payload.get('data') or {}

    if msg_type == WEBSOCKET_CONFIG_TYPE:
      await job_state.configure(data, websocket)
      return
    if msg_type == WEBSOCKET_LINK_TYPE:
      await job_state.enqueue_download(data, websocket)
      return
    if msg_type == WEBSOCKET_COMPLETE_TYPE:
      await job_state.finalize(websocket)
      return

    logging.debug('skip unknown message type=%s', msg_type)

  def _build_target_path(self, relative_path: str, file_name: str, base_dir: Optional[Path] = None) -> Path:
    """组合前端的路径信息并防止目录穿越。"""
    root_dir = base_dir or self.output_dir
    safe_name = Path(file_name).name or 'unknown'
    safe_relative = Path(relative_path.replace('\\', '/'))
    tentative_path = (root_dir / safe_relative / safe_name).resolve()
    if not str(tentative_path).startswith(str(root_dir)):
      raise ValueError('invalid path detected, aborting download.')
    return self._ensure_unique_name(tentative_path)

  def _ensure_unique_name(self, destination: Path) -> Path:
    """为已存在的文件追加编号后缀，避免覆盖。"""
    if not destination.exists():
      return destination
    stem = destination.stem
    suffix = destination.suffix
    parent = destination.parent
    counter = 1
    while True:
      candidate = parent / f'{stem}_{counter}{suffix}'
      if not candidate.exists():
        return candidate
      counter += 1
    return destination

  def _sanitize_component(self, value: str) -> str:
    """移除路径中不安全的字符。"""
    allowed = '-_'
    return ''.join(ch for ch in value if ch.isalnum() or ch in allowed).strip(allowed)

  def _create_job_directory(self, job_name: str, job_id: Optional[str]) -> Path:
    """为每个任务创建独立的保存目录。"""
    base_name = job_name or f'download_{job_id}'
    target = self.output_dir / base_name
    if target.exists():
      suffix = job_id or str(int(time.time()))
      target = self.output_dir / f'{base_name}_{suffix}'
    target.mkdir(parents=True, exist_ok=True)
    return target

  async def _download_file(self, session: aiohttp.ClientSession, url: str, destination: Path) -> Path:
    """使用 aiohttp 流式下载文件。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    logging.info('downloading %s -> %s', url, destination)
    async with session.get(url) as response:
      response.raise_for_status()
      with destination.open('wb') as file_obj:
        async for chunk in response.content.iter_chunked(128 * 1024):
          file_obj.write(chunk)
    logging.info('saved file to %s', destination)
    return destination

  async def _send_ack(
    self,
    websocket,
    *,
    status: str,
    message: str,
    order: Optional[int],
    extra: Optional[Dict[str, Any]] = None
  ) -> None:
    """向前端回传 ACK，便于 UI 展示。"""
    payload: Dict[str, Any] = {
      'type': ACK_MESSAGE_TYPE,
      'data': {
        'status': status,
        'message': message,
        'order': order
      }
    }
    if extra:
      payload['data'].update(extra)
    if getattr(websocket, 'closed', False):
      logging.debug('websocket already closed, skip ack for %s', payload['data'])
      return
    try:
      await websocket.send(json.dumps(payload))
    except websockets.ConnectionClosed:
      logging.debug('websocket closed before ack could be sent')
    except Exception as exc:  # noqa: BLE001
      logging.warning('failed to send ack: %s', exc)

  def _monitor_connection(self, connected: bool) -> None:
    """更新连接状态供桌面端展示。"""
    if self.monitor:
      self.monitor.set_connection(connected)

  def _monitor_job_started(self, total: int) -> None:
    """记录新的下载任务。"""
    if self.monitor:
      self.monitor.start_job(total)

  def _monitor_download_started(self) -> None:
    """记录单个文件开始下载。"""
    if self.monitor:
      self.monitor.start_download()

  def _monitor_download_finished(self, *, success: bool) -> None:
    """记录单个文件完成。"""
    if self.monitor:
      self.monitor.finish_download(success)

  def _monitor_job_finished(self) -> None:
    """通知任务阶段结束。"""
    if self.monitor:
      self.monitor.job_finished()


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
