import { i18n } from '@/locales/i18n.js'

const $t = i18n.global.t

// WebSocket 消息类型常量
const WEBSOCKET_LINK_TYPE = 'feishu_attachment_link'
const WEBSOCKET_CONFIG_TYPE = 'feishu_attachment_config'
const WEBSOCKET_COMPLETE_TYPE = 'feishu_attachment_complete'
const WEBSOCKET_REFRESH_TYPE = 'feishu_attachment_refresh'
const WEBSOCKET_ACK_TYPE = 'feishu_attachment_ack'

/**
 * WebSocket 推送下载器
 * 职责:
 * - 管理 WebSocket 连接
 * - 临时链接模式推送
 * - 授权码模式推送
 * - 处理服务端 ACK 消息
 * - 链接刷新机制
 */
class WebSocketDownloader {
  constructor(emitter, fileProcessor, browserDownloader) {
    this.emitter = emitter
    this.fileProcessor = fileProcessor
    this.browserDownloader = browserDownloader
  }

  /**
   * 组合用户输入的 WebSocket URL
   */
  _buildWebSocketUrl(config) {
    const rawHost = (config.wsHost || '').trim()
    if (!rawHost) {
      throw new Error($t('error_websocket_host_required'))
    }
    if (/^wss?:\/\//i.test(rawHost)) {
      return rawHost
    }
    const port = config.wsPort ? String(config.wsPort).trim() : ''
    if (rawHost.includes(':') || !port) {
      return `ws://${rawHost}`
    }
    return `ws://${rawHost}:${port}`
  }

