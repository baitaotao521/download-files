/**
 * 轻量级事件发射器
 * 职责:管理事件订阅与发布,解耦下载器与 UI 层的通信
 */
class EventEmitter {
  constructor() {
    this._listeners = new Map()
  }

  /**
   * 注册事件监听器
   * @param {string} event - 事件名称
   * @param {Function} callback - 回调函数
   * @returns {EventEmitter} this
   */
  on(event, callback) {
    if (typeof callback !== 'function') {
      throw new Error('Callback must be a function')
    }
    if (!this._listeners.has(event)) {
      this._listeners.set(event, [])
    }
    this._listeners.get(event).push(callback)
    return this
  }

  /**
   * 触发事件
   * @param {string} event - 事件名称
   * @param {*} data - 事件数据
   */
  emit(event, data) {
    const listeners = this._listeners.get(event)
    if (!listeners || !listeners.length) {
      return
    }
    listeners.forEach((listener) => {
      try {
        listener(data)
      } catch (error) {
        console.error(`Error in ${event} listener:`, error)
      }
    })
  }

  /**
   * 移除事件监听器
   * @param {string} event - 事件名称
   * @param {Function} callback - 回调函数(可选,不传则移除所有监听器)
   */
  off(event, callback) {
    if (!callback) {
      this._listeners.delete(event)
      return
    }
    const listeners = this._listeners.get(event)
    if (!listeners) return

    const index = listeners.indexOf(callback)
    if (index !== -1) {
      listeners.splice(index, 1)
    }
    if (listeners.length === 0) {
      this._listeners.delete(event)
    }
  }

  /**
   * 清空所有监听器
   */
  clear() {
    this._listeners.clear()
  }
}

export default EventEmitter
