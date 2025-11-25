"""
跨平台桌面应用，提供 WebSocket 服务的启动/停止与日志查看。
"""
from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional

from dotenv import load_dotenv, find_dotenv

from .config import ServerConfig
from .i18n import DEFAULT_LANGUAGE, Localizer, SUPPORTED_LANGUAGES, normalize_locale
from .logging_utils import configure_logging
from .monitor import DownloadMonitor
from .websocket_server import WebSocketDownloadServer
from .user_config import (
  CONFIG_FILE,
  DEFAULT_HOST,
  DEFAULT_OUTPUT_DIR,
  DEFAULT_FILE_DISPLAY_LIMIT,
  UserPreferences,
  load_user_config,
  save_user_config
)

load_dotenv(find_dotenv(), override=False)

DEFAULT_PYTHON_CONCURRENCY = 20


class GuiLogHandler(logging.Handler):
  """将日志消息转发到 Tkinter 队列的处理器。"""

  def __init__(self, message_queue: queue.Queue[str]) -> None:
    """记录队列引用并配置格式。"""
    super().__init__()
    self.message_queue = message_queue
    self.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))

  def emit(self, record: logging.LogRecord) -> None:
    """将格式化后的日志写入队列。"""
    try:
      message = self.format(record)
      self.message_queue.put_nowait(message)
    except Exception:  # noqa: BLE001
      self.handleError(record)


