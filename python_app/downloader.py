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
from typing import Any, Deque, Dict, Literal, Optional, Set

import aiohttp
import websockets

from .config import ServerConfig
from .monitor import DownloadMonitor

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
    self.download_mode: Literal['url', 'token'] = 'url'
    self.app_token: Optional[str] = None
    self.table_id: Optional[str] = None
    self.sdk_client: Any = None
    self._download_url_refresh_waiters: Dict[str, asyncio.Future[str]] = {}
    self._download_url_refresh_cache: Dict[str, str] = {}
    self._download_url_refresh_semaphore = asyncio.Semaphore(DOWNLOAD_URL_REFRESH_MAX_INFLIGHT)

  async def request_download_url_refresh(
    self,
    websocket,
    *,
    order: Optional[int],
    file_key: str,
    file_name: str
  ) -> str:
    """向前端请求刷新 downloadUrl，并等待新的临时链接返回。"""
    if order is None:
      raise RuntimeError('missing order for download url refresh')
    cached_url = self._download_url_refresh_cache.pop(file_key, None)
    if cached_url:
      logging.debug('consume cached download url for %s (%s)', file_name, file_key)
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
    if self.download_mode == 'token':
      self.semaphore = asyncio.Semaphore(concurrent)
    self.handler._monitor_job_started(self.total)
    concurrent_label = concurrent if self.semaphore else 'unlimited'
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

  def schedule_finalize(self, websocket) -> None:
    """后台触发 finalize，避免阻塞 WebSocket 收消息（refresh 链接需要继续接收）。"""
    if self._finalize_task and not self._finalize_task.done():
      return

    async def _run_finalize() -> None:
      try:
        await self.finalize(websocket)
      except Exception:  # noqa: BLE001
        logging.exception('finalize task failed')

    self._finalize_task = asyncio.create_task(_run_finalize())

  async def shutdown(self) -> None:
    """在连接异常结束时取消挂起任务。"""
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
    if not self.tasks:
      self.handler._monitor_job_finished()
      return
    tasks = list(self.tasks)
    self.tasks.clear()
    for task in tasks:
      task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    self.handler._monitor_job_finished()
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
    file_key = self.handler._build_file_key(order, file_name, relative_path, identifier)

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
        return

    if self.download_mode == 'url' and not download_url and not isinstance(order, int):
      await self.handler._send_ack(
        websocket,
        status='error',
        message='missing downloadUrl and order; cannot request url refresh.',
        order=order
      )
      self.handler._monitor_file_status(file_key, 'failed', error='missing download url and order')
      return

    success = False
    saved_path = None
    last_error: Optional[str] = None
    self.handler._monitor_download_started()
    self.handler._monitor_file_status(file_key, 'downloading')

    for attempt in range(1, 4):
      try:
        target_path = self.handler._build_target_path(relative_path, file_name, base_dir=self.job_dir)
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
              file_name=file_name
            )
          saved_path = await self.handler._download_file(
            self.http_session,
            download_url,
            target_path,
            file_key=file_key
          )
        success = True
        break
      except ValueError as exc:
        last_error = str(exc)
        break
      except aiohttp.ClientResponseError as exc:
        if self.download_mode == 'url' and exc.status == 400:
          try:
            download_url = await self.request_download_url_refresh(
              websocket,
              order=order if isinstance(order, int) else None,
              file_key=file_key,
              file_name=file_name
            )
            continue
          except Exception as refresh_exc:  # noqa: BLE001
            last_error = self.handler._format_download_exception(refresh_exc)
            logging.exception('failed to refresh download url for %s (attempt %s/3)', file_name, attempt)
            if attempt < 3:
              await asyncio.sleep(0.5)
              continue
            break
        last_error = self.handler._format_download_exception(exc)
        logging.exception('download failed for %s (attempt %s/3)', file_name, attempt)
        if attempt < 3:
          await asyncio.sleep(0.5)
          continue
      except Exception as exc:  # noqa: BLE001
        last_error = self.handler._format_download_exception(exc)
        logging.exception('download failed for %s (attempt %s/3)', file_name, attempt)
        if attempt < 3:
          await asyncio.sleep(0.5)
          continue

    self.handler._monitor_download_finished(success=success)
    if not success:
      self.handler._monitor_file_status(file_key, 'failed', error=last_error or 'download failed')
      await self.handler._send_ack(
        websocket,
        status='error',
        message=f'download failed after 3 attempts: {last_error or "download failed"}',
        order=order
      )
      return

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

  def _format_download_exception(self, exc: BaseException) -> str:
    """将下载异常转换为可读文本，避免 TimeoutError 等异常返回空字符串。"""
    if isinstance(exc, aiohttp.ClientResponseError):
      message = (exc.message or '').strip()
      return f'HTTP {exc.status}: {message}' if message else f'HTTP {exc.status}'
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
    if msg_type == WEBSOCKET_REFRESH_TYPE:
      job_state.provide_download_url_refresh(data)
      return
    if msg_type == WEBSOCKET_COMPLETE_TYPE:
      job_state.schedule_finalize(websocket)
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
    file_key: str
  ) -> Path:
    """使用 aiohttp 流式下载文件（先写入临时文件，成功后再原子替换）。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_destination = destination.with_name(f'{destination.name}.part')
    logging.info('downloading %s -> %s', url, destination)
    try:
      if temp_destination.exists():
        temp_destination.unlink()
    except OSError:
      logging.debug('failed to cleanup temp file before download: %s', temp_destination)
    async with session.get(url) as response:
      response.raise_for_status()
      try:
        with temp_destination.open('wb') as file_obj:
          async for chunk in response.content.iter_chunked(128 * 1024):
            file_obj.write(chunk)
            self._monitor_file_progress(file_key, len(chunk))
        temp_destination.replace(destination)
      except Exception:  # noqa: BLE001
        try:
          if temp_destination.exists():
            temp_destination.unlink()
        except OSError:
          logging.debug('failed to cleanup temp file after error: %s', temp_destination)
        raise
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
  'WEBSOCKET_REFRESH_TYPE',
  'AttachmentDownloader',
  'DownloadJobState'
]
