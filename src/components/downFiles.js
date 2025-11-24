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
const MAX_RECORD_PAGE_SIZE = 200
const WEBSOCKET_MESSAGE_TYPE = 'feishu_attachment_link'
const WEBSOCKET_CONFIG_TYPE = 'feishu_attachment_config'
const WEBSOCKET_COMPLETE_TYPE = 'feishu_attachment_complete'
const WEBSOCKET_OPEN_STATE = 1

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
  async loopGetRecordIdList(list = [], pageToken) {
    const params = {
      pageSize: Math.min(MAX_RECORD_PAGE_SIZE, this.recordPageSize || MAX_RECORD_PAGE_SIZE),
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
    const needFolder = this.downloadType === 1 || this.downloadType === 3
    if (!needFolder) return
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

  // 通过 WebSocket 将临时链接转交给外部 Python 程序
  async sendLinksViaWebSocket() {
    if (!this.wsEndpoint) {
      this.emit('warn', $t('error_ws_endpoint_required'))
      return
    }
    if (!this.wsConcurrentDownloads) {
      this.emit('warn', $t('error_ws_concurrent_required'))
      return
    }
    const [wsError, socket] = await to(this.createWebSocketConnection())
    if (wsError || !socket) {
      this.emit('warn', wsError?.message || $t('error_websocket_connection_failed'))
      return
    }
    const jobId = `${Date.now()}_${this.tableId || ''}`
    try {
      const configPayload = {
        type: WEBSOCKET_CONFIG_TYPE,
        data: {
          jobId,
          zipAfterDownload: this.wsZipAfterDownload,
          zipName: this.zipName,
          total: this.cellList.length
        }
      }
      const [configError] = await to(this.sendMessageThroughWebSocket(socket, configPayload))
      if (configError) {
        this.emit('warn', configError.message || $t('error_websocket_send_failed'))
        return
      }
      const concurrency = this.wsConcurrentDownloads || 5
      const superTask = new SuperTask(concurrency)
      const sendErrors = []
      const sendQueue = []
      const scheduleSend = (fileInfo) => {
        if (sendErrors.length) return
        const sendPromise = (async() => {
          this.emit('progress', {
            index: fileInfo.order,
            name: fileInfo.name,
            size: fileInfo.size,
            percentage: 0
          })
          const payload = {
            type: WEBSOCKET_MESSAGE_TYPE,
            data: {
              jobId,
              downloadUrl: fileInfo.fileUrl,
              name: fileInfo.name,
              path: fileInfo.path,
              size: fileInfo.size,
              token: fileInfo.token,
              recordId: fileInfo.recordId,
              fieldId: fileInfo.fieldId,
              order: fileInfo.order
            }
          }
          const [sendError] = await to(this.sendMessageThroughWebSocket(socket, payload))
          if (sendError) {
            sendErrors.push({ error: sendError, order: fileInfo.order })
            this.emit('error', {
              message: $t('error_websocket_send_failed'),
              index: fileInfo.order
            })
            throw sendError
          }
          this.emit('progress', {
            index: fileInfo.order,
            percentage: 100
          })
        })()
        sendQueue.push(sendPromise)
      }
      const tasks = this.cellList.map((fileInfo) => {
        return async() => {
          if (sendErrors.length) return
          const [urlErr] = await to(this.getAttachmentUrl(fileInfo))
          if (urlErr) {
            sendErrors.push({ error: urlErr, order: fileInfo.order })
            this.emit('error', {
              message: urlErr.message,
              index: fileInfo.order
            })
            throw urlErr
          }
          scheduleSend(fileInfo)
        }
      })
      superTask.setTasks(tasks)
      await superTask.finished().catch(() => {})
      await Promise.allSettled(sendQueue)
      if (sendErrors.length) {
        return
      }
      const [completeError] = await to(this.sendMessageThroughWebSocket(socket, {
        type: WEBSOCKET_COMPLETE_TYPE,
        data: { jobId }
      }))
      if (completeError) {
        this.emit('warn', completeError.message || $t('error_websocket_send_failed'))
      }
    } finally {
      socket.close()
    }
  }

  // 创建 WebSocket 实例
  async createWebSocketConnection() {
    const WebSocketCtor =
      typeof window !== 'undefined'
        ? window.WebSocket
        : typeof WebSocket !== 'undefined'
          ? WebSocket
          : null
    if (!WebSocketCtor) {
      throw new Error($t('error_websocket_not_supported'))
    }
    return await new Promise((resolve, reject) => {
      let socket = null
      try {
        socket = new WebSocketCtor(this.wsEndpoint)
      } catch (error) {
        reject(error)
        return
      }
      const handleError = (event) => {
        socket?.removeEventListener('open', handleOpen)
        socket?.removeEventListener('error', handleError)
        reject(
          event?.error || new Error($t('error_websocket_connection_failed'))
        )
      }
      const handleOpen = () => {
        socket.removeEventListener('error', handleError)
        socket.removeEventListener('open', handleOpen)
        resolve(socket)
      }
      socket.addEventListener('open', handleOpen)
      socket.addEventListener('error', handleError)
    })
  }

  // 发送 WebSocket 消息
  async sendMessageThroughWebSocket(socket, payload) {
    return await new Promise((resolve, reject) => {
      if (!socket || socket.readyState !== WEBSOCKET_OPEN_STATE) {
        reject(new Error($t('error_websocket_connection_failed')))
        return
      }
      try {
        socket.send(JSON.stringify(payload))
        resolve(true)
      } catch (error) {
        reject(error)
      }
    })
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
    if (this.downloadType === 2) {
      // 逐个下载
      await this.sigleDownLoad()
    } else if (this.downloadType === 3) {
      await this.sendLinksViaWebSocket()
    } else {
      await this.zipDownLoad()
    }
    this.emit('finshed')
  }
}

export default FileDownloader
