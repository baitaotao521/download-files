"""线程安全的下载状态监控，供桌面端轮询展示。"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, List, Optional


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

  def set_connection(self, connected: bool) -> None:
    """记录当前是否有前端连接。"""
    with self._lock:
      self._connected = connected
      if not connected:
        self._total = 0
        self._completed = 0
        self._active = 0
        self._mode = 'url'
        self._files.clear()
        self._file_order.clear()

  def set_mode(self, mode: str) -> None:
    """记录当前下载模式（url / token）。"""
    normalized = mode if mode in ('url', 'token') else 'url'
    with self._lock:
      self._mode = normalized

  def start_job(self, total: int) -> None:
    """当收到新的 Job 配置时重置统计。"""
    with self._lock:
      self._total = max(int(total or 0), 0)
      self._completed = 0
      self._active = 0
      self._files.clear()
      self._file_order.clear()

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

  def job_finished(self) -> None:
    """任务整体结束，重置活动数。"""
    with self._lock:
      self._active = 0

  def snapshot(self) -> Dict[str, object]:
    """生成当前统计的浅拷贝，供 UI 渲染。"""
    with self._lock:
      pending = max(self._total - self._completed, 0)
      files = [self._files[key].as_dict() for key in self._file_order]
      total_files = max(self._total, len(files))
      completed_files = sum(1 for entry in self._files.values() if entry.status == 'completed')
      finished_files = sum(1 for entry in self._files.values() if entry.status in ('completed', 'failed'))
      failed_files = sum(1 for entry in self._files.values() if entry.status == 'failed')
      overall_percent = (finished_files / total_files * 100) if total_files else 0.0
      return {
        'connected': self._connected,
        'total': self._total,
        'completed': self._completed,
        'active': self._active,
        'pending': pending,
        'mode': self._mode,
        'files': files,
        'overall': {
          'total': total_files,
          'completed': completed_files,
          'failed': failed_files,
          'finished': finished_files,
          'percent': overall_percent
        }
      }
