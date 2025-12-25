"""
配置对象定义，集中管理 WebSocket 服务的运行参数。
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ServerConfig:
  """封装 WebSocket 下载服务的可配置项。"""

  host: str = '127.0.0.1'
  port: int = 11548
  output_dir: Path = Path('downloads')
  log_level: str = 'INFO'
  download_concurrency: int = 20
  http_connect_timeout_seconds: float = 30.0
  download_read_timeout_seconds: float = 60 * 60
  personal_base_token: Optional[str] = None

  def ensure_output_dir(self) -> Path:
    """确保输出目录存在并返回其 Path 对象。"""
    output_path = Path(self.output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path

  def normalized_concurrency(self) -> int:
    """返回合法的默认并发数。"""
    return max(1, int(self.download_concurrency or 1))

  def normalized_http_connect_timeout(self) -> float:
    """返回合法的 HTTP 连接超时秒数（<=0 或非法值将回退到 30 秒）。"""
    try:
      value = float(self.http_connect_timeout_seconds)
    except (TypeError, ValueError):
      return 30.0
    return value if value > 0 else 30.0

  def normalized_download_read_timeout(self) -> Optional[float]:
    """返回合法的下载读取超时秒数（<=0 表示不限制读超时）。"""
    try:
      value = float(self.download_read_timeout_seconds)
    except (TypeError, ValueError):
      return float(60 * 60)
    if value <= 0:
      return None
    return value

  def normalized_personal_token(self) -> Optional[str]:
    """返回去除空白的授权码，若为空则返回 None。"""
    token = (self.personal_base_token or '').strip()
    return token or None
