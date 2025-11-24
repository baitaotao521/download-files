import { bitable } from '@lark-base-open/js-sdk'
import { saveAs } from 'file-saver'
import JSZip from 'jszip'
import axios from 'axios'
import { chunkArrayByMaxSize } from '@/utils/index.js'

import { i18n } from '@/locales/i18n.js'
import to from 'await-to-js'
import { SuperTask } from '@/utils/SuperTask.js'

import {
  removeSpecialChars,
  getFolderName,
  replaceFileName
} from '@/utils/index.js'

const $t = i18n.global.t

const MAX_ZIP_SIZE_NUM = 1

const MAX_ZIP_SIZE = MAX_ZIP_SIZE_NUM * 1024 * 1024 * 1024

const WEBSOCKET_LINK_TYPE = 'feishu_attachment_link'
const WEBSOCKET_CONFIG_TYPE = 'feishu_attachment_config'
const WEBSOCKET_COMPLETE_TYPE = 'feishu_attachment_complete'
const WEBSOCKET_ACK_TYPE = 'feishu_attachment_ack'

class FileDownloader {
  constructor(formData) {
    Object.keys(formData).map((key) => {
      this[key] = formData[key]
    })

    this.oTable = null

    this.currentTotalSize = 0
    this.nameSpace = new Set()
    this.zip = null
    this.cellList = []
  }
  /**
   * 判断当前是否需要通过 WebSocket 推送文件链接。
   */
  isWebSocketChannel() {
    return this.downloadChannel === 'websocket'
  }
  async loopGetRecordIdList(list = [], pageToken) {
    const params = {
      pageSize: 200,
      viewId: this.viewId
    }
    if (pageToken) {
      params.pageToken = pageToken
    }
    const [err, response] = await to(this.oTable.getRecordsByPage(params))
    console.log('response', response)
    if (err) {
      console.log(err)
    } else {
      const { hasMore, records = [], pageToken: nextPageToken } = response

      list.push(...records)
      if (hasMore && nextPageToken) {
        await this.loopGetRecordIdList(list, nextPageToken)
      }
    }

    return list
  }
  async getCellsList() {
    const oRecordList = await this.loopGetRecordIdList()
    let cellList = []

    for (const fieldId of this.attachmentFileds) {
      for (const records of oRecordList) {
        let cell = records.fields[fieldId]
        const recordId = records.recordId

        if (cell) {
          cell = cell.map((e) => ({
            ...e,
            name: removeSpecialChars(e.name),
            recordId,
            fieldId,
            path: '',
            fileUrl: ''
          }))
          cellList.push(...cell)
          this.emit('preding', cell)
        } else {
          this.emit('preding')
        }
      }
    }
    cellList = cellList.map((e, index) => ({ ...e, order: index + 1 }))
    return cellList
  }

