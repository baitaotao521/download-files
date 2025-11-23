<template>
  <div class="dialog-process">
    <h4>{{ $t("download_progress") }}</h4>
    <div class="dialog-circle">
      <ProgressCircle :percent="percent" />
    </div>
    <h4>{{ $t("download_details") }}</h4>
    <div class="prompt">
     <p  v-if="totalSize>MAX_SIZE" style="color: var(--el-color-warning);line-height: 1.5;">{{ $t('text7') }}</p>
     <template v-if="warnList.length">
      <p v-for="item in warnList" :key="item" style="color: var(--el-color-warning);line-height: 1.5;">{{ item }}</p>
     </template>
      <!-- <p>已找到{{ fileCellLength }}个单元格</p> -->

      <p> {{ $t('text8',{totalLength}) }}</p>
      <p> {{ $t('text9',{totalSize:getFileSize(totalSize)})}}</p>
      <p> {{ $t('text10',{getCompletedIdsLength})}}</p>
      <p style="color:red" v-if="getFailedIdsLength > 0">{{ $t('text21',{failedCount: getFailedIdsLength})}}</p>
      <p>{{ maxInfo }}</p>
      <p>{{ zipProgressText }}</p>
      <p style="color:red" v-if="!!zipError">{{ $t('text11') }}</p>

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
            {{ scope.row.percentage
            }}{{ scope.row.type === "error" ? "" : "%" }}
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
      </el-table>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted, reactive, toRefs, computed, defineEmits } from 'vue'
import ProgressCircle from './ProgressCircle.vue'
import FileDownloader from './downFiles.js'
import { i18n } from '@/locales/i18n.js'
import { getFileSize, debouncedSort } from '@/utils/index.js'
const $t = i18n.global.t
const emit = defineEmits(['finsh'])
const MAX_SIZE = 1073741824 * 1 // 1G
const warnList = ref([])
const completedIds = ref(new Set())
const failedIds = ref(new Set())
const zipError = ref(false)
const totalSize = ref(0)
const totalLength = ref(0)
const fileInfo = ref([])
const maxInfo = ref('')
const fileCellLength = ref(0)
const zipProgressText = ref('')
const showFailedOnly = ref(false)

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

const filteredFileInfo = computed(() => {
  if (showFailedOnly.value) {
    return fileInfo.value.filter(item => failedIds.value.has(item.index))
  }
  return fileInfo.value
})

const percent = computed(() => {
  const val = ((getCompletedIdsLength.value / totalLength.value) * 100).toFixed(2) - 0
  return val || 0
})
const sortFileInfo = () => {
  // 定义优先级映射
  const priority = {
    'loading': 1,
    'error': 2,
    'default': 3 // 其他类型的优先级
  }
  // 重构数组，当数组长度大于20时，删除 type 为 'default' 的元素
  if (fileInfo.value.length > 20) {
    fileInfo.value = fileInfo.value.filter(item => {
      return item.type !== 'success'
    })
  }

  fileInfo.value.sort((a, b) => {
    return (priority[a.type] || priority['default']) - (priority[b.type] || priority['default'])
  })
}

const debouncedSortFileInfo = debouncedSort(sortFileInfo, 200)
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

    if (cells) {
      totalLength.value += cells.length
      cells.forEach((cell) => {
        totalSize.value += cell.size
      })
    }
  })
  fileDownloader.on('error', (errorInfo) => {
    const { index, message } = errorInfo
    const itemIndex = fileInfo.value.findIndex((item) => item.index === index)

    if (itemIndex !== -1) {
      fileInfo.value[itemIndex].type = 'error'
      fileInfo.value[itemIndex].percentage = message
      failedIds.value.add(index)
      debouncedSortFileInfo()
    }
  })
  fileDownloader.on('max_size_warning', (info) => {
    zipError.value = true
  })

  fileDownloader.on('progress', (progressInfo) => {
    const { index, percentage, name, size } = progressInfo
    if (completedIds.value.has(index)) {
      return
    }
    const itemIndex = fileInfo.value.findIndex((item) => item.index === index)

    if (itemIndex === -1) {
      fileInfo.value.unshift({
        index,
        percentage,
        name,
        size,
        type: 'loading'
      })
    } else {
      fileInfo.value[itemIndex].percentage = percentage

      if (percentage >= 100) {
        fileInfo.value[itemIndex].type = 'success'

        completedIds.value.add(index) // 标记为已处理
        debouncedSortFileInfo()
      } else {
        fileInfo.value[itemIndex].type = 'loading'
      }
    }
  })
  fileDownloader.on('finshed', (cells) => {
    emit('finsh')
  })
  fileDownloader.on('zip_progress', (percent) => {
    maxInfo.value = ''
    const text = $t('file_packing_progress_message').replace(
      'percentage',
      percent
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
  }

  .dialog-circle {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    margin-bottom: 16px;

    .statistic {
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
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
}

</style>
