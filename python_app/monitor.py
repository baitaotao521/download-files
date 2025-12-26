"""线程安全的下载状态监控，供桌面端轮询展示。"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from threading import Lock
from pathlib import Path
from typing import Any, Dict, List, Optional

from .user_config import CONFIG_DIR

HISTORY_FILE = CONFIG_DIR / 'download_history.json'
MAX_HISTORY_RECORDS = 200
FAILED_FILES_PREVIEW_LIMIT = 200


@dataclass
class FileProgress:
  """单个文件的下载状态快照。"""

  key: str
  name: str
  path: str
  size: int
  downloaded: int = 0
  status: str = 'pending'
  error: Optional[str] = None

  def as_dict(self) -> Dict[str, object]:
    """将条目转换为 UI 友好的字典。"""
    percent = self._calculate_percent()
    return {
      'key': self.key,
      'name': self.name,
      'path': self.path,
      'size': self.size,
      'downloaded': self.downloaded,
      'status': self.status,
      'error': self.error,
      'percent': percent
    }

  def _calculate_percent(self) -> float:
    """根据已下载字节计算 0-100 的进度。"""
    if self.size > 0:
      return max(min(self.downloaded / self.size * 100, 100), 0)
    if self.status == 'completed':
      return 100.0
    return 0.0


@dataclass
class DownloadMonitor:
  """维护 WebSocket 下载服务的连接与任务统计信息。"""

  _lock: Lock = field(default_factory=Lock, init=False, repr=False)
  _connected: bool = False
  _total: int = 0
  _completed: int = 0
  _active: int = 0
  _mode: str = 'url'
  _files: Dict[str, FileProgress] = field(default_factory=dict, init=False, repr=False)
  _file_order: List[str] = field(default_factory=list, init=False, repr=False)
  _history: List[Dict[str, object]] = field(default_factory=list, init=False, repr=False)
  _current_job: Optional[Dict[str, object]] = field(default=None, init=False, repr=False)

  def __post_init__(self) -> None:
    """在实例创建后加载历史记录，避免 GUI 启动时阻塞太久。"""
    self._load_history()

  def _load_history(self) -> None:
    """从磁盘读取下载记录，读取失败时回退为空列表。"""
    try:
      raw = HISTORY_FILE.read_text(encoding='utf-8')
      data = json.loads(raw)
    except FileNotFoundError:
      return
    except Exception as exc:  # noqa: BLE001
      logging.debug('failed to load download history: %s', exc)
      return
    if not isinstance(data, list):
      return
    normalized: List[Dict[str, object]] = []
    for item in data[:MAX_HISTORY_RECORDS]:
      if isinstance(item, dict):
        normalized.append(dict(item))
    with self._lock:
      self._history = normalized

  def _save_history(self) -> None:
    """将当前历史记录写回磁盘，失败时忽略（不会影响下载流程）。"""
    try:
      HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
      payload = self._history[:MAX_HISTORY_RECORDS]
      HISTORY_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as exc:  # noqa: BLE001
      logging.debug('failed to save download history: %s', exc)

  def _format_timestamp(self, value: float) -> str:
    """将时间戳格式化为可读字符串。"""
    try:
      return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(value))
    except Exception:  # noqa: BLE001
      return ''

  def start_job(
    self,
    total: int,
    *,
    job_id: str = '',
    job_name: str = '',
    mode: str = 'url',
    output_dir: Optional[Path] = None,
    job_dir: Optional[Path] = None,
    zip_after: bool = False
  ) -> None:
    """当收到新的 Job 配置时重置统计，并记录任务元信息供“下载记录”展示。"""
    normalized_mode = mode if mode in ('url', 'token') else 'url'
    started_at = self._format_timestamp(time.time())
    record_key_source = str(job_id or int(time.time() * 1000))
    with self._lock:
      self._total = max(int(total or 0), 0)
      self._completed = 0
      self._active = 0
      self._mode = normalized_mode
      self._files.clear()
      self._file_order.clear()
      self._current_job = {
        'recordKey': f'job-{record_key_source}',
        'jobId': str(job_id or ''),
        'jobName': str(job_name or ''),
        'mode': normalized_mode,
        'zipAfter': bool(zip_after),
        'outputDir': str(output_dir or ''),
        'jobDir': str(job_dir or ''),
        'zipPath': None,
        'status': 'running',
        'startedAt': started_at,
        'finishedAt': '',
        'total': 0,
        'completed': 0,
        'failed': 0,
        'failedFiles': []
      }

  def set_job_zip_path(self, zip_path: Path) -> None:
    """记录当前任务生成的 ZIP 文件路径，供记录页面展示与快速打开。"""
    with self._lock:
      if not self._current_job:
        return
      self._current_job['zipPath'] = str(zip_path)

  def finish_job(self, *, aborted: bool = False) -> None:
    """在任务整体结束时生成一条下载记录，并写入历史列表。"""
    finished_at = self._format_timestamp(time.time())
    with self._lock:
      self._active = 0
      if not self._current_job:
        return
      if self._current_job.get('status') in ('completed', 'aborted'):
        return
      total_files = max(self._total, len(self._files))
      completed_files = sum(1 for entry in self._files.values() if entry.status == 'completed')
      failed_files = sum(1 for entry in self._files.values() if entry.status == 'failed')
      failed_details = [
        entry.as_dict()
        for entry in self._files.values()
        if entry.status == 'failed'
      ]
      self._current_job['total'] = total_files
      self._current_job['completed'] = completed_files
      self._current_job['failed'] = failed_files
      self._current_job['failedFiles'] = failed_details[:FAILED_FILES_PREVIEW_LIMIT]
      self._current_job['finishedAt'] = finished_at
      finished_count = completed_files + failed_files
      status = 'aborted' if aborted and finished_count < total_files else 'completed'
      self._current_job['status'] = status
      record = dict(self._current_job)
      if not record.get('recordKey'):
        record['recordKey'] = f"job-{record.get('jobId') or int(time.time() * 1000)}"
      self._history.insert(0, record)
      self._history = self._history[:MAX_HISTORY_RECORDS]
      self._current_job = None
    self._save_history()

  def set_connection(self, connected: bool) -> None:
    """记录当前是否有前端连接。"""
    with self._lock:
      self._connected = connected
      current_status = None
      if isinstance(self._current_job, dict):
        current_status = self._current_job.get('status')
      # 授权码模式允许前端断开后继续下载：连接断开时若仍有运行中的任务，则保留状态供桌面端展示。
      if not connected and current_status != 'running':
        self._total = 0
        self._completed = 0
        self._active = 0
        self._mode = 'url'
        self._files.clear()
        self._file_order.clear()
        self._current_job = None

  def set_mode(self, mode: str) -> None:
    """记录当前下载模式（url / token）。"""
    normalized = mode if mode in ('url', 'token') else 'url'
    with self._lock:
      self._mode = normalized

  def job_finished(self, aborted: bool = False) -> None:
    """任务整体结束，兼容旧接口：记录历史并重置活动数。"""
    self.finish_job(aborted=aborted)

  def register_file(self, key: str, name: str, path: str, size: int) -> None:
    """登记一个待下载文件，方便 UI 展示。"""
    with self._lock:
      if key not in self._files:
        self._files[key] = FileProgress(key=key, name=name, path=path, size=max(size, 0))
        self._file_order.append(key)
        return
      entry = self._files[key]
      entry.name = name
      entry.path = path
      entry.size = max(size, entry.size)

  def start_download(self) -> None:
    """有文件进入下载队列时调用。"""
    with self._lock:
      self._active += 1

  def update_file_progress(self, key: str, bytes_delta: int) -> None:
    """更新指定文件的字节数，供进度计算。"""
    if bytes_delta <= 0:
      return
    with self._lock:
      entry = self._files.get(key)
      if not entry:
        return
      entry.downloaded += bytes_delta

  def set_file_downloaded(self, key: str, downloaded: int) -> None:
    """强制设置指定文件的已下载字节数（用于断点续传或重试从头下载时重置）。"""
    with self._lock:
      entry = self._files.get(key)
      if not entry:
        return
      entry.downloaded = max(int(downloaded or 0), 0)

  def mark_file_status(self, key: str, status: str, *, error: Optional[str] = None) -> None:
    """记录文件状态变更。"""
    with self._lock:
      entry = self._files.get(key)
      if not entry:
        return
      entry.status = status
      entry.error = error
      if status == 'completed' and entry.size and entry.downloaded < entry.size:
        entry.downloaded = entry.size

  def finish_download(self, success: bool) -> None:
    """单个文件完成（成功/失败）后调用。"""
    with self._lock:
      if self._active > 0:
        self._active -= 1
      if success:
        self._completed += 1

  def snapshot(self) -> Dict[str, object]:
    """生成当前统计的浅拷贝，供 UI 渲染。"""
    with self._lock:
      files = [self._files[key].as_dict() for key in self._file_order]
      total_files = max(self._total, len(files))
      completed_files = sum(1 for entry in self._files.values() if entry.status == 'completed')
      finished_files = sum(1 for entry in self._files.values() if entry.status in ('completed', 'failed'))
      failed_files = sum(1 for entry in self._files.values() if entry.status == 'failed')
      pending = max(total_files - finished_files, 0)
      overall_percent = (finished_files / total_files * 100) if total_files else 0.0
      return {
        'connected': self._connected,
        'total': self._total,
        'completed': self._completed,
        'active': self._active,
        'pending': pending,
        'mode': self._mode,
        'files': files,
        'history': list(self._history),
        'overall': {
          'total': total_files,
          'completed': completed_files,
          'failed': failed_files,
          'finished': finished_files,
          'percent': overall_percent
        }
      }
