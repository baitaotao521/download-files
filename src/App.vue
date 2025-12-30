<script setup>
import Form from './components/Form.vue'
import { Warning, Refresh, QuestionFilled } from '@element-plus/icons-vue'
import { ref } from 'vue'
import { useTheme } from '@/hooks/useTheme'
useTheme()
const isVisible = ref(true)
const usageInstructionsUrl =
  'https://p6bgwki4n6.feishu.cn/docx/Pn7Kdw2rPocwPZxVfF5cMsAcnle'

// 打开“使用须知”飞书文档
const openUsageInstructions = () => {
  const newWindow = window.open(
    usageInstructionsUrl,
    '_blank',
    'noopener,noreferrer'
  )
  if (newWindow) newWindow.opener = null
}
const refreshForm = () => {
  isVisible.value = false
  setTimeout(() => {
    isVisible.value = true
  }, 300)
}
</script>

<template>
  <main>
    <div class="help">
      <a
        target="_blank"
        href="https://applink.feishu.cn/client/chat/chatter/add_by_link?link_token=9cei5274-2def-477b-86e2-df3471804317"
        >{{ $t('help') }}
        <el-icon class="el-icon--right"
          ><QuestionFilled size="small"
        /></el-icon>
      </a>
    </div>

    <div class="hd">
      <el-button type="primary" @click="openUsageInstructions">
        {{ $t('usage_instructions')
        }}<el-icon class="el-icon--right"><Warning /></el-icon>
      </el-button>
      <el-button type="primary" @click="refreshForm">
        {{ $t("refresh_form")
        }}<el-icon class="el-icon--right"><Refresh /></el-icon>
      </el-button>
    </div>
    <div class="forms" v-loading="!isVisible">
      <Form v-if="isVisible" />
    </div>
  </main>
</template>

<style scoped lang="scss">
main {
  padding: 1rem;
  position: relative;
}
.help {
  display: flex;
  justify-content: flex-end;
  a {
    color: var(--el-color-primary);
    font-size: 16px;
    cursor: pointer;
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    justify-content: end;
    text-decoration: none; /* 确保没有下划线 */
  }
}
.hd {
  margin-bottom: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;

  .el-button {
    flex: 1;
  }
}
  .forms {
    min-height: 300px;
  }
.corner-stat {
  position: absolute;
  right: 8px;
  bottom: 8px;
  width: 120px;
  opacity: 0.28;
  pointer-events: none;
  img {
    width: 100%;
    display: block;
    border-radius: 4px;
    filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.12));
  }
}
</style>
