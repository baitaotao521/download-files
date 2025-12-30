<template>
  <div class="dialog-process">
    <h4>
      <el-icon class="title-icon"><Download /></el-icon>
      {{ $t("download_progress") }}
    </h4>
    <div class="dialog-circle">
      <ProgressCircle :percent="percent" />
      <div class="progress-text">
        {{ percent }}%
      </div>
    </div>

    <!-- 警告信息区域 -->
    <div v-if="totalSize > MAX_SIZE || warnList.length || zipError" class="warning-section">
      <el-alert
        v-if="totalSize > MAX_SIZE"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 8px;"
      >
        {{ $t('text7') }}
      </el-alert>
      <el-alert
        v-for="item in warnList"
        :key="item"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 8px;"
      >
        {{ item }}
      </el-alert>
      <el-alert
        v-if="!!zipError"
        type="error"
        :closable="false"
        show-icon
        style="margin-bottom: 8px;"
      >
        {{ $t('text11') }}
      </el-alert>
    </div>

    <h4>{{ $t("download_details") }}</h4>
    <div class="prompt">
      <!-- 统计卡片 - 边栏竖向布局 -->
      <el-row :gutter="8" class="stats-row">
        <el-col :span="12">
          <div class="stat-card">
            <div class="stat-label">{{ $t('text8', { totalLength: '' }).replace(/\d+/, '').trim() }}</div>
            <div class="stat-value">{{ totalLength }}</div>
          </div>
        </el-col>
        <el-col :span="12">
          <div class="stat-card">
            <div class="stat-label">{{ $t('text10', { getCompletedIdsLength: '' }).replace(/\d+/, '').trim() }}</div>
            <div class="stat-value stat-success">{{ getCompletedIdsLength }}</div>
          </div>
        </el-col>
      </el-row>
      <el-row :gutter="8" class="stats-row">
        <el-col :span="12">
          <div class="stat-card">
            <div class="stat-label">{{ $t('text21', { failedCount: '' }).replace(/\d+/, '').trim() }}</div>
            <div class="stat-value stat-danger">{{ getFailedIdsLength }}</div>
          </div>
        </el-col>
        <el-col :span="12">
          <div class="stat-card">
            <div class="stat-label">{{ $t('text9', { totalSize: '' }).split(':')[0] }}</div>
            <div class="stat-value stat-info">{{ getFileSize(totalSize) }}</div>
          </div>
        </el-col>
      </el-row>

      <!-- 速度和时间信息 -->
      <div class="speed-time-info">
        <div class="info-item">
          <el-icon class="info-icon"><Odometer /></el-icon>
          <span class="info-label">{{ $t('download_speed') }}:</span>
          <span class="info-value">{{ speedText }}</span>
        </div>
        <div class="info-item">
          <el-icon class="info-icon"><Clock /></el-icon>
          <span class="info-label">{{ $t('remaining_time') }}:</span>
          <span class="info-value">{{ remainingTimeText }}</span>
        </div>
      </div>

      <!-- 状态信息 -->
      <div v-if="maxInfo || zipProgressText" class="status-info">
        <p v-if="maxInfo" class="status-text">{{ maxInfo }}</p>
        <p v-if="zipProgressText" class="status-text">
          <el-icon class="status-icon"><Loading /></el-icon>
          {{ zipProgressText }}
        </p>
      </div>

      <div style="display: flex; justify-content: flex-end; align-items: center; margin-bottom: 8px;">
        <el-button
          v-if="getFailedIdsLength > 0"
          size="small"
          :type="showFailedOnly ? 'primary' : 'default'"
          @click="showFailedOnly = !showFailedOnly"
        >
          {{ showFailedOnly ? $t('text22') : $t('text23') }}
        </el-button>
      </div>
      <el-table
        :data="filteredFileInfo"
        style="width: 100%"
        show-overflow-tooltip
        size="small"
      >
        <el-table-column type="index" width="50" />
        <el-table-column prop="name" :label="$t('text12')" width="" />
      <el-table-column prop="percentage" :label="$t('text13')">
          <template #default="scope">
            {{ scope.row.percentage }}%
          </template>
        </el-table-column>
        <el-table-column prop="size" :label="$t('text14')">
          <template #default="scope">
            {{ getFileSize(scope.row.size) }}
          </template>
        </el-table-column>
        <el-table-column prop="status" :label="$t('text15')">
          <template #default="scope">
            <el-button
              type="primary"
              v-if="scope.row.type === 'loading'"
              size="small"
              link
              >{{ $t('text16') }}</el-button
            >
            <el-button
              type="success"
              link
              v-if="scope.row.type === 'success'"
              size="small"
              >{{ $t('text17') }}</el-button
            >
            <el-button
              type="danger"
              link
              v-if="scope.row.type === 'error'"
              size="small"
              >{{ $t('text18') }}</el-button
            >
          </template>
        </el-table-column>
        <el-table-column prop="errorMessage" :label="$t('error_message')">
          <template #default="scope">
            <span v-if="scope.row.type === 'error'">{{ scope.row.errorMessage }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted, toRefs, computed, defineEmits } from 'vue'
