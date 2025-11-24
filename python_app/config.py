"""
配置对象定义，集中管理 WebSocket 服务的运行参数。
"""
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ServerConfig:
  """封装 WebSocket 下载服务的可配置项。"""

  host: str = '127.0.0.1'
  port: int = 11548
  output_dir: Path = Path('downloads')
  log_level: str = 'INFO'
  download_concurrency: int = 5

  def ensure_output_dir(self) -> Path:
    """确保输出目录存在并返回其 Path 对象。"""
    output_path = Path(self.output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path

  def normalized_concurrency(self) -> int:
    """返回合法的默认并发数。"""
    return max(1, int(self.download_concurrency or 1))