  // 注册进度事件监听器
  on(event, callback) {
    if (!this[event + 'Listeners']) {
      this[event + 'Listeners'] = []
    }
    this[event + 'Listeners'].push(callback)

    return this
  }
  emit(type, messgae) {
    this[type + 'Listeners']?.forEach((listener) => {
      listener(messgae)
    })
  }
  async setFileNames() {
    if (this.fileNameType !== 1) return
    const targetFieldIds = this.fileNameByField
    const getFileName = async(cell, fieldIds) => {
      const names = await Promise.all(
        fieldIds.map(fieldId =>
          this.oTable.getCellString(fieldId, cell.recordId)
        )
      )
      // 过滤掉空字符串，并用 '-' 连接剩余的名称部分
      return names.filter(name => name).join(this.nameMark)
    }

    const updateCellNames = (cell, newName) => {
      if (newName !== cell.name) {
        const cName = replaceFileName(cell.name, newName, $t('undefined'))
        cell.name = removeSpecialChars(cName)
      }
    }

    // 使用 map 创建一个包含所有异步操作的数组
    const promises = this.cellList.map((cell) =>
      getFileName(cell, targetFieldIds)
    )

    // 等待所有异步操作完成
    const names = await Promise.all(promises)

    // 使用 names 更新 cellList 中每个 cell 的 name
    names.forEach((name, index) => {
      updateCellNames(this.cellList[index], name)
    })
  }
  async setFolderPath() {
    // 逐个下载
    if (this.downloadType !== 1) return
    // zip不需要文件夹分类
    if (!this.downloadTypeByFolders) return

    // 封装获取和处理文件夹名称的逻辑
    const getProcessedFolderName = async(fieldKey, recordId) => {
      const name = await this.oTable.getCellString(fieldKey, recordId)
      return removeSpecialChars(getFolderName(name)) || $t('uncategorized')
    }

    const setCellFolderName = async(cell, firstFolderKey, secondFolderKey) => {
      let parentFolder = ''
      if (firstFolderKey) {
        parentFolder += `${await getProcessedFolderName(firstFolderKey, cell.recordId)}/`
      }
      if (secondFolderKey) {
        parentFolder += `${await getProcessedFolderName(secondFolderKey, cell.recordId)}/`
      }
      cell.path = parentFolder
    }

    // 使用 Promise.all 处理所有单元格的文件夹名称设置
    await Promise.all(
      this.cellList.map((cell) =>
        setCellFolderName(cell, this.firstFolderKey, this.secondFolderKey)
      )
    )
  }
  getUniqueFileName(name, path) {
    const fileExtension = name.substring(name.lastIndexOf('.'))
    const baseName = name.substring(0, name.lastIndexOf('.'))
    let nameIndex = 1
    while (this.nameSpace.has(path + name)) {
      name = `${baseName}_${nameIndex}${fileExtension}`
      nameIndex++
    }
    this.nameSpace.add(path + name)
    return name
  }
  async zipDownLoad() {
    const { chunks: zipsList, maxChunks: maxChunksList, total } = chunkArrayByMaxSize(this.cellList, MAX_ZIP_SIZE)
    if (zipsList.length > 1) {
      this.emit('warn', $t('text19', { length: zipsList.length }))
    }
    if (maxChunksList.length) {
      this.emit('warn', $t('text20', { length: maxChunksList.length }))
    }

    const concurrency = this.concurrentDownloads || 5
    for (const zipList of zipsList) {
      this.zip = new JSZip()
      this.currentTotalSize = 0 // 重置当前总大小
      const superTask = new SuperTask(concurrency)
      const tasks = zipList.map((fileInfo) => {
        return async() => await this.processFile(fileInfo)
      })
      superTask.setTasks(tasks)

      await superTask.finished().catch((errors) => {})
      const [err, content] = await to(this.zip.generateAsync(
        { type: 'blob' },
        (metadata) => {
          const percent = metadata.percent.toFixed(2)
          this.emit('zip_progress', percent)
        }
      ))
      if (err) {
        this.emit('max_size_warning')
      } else {
        saveAs(content, `${this.zipName}.zip`)
        this.zip = null // 释放 zip 实例
      }
    }
    for (const fileInfo of maxChunksList) {
      await this.sigleDownLoad(fileInfo)
    }
  }
  async getAttachmentUrl(fileInfo) {
    const { token, fieldId, recordId, path, name } = fileInfo

    fileInfo.name = this.getUniqueFileName(name, path)
    fileInfo.fileUrl = await this.oTable.getAttachmentUrl(
      token,
      fieldId,
      recordId
    )
  }
  // 处理单个文件的异步函数
  async processFile(fileInfo) {
    await this.getAttachmentUrl(fileInfo)

    const blob = await this.downloadFile(fileInfo)

    if (blob) {
      this.zip.file(`${fileInfo.path}${fileInfo.name}`, blob)
    }
  }
  async sigleDownLoad(file) {
    const cellList = file ? [file] : this.cellList
    const downLocal = async(fileInfo) => {
      const blob = await this.downloadFile(fileInfo)
      if (blob) {
        const objectUrl = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.setAttribute('href', objectUrl)
        a.setAttribute('download', fileInfo.name)
        a.click()
        URL.revokeObjectURL(objectUrl)
      }
    }
    for (let index = 0; index < cellList.length; index++) {
      const fileInfo = cellList[index]

      await this.getAttachmentUrl(fileInfo)
      await downLocal(fileInfo)
    }
  }
  /**
   * 将附件临时链接推送给本地 Python WebSocket 服务端。
   */
  async websocketDownload() {
    const wsUrl = this._buildWebSocketUrl()
    const socket = await this._createWebSocket(wsUrl)
    const completion = this._bindWebSocketLifecycle(socket)
    const jobId = `${Date.now()}`
    const concurrency = Math.max(1, Number(this.concurrentDownloads) || 5)
    try {
      this._sendWebSocketMessage(socket, {
        type: WEBSOCKET_CONFIG_TYPE,
        data: {
          concurrent: concurrency,
          zipAfterDownload: this.downloadType === 1,
          jobId,
          jobName: this.zipName || jobId,
          zipName: this.zipName || jobId,
          total: this.cellList.length
        }
      })
      for (const fileInfo of this.cellList) {
        const { order } = fileInfo
        try {
          await this.getAttachmentUrl(fileInfo)
          this.emit('progress', {
            index: order,
            name: fileInfo.name,
            size: fileInfo.size,
            percentage: 0
          })
          this._sendWebSocketMessage(socket, {
            type: WEBSOCKET_LINK_TYPE,
            data: {
              downloadUrl: fileInfo.fileUrl,
              name: fileInfo.name,
              path: fileInfo.path,
              order: fileInfo.order,
              size: fileInfo.size
            }
          })
        } catch (error) {
          const message = error?.message || $t('file_download_failed')
          this.emit('error', {
            index: order,
            message
          })
          continue
        }
      }
      this._sendWebSocketMessage(socket, {
        type: WEBSOCKET_COMPLETE_TYPE,
        data: {
          jobId
        }
      })
      await completion
    } finally {
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
        socket.close()
      }
    }
  }
  /**
   * 组合用户输入的 WebSocket URL。
   */
  _buildWebSocketUrl() {
    const rawHost = (this.wsHost || '').trim()
    if (!rawHost) {
      throw new Error($t('error_websocket_host_required'))
    }
    if (/^wss?:\/\//i.test(rawHost)) {
      return rawHost
    }
    const port = this.wsPort ? String(this.wsPort).trim() : ''
    if (rawHost.includes(':') || !port) {
      return `ws://${rawHost}`
    }
    return `ws://${rawHost}:${port}`
  }
  /**
   * 建立 WebSocket 连接并在 ready 时返回实例。
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
   * 监听服务端 ACK，驱动 UI 并在任务完成或失败时结束。
   */
  _bindWebSocketLifecycle(socket) {
    return new Promise((resolve, reject) => {
      let finished = false
      let hasJobCompleted = false
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
          if (Number.isInteger(order) && order > 0) {
            if (status === 'success') {
              this.emit('progress', {
                index: order,
                percentage: 100
              })
            } else {
              this.emit('error', {
                index: order,
                message: data.message || $t('file_download_failed')
              })
            }
            return
          }
          if (stage === 'zip') {
            this.emit('zip_progress', {
              stage,
              path: data.path,
              message: data.message
            })
            return
          }
          if (stage === 'job_complete') {
            hasJobCompleted = true
            this.emit('zip_progress', {
              stage,
              message: data.message
            })
            finish()
            return
          }
          if (status === 'error') {
            const message = data.message || $t('file_download_failed')
            this.emit('warn', message)
            finish(new Error(message))
          }
        } catch (error) {
          console.error('failed to parse websocket ack', error)
        }
      }
      socket.onerror = () => {
        finish(new Error($t('websocket_connection_failed')))
      }
      socket.onclose = () => {
        if (hasJobCompleted) {
          finish()
        } else {
          finish(new Error($t('websocket_connection_failed')))
        }
      }
    })
  }
  /**
   * 发送序列化后的 WebSocket 消息。
   */
  _sendWebSocketMessage(socket, payload) {
    if (socket.readyState !== WebSocket.OPEN) {
      throw new Error($t('websocket_connection_failed'))
    }
    socket.send(JSON.stringify(payload))
  }

  async downloadFile(fileInfo) {
    const { fileUrl, name, order, size } = fileInfo
    let isDownloadComplete = false // 新增变量，用于跟踪下载是否完成
    this.emit('progress', {
      index: order,
      name,
      size,
      percentage: 0
    })
    const [err, response] = await to(
      axios({
        method: 'get',
        responseType: 'blob',
        url: fileUrl,
        onDownloadProgress: (progressEvent) => {
          if (progressEvent.lengthComputable && !isDownloadComplete) {
            const percentage = Math.round(
              (progressEvent.loaded * 100) / progressEvent.total
            )
            this.emit('progress', {
              index: order,
              percentage
            })
          }
        }
      })
    )
    if (!isDownloadComplete) {
      this.emit('progress', {
        index: order,

        percentage: 100
      })
      isDownloadComplete = true // 标记下载完成
    }
    if (err) {
      this.emit('error', {
        message: err.message,
        index: order
      })
      return null
    }
    return response.data
  }

  async startDownload() {
    this.oTable = await bitable.base.getTableById(this.tableId)
    // 获取所有附件信息
    this.cellList = await this.getCellsList()
    //  为所有附件重新取名
    await this.setFileNames()
    await this.setFolderPath()

    if (!this.cellList.length) {
      this.emit('info', $t('no_files_to_download_message'))
      this.emit('finshed')
      return ''
    }
    try {
      if (this.isWebSocketChannel()) {
        await this.websocketDownload()
      } else if (this.downloadType === 2) {
        // 逐个下载
        await this.sigleDownLoad()
      } else {
        await this.zipDownLoad()
      }
    } catch (error) {
      console.error('download failed', error)
      const message = error?.message || $t('file_download_failed')
      this.emit('warn', message)
    } finally {
      this.emit('finshed')
    }
  }
}

export default FileDownloader