import { Loading, Download, Odometer, Clock } from '@element-plus/icons-vue'
import ProgressCircle from './ProgressCircle.vue'
import FileDownloader from './downFiles.js'
import { i18n } from '@/locales/i18n.js'
import { getFileSize } from '@/utils/index.js'
const $t = i18n.global.t
const emit = defineEmits(['finsh'])
const MAX_SIZE = 1073741824 * 1 // 1G
const warnList = ref([])
const completedIds = ref(new Set())
const failedIds = ref(new Set())
const zipError = ref(false)
const totalSize = ref(0)
const totalLength = ref(0)
const maxInfo = ref('')
const fileCellLength = ref(0)
const zipProgressText = ref('')
const showFailedOnly = ref(false)
const activeRecords = new Map()
const visibleActive = ref([])
const visibleFailed = ref([])

// 下载速度和时间追踪
const startTime = ref(0)
const downloadedBytes = ref(0)
const lastUpdateTime = ref(0)
const lastDownloadedBytes = ref(0)
// 所有文件的完整记录 Map<index, {size, percentage}>
const allFilesMap = new Map()

const props = defineProps({
  zipName: {
    type: String,
    default: ''
  },
  formData: {
    type: Object,
    default: () => {}
  }
})
const getCompletedIdsLength = computed(() => {
  return completedIds.value.size
})

const getFailedIdsLength = computed(() => {
  return failedIds.value.size
})

const MAX_VISIBLE_ITEMS = 30
const filteredFileInfo = computed(() => {
  return showFailedOnly.value ? visibleFailed.value : visibleActive.value
})

const refreshActiveDisplay = () => {
  const items = Array.from(activeRecords.values())
    .filter(item => item.type === 'loading')
    .sort((a, b) => a.index - b.index)
    .slice(0, MAX_VISIBLE_ITEMS)
  visibleActive.value = items
}

const recordFailedDisplay = (entry) => {
  const next = [entry, ...visibleFailed.value.filter(item => item.index !== entry.index)]
  visibleFailed.value = next.slice(0, MAX_VISIBLE_ITEMS)
}

const removeFromFailedDisplay = (index) => {
  const filtered = visibleFailed.value.filter(item => item.index !== index)
  if (filtered.length !== visibleFailed.value.length) {
    visibleFailed.value = filtered
  }
}

// 格式化时间显示（秒 -> 时分秒）
const formatTime = (seconds) => {
  if (!seconds || seconds <= 0 || !isFinite(seconds)) {
    return '--'
  }
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)

  if (h > 0) {
    return `${h}h ${m}m ${s}s`
  } else if (m > 0) {
    return `${m}m ${s}s`
  } else {
    return `${s}s`
  }
}

// 格式化速度显示
const formatSpeed = (bytesPerSecond) => {
  if (!bytesPerSecond || bytesPerSecond <= 0 || !isFinite(bytesPerSecond)) {
    return '--'
  }
  return `${getFileSize(bytesPerSecond)}/s`
}

// 计算下载速度（字节/秒）
const downloadSpeed = computed(() => {
  const now = Date.now()
  const elapsedSeconds = (now - startTime.value) / 1000

  if (elapsedSeconds <= 0 || downloadedBytes.value <= 0) {
    return 0
  }

  return downloadedBytes.value / elapsedSeconds
})

// 计算剩余时间（秒）
const remainingTime = computed(() => {
  const speed = downloadSpeed.value

  if (speed <= 0 || totalSize.value <= 0) {
    return 0
  }

  const remainingBytes = totalSize.value - downloadedBytes.value

  if (remainingBytes <= 0) {
    return 0
  }

  return remainingBytes / speed
})

// 格式化的速度文本
const speedText = computed(() => formatSpeed(downloadSpeed.value))

// 格式化的剩余时间文本
const remainingTimeText = computed(() => formatTime(remainingTime.value))

