/**
 * Umami 统计追踪器
 * 职责: 统一管理下载行为的数据埋点
 *
 * 埋点规范:
 * - 事件名: 中文下划线命名（如：下载_开始）
 * - 参数名: 中文下划线命名（如：文件总数、下载模式）
 * - 枚举值: 中文（如：浏览器直下、网络错误）
 */
class UmamiTracker {
  constructor() {
    this.isEnabled = typeof window !== 'undefined' && typeof window.umami !== 'undefined'
    this.sessionId = this._generateSessionId()
  }

  /**
   * 生成会话 ID（用于关联同一次下载任务的所有事件）
   */
  _generateSessionId() {
    return `${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }

  /**
   * 重置会话 ID（每次新下载任务调用）
   */
  resetSession() {
    this.sessionId = this._generateSessionId()
  }

  /**
   * 获取通用参数
   */
  _getCommonParams() {
    return {
      会话ID: this.sessionId,
      时间戳: Date.now()
    }
  }

  /**
   * 下载模式映射
   */
  _getDownloadMode(channel) {
    const modeMap = {
      browser: '浏览器直下',
      websocket: 'WebSocket临时链接',
      websocket_auth: 'WebSocket授权码'
    }
    return modeMap[channel] || channel || '未知'
  }

  /**
   * 下载类型映射
   */
  _getDownloadType(type, channel) {
    // WebSocket 模式下无 downloadType 参数
    if (!type && (channel === 'websocket' || channel === 'websocket_auth')) {
      return 'WebSocket推送'
    }

    const typeMap = {
      1: 'ZIP打包',
      2: '逐个下载'
    }
    return typeMap[type] || '未知'
  }

  /**
   * 1. 下载_开始
   * 用户启动下载任务
   */
  trackDownloadStart(options = {}) {
    if (!this.isEnabled) return

    const { downloadChannel, downloadType, fileCount, totalSize } = options

    window.umami.track('下载_开始', {
      ...this._getCommonParams(),
      下载模式: this._getDownloadMode(downloadChannel),
      下载类型: this._getDownloadType(downloadType, downloadChannel),
      文件总数: fileCount || 0,
      总大小MB: totalSize ? parseFloat((totalSize / (1024 * 1024)).toFixed(2)) : 0
    })
  }

  /**
   * 2. 下载_完成
   * 下载任务正常结束（无论成功/失败）
   */
  trackDownloadComplete(result = {}) {
    if (!this.isEnabled) return

    try {
      const {
        fileCount,
        successCount,
        failedCount,
        duration,
        isCancelled,
        failureStats,
        downloadChannel
      } = result

      const eventData = {
        ...this._getCommonParams(),
        下载模式: this._getDownloadMode(downloadChannel),
        文件总数: fileCount || 0,
        成功数量: successCount || 0,
        失败数量: failedCount || 0,
        耗时秒: duration ? Math.round(duration / 1000) : 0,
        成功率: fileCount ? parseFloat(((successCount / fileCount) * 100).toFixed(2)) : 0,
        是否被取消: Boolean(isCancelled)
      }

      // 添加失败原因详细统计（仅当有失败时）
      if (failureStats?.byType && Object.keys(failureStats.byType).length > 0) {
        const typeMapping = {
          network: '失败_网络错误',
          auth: '失败_授权错误',
          expired_url: '失败_链接过期',
          server: '失败_服务器错误',
          client: '失败_客户端错误',
          timeout: '失败_超时错误',
          cors: '失败_CORS错误',
          filesystem: '失败_文件系统错误',
          unknown: '失败_未知错误'
        }

        Object.entries(failureStats.byType).forEach(([type, count]) => {
          if (count > 0 && typeMapping[type]) {
            eventData[typeMapping[type]] = count
          }
        })
      }

      window.umami.track('下载_完成', eventData)
    } catch (error) {
      console.warn('[UmamiTracker] trackDownloadComplete 失败:', error)
    }
  }

  /**
   * 3. 下载_取消
   * 用户主动取消或异常中断
   */
  trackDownloadCancel(cancelInfo = {}) {
    if (!this.isEnabled) return

    try {
      const {
        reason,
        fileCount,
        successCount,
        failedCount,
        duration,
        downloadChannel,
        errorCode,
        errorStack
      } = cancelInfo

      const reasonMap = {
        user_manual_cancel: '用户主动取消',
        network_error: '网络异常中断',
        auth_error: '授权失败中断',
        server_error: '服务器错误中断',
        websocket_error: 'WebSocket断开',
        unknown_error: '未知错误中断'
      }

      const eventData = {
        ...this._getCommonParams(),
        下载模式: this._getDownloadMode(downloadChannel),
        取消原因: reasonMap[reason] || reason || '未知',
        文件总数: fileCount || 0,
        已完成数量: successCount || 0,
        已失败数量: failedCount || 0,
        已耗时秒: duration ? Math.round(duration / 1000) : 0,
        完成进度: fileCount ? parseFloat((((successCount + failedCount) / fileCount) * 100).toFixed(2)) : 0
      }

      // 添加错误详情（仅在异常中断时）
      if (reason !== 'user_manual_cancel') {
        if (errorCode) eventData.错误代码 = errorCode
        if (errorStack) eventData.错误堆栈 = errorStack.substring(0, 200) // 截取前200字符
      }

      window.umami.track('下载_取消', eventData)
    } catch (error) {
      console.warn('[UmamiTracker] trackDownloadCancel 失败:', error)
    }
  }

  /**
   * 4. 下载_致命错误
   * 导致下载任务无法继续的严重错误
   */
  trackDownloadFatalError(error = {}) {
    if (!this.isEnabled) return

    try {
      const {
        type,
        message,
        downloadMode,
        downloadChannel, // 兼容新参数名
        code,
        stack,
        httpStatus,
        url,
        fileName
      } = error

      const eventData = {
        ...this._getCommonParams(),
        下载模式: this._getDownloadMode(downloadChannel, downloadMode), // 优先使用 downloadChannel
        错误类型: type || '未知',
        错误信息: message || '未知错误',
        错误代码: code || '',
        HTTP状态码: httpStatus || 0,
        错误堆栈: stack ? stack.substring(0, 200) : ''
      }

      // 添加上下文信息
      if (url) eventData.错误URL = url.substring(0, 100)
      if (fileName) eventData.错误文件 = fileName

      window.umami.track('下载_致命错误', eventData)
    } catch (err) {
      console.warn('[UmamiTracker] trackDownloadFatalError 失败:', err)
    }
  }

  /**
   * 5. 文件_下载失败
   * 单个文件下载失败（用于统计失败原因分布）
   */
  trackFileDownloadError(error = {}) {
    if (!this.isEnabled) return

    const {
      fileName,
      fileSize,
      errorType,
      httpStatus,
      retryCount,
      downloadMode
    } = error

    const errorTypeMap = {
      network: '网络错误',
      auth: '授权错误',
      expired_url: '链接过期',
      server: '服务器错误',
      client: '客户端错误',
      timeout: '超时错误',
      cors: 'CORS错误',
      filesystem: '文件系统错误',
      unknown: '未知错误'
    }

    window.umami.track('文件_下载失败', {
      ...this._getCommonParams(),
      下载模式: this._getDownloadMode(downloadMode),
      文件名: fileName || '未知',
      文件大小MB: fileSize ? parseFloat((fileSize / (1024 * 1024)).toFixed(2)) : 0,
      失败类型: errorTypeMap[errorType] || errorType || '未知',
      HTTP状态码: httpStatus || 0,
      已重试次数: retryCount || 0
    })
  }

  /**
   * 6. 重试_单个文件
   * 用户手动重试单个失败文件
   */
  trackRetryFile(retryInfo = {}) {
    if (!this.isEnabled) return

    const { fileName, fileSize, errorType, downloadMode } = retryInfo

    window.umami.track('重试_单个文件', {
      ...this._getCommonParams(),
      下载模式: this._getDownloadMode(downloadMode),
      文件名: fileName || '未知',
      文件大小MB: fileSize ? parseFloat((fileSize / (1024 * 1024)).toFixed(2)) : 0,
      原失败类型: errorType || '未知'
    })
  }

  /**
   * 7. 重试_批量失败
   * 用户批量重试所有失败文件
   */
  trackRetryBatch(retryInfo = {}) {
    if (!this.isEnabled) return

    const { fileCount, totalSize, downloadMode, failureTypes } = retryInfo

    const eventData = {
      ...this._getCommonParams(),
      下载模式: this._getDownloadMode(downloadMode),
      重试文件数: fileCount || 0,
      重试总大小MB: totalSize ? parseFloat((totalSize / (1024 * 1024)).toFixed(2)) : 0
    }

    // 添加失败类型分布
    if (failureTypes) {
      eventData.包含网络错误 = failureTypes.network || 0
      eventData.包含授权错误 = failureTypes.auth || 0
      eventData.包含链接过期 = failureTypes.expired_url || 0
      eventData.包含服务器错误 = failureTypes.server || 0
      eventData.包含其他错误 = failureTypes.unknown || 0
    }

    window.umami.track('重试_批量失败', eventData)
  }

  /**
   * 8. 打包_ZIP完成
   * ZIP 打包任务完成
   */
  trackZipComplete(zipInfo = {}) {
    if (!this.isEnabled) return

    const { fileCount, totalSize, duration, downloadMode } = zipInfo

    window.umami.track('打包_ZIP完成', {
      ...this._getCommonParams(),
      下载模式: this._getDownloadMode(downloadMode),
      打包文件数: fileCount || 0,
      打包大小MB: totalSize ? parseFloat((totalSize / (1024 * 1024)).toFixed(2)) : 0,
      打包耗时秒: duration ? Math.round(duration / 1000) : 0
    })
  }

  /**
   * 9. 连接_WebSocket
   * WebSocket 连接状态
   */
  trackWebSocketConnection(connection = {}) {
    if (!this.isEnabled) return

    const { status, mode, errorMessage, retryCount } = connection

    const statusMap = {
      success: '连接成功',
      failed: '连接失败',
      closed: '连接关闭',
      error: '连接错误'
    }

    const modeMap = {
      url: '临时链接模式',
      token: '授权码模式'
    }

    const eventData = {
      ...this._getCommonParams(),
      连接状态: statusMap[status] || status || '未知',
      连接模式: modeMap[mode] || mode || '未知'
    }

    if (status === 'failed' || status === 'error') {
      eventData.错误信息 = errorMessage || '未知错误'
      eventData.重试次数 = retryCount || 0
    }

    window.umami.track('连接_WebSocket', eventData)
  }

  /**
   * 10. 刷新_临时链接
   * 飞书临时下载链接失效后刷新
   */
  trackRefreshTempUrl(refreshInfo = {}) {
    if (!this.isEnabled) return

    const {
      fileName,
      httpStatus,
      refreshSuccess,
      downloadMode,
      retryCount
    } = refreshInfo

    window.umami.track('刷新_临时链接', {
      ...this._getCommonParams(),
      下载模式: this._getDownloadMode(downloadMode),
      文件名: fileName || '未知',
      触发状态码: httpStatus || 0,
      刷新是否成功: Boolean(refreshSuccess),
      累计刷新次数: retryCount || 1
    })
  }

  /**
   * 11. 配置_提交
   * 用户提交下载配置
   */
  trackConfigSubmit(config = {}) {
    if (!this.isEnabled) return

    const {
      fileNameType,
      downloadTypeByFolders,
      attachmentFieldsCount,
      downloadChannel,
      downloadType,
      concurrency
    } = config

    window.umami.track('配置_提交', {
      ...this._getCommonParams(),
      下载模式: this._getDownloadMode(downloadChannel),
      下载类型: this._getDownloadType(downloadType, downloadChannel),
      使用自定义命名: fileNameType === 1,
      使用目录分类: Boolean(downloadTypeByFolders),
      附件字段数量: attachmentFieldsCount || 0,
      并发数: concurrency || 0
    })
  }

  /**
   * 12. 性能_下载速度
   * 记录下载速度统计（用于性能分析）
   */
  trackDownloadSpeed(speedInfo = {}) {
    if (!this.isEnabled) return

    try {
      const {
        averageSpeedMBps,
        peakSpeedMBps,
        fileCount,
        totalSizeMB,
        duration,
        downloadMode,
        downloadChannel // 兼容新参数名
      } = speedInfo

      // 如果没有传入速度参数，使用内部统计的速度
      const actualAverageSpeed = averageSpeedMBps ?? this.getAverageSpeed()
      const actualPeakSpeed = peakSpeedMBps ?? this.peakSpeedMBps

      window.umami.track('性能_下载速度', {
        ...this._getCommonParams(),
        下载模式: this._getDownloadMode(downloadChannel, downloadMode),
        平均速度MBps: actualAverageSpeed ? parseFloat(actualAverageSpeed.toFixed(2)) : 0,
        峰值速度MBps: actualPeakSpeed ? parseFloat(actualPeakSpeed.toFixed(2)) : 0,
        文件总数: fileCount || 0,
        总大小MB: totalSizeMB || 0,
        总耗时秒: duration ? Math.round(duration / 1000) : 0
      })
    } catch (error) {
      console.warn('[UmamiTracker] trackDownloadSpeed 失败:', error)
    }
  }
}

export default UmamiTracker
