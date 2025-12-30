/**
 * Umami 统计追踪器
 * 职责: 统一管理下载行为的数据埋点
 */
class UmamiTracker {
  constructor() {
    this.isEnabled = typeof window !== 'undefined' && typeof window.umami !== 'undefined'
  }

  /**
   * 追踪下载开始事件
   * @param {Object} options - 下载配置
   */
  trackDownloadStart(options = {}) {
    if (!this.isEnabled) return

    const { downloadChannel, downloadType, fileCount, totalSize } = options

    // 下载模式映射
    const modeMap = {
      browser: '浏览器直接下载',
      websocket: 'WebSocket临时链接',
      websocket_auth: 'WebSocket授权码'
    }

    // 下载类型映射
    const typeMap = {
      1: 'ZIP打包',
      2: '逐个下载'
    }

    window.umami.track('download_start', {
      download_mode: modeMap[downloadChannel] || downloadChannel,
      download_type: downloadType ? typeMap[downloadType] : 'WebSocket推送',
      file_count: fileCount || 0,
      total_size_mb: totalSize ? (totalSize / (1024 * 1024)).toFixed(2) : 0
    })
  }

  /**
   * 追踪下载完成事件
   * @param {Object} result - 下载结果
   */
  trackDownloadComplete(result = {}) {
    if (!this.isEnabled) return

    const { fileCount, successCount, failedCount, duration } = result

    window.umami.track('download_complete', {
      file_count: fileCount || 0,
      success_count: successCount || 0,
      failed_count: failedCount || 0,
      duration_seconds: duration ? Math.round(duration / 1000) : 0,
      success_rate: fileCount ? ((successCount / fileCount) * 100).toFixed(2) : 0
    })
  }

  /**
   * 追踪下载失败事件
   * @param {Object} error - 错误信息
   */
  trackDownloadError(error = {}) {
    if (!this.isEnabled) return

    window.umami.track('download_error', {
      error_type: error.type || 'unknown',
      error_message: error.message || '未知错误',
      download_mode: error.downloadMode || 'unknown'
    })
  }

  /**
   * 追踪 ZIP 打包进度
   * @param {Object} progress - 打包进度
   */
  trackZipProgress(progress = {}) {
    if (!this.isEnabled) return

    // 仅在特定阶段上报（避免过于频繁）
    const { stage, fileCount } = progress
    if (stage === 'complete') {
      window.umami.track('zip_package_complete', {
        file_count: fileCount || 0
      })
    }
  }

  /**
   * 追踪 WebSocket 连接
   * @param {Object} connection - 连接信息
   */
  trackWebSocketConnection(connection = {}) {
    if (!this.isEnabled) return

    const { status, mode } = connection

    window.umami.track('websocket_connection', {
      status: status || 'unknown', // 'success' | 'failed'
      mode: mode || 'unknown'      // 'url' | 'token'
    })
  }

  /**
   * 追踪用户配置选择
   * @param {Object} config - 用户配置
   */
  trackUserConfig(config = {}) {
    if (!this.isEnabled) return

    const {
      fileNameType,
      downloadTypeByFolders,
      attachmentFieldsCount
    } = config

    window.umami.track('download_config', {
      use_custom_filename: fileNameType === 1,
      use_folder_classification: Boolean(downloadTypeByFolders),
      attachment_fields_count: attachmentFieldsCount || 0
    })
  }
}

export default UmamiTracker