class DownloaderDesktopApp:
  """桌面程序主体，封装界面与后台服务控制。"""

  def __init__(self) -> None:
    """初始化 Tk 根窗口、控件、日志管道与本地化。"""
    configure_logging('INFO')
    self.localizer = Localizer(DEFAULT_LANGUAGE)
    self.user_preferences: UserPreferences = load_user_config()
    self.root = tk.Tk()
    self.root.minsize(640, 420)
    self.server: Optional[WebSocketDownloadServer] = None
    self.monitor = DownloadMonitor()
    self.log_queue: queue.Queue[str] = queue.Queue()
    self.log_handler = GuiLogHandler(self.log_queue)
    logging.getLogger().addHandler(self.log_handler)
    self.language_label_map: Dict[str, str] = {code: label for label, code in SUPPORTED_LANGUAGES}
    self.language_code_map: Dict[str, str] = {label: code for label, code in SUPPORTED_LANGUAGES}
    self._status_state = 'idle'
    self._status_context: Dict[str, str] = {}
    self.file_display_limit = max(self.user_preferences.file_display_limit or DEFAULT_FILE_DISPLAY_LIMIT, 100)
    self._initial_language_code = self._normalize_language_code(self.user_preferences.language)
    self.file_columns = ('name', 'status', 'progress', 'path')
    self._build_widgets()
    self._set_language(self._initial_language_code)
    self._schedule_log_polling()
    self._schedule_stats_refresh()
    self._start_server(auto=True)

  def _build_widgets(self) -> None:
    """创建并布局所有 UI 控件。"""
    main_frame = ttk.Frame(self.root, padding=12)
    main_frame.pack(fill=tk.BOTH, expand=True)

    language_frame = ttk.Frame(main_frame, padding=(0, 0, 0, 8))
    language_frame.pack(fill=tk.X)
    self.language_label_widget = ttk.Label(language_frame, text='')
    self.language_label_widget.pack(side=tk.LEFT)
    default_label = self.language_label_map.get(self._initial_language_code, SUPPORTED_LANGUAGES[0][0])
    self.language_var = tk.StringVar(value=default_label)
    self.language_combo = ttk.Combobox(
      language_frame,
      state='readonly',
      textvariable=self.language_var,
      values=[label for label, _ in SUPPORTED_LANGUAGES],
      width=18
    )
    self.language_combo.pack(side=tk.LEFT, padx=8)
    self.language_combo.bind('<<ComboboxSelected>>', self._on_language_change)

    self.form_frame = ttk.LabelFrame(main_frame, text='', padding=12)
    self.form_frame.pack(fill=tk.X, expand=False)
    self.output_label = ttk.Label(self.form_frame, text='')
    self.output_label.grid(row=0, column=0, sticky=tk.W, padx=4, pady=4)
    self.output_var = tk.StringVar(value=self.user_preferences.output_dir or 'downloads')
    output_entry = ttk.Entry(self.form_frame, textvariable=self.output_var, width=40)
    output_entry.grid(row=0, column=1, columnspan=2, sticky=tk.W + tk.E, padx=4, pady=4)
    output_entry.bind('<FocusOut>', self._on_output_dir_commit)
    output_entry.bind('<Return>', self._on_output_dir_commit)
    self.browse_button = ttk.Button(self.form_frame, text='', command=self._choose_output_dir)
    self.browse_button.grid(row=0, column=3, sticky=tk.W, padx=4, pady=4)
    self.open_output_button = ttk.Button(self.form_frame, text='', command=self._open_output_dir)
    self.open_output_button.grid(row=0, column=4, sticky=tk.W, padx=4, pady=4)
    initial_token = self.user_preferences.personal_base_token or os.environ.get('PERSONAL_BASE_TOKEN', '')
    self.personal_token_label = ttk.Label(self.form_frame, text='')
    self.personal_token_label.grid(row=1, column=0, sticky=tk.W, padx=4, pady=4)
    self.personal_token_var = tk.StringVar(value=initial_token)
    personal_token_entry = ttk.Entry(self.form_frame, textvariable=self.personal_token_var, width=40, show='*')
    personal_token_entry.grid(row=1, column=1, columnspan=3, sticky=tk.W + tk.E, padx=4, pady=4)
    personal_token_entry.bind('<FocusOut>', self._on_personal_token_commit)
    personal_token_entry.bind('<Return>', self._on_personal_token_commit)
    self.personal_token_hint = ttk.Label(self.form_frame, text='', wraplength=420, foreground='#666666')
    self.personal_token_hint.grid(row=2, column=1, columnspan=3, sticky=tk.W, padx=4, pady=(0, 8))
    self.form_frame.columnconfigure(1, weight=1)
    self.form_frame.columnconfigure(2, weight=1)

    self.stats_frame = ttk.LabelFrame(main_frame, text='', padding=12)
    self.stats_frame.pack(fill=tk.X, expand=False, pady=(8, 0))
    self.connection_var = tk.StringVar(value='')
    self.mode_var = tk.StringVar(value='')
    self.current_var = tk.StringVar(value='0')
    self.completed_var = tk.StringVar(value='0')
    self.pending_var = tk.StringVar(value='0')
    ttk.Label(self.stats_frame, textvariable=self.connection_var).grid(row=0, column=0, sticky=tk.W, padx=4, pady=4)
    ttk.Label(self.stats_frame, textvariable=self.mode_var).grid(row=0, column=1, sticky=tk.W, padx=4, pady=4)
    ttk.Label(self.stats_frame, textvariable=self.current_var).grid(row=1, column=0, sticky=tk.W, padx=4, pady=4)
    ttk.Label(self.stats_frame, textvariable=self.completed_var).grid(row=1, column=1, sticky=tk.W, padx=4, pady=4)
    ttk.Label(self.stats_frame, textvariable=self.pending_var).grid(row=1, column=2, sticky=tk.W, padx=4, pady=4)
    self.stats_frame.columnconfigure(0, weight=1)
    self.stats_frame.columnconfigure(1, weight=1)
    self.stats_frame.columnconfigure(2, weight=1)

    self.progress_frame = ttk.LabelFrame(main_frame, text='', padding=12)
    self.progress_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
    self.total_progress_var = tk.StringVar(value='')
    self.total_progress_label = ttk.Label(self.progress_frame, textvariable=self.total_progress_var)
    self.total_progress_label.pack(anchor=tk.W)
    self.total_progress_bar = ttk.Progressbar(self.progress_frame, mode='determinate', maximum=100)
    self.total_progress_bar.pack(fill=tk.X, pady=(4, 8))
    table_container = ttk.Frame(self.progress_frame)
    table_container.pack(fill=tk.BOTH, expand=True)
    self.file_tree = ttk.Treeview(
      table_container,
      columns=self.file_columns,
      show='headings',
      height=8,
      selectmode='browse'
    )
    self.file_tree.column('name', anchor=tk.W, width=220)
    self.file_tree.column('status', anchor=tk.W, width=140)
    self.file_tree.column('progress', anchor=tk.CENTER, width=80)
    self.file_tree.column('path', anchor=tk.W, width=220)
    self.file_tree_scrollbar = ttk.Scrollbar(table_container, orient=tk.VERTICAL, command=self.file_tree.yview)
    self.file_tree.configure(yscrollcommand=self.file_tree_scrollbar.set)
    self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    self.file_tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    self.advanced_visible = False
    self.advanced_button = ttk.Button(main_frame, text='', command=self._toggle_advanced)
    self.advanced_button.pack(fill=tk.X, pady=(8, 0))
    self.advanced_frame = ttk.LabelFrame(main_frame, text='', padding=12)
    self.host_label = ttk.Label(self.advanced_frame, text='')
    self.host_label.grid(row=0, column=0, sticky=tk.W, padx=4, pady=4)
    self.host_var = tk.StringVar(value=self.user_preferences.host or '127.0.0.1')
    host_entry = ttk.Entry(self.advanced_frame, textvariable=self.host_var, width=20)
    host_entry.grid(row=0, column=1, sticky=tk.W, padx=4, pady=4)
    host_entry.bind('<FocusOut>', self._on_host_commit)
    host_entry.bind('<Return>', self._on_host_commit)
    self.port_label = ttk.Label(self.advanced_frame, text='')
    self.port_label.grid(row=1, column=0, sticky=tk.W, padx=4, pady=4)
    self.port_var = tk.StringVar(value=str(self.user_preferences.port or 11548))
    port_entry = ttk.Entry(self.advanced_frame, textvariable=self.port_var, width=10)
    port_entry.grid(row=1, column=1, sticky=tk.W, padx=4, pady=4)
    port_entry.bind('<FocusOut>', self._on_port_commit)
    port_entry.bind('<Return>', self._on_port_commit)
    self.file_limit_label = ttk.Label(self.advanced_frame, text='')
    self.file_limit_label.grid(row=2, column=0, sticky=tk.W, padx=4, pady=4)
    self.file_limit_var = tk.StringVar(value=str(self.file_display_limit))
    file_limit_entry = ttk.Entry(self.advanced_frame, textvariable=self.file_limit_var, width=10)
    file_limit_entry.grid(row=2, column=1, sticky=tk.W, padx=4, pady=4)
    file_limit_entry.bind('<FocusOut>', self._on_file_limit_commit)
    file_limit_entry.bind('<Return>', self._on_file_limit_commit)
    self.advanced_tip = ttk.Label(self.advanced_frame, text='', wraplength=360)
    self.advanced_tip.grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=4, pady=(4, 0))
    self.advanced_frame.columnconfigure(1, weight=1)

    button_frame = ttk.Frame(main_frame, padding=(0, 12))
    button_frame.pack(fill=tk.X)

    self.status_var = tk.StringVar(value='Idle')
    self.status_label = ttk.Label(button_frame, textvariable=self.status_var)
    self.status_label.pack(side=tk.LEFT)

    self.log_visible = False
    self.log_toggle_button = ttk.Button(button_frame, text='', command=self._toggle_logs)
    self.log_toggle_button.pack(side=tk.RIGHT, padx=4)
    self.start_button = ttk.Button(button_frame, text='', command=self._start_server)
    self.start_button.pack(side=tk.RIGHT, padx=4)
    self.stop_button = ttk.Button(button_frame, text='', command=self._stop_server)
    self.stop_button.pack(side=tk.RIGHT, padx=4)
    self.open_config_button = ttk.Button(button_frame, text='', command=self._open_config_folder)
    self.open_config_button.pack(side=tk.RIGHT, padx=4)

    self.log_frame = ttk.LabelFrame(main_frame, text='', padding=8)
    self.log_text = tk.Text(self.log_frame, state=tk.DISABLED, height=12, wrap=tk.NONE)
    self.log_text.pack(fill=tk.BOTH, expand=True)
    self._update_advanced_visibility()
    self._update_log_visibility()

  def _choose_output_dir(self) -> None:
    """弹出目录选择器并更新输出路径。"""
    selected = filedialog.askdirectory()
    if selected:
      self.output_var.set(selected)
      self._apply_output_dir_change()

  def _on_output_dir_commit(self, _event=None) -> None:
    """处理输入框失焦或回车事件，应用新的目录。"""
    self._apply_output_dir_change()

  def _apply_output_dir_change(self) -> None:
    """将最新的保存目录同步到运行中的服务。"""
    new_dir = self.output_var.get().strip()
    if not new_dir:
      return
    self._update_user_preferences(output_dir=new_dir)
    if not self.server or not self.server.is_running:
      return
    try:
      updated = self.server.update_output_dir(new_dir)
      logging.info('output directory updated to %s', updated)
    except Exception as exc:  # noqa: BLE001
      logging.exception('failed to update output directory')
      messagebox.showerror(
        self._t('dialog_error_title'),
        self._t('msg_output_dir_failed', error=str(exc))
      )

  def _on_host_commit(self, _event=None) -> None:
    """在主机输入框失焦或回车时保存配置。"""
    host = self.host_var.get().strip() or DEFAULT_HOST
    self.host_var.set(host)
    self._update_user_preferences(host=host)

  def _on_port_commit(self, _event=None) -> None:
    """在端口输入框失焦或回车时校验并保存。"""
    try:
      port = self._parse_port_value(self.port_var.get())
    except ValueError as exc:
      messagebox.showerror(self._t('dialog_error_title'), str(exc))
      self.port_var.set(str(self.user_preferences.port))
      return
    self._update_user_preferences(port=port)

  def _on_file_limit_commit(self, _event=None) -> None:
    """在高级设置中调整文件展示数量。"""
    value = (self.file_limit_var.get() or '').strip()
    try:
      limit = int(value)
    except ValueError:
      messagebox.showerror(self._t('dialog_error_title'), self._t('msg_invalid_file_limit'))
      self.file_limit_var.set(str(self.file_display_limit))
      return
    if limit < 100 or limit > 5000:
      messagebox.showerror(self._t('dialog_error_title'), self._t('msg_invalid_file_limit'))
      self.file_limit_var.set(str(self.file_display_limit))
      return
    self.file_display_limit = limit
    self._update_user_preferences(file_display_limit=limit)

  def _on_personal_token_commit(self, _event=None) -> None:
    """在授权码输入框失焦或回车时保存值。"""
    token = self.personal_token_var.get().strip()
    self._update_user_preferences(personal_base_token=token)
    self._apply_personal_token_change(token)

  def _update_user_preferences(self, **changes) -> None:
    """合并偏好修改并写入配置文件。"""
    for key, value in changes.items():
      setattr(self.user_preferences, key, value)
    self.file_display_limit = max(self.user_preferences.file_display_limit or DEFAULT_FILE_DISPLAY_LIMIT, 100)
    self._save_user_preferences()

  def _apply_personal_token_change(self, token: str) -> None:
    """将授权码变更同步至运行中的服务。"""
    if not self.server or not self.server.is_running:
      return
    normalized = token.strip()
    try:
      self.server.update_personal_token(normalized or None)
      logging.info('personal base token updated')
    except Exception as exc:  # noqa: BLE001
      logging.exception('failed to update personal token')
      messagebox.showerror(
        self._t('dialog_error_title'),
        self._t('msg_personal_token_failed', error=str(exc))
      )

  def _save_user_preferences(self) -> None:
    """安全地保存用户配置。"""
    try:
      save_user_config(self.user_preferences)
    except Exception as exc:  # noqa: BLE001
      logging.exception('failed to save user preferences: %s', exc)

  def _toggle_advanced(self) -> None:
    """切换高级设置面板可见性。"""
    self.advanced_visible = not self.advanced_visible
    self._update_advanced_visibility()

  def _update_advanced_visibility(self) -> None:
    """根据状态显示/隐藏高级设置。"""
    if self.advanced_visible:
      self.advanced_frame.pack(fill=tk.X, expand=False, pady=(0, 8))
      button_text = self._t('advanced_toggle_hide')
    else:
      self.advanced_frame.pack_forget()
      button_text = self._t('advanced_toggle_show')
    self.advanced_button.config(text=button_text)
    self.advanced_frame.config(text=self._t('advanced_settings'))
    self.advanced_tip.config(text=self._t('advanced_settings_desc'))

  def _toggle_logs(self) -> None:
    """切换日志面板显示。"""
    self.log_visible = not self.log_visible
    self._update_log_visibility()

  def _open_output_dir(self) -> None:
    """打开当前保存目录。"""
    output_path = self.output_var.get().strip() or self.user_preferences.output_dir or DEFAULT_OUTPUT_DIR
    try:
      target = Path(output_path).expanduser().resolve()
      target.mkdir(parents=True, exist_ok=True)
      if sys.platform.startswith('win'):
        os.startfile(target)  # type: ignore[attr-defined]
      elif sys.platform == 'darwin':
        subprocess.Popen(['open', str(target)], close_fds=True)
      else:
        subprocess.Popen(['xdg-open', str(target)], close_fds=True)
    except Exception as exc:  # noqa: BLE001
      logging.exception('failed to open output directory')
      messagebox.showerror(self._t('dialog_error_title'), self._t('msg_open_output_failed', error=str(exc)))

  def _open_config_folder(self) -> None:
    """通过系统默认程序打开配置文件所在目录。"""
    try:
      target_dir = CONFIG_FILE.parent
      target_dir.mkdir(parents=True, exist_ok=True)
      CONFIG_FILE.touch(exist_ok=True)
      if sys.platform.startswith('win'):
        os.startfile(target_dir)  # type: ignore[attr-defined]
      elif sys.platform == 'darwin':
        subprocess.Popen(['open', str(target_dir)], close_fds=True)
      else:
        subprocess.Popen(['xdg-open', str(target_dir)], close_fds=True)
    except Exception as exc:  # noqa: BLE001
      logging.exception('failed to open config folder')
      messagebox.showerror(self._t('dialog_error_title'), self._t('msg_open_config_failed', error=str(exc)))

  def _update_log_visibility(self) -> None:
    """根据状态显示/隐藏日志区。"""
    if self.log_visible:
      self.log_frame.pack(fill=tk.BOTH, expand=True)
      button_text = self._t('btn_hide_logs')
    else:
      self.log_frame.pack_forget()
      button_text = self._t('btn_show_logs')
    self.log_toggle_button.config(text=button_text)

  def _schedule_stats_refresh(self) -> None:
    """定时更新统计信息。"""
    self._refresh_stats()
    self.root.after(500, self._schedule_stats_refresh)

  def _refresh_stats(self) -> None:
    """将下载统计渲染到界面。"""
    snapshot = self.monitor.snapshot()
    connection_key = 'stat_connection_connected' if snapshot['connected'] else 'stat_connection_disconnected'
    self.connection_var.set(self._t(connection_key))
    mode_key = 'mode_client_token' if snapshot.get('mode') == 'token' else 'mode_client'
    self.mode_var.set(self._t('stat_mode', mode=self._t(mode_key)))
    self.current_var.set(self._t('stat_current', count=snapshot['active']))
    self.completed_var.set(self._t('stat_completed', count=snapshot['completed']))
    self.pending_var.set(self._t('stat_pending', count=snapshot['pending']))
    overall = snapshot.get('overall') or {}
    percent = float(overall.get('percent', 0.0) or 0.0)
    finished = overall.get('finished', 0)
    total = overall.get('total', 0)
    self.total_progress_var.set(self._t('overall_progress', percent=f'{percent:.0f}%', finished=finished, total=total))
    self.total_progress_bar['value'] = percent
    self._refresh_file_table(snapshot.get('files') or [])

  def _refresh_file_table(self, files: List[Dict[str, object]]) -> None:
    """在表格中渲染单个文件的进度。"""
    limit = max(self.user_preferences.file_display_limit or DEFAULT_FILE_DISPLAY_LIMIT, 100)
    visible_files = files[-limit:]
    for item in self.file_tree.get_children():
      self.file_tree.delete(item)
    for entry in visible_files:
      status_key = f"file_status_{entry.get('status', 'pending')}"
      status_label = self._t(status_key)
      error = entry.get('error')
      if error:
        status_label = f"{status_label} ({error})"
      progress_value = float(entry.get('percent', 0.0) or 0.0)
      progress_text = f"{progress_value:.0f}%"
      self.file_tree.insert(
        '',
        tk.END,
        iid=str(entry.get('key', '')),
        values=(
          entry.get('name', ''),
          status_label,
          progress_text,
          entry.get('path', '')
        )
      )
    if visible_files:
      self.file_tree.yview_moveto(1.0)

  def _parse_port_value(self, value: str) -> int:
    """校验端口输入并返回整数。"""
    try:
      port = int(value)
    except ValueError as exc:
      raise ValueError(self._t('msg_invalid_port')) from exc
    if not 1 <= port <= 65535:
      raise ValueError(self._t('msg_invalid_port'))
    return port

  def _build_config(self) -> ServerConfig:
    """根据界面输入构造 ServerConfig。"""
    port = self._parse_port_value(self.port_var.get())
    host = self.host_var.get().strip() or '127.0.0.1'
    output_dir = self.output_var.get().strip() or 'downloads'
    personal_token = self.personal_token_var.get().strip()
    self._update_user_preferences(host=host, port=port, output_dir=output_dir, personal_base_token=personal_token)
    return ServerConfig(
      host=host,
      port=port,
      output_dir=output_dir,
      download_concurrency=DEFAULT_PYTHON_CONCURRENCY,
      personal_base_token=personal_token
    )

  def _start_server(self, auto: bool = False) -> None:
    """启动 WebSocket 服务并更新状态。"""
    if self.server and self.server.is_running:
      if not auto:
        messagebox.showinfo(self._t('dialog_info_title'), self._t('msg_server_running'))
      return
    try:
      config = self._build_config()
    except ValueError as exc:
      if not auto:
        messagebox.showerror(self._t('dialog_error_title'), str(exc))
      return
    try:
      self.server = WebSocketDownloadServer(config, monitor=self.monitor)
      self.server.start()
      self._set_status('running', host=config.host, port=config.port)
      logging.info('desktop server started')
    except Exception as exc:  # noqa: BLE001
      logging.exception('failed to start desktop server')
      if not auto:
        messagebox.showerror(self._t('dialog_error_title'), self._t('msg_start_failed', error=str(exc)))

  def _stop_server(self) -> None:
    """停止 WebSocket 服务并更新状态。"""
    if not self.server:
      return
    try:
      self.server.stop()
      self._set_status('stopped')
      logging.info('desktop server stopped by user')
    except Exception as exc:  # noqa: BLE001
      logging.exception('failed to stop desktop server')
      messagebox.showerror(self._t('dialog_error_title'), self._t('msg_stop_failed', error=str(exc)))

  def _schedule_log_polling(self) -> None:
    """启动循环任务，从队列中读取日志到界面。"""
    self._drain_log_queue()
    self.root.after(200, self._schedule_log_polling)

  def _drain_log_queue(self) -> None:
    """将队列中的日志逐条写入文本框。"""
    while not self.log_queue.empty():
      message = self.log_queue.get_nowait()
      self.log_text.configure(state=tk.NORMAL)
      self.log_text.insert(tk.END, message + '\n')
      self.log_text.configure(state=tk.DISABLED)
      self.log_text.see(tk.END)

  def run(self) -> None:
    """进入 Tkinter 主循环。"""
    self.root.protocol('WM_DELETE_WINDOW', self._on_close)
    self.root.mainloop()

  def _on_close(self) -> None:
    """在窗口关闭时停止服务并销毁 GUI。"""
    if self.server and self.server.is_running:
      if not messagebox.askyesno(self._t('dialog_confirm_title'), self._t('msg_exit_running')):
        return
      self.server.stop()
    self.root.destroy()

  def _set_language(self, code: str) -> None:
    """根据语言代码更新界面文本。"""
    code = self._normalize_language_code(code)
    self.localizer.set_locale(code)
    if self.user_preferences.language != code:
      self._update_user_preferences(language=code)
    label = self.language_label_map.get(code, list(self.language_label_map.values())[0])
    if self.language_combo.get() != label:
      self.language_combo.set(label)
    self._apply_translations()

  def _normalize_language_code(self, code: Optional[str]) -> str:
    """确保语言代码落在支持范围内，并兼容区域化代码。"""
    normalized = normalize_locale(code or DEFAULT_LANGUAGE)
    if normalized in self.language_label_map:
      return normalized
    return DEFAULT_LANGUAGE

  def _on_language_change(self, _event) -> None:
    """语言选择事件回调。"""
    label = self.language_combo.get()
    code = self.language_code_map.get(label, DEFAULT_LANGUAGE)
    self._set_language(code)

  def _apply_translations(self) -> None:
    """刷新界面上的多语言文本。"""
    self.root.title(self._t('title'))
    self.language_label_widget.config(text=self._t('language_label') + ':')
    self.form_frame.config(text=self._t('server_config'))
    self.stats_frame.config(text=self._t('stats_title'))
    self.host_label.config(text=self._t('host') + ':')
    self.port_label.config(text=self._t('port') + ':')
    self.output_label.config(text=self._t('output_dir') + ':')
    self.browse_button.config(text=self._t('browse'))
    self.start_button.config(text=self._t('btn_start'))
    self.stop_button.config(text=self._t('btn_stop'))
    self.open_output_button.config(text=self._t('btn_open_output_dir'))
    self.open_config_button.config(text=self._t('btn_open_config'))
    self.log_frame.config(text=self._t('logs'))
    self.advanced_frame.config(text=self._t('advanced_settings'))
    self.advanced_tip.config(text=self._t('advanced_settings_desc'))
    self.personal_token_label.config(text=self._t('personal_token') + ':')
    self.personal_token_hint.config(text=self._t('personal_token_hint'))
    self.progress_frame.config(text=self._t('files_title'))
    self.file_limit_label.config(text=self._t('file_limit_label') + ':')
    self.file_tree.heading('name', text=self._t('file_column_name'))
    self.file_tree.heading('status', text=self._t('file_column_status'))
    self.file_tree.heading('progress', text=self._t('file_column_progress'))
    self.file_tree.heading('path', text=self._t('file_column_path'))
    self._update_advanced_visibility()
    self._update_log_visibility()
    self._refresh_stats()
    self._refresh_status_text()

  def _refresh_status_text(self) -> None:
    """根据当前状态刷新状态栏文本。"""
    key = f'status_{self._status_state}'
    self.status_var.set(self._t(key, **self._status_context))

  def _set_status(self, state: str, **context) -> None:
    """记录状态并更新状态栏。"""
    self._status_state = state
    self._status_context = context
    self._refresh_status_text()

  def _t(self, key: str, **kwargs) -> str:
    """封装本地化翻译调用。"""
    return self.localizer.translate(key, **kwargs)


def launch_desktop_app() -> None:
  """启动桌面程序入口。"""
  app = DownloaderDesktopApp()
  app.run()
