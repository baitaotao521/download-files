/**
 * 进度节流器
 * 职责:
 * - 减少高频进度更新对 UI 的影响
 * - 批量处理进度事件,降低渲染压力
 * - 保证最后一次 100% 进度必定触发
 */
class ProgressThrottler {
  constructor(emitter, throttleInterval = 100) {
    this.emitter = emitter
    this.throttleInterval = throttleInterval
    this.pendingUpdates = new Map() // fileIndex -> progressInfo
    this.timerId = null
    this.lastFlushTime = Date.now()
  }

  /**
   * 更新进度(节流)
   */
  updateProgress(progressInfo) {
    const { index, percentage } = progressInfo

    // 100% 进度立即发送,不节流
    if (percentage === 100) {
      this.pendingUpdates.delete(index)
      this.emitter.emit('progress', progressInfo)
      return
    }

    // 缓存进度更新
    this.pendingUpdates.set(index, progressInfo)

    // 启动定时器
    if (!this.timerId) {
      this.timerId = setTimeout(() => {
        this.flush()
      }, this.throttleInterval)
    }
  }

  /**
   * 批量刷新进度
   */
  flush() {
    if (this.pendingUpdates.size === 0) {
      this.timerId = null
      return
    }

    // 发送所有缓存的进度更新
    for (const progressInfo of this.pendingUpdates.values()) {
      this.emitter.emit('progress', progressInfo)
    }

    this.pendingUpdates.clear()
    this.lastFlushTime = Date.now()
    this.timerId = null
  }

  /**
   * 清理资源
   */
  destroy() {
    if (this.timerId) {
      clearTimeout(this.timerId)
      this.timerId = null
    }
    this.flush() // 确保最后的进度更新被发送
    this.pendingUpdates.clear()
  }
}

export default ProgressThrottler