  /**
   * 建立 WebSocket 连接并在 ready 时返回实例
   */
  _createWebSocket(url) {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(url)
      const cleanup = () => {
        socket.onopen = null
        socket.onerror = null
      }
      socket.onopen = () => {
        cleanup()
        resolve(socket)
      }
      socket.onerror = () => {
        cleanup()
        reject(new Error($t('websocket_connection_failed')))
      }
    })
  }

  /**
   * 发送序列化后的 WebSocket 消息
   */
  _sendMessage(socket, payload) {
    if (socket.readyState !== WebSocket.OPEN) {
      throw new Error($t('websocket_connection_failed'))
    }
    socket.send(JSON.stringify(payload))
  }

  /**
   * 监听服务端 ACK,驱动 UI 并在任务完成或失败时结束
   */
  _bindLifecycle(socket, hooks = {}) {
    return new Promise((resolve, reject) => {
      let finished = false
      let hasJobCompleted = false
      const notifyFatal = (error) => {
        if (typeof hooks.onFatalError === 'function') {
          try {
            hooks.onFatalError(error)
          } catch (err) {
            console.error('onFatalError hook failed', err)
          }
        }
      }
      const finish = (error) => {
        if (finished) return
        finished = true
        if (error) {
          reject(error)
        } else {
          resolve()
        }
      }
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data)
          if (payload.type !== WEBSOCKET_ACK_TYPE) {
            return
          }
          const data = payload.data || {}
          const rawOrder = data.order
          const order = Number(rawOrder)
          const status = data.status
          const stage = data.stage
          if (stage === 'server_info') {
            if (typeof hooks.onServerInfo === 'function') {
              try {
                hooks.onServerInfo(data)
              } catch (err) {
                console.error('onServerInfo hook failed', err)
              }
            }
            return
          }
          if (Number.isInteger(order) && order > 0) {
            if (status === 'progress') {
              // Python 端实时进度推送
              const percentage = data.percentage
              if (typeof percentage === 'number') {
                this.emitter.emit('progress', {
                  index: order,
                  percentage: Math.min(Math.max(percentage, 0), 99)
                })
              }
            } else if (status === 'success') {
              this.emitter.emit('progress', {
                index: order,
                percentage: 100
              })
            } else if (status === 'refresh') {
              const message = data.message || $t('file_download_failed')
              if (typeof hooks.onRefreshUrl === 'function') {
                Promise.resolve()
                  .then(() => hooks.onRefreshUrl(order, data))
                  .then((downloadUrl) => {
                    this._sendMessage(socket, {
                      type: WEBSOCKET_REFRESH_TYPE,
                      data: {
                        order,
                        downloadUrl
                      }
                    })
                  })
                  .catch((error) => {
                    const errorMessage = error?.message || message
                    try {
                      this._sendMessage(socket, {
                        type: WEBSOCKET_REFRESH_TYPE,
                        data: {
                          order,
                          error: errorMessage
                        }
                      })
                    } catch (sendError) {
                      console.error('failed to send refresh error', sendError)
                    }
                  })
              }
            } else {
              this.emitter.emit('error', {
                index: order,
                message: data.message || $t('file_download_failed')
              })
            }
            return
          }
          if (stage === 'zip') {
            this.emitter.emit('zip_progress', {
              stage,
              path: data.path,
              message: data.message
            })
            return
          }
          if (stage === 'retry_failed_files') {
            this.emitter.emit('zip_progress', {
              stage,
              message: data.message,
              failed: data.failed
            })
            return
          }
          if (stage === 'job_complete') {
            hasJobCompleted = true
            this.emitter.emit('zip_progress', {
              stage,
              message: data.message
            })
            finish()
            return
          }
          if (status === 'error') {
            const message = data.message || $t('file_download_failed')
            this.emitter.emit('warn', message)
            notifyFatal(message)
            finish(new Error(message))
          }
        } catch (error) {
          console.error('failed to parse websocket ack', error)
        }
      }
      socket.onerror = () => {
        notifyFatal($t('websocket_connection_failed'))
        finish(new Error($t('websocket_connection_failed')))
      }
      socket.onclose = () => {
        if (hasJobCompleted) {
          finish()
        } else {
          notifyFatal($t('websocket_connection_failed'))
          finish(new Error($t('websocket_connection_failed')))
        }
      }
    })
  }

  /**
   * 授权码模式:按批次将附件标识推送给桌面端,推送完成后即可关闭前端
   */
  async _pushTokenFilesInBatches(socket, cellList, config, { sleep, drainSocketBuffer, shouldAbort }) {
    const tokenBatchSize = Math.max(1, Math.min(Number(config.tokenPushBatchSize) || 50, 10000))
    let batch = []

    const flush = async() => {
      if (!batch.length) {
        return
      }
      this._sendMessage(socket, {
        type: WEBSOCKET_LINK_TYPE,
        data: {
          files: batch
        }
      })
      batch = []
      await drainSocketBuffer()
      await sleep(0)
    }

    for (const fileInfo of cellList) {
      if (typeof shouldAbort === 'function' && shouldAbort()) {
        break
      }
      const { order } = fileInfo
      this.fileProcessor._prepareUniqueFileName(fileInfo)
      this.emitter.emit('progress', {
        index: order,
        name: fileInfo.name,
        size: fileInfo.size,
        percentage: 0
      })
      batch.push({
        name: fileInfo.name,
        path: fileInfo.path,
        order: fileInfo.order,
        size: fileInfo.size,
        token: fileInfo.token,
        fieldId: fileInfo.fieldId,
        recordId: fileInfo.recordId
      })
      if (batch.length >= tokenBatchSize) {
        await flush()
      }
    }

    if (!(typeof shouldAbort === 'function' && shouldAbort())) {
      await flush()
    }
  }

  /**
   * 本地客户端下载:串行发送链接或鉴权码
   */
  async download(cellList, config, oTable) {
    const wsUrl = this._buildWebSocketUrl(config)
    const socket = await this._createWebSocket(wsUrl)
    let abortDownloads = false
    // 宏任务延迟:让出事件循环,确保能及时处理服务端 ACK/refresh
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
    // WebSocket 发送回压:避免 bufferedAmount 过大导致 refresh 消息排队过久
    const drainSocketBuffer = async(maxBufferedAmount = 2 * 1024 * 1024) => {
      while (socket.bufferedAmount > maxBufferedAmount) {
        if (abortDownloads) return
        await sleep(20)
      }
    }
    const stopAllDownloads = (reason) => {
      if (abortDownloads) return
      abortDownloads = true
      const message = reason?.message || reason
      if (message) {
        this.emitter.emit('warn', message)
      }
    }
    const jobId = `${Date.now()}`
    const useTokenMode = config.downloadChannel === 'websocket_auth'
    if (useTokenMode && !config.appToken) {
      throw new Error($t('error_app_token_missing'))
    }
    const completion = useTokenMode
      ? Promise.resolve()
      : this._bindLifecycle(socket, {
        onFatalError: stopAllDownloads,
        onRefreshUrl: (() => {
          const fileInfoByOrder = new Map(
            (cellList || []).map((item) => [Number(item?.order), item])
          )
          const inflight = new Map()
          const maxConcurrent = Number.POSITIVE_INFINITY
          let active = 0
          const waitQueue = []
          const acquireSlot = async() => {
            if (active < maxConcurrent) {
              active += 1
              return
            }
            await new Promise((resolve) => waitQueue.push(resolve))
            active += 1
          }
          const releaseSlot = () => {
            active = Math.max(active - 1, 0)
            const next = waitQueue.shift()
            if (typeof next === 'function') {
              next()
            }
          }
          return async(order) => {
            if (inflight.has(order)) {
              return inflight.get(order)
            }
            const task = (async() => {
              const fileInfo = fileInfoByOrder.get(order)
              if (!fileInfo) {
                throw new Error($t('file_download_failed'))
              }
              await acquireSlot()
              try {
                // refresh 场景必须强制重新拉取临时链接(旧链接 10 分钟后会失效)
                fileInfo.fileUrl = null
                const url = await this.browserDownloader.getAttachmentUrl(fileInfo, oTable)
                if (!url) {
                  throw new Error($t('file_download_failed'))
                }
                return url
              } finally {
                releaseSlot()
              }
            })()
            inflight.set(order, task)
            try {
              return await task
            } finally {
              inflight.delete(order)
            }
          }
        })()
      })
    try {
      this._sendMessage(socket, {
        type: WEBSOCKET_CONFIG_TYPE,
        data: {
          concurrent: 1,
          zipAfterDownload: Boolean(config.zipAfterDownload),
          jobId,
          jobName: config.zipName || jobId,
          zipName: config.zipName || jobId,
          total: cellList.length,
          downloadMode: useTokenMode ? 'token' : 'url',
          ...(useTokenMode
            ? {
              tableId: config.tableId,
              appToken: config.appToken
            }
            : {})
        }
      })
      if (useTokenMode) {
        await this._pushTokenFilesInBatches(socket, cellList, config, {
          sleep,
          drainSocketBuffer,
          shouldAbort: () => abortDownloads
        })
        if (abortDownloads) {
          return
        }
        this.emitter.emit('zip_progress', {
          message: $t('token_push_waiting_message')
        })
        this._sendMessage(socket, {
          type: WEBSOCKET_COMPLETE_TYPE,
          data: {
            jobId
          }
        })
        await drainSocketBuffer()
        await sleep(0)
        return
      }

      let sentCount = 0
      for (const fileInfo of cellList) {
        if (abortDownloads) break
        const { order } = fileInfo
        try {
          this.fileProcessor._prepareUniqueFileName(fileInfo)
          if (abortDownloads) break
          this.emitter.emit('progress', {
            index: order,
            name: fileInfo.name,
            size: fileInfo.size,
            percentage: 0
          })
          const payload = {
            name: fileInfo.name,
            path: fileInfo.path,
            order: fileInfo.order,
            size: fileInfo.size,
            token: fileInfo.token,
            fieldId: fileInfo.fieldId,
            recordId: fileInfo.recordId
          }
          if (abortDownloads) break
          this._sendMessage(socket, {
            type: WEBSOCKET_LINK_TYPE,
            data: payload
          })
          sentCount += 1
          if (sentCount % 50 === 0) {
            await sleep(0)
          }
          await drainSocketBuffer()
        } catch (error) {
          const message = error?.message || $t('file_download_failed')
          this.emitter.emit('error', {
            index: order,
            message
          })
          stopAllDownloads(error)
        }
      }

      if (!abortDownloads) {
        this._sendMessage(socket, {
          type: WEBSOCKET_COMPLETE_TYPE,
          data: {
            jobId
          }
        })
        await completion
      } else {
        await completion.catch(() => {})
      }
    } finally {
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
        socket.close()
      }
    }
  }
}

export default WebSocketDownloader
