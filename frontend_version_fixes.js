/**
 * System.vue 前端修复代码片段
 *
 * 使用说明：
 * 1. 安装Element Plus: npm install element-plus
 * 2. 在main.js中引入Element Plus
 * 3. 替换System.vue中的相关函数
 */

// ============================================
// 1. 在script setup顶部添加导入
// ============================================
import { ElMessageBox, ElMessage, ElLoading } from 'element-plus'

// ============================================
// 2. 替换 pushToGitHub 函数
// ============================================
async function pushToGitHub() {
  try {
    const confirmed = await ElMessageBox.confirm(
      '确定要推送当前版本到GitHub吗？推送成功后版本号将自动 +0.0.1',
      '确认推送',
      {
        confirmButtonText: '确认推送',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    if (!confirmed) return

    const loading = ElLoading.service({
      lock: true,
      text: '正在推送到GitHub...',
      background: 'rgba(0, 0, 0, 0.7)'
    })

    try {
      const response = await api.post('/api/v1/system/github/push', {
        remark: pushRemark.value || undefined
      })

      loading.close()

      // Update local version display
      if (response.data.frontend_version && response.data.backend_version) {
        systemInfo.value.frontend_version = response.data.frontend_version
        systemInfo.value.backend_version = response.data.backend_version
      }

      ElMessage.success({
        message: `推送成功！\n前端版本: ${response.data.frontend_version}\n后端版本: ${response.data.backend_version}`,
        duration: 5000,
        showClose: true
      })

      pushRemark.value = ''
      await loadVersionHistory()
      await loadSystemInfo() // Refresh system info
    } catch (error) {
      loading.close()
      throw error
    }
  } catch (error) {
    if (error === 'cancel') return // User cancelled

    console.error('Failed to push to GitHub:', error)

    // Parse error message for specific issues
    const errorDetail = error.response?.data?.detail || error.message
    let errorTitle = '推送失败'
    let errorMessage = errorDetail

    if (errorDetail.includes('认证失败')) {
      errorTitle = 'GitHub 认证失败'
    } else if (errorDetail.includes('分支冲突')) {
      errorTitle = '分支冲突'
    } else if (errorDetail.includes('限流')) {
      errorTitle = 'API 限流'
    }

    ElMessageBox.alert(errorMessage, errorTitle, {
      confirmButtonText: '确定',
      type: 'error',
      dangerouslyUseHTMLString: true
    })
  }
}

// ============================================
// 3. 替换 rollbackToVersion 函数
// ============================================
async function rollbackToVersion(hash) {
  try {
    const confirmed = await ElMessageBox.confirm(
      `确定要还原到版本 ${hash.substring(0, 7)} 吗？\n\n此操作将：\n1. 重置代码到该版本\n2. 版本号回退到该版本的数值\n3. 需要重启系统才能生效`,
      '确认还原版本',
      {
        confirmButtonText: '确认还原',
        cancelButtonText: '取消',
        type: 'warning',
        dangerouslyUseHTMLString: true
      }
    )

    if (!confirmed) return

    const loading = ElLoading.service({
      lock: true,
      text: '正在还原版本...',
      background: 'rgba(0, 0, 0, 0.7)'
    })

    try {
      const response = await api.post('/api/v1/system/github/rollback', { hash })

      loading.close()

      // Update local version display
      if (response.data.frontend_version && response.data.backend_version) {
        systemInfo.value.frontend_version = response.data.frontend_version
        systemInfo.value.backend_version = response.data.backend_version
      }

      ElMessage.success({
        message: `还原成功！\n前端版本: ${response.data.frontend_version}\n后端版本: ${response.data.backend_version}\n\n请重启系统使更改生效`,
        duration: 8000,
        showClose: true
      })

      await loadVersionHistory()
      await loadSystemInfo()
    } catch (error) {
      loading.close()
      throw error
    }
  } catch (error) {
    if (error === 'cancel') return

    console.error('Failed to rollback:', error)
    ElMessage.error({
      message: '还原失败: ' + (error.response?.data?.detail || error.message),
      duration: 5000,
      showClose: true
    })
  }
}

// ============================================
// 4. 替换 deleteVersionByHash 函数
// ============================================
async function deleteVersionByHash(hash) {
  try {
    const confirmed = await ElMessageBox.confirm(
      `确定要删除版本 ${hash.substring(0, 7)} 在 GitHub 的备份吗？\n\n⚠️ 警告：\n1. 此操作将删除该版本的 GitHub 标签\n2. 删除后不可恢复\n3. 提交历史将保留用于审计\n\n如果您想还原到此版本，请使用"还原"按钮`,
      '确认删除备份',
      {
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        type: 'error',
        dangerouslyUseHTMLString: true,
        confirmButtonClass: 'el-button--danger'
      }
    )

    if (!confirmed) return

    const loading = ElLoading.service({
      lock: true,
      text: '正在删除GitHub备份...',
      background: 'rgba(0, 0, 0, 0.7)'
    })

    try {
      const response = await api.delete(`/api/v1/system/github/version/${hash}`)

      loading.close()

      ElMessage.success({
        message: response.data.message + '\n' + (response.data.note || ''),
        duration: 5000,
        showClose: true
      })

      await loadVersionHistory()
    } catch (error) {
      loading.close()
      throw error
    }
  } catch (error) {
    if (error === 'cancel') return

    console.error('Failed to delete version:', error)

    const errorDetail = error.response?.data?.detail || error.message

    if (error.response?.status === 403) {
      ElMessageBox.alert(
        '您没有删除GitHub备份的权限。\n此操作需要管理员权限。',
        '权限不足',
        {
          confirmButtonText: '确定',
          type: 'error'
        }
      )
    } else {
      ElMessage.error({
        message: '删除失败: ' + errorDetail,
        duration: 5000,
        showClose: true
      })
    }
  }
}

// ============================================
// 5. 添加 loadSystemInfo 函数（如果不存在）
// ============================================
async function loadSystemInfo() {
  try {
    const response = await api.get('/api/v1/system/info')
    systemInfo.value = response.data
  } catch (error) {
    console.error('Failed to load system info:', error)
  }
}

// ============================================
// 6. 模板修改 - 更新操作列按钮
// ============================================
/*
在版本备份记录表格的操作列中，将按钮修改为：

<td class="py-3 px-4">
  <!-- 还原按钮 -->
  <button
    @click="rollbackToVersion(version.hash)"
    class="text-primary hover:text-primary-hover mr-3"
    title="还原到此版本"
  >
    <svg class="w-4 h-4 inline mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
    </svg>
    还原
  </button>

  <!-- 删除备份按钮 -->
  <button
    @click="deleteVersionByHash(version.hash)"
    class="text-danger hover:text-red-400"
    title="删除GitHub备份"
  >
    <svg class="w-4 h-4 inline mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
    </svg>
    删除备份
  </button>
</td>
*/
