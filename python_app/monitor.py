"""
线程安全的下载状态监控，供桌面端轮询展示。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Dict


@dataclass
class DownloadMonitor:
  """维护 WebSocket 下载服务的连接与任务统计信息。"""

  _lock: Lock = field(default_factory=Lock, init=False, repr=False)
  _connected: bool = False
  _total: int = 0
  _completed: int = 0
  _active: int = 0
  _mode: str = 'url'

  def set_connection(self, connected: bool) -> None:
    """记录当前是否有前端连接。"""
    with self._lock:
      self._connected = connected
      if not connected:
        self._total = 0
        self._completed = 0
        self._active = 0
        self._mode = 'url'

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

  def start_download(self) -> None:
    """有文件进入下载队列时调用。"""
    with self._lock:
      self._active += 1

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

  def snapshot(self) -> Dict[str, int]:
    """生成当前统计的浅拷贝，供 UI 渲染。"""
    with self._lock:
      pending = max(self._total - self._completed, 0)
      return {
        'connected': self._connected,
        'total': self._total,
        'completed': self._completed,
        'active': self._active,
        'pending': pending,
        'mode': self._mode
      }