const percent = computed(() => {
  if (!totalLength.value || !totalSize.value) {
    return 0
  }

  // 基于字节的加权进度计算
  let totalBytes = totalSize.value
  let downloadedBytes = 0

  // 计算已完成文件的字节数
  const completedSet = completedIds.value
  const failedSet = failedIds.value

  // 遍历所有活动记录计算进度
  activeRecords.forEach((record) => {
    const size = record.size || 0
    const percentage = record.percentage || 0

    if (completedSet.has(record.index)) {
      // 已完成的文件
      downloadedBytes += size
    } else if (failedSet.has(record.index)) {
      // 失败的文件不计入下载字节
      // 但为了总进度不卡住，我们仍然算作"处理完成"
      downloadedBytes += size
    } else {
      // 正在下载的文件，按百分比计算
      downloadedBytes += size * (percentage / 100)
    }
  })

  // 如果没有活动记录，但有完成的文件，使用简单的文件数量计算
  if (activeRecords.size === 0 && (completedSet.size > 0 || failedSet.size > 0)) {
    const finished = completedSet.size + failedSet.size
    const val = ((finished / totalLength.value) * 100).toFixed(2) - 0
    return val || 0
  }

  if (totalBytes <= 0) {
    return 0
  }

  const val = ((downloadedBytes / totalBytes) * 100).toFixed(2) - 0
  return Math.min(Math.max(val || 0, 0), 100)
})
const { formData, zipName } = toRefs(props)
onMounted(async() => {
  const fileDownloader = new FileDownloader({
    ...formData.value,
    zipName: zipName.value
  })
  fileDownloader.on('warn', (msg) => {
    warnList.value.push(msg)
  })
  fileDownloader.on('preding', (cells) => {
    fileCellLength.value += 1

    // 记录下载开始时间
    if (!startTime.value) {
      startTime.value = Date.now()
      lastUpdateTime.value = Date.now()
    }

    if (cells) {
      totalLength.value += cells.length
      cells.forEach((cell) => {
        totalSize.value += cell.size
      })
    }
  })
  fileDownloader.on('error', (errorInfo) => {
    const { index, message } = errorInfo
    if (!Number.isInteger(index)) {
      return
    }
    failedIds.value.add(index)
    const existing = activeRecords.get(index) || {
      index,
      name: $t('undefined'),
      size: 0,
      percentage: 0,
      errorMessage: '',
      type: 'error'
    }
    existing.type = 'error'
    existing.errorMessage = message || $t('file_download_failed')
    activeRecords.delete(index)
    recordFailedDisplay(existing)
    refreshActiveDisplay()
  })
  fileDownloader.on('max_size_warning', (info) => {
    zipError.value = true
  })

  fileDownloader.on('progress', (progressInfo) => {
    const { index, percentage = 0, name, size } = progressInfo
    if (!Number.isInteger(index) || completedIds.value.has(index)) {
      return
    }

    // 更新文件记录 Map
    if (size !== undefined) {
      const existing = allFilesMap.get(index) || {}
      allFilesMap.set(index, {
        ...existing,
        size: size,
        percentage: percentage,
        name: name || existing.name
      })
    }

    let existing = activeRecords.get(index)
    if (!existing) {
      existing = {
        index,
        name: name || $t('undefined'),
        size,
        percentage,
        errorMessage: '',
        type: 'loading'
      }
    } else {
      if (name) {
        existing.name = name
      }
      if (size !== undefined) {
        existing.size = size
      }
      existing.percentage = percentage
    }
    existing.type = 'loading'
    existing.errorMessage = ''
    removeFromFailedDisplay(index)
    failedIds.value.delete(index)

    if (percentage >= 100) {
      existing.type = 'success'
      completedIds.value.add(index)
      activeRecords.delete(index)
      // 更新文件 Map，标记为完成
      const fileData = allFilesMap.get(index)
      if (fileData) {
        allFilesMap.set(index, { ...fileData, percentage: 100 })
      }
    } else {
      activeRecords.set(index, existing)
    }
    refreshActiveDisplay()

    // 重新计算总下载字节数
    let totalDownloaded = 0
    allFilesMap.forEach((fileData) => {
      const fileSize = fileData.size || 0
      const filePercentage = fileData.percentage || 0
      totalDownloaded += fileSize * (filePercentage / 100)
    })

    downloadedBytes.value = totalDownloaded
    lastUpdateTime.value = Date.now()
  })
  fileDownloader.on('finshed', (cells) => {
    emit('finsh')
  })
  fileDownloader.on('zip_progress', (payload) => {
    maxInfo.value = ''
    if (payload && typeof payload === 'object') {
      if (payload.stage === 'zip') {
        const path = payload.path || payload.message || ''
        zipProgressText.value = $t('websocket_zip_stage_message', { path })
        return
      }
      if (payload.stage === 'retry_failed_files') {
        const count = Number(payload.failed) || 0
        zipProgressText.value = $t('websocket_retry_failed_files_message', { count })
        return
      }
      if (payload.stage === 'job_complete') {
        zipProgressText.value = $t('websocket_job_stage_message')
        return
      }
      if (payload.message) {
        zipProgressText.value = payload.message
        return
      }
    }
    const text = $t('file_packing_progress_message').replace(
      'percentage',
      payload
    )
    zipProgressText.value = text
  })
  await fileDownloader.startDownload()
})
</script>

