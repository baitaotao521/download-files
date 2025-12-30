"""
下载核心模块，负责解析 WebSocket 消息并执行附件下载逻辑。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import zipfile
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Literal, Optional, Set, Tuple

import aiohttp
import websockets

from .config import ServerConfig
from .monitor import DownloadMonitor
from .version import APP_VERSION

try:  # pragma: no cover - optional dependency for授权模式
  from baseopensdk import BaseClient
  from baseopensdk.api.drive.v1 import DownloadMediaRequest
except ImportError:  # noqa: WPS440
  BaseClient = None  # type: ignore[assignment]
  DownloadMediaRequest = None  # type: ignore[assignment]

WEBSOCKET_LINK_TYPE = 'feishu_attachment_link'
WEBSOCKET_CONFIG_TYPE = 'feishu_attachment_config'
WEBSOCKET_COMPLETE_TYPE = 'feishu_attachment_complete'
WEBSOCKET_REFRESH_TYPE = 'feishu_attachment_refresh'
WEBSOCKET_PROBE_TYPE = 'feishu_attachment_probe'
ACK_MESSAGE_TYPE = 'feishu_attachment_ack'

# 仅限制“向前端请求临时链接”的并发数，避免一次性触发大量 refresh 导致排队超时。
DOWNLOAD_URL_REFRESH_MAX_INFLIGHT = 20
# 等待前端回传临时链接的超时时间（秒），可覆盖“前端繁忙/限流”导致的短暂延迟。
DOWNLOAD_URL_REFRESH_TIMEOUT_SECONDS = 10 * 60


class DownloadJobState:
  """维护当前 WebSocket 会话的下载状态。"""

  def __init__(self, handler: 'AttachmentDownloader', session: aiohttp.ClientSession) -> None:
    """保存下载器引用、HTTP 会话与当前任务上下文。"""
    self.handler = handler
    self.http_session = session
    self.semaphore: Optional[asyncio.Semaphore] = None
    self.tasks: Set[asyncio.Task] = set()
    self._finalize_task: Optional[asyncio.Task] = None
    self.configured = False
    self.zip_after = False
    self.job_dir: Optional[Path] = None
    self.job_id: Optional[str] = None
    self.job_name: Optional[str] = None
    self.total: int = 0
    self.completed = False
    self.concurrency: int = handler.default_concurrency
    self.download_mode: Literal['url', 'token'] = 'url'
    self.app_token: Optional[str] = None
    self.table_id: Optional[str] = None
    self.sdk_client: Any = None
    self._completion_requested = False
    self._file_payloads: Dict[str, Dict[str, Any]] = {}
    self._failed_file_keys: Set[str] = set()
    self._download_url_refresh_waiters: Dict[str, asyncio.Future[str]] = {}
    self._download_url_refresh_cache: Dict[str, str] = {}
    self._download_url_refresh_semaphore = asyncio.Semaphore(DOWNLOAD_URL_REFRESH_MAX_INFLIGHT)
    self._retried_failed_files_once = False

  def _normalize_file_payload(self, data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """标准化单文件 payload，并返回 (file_key, normalized_payload)。"""
    normalized = dict(data)
    order = normalized.get('order')
    if order is not None:
      try:
        normalized['order'] = int(order)
      except (TypeError, ValueError):
        pass
    normalized['path'] = str(normalized.get('path') or '')
    if 'name' in normalized and normalized['name'] is not None:
      normalized['name'] = str(normalized['name'])
    if 'downloadUrl' in normalized and normalized['downloadUrl'] is not None:
      normalized['downloadUrl'] = str(normalized['downloadUrl'])
    identifier = normalized.get('recordId') or normalized.get('token') or normalized.get('downloadUrl')
    file_key = self.handler._build_file_key(normalized.get('order'), normalized.get('name'), normalized['path'], identifier)
    return (file_key, normalized)

  def _remember_file_payload(self, file_key: str, payload: Dict[str, Any]) -> None:
    """缓存文件 payload 供下载结束后重试失败文件。"""
    existing = self._file_payloads.get(file_key) or {}
    merged = dict(existing)
    for key, value in payload.items():
      if value is None:
        continue
      merged[key] = value
    self._file_payloads[file_key] = merged

  def _remember_download_url(self, file_key: str, download_url: str) -> None:
    """在 URL 模式下缓存临时下载链接，便于断线后重试失败文件。"""
    if not download_url:
      return
    payload = self._file_payloads.get(file_key) or {}
    payload['downloadUrl'] = str(download_url)
    self._file_payloads[file_key] = payload

  def get_failed_file_payloads(self) -> List[Dict[str, Any]]:
    """返回失败文件的 payload 列表（用于桌面端提示后重试）。"""
    failed_payloads: List[Dict[str, Any]] = []
    for file_key in self._failed_file_keys:
      payload = self._file_payloads.get(file_key)
      if isinstance(payload, dict) and payload:
        failed_payloads.append(dict(payload))
    failed_payloads.sort(key=lambda item: (item.get('order') is None, item.get('order') or 0))
    return failed_payloads

  async def retry_failed_files_via_frontend(self, websocket) -> int:
    """客户端模式兜底：对失败文件再重试一轮，并强制向前端刷新临时链接。"""
    if self.download_mode != 'url':
      return 0
    if self._retried_failed_files_once:
      return 0
    if not self._failed_file_keys:
      return 0
    if websocket is None or getattr(websocket, 'closed', False):
      return 0

    failed_payloads = self.get_failed_file_payloads()
    if not failed_payloads:
      return 0
    retry_payloads: List[Dict[str, Any]] = []
    for payload in failed_payloads:
      order = payload.get('order')
      if not isinstance(order, int):
        continue
      retry_payload = dict(payload)
      retry_payload.pop('downloadUrl', None)
      retry_payloads.append(retry_payload)
    if not retry_payloads:
      return 0

    self._retried_failed_files_once = True
    await self.handler._send_ack(
      websocket,
      status='success',
      message=f'Retrying {len(retry_payloads)} failed file(s)...',
      order=None,
      extra={'stage': 'retry_failed_files', 'failed': len(retry_payloads)}
    )
    for payload in retry_payloads:
      await self.enqueue_download(payload, websocket)
    return len(retry_payloads)

  async def request_download_url_refresh(
    self,
    websocket,
    *,
    order: Optional[int],
    file_key: str,
    file_name: str
  ) -> str:
    """向前端请求刷新 downloadUrl，并等待新的临时链接返回。"""
    if websocket is None or getattr(websocket, 'closed', False):
      raise RuntimeError('WebSocket 已断开，无法刷新下载链接，请在前端重新发起下载。')
    if order is None:
      raise RuntimeError('missing order for download url refresh')
    cached_url = self._download_url_refresh_cache.pop(file_key, None)
    if cached_url:
      logging.debug('consume cached download url for %s (%s)', file_name, file_key)
      self._remember_download_url(file_key, str(cached_url))
      return cached_url
    async with self._download_url_refresh_semaphore:
      waiter = self._download_url_refresh_waiters.get(file_key)
      if not waiter or waiter.done():
        waiter = asyncio.get_running_loop().create_future()
        self._download_url_refresh_waiters[file_key] = waiter
      await self.handler._send_ack(
        websocket,
        status='refresh',
        message='正在向前端请求新的下载链接…',
        order=order,
        extra={'stage': 'refresh', 'name': file_name}
      )
      try:
        return await asyncio.wait_for(waiter, timeout=DOWNLOAD_URL_REFRESH_TIMEOUT_SECONDS)
      except asyncio.TimeoutError as exc:
        raise TimeoutError('等待前端刷新下载链接超时') from exc
      finally:
        self._download_url_refresh_waiters.pop(file_key, None)

  def provide_download_url_refresh(self, data: Dict[str, Any]) -> None:
    """接收前端回传的新 downloadUrl，并唤醒等待中的下载任务。"""
    order = data.get('order')
    download_url = data.get('downloadUrl')
    error = data.get('error')
    try:
      parsed_order = int(order)
    except (TypeError, ValueError):
      logging.debug('skip invalid refresh payload: %s', data)
      return
    file_key = f'order-{parsed_order}'
    waiter = self._download_url_refresh_waiters.get(file_key)
    if not waiter or waiter.done():
      if download_url and not error:
        self._download_url_refresh_cache[file_key] = str(download_url)
        logging.debug('cache refresh download url for order=%s', parsed_order)
      else:
        logging.debug('no waiter for refresh order=%s', parsed_order)
      return
    if error:
      waiter.set_exception(RuntimeError(str(error)))
      return
    if not download_url:
      waiter.set_exception(RuntimeError('refresh download url is empty'))
      return
    waiter.set_result(str(download_url))

  def _coerce_concurrency(self, value: Any, *, fallback: int) -> int:
    """解析并校验前端传入的并发数，确保落在 1-50 范围内（主要用于授权码模式）。"""
    try:
      parsed = int(value)
    except (TypeError, ValueError):
      return fallback
    if 1 <= parsed <= 50:
      return parsed
    return fallback

  def _is_refreshable_download_status(self, status: int) -> bool:
    """判断 HTTP 状态码是否可能由临时链接失效触发，从而需要向前端刷新 downloadUrl。"""
    return status in (400, 401, 403, 404, 410)

  def _parse_retry_after_seconds(self, value: Optional[str]) -> Optional[float]:
    """解析 Retry-After 秒数，非法或缺失时返回 None。"""
    if not value:
      return None
    try:
      seconds = float(value)
    except (TypeError, ValueError):
      return None
    return seconds if seconds > 0 else None

  def _calculate_retry_delay_seconds(self, attempt: int, *, retry_after: Optional[str] = None) -> float:
    """根据当前失败次数计算下一次重试等待时间，优先使用 Retry-After。"""
    header_delay = self._parse_retry_after_seconds(retry_after)
    if header_delay is not None:
      return min(header_delay, 30.0)
    # 指数退避：0.5s / 1s / 2s ... 最多 5s
    return min(0.5 * (2 ** max(attempt - 1, 0)), 5.0)

  def mark_completion_requested(self) -> None:
    """标记前端已发送“任务完成推送”的消息，用于断连兜底时区分是否需要标记为 aborted。"""
    self._completion_requested = True

  def should_detach_on_disconnect(self, websocket) -> bool:
    """判断当前任务是否允许在 WebSocket 断开后继续执行（授权码模式可离线下载）。"""
    return bool(
      websocket is not None
      and self.download_mode == 'token'
      and self.configured
      and not self.completed
    )

  async def configure(self, data: Dict[str, Any], websocket) -> bool:
    """应用前端传来的配置，若缺失则通知前端并阻止下载。"""
    if self.configured:
      return True
    self.download_mode = 'url'
    self.app_token = None
    self.table_id = None
    self.sdk_client = None
    try:
      concurrent = self._coerce_concurrency(data.get('concurrent'), fallback=self.handler.default_concurrency)
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

    self.semaphore = None
    self.zip_after = zip_after
    self.job_id = job_id
    self.job_name = self.handler._sanitize_component(job_name) or f'download_{job_id}'
    self.job_dir = self.handler._create_job_directory(self.job_name, self.job_id)
    self.total = max(total, 0)
    self.configured = True
    await self._configure_download_mode(data, websocket)
    if not self.configured:
      return False
    # URL 模式并发由 Python 端统一控制，避免前端固定传 1 导致下载过慢；
    # 授权码模式则沿用前端配置（允许更灵活地压低并发以规避鉴权限流）。
    if self.download_mode == 'token':
      self.semaphore = asyncio.Semaphore(concurrent)
      self.concurrency = concurrent
    else:
      self.semaphore = asyncio.Semaphore(self.handler.default_concurrency)
      self.concurrency = self.handler.default_concurrency
    self.handler.register_active_job_state(self)
    self.handler._monitor_job_started(
      self.total,
      job_id=self.job_id,
      job_name=self.job_name,
      job_dir=self.job_dir,
      zip_after=self.zip_after,
      mode=self.download_mode
    )
    await self.handler._send_ack(
      websocket,
      status='success',
      message='server info',
      order=None,
      extra={'stage': 'server_info', 'version': APP_VERSION}
    )
    concurrent_label = concurrent if self.download_mode == 'token' else self.handler.default_concurrency
    logging.info('job configured: job_id=%s concurrent=%s zip=%s', self.job_id, concurrent_label, zip_after)
    return True

  async def _configure_download_mode(self, data: Dict[str, Any], websocket) -> None:
    """根据前端传入信息记录下载模式。"""
    requested_mode = str(data.get('downloadMode') or 'url').lower()
    self.download_mode = requested_mode if requested_mode in ('url', 'token') else 'url'
    self.handler._monitor_download_mode(self.download_mode)
    if self.download_mode != 'token':
      return
    app_token = str(data.get('appToken') or '').strip()
    table_id = str(data.get('tableId') or '').strip()
    if not app_token or not table_id:
      await self.handler._send_ack(
        websocket,
        status='error',
        message='app token or table id missing for authorization download mode.',
        order=None
      )
      self.configured = False
      return
    try:
      self.sdk_client = self.handler.create_sdk_client(app_token)
    except RuntimeError as exc:
      await self.handler._send_ack(
        websocket,
        status='error',
        message=str(exc),
        order=None
      )
      self.configured = False
      return
    self.app_token = app_token
    self.table_id = table_id
    logging.info('authorization download enabled for job %s with app_token=%s', self.job_id, app_token)

  async def enqueue_download(self, data: Dict[str, Any], websocket) -> None:
    """按配置并发下载文件。"""
    if not self.configured or not self.job_dir:
      await self.handler._send_ack(
        websocket,
        status='error',
        message='job configuration not received; cannot download.',
        order=data.get('order')
      )
      return
    file_key, normalized = self._normalize_file_payload(data)
    self._remember_file_payload(file_key, normalized)
    task = asyncio.create_task(self._download_worker(dict(normalized), websocket))
    self.tasks.add(task)
    task.add_done_callback(lambda fut: self.tasks.discard(fut))

  async def finalize(self, websocket, *, aborted: bool = False) -> None:
    """等待所有下载完成，并根据配置执行打包。"""
    if self.completed:
      return
    if self.tasks:
      await asyncio.gather(*self.tasks, return_exceptions=True)
    if not aborted:
      retry_count = await self.retry_failed_files_via_frontend(websocket)
      if retry_count and self.tasks:
        await asyncio.gather(*self.tasks, return_exceptions=True)
    if self.zip_after and self.job_dir:
      zip_path = await asyncio.to_thread(self._create_zip_archive, self.job_dir)
      self.handler._monitor_job_zip_path(zip_path)
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
    self.sdk_client = None
    self.handler._monitor_job_finished(aborted=aborted)

  def schedule_finalize(self, websocket, *, aborted: bool = False) -> None:
    """后台触发 finalize，避免阻塞 WebSocket 收消息（refresh 链接需要继续接收）。"""
    if self._finalize_task and not self._finalize_task.done():
      return

    async def _run_finalize() -> None:
      try:
        await self.finalize(websocket, aborted=aborted)
      except Exception:  # noqa: BLE001
        logging.exception('finalize task failed')

    self._finalize_task = asyncio.create_task(_run_finalize())

  async def shutdown(self, websocket=None) -> None:
    """在连接异常结束时取消挂起任务。"""
    if self.should_detach_on_disconnect(websocket):
      # 授权码模式允许前端断开：保持任务继续运行，并在需要时自动 finalize。
      if not self._finalize_task or self._finalize_task.done():
        self.schedule_finalize(websocket, aborted=not self._completion_requested)
    else:
      if self._finalize_task and not self._finalize_task.done():
        self._finalize_task.cancel()
        await asyncio.gather(self._finalize_task, return_exceptions=True)
      self._finalize_task = None
    waiters = list(self._download_url_refresh_waiters.values())
    self._download_url_refresh_waiters.clear()
    self._download_url_refresh_cache.clear()
    for waiter in waiters:
      if not waiter.done():
        waiter.cancel()
    if self.should_detach_on_disconnect(websocket):
      return
    if not self.tasks:
      self.handler._monitor_job_finished(aborted=not self.completed)
      return
    tasks = list(self.tasks)
    self.tasks.clear()
    for task in tasks:
      task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    self.handler._monitor_job_finished(aborted=not self.completed)
    self.sdk_client = None

  async def _download_worker(self, file_info: Dict[str, Any], websocket) -> None:
    """受限的下载任务，负责单个文件处理。"""
    if self.semaphore:
      async with self.semaphore:
        await self._process_single_download(file_info, websocket)
    else:
      await self._process_single_download(file_info, websocket)

  async def _process_single_download(self, file_info: Dict[str, Any], websocket) -> None:
    """根据配置选择 URL 或授权模式执行下载。"""
    download_url = file_info.get('downloadUrl')
    file_token = file_info.get('token')
    field_id = file_info.get('fieldId')
    record_id = file_info.get('recordId')
    file_name = file_info.get('name')
    relative_path = file_info.get('path', '')
    order = file_info.get('order')
    identifier = record_id or file_token or download_url
    file_key = self.handler._build_file_key(order, file_name, str(relative_path or ''), identifier)

    self._remember_file_payload(file_key, dict(file_info))
    if isinstance(download_url, str) and download_url:
      self._remember_download_url(file_key, download_url)

    self.handler._monitor_file_registered(
      file_key,
      name=file_name or 'unknown',
      size=int(file_info.get('size') or 0),
      path=str(relative_path or '')
    )

    if not file_name:
      await self.handler._send_ack(
        websocket,
        status='error',
        message='missing file name',
        order=order
      )
      self.handler._monitor_file_status(file_key, 'failed', error='missing file name')
      self._failed_file_keys.add(file_key)
      return

    if self.download_mode == 'token':
      if not all([file_token, field_id, record_id, self.table_id, self.sdk_client]):
        await self.handler._send_ack(
          websocket,
          status='error',
          message='authorization download payload missing attachment identifiers.',
          order=order
        )
        self.handler._monitor_file_status(file_key, 'failed', error='authorization payload missing identifiers')
        self._failed_file_keys.add(file_key)
        return

    if self.download_mode == 'url' and not download_url and not isinstance(order, int):
      await self.handler._send_ack(
        websocket,
        status='error',
        message='missing downloadUrl and order; cannot request url refresh.',
        order=order
      )
      self.handler._monitor_file_status(file_key, 'failed', error='missing download url and order')
      self._failed_file_keys.add(file_key)
      return

    success = False
    saved_path: Optional[Path] = None
    last_error: Optional[str] = None
    target_path: Optional[Path] = None
    self.handler._monitor_download_started()
    self.handler._monitor_file_status(file_key, 'downloading')

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
      try:
        if target_path is None:
          # 为同一个文件在多次重试时复用同一目标路径，配合 .part 文件实现断点续传。
          target_path = self.handler._build_target_path(str(relative_path or ''), str(file_name), base_dir=self.job_dir)
        if self.download_mode == 'token':
          saved_path = await self.handler._download_file_with_token(
            self.sdk_client,
            table_id=self.table_id,
            field_id=field_id,
            record_id=record_id,
            file_token=file_token,
            destination=target_path,
            file_key=file_key
          )
        else:
          if not download_url:
            download_url = await self.request_download_url_refresh(
              websocket,
              order=order if isinstance(order, int) else None,
              file_key=file_key,
              file_name=str(file_name)
            )
            self._remember_download_url(file_key, str(download_url))
          saved_path = await self.handler._download_file(
            self.http_session,
            str(download_url),
            target_path,
            file_key=file_key,
            websocket=websocket,
            order=order if isinstance(order, int) else None
          )
        success = True
        break
      except ValueError as exc:
        last_error = str(exc)
        break
      except aiohttp.ClientResponseError as exc:
        retry_after_header = None
        if getattr(exc, 'headers', None):
          retry_after_header = exc.headers.get('Retry-After')  # type: ignore[union-attr]
        if self.download_mode == 'url' and self._is_refreshable_download_status(exc.status):
          try:
            download_url = await self.request_download_url_refresh(
              websocket,
              order=order if isinstance(order, int) else None,
              file_key=file_key,
              file_name=str(file_name)
            )
            self._remember_download_url(file_key, str(download_url))
            continue
          except Exception as refresh_exc:  # noqa: BLE001
            last_error = self.handler._format_download_exception(refresh_exc)
            logging.exception(
              'failed to refresh download url for %s (attempt %s/%s)',
              file_name,
              attempt,
              max_attempts
            )
            if attempt < max_attempts:
              await asyncio.sleep(self._calculate_retry_delay_seconds(attempt))
              continue
            break
        last_error = self.handler._format_download_exception(exc)
        logging.exception('download failed for %s (attempt %s/%s)', file_name, attempt, max_attempts)
        if attempt < max_attempts:
          await asyncio.sleep(self._calculate_retry_delay_seconds(attempt, retry_after=retry_after_header))
          continue
      except Exception as exc:  # noqa: BLE001
        last_error = self.handler._format_download_exception(exc)
        logging.exception('download failed for %s (attempt %s/%s)', file_name, attempt, max_attempts)
        if attempt < max_attempts:
          await asyncio.sleep(self._calculate_retry_delay_seconds(attempt))
          continue

    self.handler._monitor_download_finished(success=success)
    if not success:
      self._failed_file_keys.add(file_key)
      self.handler._monitor_file_status(file_key, 'failed', error=last_error or 'download failed')
      await self.handler._send_ack(
        websocket,
        status='error',
        message=f'download failed after {max_attempts} attempts: {last_error or "download failed"}',
        order=order,
        extra={
          'stage': 'file',
          'name': file_name,
          'path': str(relative_path or ''),
          'fileKey': file_key,
          'attempts': max_attempts
        }
      )
      return

    self._failed_file_keys.discard(file_key)
    self.handler._monitor_file_status(file_key, 'completed')
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


class AttachmentDownloader:
  """处理 WebSocket 消息并负责飞书附件下载。"""

  def __init__(self, config: ServerConfig, monitor: Optional[DownloadMonitor] = None) -> None:
    """记录输出目录并保存默认配置。"""
    self.config = config
    self.output_dir = config.ensure_output_dir()
    self.default_concurrency = config.normalized_concurrency()
    self.monitor = monitor
    self._client_cache: Dict[str, Any] = {}
    self._sdk_rate_lock = asyncio.Lock()
    self._sdk_request_times: Deque[float] = deque()
    self._active_job_state: Optional[DownloadJobState] = None
    self._retry_task: Optional[asyncio.Task] = None

  def _build_http_timeout(self) -> aiohttp.ClientTimeout:
    """构造适合大文件下载的 aiohttp 超时策略，避免长耗时请求被默认超时取消。"""
    return aiohttp.ClientTimeout(
      total=None,
      connect=self.config.normalized_http_connect_timeout(),
      sock_read=self.config.normalized_download_read_timeout()
    )

  def _build_http_connector(self) -> aiohttp.TCPConnector:
    """构造不限制连接数的连接器，避免 aiohttp 默认连接上限影响普通模式并发下载。"""
    return aiohttp.TCPConnector(limit=0, limit_per_host=0)

  def register_active_job_state(self, job_state: DownloadJobState) -> None:
    """记录最近一次配置的任务状态，便于桌面端触发失败文件重试。"""
    self._active_job_state = job_state

  async def schedule_retry_failed_files(self) -> Dict[str, int]:
    """调度失败文件重试任务（后台执行），返回可重试/不可重试数量。"""
    if self._retry_task and not self._retry_task.done():
      raise RuntimeError('已有失败文件重试任务正在执行，请等待结束后再试。')
    job_state = self._active_job_state
    if not job_state or not job_state.configured or not job_state.job_dir:
      raise RuntimeError('没有可重试的下载任务。')
    failed_payloads = job_state.get_failed_file_payloads()
    failed_total = len(failed_payloads)
    if failed_total == 0:
      raise RuntimeError('当前任务没有失败文件，无需重试。')

    mode = job_state.download_mode
    retryable: List[Dict[str, Any]] = []
    unavailable = 0
    if mode == 'token':
      if not job_state.app_token or not job_state.table_id:
        unavailable = failed_total
      else:
        for payload in failed_payloads:
          if payload.get('token') and payload.get('fieldId') and payload.get('recordId'):
            retryable.append(payload)
          else:
            unavailable += 1
    else:
      for payload in failed_payloads:
        if payload.get('downloadUrl'):
          retryable.append(payload)
        else:
          unavailable += 1

    if not retryable:
      return {
        'failed': failed_total,
        'retryable': 0,
        'unavailable': unavailable
      }

    context = {
      'jobDir': job_state.job_dir,
      'jobId': job_state.job_id or '',
      'jobName': job_state.job_name or 'download',
      'mode': mode,
      'appToken': job_state.app_token,
      'tableId': job_state.table_id,
      'concurrency': job_state.concurrency or self.default_concurrency
    }
    self._retry_task = asyncio.create_task(self._run_retry_job(context, retryable))
    return {
      'failed': failed_total,
      'retryable': len(retryable),
      'unavailable': unavailable
    }

  async def _run_retry_job(self, context: Dict[str, Any], payloads: List[Dict[str, Any]]) -> None:
    """后台执行失败文件重试任务（不依赖前端连接）。"""
    if not payloads:
      return
    mode = str(context.get('mode') or 'url')
    base_job_id = str(context.get('jobId') or 'job')
    base_job_name = str(context.get('jobName') or base_job_id)
    job_dir = context.get('jobDir')
    if not isinstance(job_dir, Path):
      job_dir = Path(str(job_dir or '')).expanduser().resolve()
    retry_job_id = f'{base_job_id}_retry_{int(time.time() * 1000)}'
    retry_job_name = f'{base_job_name}_retry'
    try:
      concurrency = int(context.get('concurrency') or self.default_concurrency)
    except (TypeError, ValueError):
      concurrency = self.default_concurrency
    concurrency = max(1, min(concurrency, 50))

    self._monitor_job_started(
      len(payloads),
      job_id=retry_job_id,
      job_name=retry_job_name,
      job_dir=job_dir,
      zip_after=False,
      mode=mode
    )

    retry_state: Optional[DownloadJobState] = None
    try:
      async with aiohttp.ClientSession(
        timeout=self._build_http_timeout(),
        connector=self._build_http_connector()
      ) as session:
        retry_state = DownloadJobState(self, session)
        self._active_job_state = retry_state
        retry_state.configured = True
        retry_state.zip_after = False
        retry_state.job_dir = job_dir
        retry_state.job_id = retry_job_id
        retry_state.job_name = retry_job_name
        retry_state.total = len(payloads)
        retry_state.download_mode = mode if mode in ('url', 'token') else 'url'
        retry_state.concurrency = concurrency
        retry_state.semaphore = asyncio.Semaphore(concurrency)
        if retry_state.download_mode == 'token':
          retry_state.app_token = str(context.get('appToken') or '').strip() or None
          retry_state.table_id = str(context.get('tableId') or '').strip() or None
          if not retry_state.app_token or not retry_state.table_id:
            raise RuntimeError('授权码模式缺少 appToken 或 tableId，无法重试失败文件。')
          retry_state.sdk_client = self.create_sdk_client(retry_state.app_token)
        for payload in payloads:
          await retry_state.enqueue_download(dict(payload), websocket=None)
        retry_state.mark_completion_requested()
        await retry_state.finalize(websocket=None, aborted=False)
    except Exception:  # noqa: BLE001
      logging.exception('failed files retry task crashed')
      if retry_state:
        await retry_state.shutdown(None)
      else:
        self._monitor_job_finished(aborted=True)

  def _parse_content_range(self, value: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    """解析 Content-Range 头，返回 (start, total)，解析失败则返回 (None, None)。"""
    if not value:
      return (None, None)
    raw = str(value).strip()
    if not raw:
      return (None, None)
    try:
      unit, rest = raw.split(' ', 1)
    except ValueError:
      return (None, None)
    if unit.lower() != 'bytes':
      return (None, None)
    try:
      range_part, total_part = rest.split('/', 1)
    except ValueError:
      return (None, None)
    total = None
    total_part = total_part.strip()
    if total_part and total_part != '*':
      try:
        total = int(total_part)
      except ValueError:
        total = None
    range_part = range_part.strip()
    if not range_part or range_part.startswith('*'):
      return (None, total)
    try:
      start_text, _ = range_part.split('-', 1)
      start = int(start_text)
    except (ValueError, TypeError):
      return (None, total)
    return (start, total)

  def _format_download_exception(self, exc: BaseException) -> str:
    """将下载异常转换为可读文本，避免 TimeoutError 等异常返回空字符串。"""
    if isinstance(exc, aiohttp.ClientResponseError):
      message = (exc.message or '').strip()
      return f'HTTP {exc.status}: {message}' if message else f'HTTP {exc.status}'
    if isinstance(exc, aiohttp.ClientPayloadError):
      return '下载中断：响应体不完整（可能是网络抖动或连接被重置），请稍后重试。'
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
      read_timeout = self.config.normalized_download_read_timeout()
      if read_timeout:
        return f'下载超时：超过 {int(read_timeout)} 秒未收到数据，请检查网络或提高下载超时后重试。'
      return '下载超时：长时间未收到数据，请检查网络后重试。'
    message = str(exc).strip()
    return message or exc.__class__.__name__

  def update_output_dir(self, new_dir: Path) -> Path:
    """更新基础保存目录，确保新路径立即生效。"""
    self.config.output_dir = Path(new_dir)
    self.output_dir = self.config.ensure_output_dir()
    logging.info('output directory switched to %s', self.output_dir)
    return self.output_dir

  def update_personal_token(self, token: Optional[str]) -> None:
    """更新授权码并清理旧缓存。"""
    self.config.personal_base_token = token
    self._client_cache.clear()

  async def handle_connection(self, websocket, path=None) -> None:
    """处理单个客户端连接，并监听其消息流。"""
    peer = getattr(websocket, 'remote_address', ('unknown', ''))
    logging.info('client connected %s:%s', peer[0], peer[1])
    self._monitor_connection(True)
    async with aiohttp.ClientSession(
      timeout=self._build_http_timeout(),
      connector=self._build_http_connector()
    ) as session:
      job_state = DownloadJobState(self, session)
      try:
        async for message in websocket:
          await self._process_message(message, websocket, job_state)
      except websockets.ConnectionClosedOK:
        logging.info('client closed the connection normally')
      except websockets.ConnectionClosedError as exc:
        logging.warning('connection closed with error: %s', exc)
      finally:
        await job_state.shutdown(websocket)
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

    if msg_type == WEBSOCKET_PROBE_TYPE:
      await self._send_ack(
        websocket,
        status='success',
        message='server info',
        order=None,
        extra={'stage': 'server_info', 'version': APP_VERSION}
      )
      return

    if msg_type == WEBSOCKET_CONFIG_TYPE:
      await job_state.configure(data, websocket)
      return
    if msg_type == WEBSOCKET_LINK_TYPE:
      files_payload = None
      if isinstance(data, dict):
        files_payload = data.get('files')
      if isinstance(files_payload, list):
        for item in files_payload:
          if isinstance(item, dict):
            await job_state.enqueue_download(item, websocket)
        return
      if isinstance(data, list):
        for item in data:
          if isinstance(item, dict):
            await job_state.enqueue_download(item, websocket)
        return
      await job_state.enqueue_download(data, websocket)
      return
    if msg_type == WEBSOCKET_REFRESH_TYPE:
      job_state.provide_download_url_refresh(data)
      return
    if msg_type == WEBSOCKET_COMPLETE_TYPE:
      job_state.mark_completion_requested()
      job_state.schedule_finalize(websocket, aborted=False)
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

  def _is_destination_occupied(self, destination: Path) -> bool:
    """判断目标路径是否已被占用（包含临时 .part 文件），用于并发下载避免命名冲突。"""
    if destination.exists():
      return True
    temp_destination = destination.with_name(f'{destination.name}.part')
    return temp_destination.exists()

  def _ensure_unique_name(self, destination: Path) -> Path:
    """为已存在的文件追加编号后缀，避免覆盖。"""
    if not self._is_destination_occupied(destination):
      return destination
    stem = destination.stem
    suffix = destination.suffix
    parent = destination.parent
    counter = 1
    while True:
      candidate = parent / f'{stem}_{counter}{suffix}'
      if not self._is_destination_occupied(candidate):
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

  async def _download_file(
    self,
    session: aiohttp.ClientSession,
    url: str,
    destination: Path,
    *,
    file_key: str,
    websocket=None,
    order: Optional[int] = None
  ) -> Path:
    """使用 aiohttp 流式下载文件（支持断点续传，成功后再原子替换）。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_destination = destination.with_name(f'{destination.name}.part')
    resume_from = 0
    if temp_destination.exists():
      try:
        resume_from = temp_destination.stat().st_size
      except OSError:
        resume_from = 0

    headers: Dict[str, str] = {}
    if resume_from > 0:
      headers['Range'] = f'bytes={resume_from}-'
      self._monitor_file_downloaded(file_key, resume_from)
      logging.info('resuming %s (offset=%s) -> %s', url, resume_from, destination)
    else:
      logging.info('downloading %s -> %s', url, destination)

    async with session.get(url, headers=headers) as response:
      if response.status == 416 and resume_from > 0:
        start, total = self._parse_content_range(response.headers.get('Content-Range'))
        if total is not None and resume_from >= total:
          self._monitor_file_downloaded(file_key, total)
          temp_destination.replace(destination)
          logging.info('saved file to %s', destination)
          return destination
        try:
          temp_destination.unlink()
        except OSError:
          logging.debug('failed to cleanup temp file after 416: %s', temp_destination)
        self._monitor_file_downloaded(file_key, 0)
        return await self._download_file(session, url, destination, file_key=file_key, websocket=websocket, order=order)

      response.raise_for_status()

      write_mode = 'wb'
      if resume_from > 0 and response.status == 206:
        start, _ = self._parse_content_range(response.headers.get('Content-Range'))
        if start != resume_from:
          logging.info(
            'range mismatch for %s (expected=%s got=%s), restart full download',
            destination,
            resume_from,
            start
          )
          try:
            temp_destination.unlink()
          except OSError:
            logging.debug('failed to cleanup temp file after range mismatch: %s', temp_destination)
          self._monitor_file_downloaded(file_key, 0)
          return await self._download_file(session, url, destination, file_key=file_key, websocket=websocket, order=order)
        write_mode = 'ab'
      elif resume_from > 0 and response.status == 200:
        # 服务端不支持 Range 时会返回 200，此时需要从头下载并重置进度。
        self._monitor_file_downloaded(file_key, 0)

      # 获取文件总大小用于进度计算
      content_length = response.headers.get('Content-Length')
      total_size = int(content_length) if content_length else 0
      downloaded = resume_from
      last_report_time = time.time()
      report_interval = 0.5  # 每 500ms 上报一次进度

      with temp_destination.open(write_mode) as file_obj:
        async for chunk in response.content.iter_chunked(128 * 1024):
          file_obj.write(chunk)
          chunk_size = len(chunk)
          downloaded += chunk_size
          self._monitor_file_progress(file_key, chunk_size)

          # 定期向前端推送实时进度
          current_time = time.time()
          if websocket is not None and order is not None and current_time - last_report_time >= report_interval:
            if total_size > 0:
              percentage = min(int((downloaded / total_size) * 100), 99)
              await self._send_ack(
                websocket,
                status='progress',
                message='downloading',
                order=order,
                extra={'percentage': percentage}
              )
            last_report_time = current_time

      temp_destination.replace(destination)
    logging.info('saved file to %s', destination)
    return destination

  async def _download_file_with_token(
    self,
    client: Any,
    *,
    table_id: Optional[str],
    field_id: str,
    record_id: str,
    file_token: str,
    destination: Path,
    file_key: str
  ) -> Path:
    """通过 BaseOpenSDK 使用授权码下载附件。"""
    if client is None or DownloadMediaRequest is None:
      raise RuntimeError('authorization client unavailable')
    if not table_id:
      raise ValueError('table id missing for authorization download.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    logging.info('downloading via SDK token=%s -> %s', file_token, destination)

    await self._acquire_sdk_slot()

    def _download() -> Path:
      extra_payload = json.dumps({
        'bitablePerm': {
          'tableId': table_id,
          'attachments': {
            field_id: {
              record_id: [file_token]
            }
          }
        }
      })
      max_retries = 3
      retry_delay = 1
      for attempt in range(max_retries):
        if attempt:
          logging.info('retrying download for token=%s attempt=%s', file_token, attempt + 1)
          time.sleep(retry_delay)
        request = (
          DownloadMediaRequest.builder()
          .file_token(file_token)
          .extra(extra_payload)
          .build()
        )
        response = client.drive.v1.media.download(request)
        if not response or not response.success():
          self._handle_download_failure(response)
          continue
        stream = getattr(response, 'file', None)
        if stream is None or not hasattr(stream, 'read'):
          logging.warning('empty file stream for token=%s', file_token)
          continue
        try:
          file_content = stream.read()
        except Exception as exc:  # noqa: BLE001
          logging.error('failed to read file stream: %s', exc)
          continue
        if not file_content:
          logging.warning('empty file content for token=%s', file_token)
          continue
        preview = file_content[:8].strip()
        if preview.startswith(b'{'):
          try:
            payload = json.loads(file_content.decode('utf-8'))
            code = payload.get('code')
            message = payload.get('msg') or payload.get('error') or '下载失败'
            if code == 1011 or 'personal token is invalid' in str(message).lower():
              raise RuntimeError('授权码无效，请在本地客户端下载器的“服务配置”中重新填写 Personal Base Token 后重试。')
            raise RuntimeError(message)
          except UnicodeDecodeError:
            logging.warning('unexpected json-like response for token=%s', file_token)
            continue
        try:
          with destination.open('wb') as file_obj:
            file_obj.write(file_content)
          self._monitor_file_progress(file_key, len(file_content))
        except Exception as exc:  # noqa: BLE001
          logging.error('failed to write file %s: %s', destination, exc)
          continue
        if not destination.exists():
          logging.warning('file not created after write: %s', destination)
          continue
        return destination
      raise RuntimeError('下载失败，请稍后重试。')

    return await asyncio.to_thread(_download)

  async def _acquire_sdk_slot(self) -> None:
    """限制 SDK 调用速率至每秒 2 次。"""
    async with self._sdk_rate_lock:
      while True:
        now = time.monotonic()
        while self._sdk_request_times and now - self._sdk_request_times[0] >= 1:
          self._sdk_request_times.popleft()
        if len(self._sdk_request_times) < 2:
          self._sdk_request_times.append(now)
          return
        wait_time = 1 - (now - self._sdk_request_times[0])
        await asyncio.sleep(max(wait_time, 0))

  def _handle_download_failure(self, response: Any) -> None:
    """根据 baseopensdk 响应抛出更友好的提示。"""
    message = getattr(response, 'msg', '下载失败') or '下载失败'
    normalized = str(message).lower()
    code = getattr(response, 'code', None)
    raw = getattr(response, 'raw', None)
    status_code = None
    if raw and hasattr(raw, 'header') and isinstance(raw.header, dict):
      status_code = raw.header.get('status_code') or raw.header.get('Status-Code')
    raw_content = getattr(raw, 'content', None)
    raw_text = ''
    if isinstance(raw_content, bytes):
      try:
        raw_text = raw_content.decode('utf-8')
      except UnicodeDecodeError:
        raw_text = ''
    elif isinstance(raw_content, str):
      raw_text = raw_content
    logging.error(
      'download failed code=%s status=%s msg=%s log_id=%s raw=%s',
      code,
      status_code,
      message,
      getattr(response, 'get_log_id', lambda: None)(),
      raw_text
    )
    if code == 1011 or 'personal token is invalid' in normalized:
      raise RuntimeError('授权码无效，请在本地客户端下载器的“服务配置”中重新填写 Personal Base Token 后重试。')
    if status_code in (400, '400'):
      raise RuntimeError('高级权限鉴权失败，请检查 extra 参数或授权信息。')
    if status_code in (403, '403'):
      raise RuntimeError('没有下载权限，请确认调用身份具备访问该附件的权限。')
    if status_code in (404, '404'):
      raise RuntimeError('附件不存在或已被删除，请检查 file_token 是否正确。')
    if status_code in (500, '500'):
      raise RuntimeError('服务端异常，请稍后重试。')
    raise RuntimeError(message)

  def create_sdk_client(self, app_token: str) -> Any:
    """基于 app token 构建或复用 BaseOpenSDK 客户端。"""
    personal_token = self.config.normalized_personal_token()
    if not personal_token:
      raise RuntimeError('客户端未配置授权码（Personal Base Token），请在本地客户端下载器的“服务配置”中填写后重试。')
    if BaseClient is None or DownloadMediaRequest is None:
      raise RuntimeError('baseopensdk dependency is not installed on the local client.')
    cache_key = f'{app_token}:{personal_token}'
    cached = self._client_cache.get(cache_key)
    if cached:
      return cached
    client = (
      BaseClient.builder()
      .app_token(app_token)
      .personal_base_token(personal_token)
      .build()
    )
    self._client_cache[cache_key] = client
    return client

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
    if websocket is None:
      return
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

  def _monitor_job_started(
    self,
    total: int,
    *,
    job_id: Optional[str] = None,
    job_name: Optional[str] = None,
    job_dir: Optional[Path] = None,
    zip_after: bool = False,
    mode: Optional[str] = None
  ) -> None:
    """记录新的下载任务，供桌面端“下载记录”页面展示。"""
    if self.monitor:
      self.monitor.start_job(
        total,
        job_id=str(job_id or ''),
        job_name=str(job_name or ''),
        mode=str(mode or 'url'),
        output_dir=self.output_dir,
        job_dir=job_dir,
        zip_after=zip_after
      )

  def _monitor_download_started(self) -> None:
    """记录单个文件开始下载。"""
    if self.monitor:
      self.monitor.start_download()

  def _monitor_download_finished(self, *, success: bool) -> None:
    """记录单个文件完成。"""
    if self.monitor:
      self.monitor.finish_download(success)

  def _monitor_job_zip_path(self, zip_path: Path) -> None:
    """记录任务生成的 ZIP 文件路径。"""
    if self.monitor:
      self.monitor.set_job_zip_path(zip_path)

  def _monitor_job_finished(self, *, aborted: bool = False) -> None:
    """通知任务阶段结束，并将当前任务写入下载记录。"""
    if self.monitor:
      self.monitor.job_finished(aborted=aborted)

  def _monitor_download_mode(self, mode: str) -> None:
    """记录下载模式供桌面端展示。"""
    if self.monitor:
      self.monitor.set_mode(mode)

  def _monitor_file_registered(self, key: str, *, name: str, size: int, path: str) -> None:
    """登记文件信息供 UI 展示。"""
    if self.monitor:
      self.monitor.register_file(key, name=name, path=path, size=size)

  def _monitor_file_progress(self, key: str, bytes_count: int) -> None:
    """记录指定文件的字节进度。"""
    if self.monitor:
      self.monitor.update_file_progress(key, bytes_count)

  def _monitor_file_downloaded(self, key: str, downloaded: int) -> None:
    """强制同步指定文件的已下载字节数（用于断点续传/重试重置进度）。"""
    if self.monitor:
      self.monitor.set_file_downloaded(key, downloaded)

  def _monitor_file_status(self, key: str, status: str, *, error: Optional[str] = None) -> None:
    """更新文件状态供 UI 展示。"""
    if self.monitor:
      self.monitor.mark_file_status(key, status, error=error)

  def _build_file_key(self, order: Optional[Any], name: Optional[str], path: str, extra: Optional[Any]) -> str:
    """组合一个稳定的文件标识符。"""
    if order is not None:
      return f'order-{order}'
    if path:
      return f'{path}-{name or "unknown"}'
    if name:
      return name
    if extra is not None:
      return str(extra)
    return 'file'


__all__ = [
  'ACK_MESSAGE_TYPE',
  'WEBSOCKET_COMPLETE_TYPE',
  'WEBSOCKET_CONFIG_TYPE',
  'WEBSOCKET_LINK_TYPE',
  'WEBSOCKET_PROBE_TYPE',
  'WEBSOCKET_REFRESH_TYPE',
  'AttachmentDownloader',
  'DownloadJobState'
]