<style scoped lang="scss">
.dialog-process {
  h4 {
    color: var(--N900);
    margin-bottom: 16px;
    font-size: 16px;
    border-left: 3px solid var(--el-color-primary);
    padding-left: 8px;
    display: flex;
    align-items: center;
    gap: 6px;

    .title-icon {
      font-size: 18px;
      color: var(--el-color-primary);
    }
  }

  .dialog-circle {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    margin-bottom: 16px;

    .progress-text {
      position: absolute;
      font-size: 18px;
      font-weight: 600;
      color: var(--el-color-primary);
      animation: pulse 2s ease-in-out infinite;
    }

    .statistic {
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
  }

  .warning-section {
    margin-bottom: 16px;
  }
}

.prompt {
  h4 {
    margin-bottom: 8px;
  }

  p {
    line-height: 1.2;
    color: var(--N500);
    font-size: 14px;
    margin-bottom: 8px;
  }

  .stats-row {
    margin-bottom: 8px;
  }

  .stat-card {
    background: linear-gradient(135deg, var(--el-bg-color-page) 0%, var(--el-fill-color-lighter) 100%);
    border-radius: 6px;
    padding: 10px 8px;
    text-align: center;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    border: 1px solid var(--el-border-color-lighter);
    position: relative;
    overflow: hidden;

    &::before {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 2px;
      background: linear-gradient(90deg, transparent, var(--el-color-primary), transparent);
      transform: translateX(-100%);
      animation: shimmer 2s infinite;
    }

    &:hover {
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
      border-color: var(--el-border-color-light);
      transform: translateY(-2px);
    }

    .stat-label {
      font-size: 11px;
      color: var(--el-text-color-secondary);
      margin-bottom: 6px;
      line-height: 1.2;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .stat-value {
      font-size: 20px;
      font-weight: 600;
      color: var(--el-text-color-primary);
      line-height: 1;
      transition: all 0.3s;

      &.stat-success {
        color: var(--el-color-success);
        text-shadow: 0 0 8px rgba(103, 194, 58, 0.3);
      }

      &.stat-danger {
        color: var(--el-color-danger);
        text-shadow: 0 0 8px rgba(245, 108, 108, 0.3);
      }

      &.stat-info {
        color: var(--el-color-info);
        font-size: 16px;
      }
    }
  }

  .speed-time-info {
    margin-bottom: 12px;
    padding: 10px 12px;
    background: linear-gradient(135deg, var(--el-fill-color-lighter) 0%, var(--el-fill-color-light) 100%);
    border-radius: 6px;
    border: 1px solid var(--el-border-color-lighter);
    display: flex;
    flex-direction: column;
    gap: 8px;

    .info-item {
      display: flex;
      align-items: center;
      font-size: 13px;
      color: var(--el-text-color-regular);

      .info-icon {
        font-size: 16px;
        margin-right: 6px;
        color: var(--el-color-primary);
      }

      .info-label {
        margin-right: 6px;
        color: var(--el-text-color-secondary);
      }

      .info-value {
        font-weight: 600;
        color: var(--el-color-primary);
        margin-left: auto;
      }
    }
  }

  .status-info {
    margin-bottom: 12px;
    padding: 12px;
    background: linear-gradient(135deg, var(--el-fill-color-light) 0%, var(--el-fill-color) 100%);
    border-radius: 6px;
    border-left: 3px solid var(--el-color-primary);
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);

    .status-text {
      margin: 0;
      padding: 4px 0;
      color: var(--el-text-color-primary);
      font-size: 14px;
      line-height: 1.5;
      display: flex;
      align-items: center;

      .status-icon {
        margin-right: 8px;
        animation: rotating 2s linear infinite;
        color: var(--el-color-primary);
      }
    }
  }
}

@keyframes rotating {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.8;
    transform: scale(1.05);
  }
}

@keyframes shimmer {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(100%);
  }
}
</style>
