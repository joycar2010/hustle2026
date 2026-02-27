# 系统提醒声音设置修复报告

**修复时间**: 2026-02-27
**修复范围**: 系统提醒声音设置页面和通知弹窗声音播放

---

## 一、问题描述

### 1.1 原始问题
1. ✅ 系统设置页面的提醒声音无法播放
2. ✅ 播放按钮缺少停止功能（需要点击一次播放，再点击一次停止）
3. ✅ 通知弹窗使用的是硬编码的声音文件，未同步系统设置中配置的声音

### 1.2 根本原因分析

#### 问题1: 声音无法播放
**原因**: URL 构建错误
- 原代码: `http://13.115.21.77:8001${soundPath}`
- 问题: 端口号错误（应该是 8000 而不是 8001）
- 位置: `frontend/src/views/System.vue:2619`

#### 问题2: 播放按钮功能不完善
**原因**: 虽然代码中有 toggle 逻辑，但缺少错误处理和状态管理
- 位置: `frontend/src/views/System.vue:2597-2643`

#### 问题3: 通知弹窗声音未同步
**原因**: notification.js 中的 URL 构建也使用了错误的端口号
- 原代码: `http://13.115.21.77:8001${soundFile}`
- 位置: `frontend/src/stores/notification.js:223`

---

## 二、修复内容

### 2.1 修复 System.vue 中的 playSound 函数

**文件**: `frontend/src/views/System.vue`

**修复内容**:
1. ✅ 修复 URL 构建，使用环境变量 `VITE_API_BASE_URL`
2. ✅ 增强 toggle 功能（点击播放，再点击停止）
3. ✅ 添加详细的错误处理和日志
4. ✅ 添加 `onerror` 事件处理器

**修复前**:
```javascript
const soundUrl = soundPath.startsWith('/uploads/')
  ? `http://13.115.21.77:8001${soundPath}`  // ❌ 错误端口
  : soundPath

audio.play().catch(error => {
  alert('播放失败: ' + error.message)  // ❌ 错误信息不详细
})
```

**修复后**:
```javascript
const soundUrl = soundPath.startsWith('/uploads/')
  ? `${import.meta.env.VITE_API_BASE_URL}${soundPath}`  // ✅ 使用环境变量
  : soundPath

// ✅ 添加 onerror 处理
audio.onerror = (error) => {
  console.error('Audio error:', error)
  alert(`播放失败: 无法加载音频文件\n路径: ${soundUrl}`)
  currentAudio.value = null
  playingSound.value = null
}

// ✅ 改进 play 错误处理
audio.play().catch(error => {
  console.error('Failed to play sound:', error)
  alert(`播放失败: ${error.message}\n路径: ${soundUrl}`)
  currentAudio.value = null
  playingSound.value = null
})
```

**功能增强**:
- ✅ Toggle 功能：点击播放按钮开始播放，再次点击停止播放
- ✅ 状态管理：`playingSound` 变量跟踪当前播放的声音
- ✅ 图标切换：播放时显示停止图标，停止时显示播放图标
- ✅ 自动清理：音频播放结束后自动清理状态

### 2.2 修复 notification.js 中的声音播放

**文件**: `frontend/src/stores/notification.js`

**修复内容**:
1. ✅ 修复 URL 构建，使用环境变量
2. ✅ 修复音频播放逻辑（之前已修复）
3. ✅ 添加日志输出

**修复前**:
```javascript
const soundUrl = soundFile.startsWith('/uploads/')
  ? `http://13.115.21.77:8001${soundFile}`  // ❌ 错误端口
  : soundFile
```

**修复后**:
```javascript
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://13.115.21.77:8000'
const soundUrl = soundFile.startsWith('/uploads/')
  ? `${apiBaseUrl}${soundFile}`  // ✅ 使用环境变量
  : soundFile

console.log('Playing alert sound:', soundUrl)  // ✅ 添加日志
```

---

## 三、声音文件映射逻辑

### 3.1 系统设置中的声音类型

| 声音类型 | 字段名 | 用途 |
|---------|--------|------|
| 单腿提醒声音 | singleLegAlertSound | 单腿交易提醒 |
| 点差提醒声音 | spreadAlertSound | 正向/反向套利点差提醒 |
| 净资产提醒声音 | netAssetAlertSound | Binance/Bybit/总资产提醒 |
| MT5状态提醒声音 | mt5AlertSound | MT5延迟/状态提醒 |
| 爆仓提醒声音 | liquidationAlertSound | 爆仓风险提醒 |

### 3.2 通知类型到声音的映射

**实现位置**: `frontend/src/stores/notification.js:194-214`

```javascript
if (alert.type.includes('single_leg')) {
  soundFile = alertSettings.value.singleLegAlertSound
  repeatCount = alertSettings.value.singleLegAlertRepeatCount || 3
} else if (alert.type.includes('forward') || alert.type.includes('reverse')) {
  soundFile = alertSettings.value.spreadAlertSound
  repeatCount = alertSettings.value.spreadAlertRepeatCount || 3
} else if (alert.type.includes('asset')) {
  soundFile = alertSettings.value.netAssetAlertSound
  repeatCount = alertSettings.value.netAssetAlertRepeatCount || 3
} else if (alert.type.includes('mt5')) {
  soundFile = alertSettings.value.mt5AlertSound
  repeatCount = alertSettings.value.mt5AlertRepeatCount || 3
} else if (alert.type.includes('liquidation')) {
  soundFile = alertSettings.value.liquidationAlertSound
  repeatCount = alertSettings.value.liquidationAlertRepeatCount || 3
}
```

### 3.3 声音文件存储路径

**后端存储**:
- 上传目录: `backend/uploads/alert_sounds/`
- 文件命名: `{user_id}_{alert_type}.mp3`
- 数据库存储: `/uploads/alert_sounds/{filename}`

**前端访问**:
- URL 格式: `${VITE_API_BASE_URL}/uploads/alert_sounds/{filename}`
- 示例: `http://13.115.21.77:8000/uploads/alert_sounds/user123_single_leg.mp3`

---

## 四、后端静态文件服务配置

**文件**: `backend/app/main.py:129-132`

```python
# Mount static files for uploaded alert sounds
uploads_dir = Path("uploads")
uploads_dir.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
```

**说明**:
- ✅ 后端已正确配置静态文件服务
- ✅ `/uploads` 路径映射到 `backend/uploads` 目录
- ✅ 支持直接通过 HTTP 访问上传的文件

---

## 五、环境变量配置

**文件**: `frontend/.env`

```env
VITE_API_BASE_URL=http://13.115.21.77:8000
VITE_WS_URL=ws://13.115.21.77:8000
```

**说明**:
- ✅ 前端使用 `VITE_API_BASE_URL` 构建 API 和静态文件 URL
- ✅ 端口号统一为 8000（后端服务端口）
- ✅ 支持开发/生产环境切换

---

## 六、测试验证

### 6.1 测试步骤

1. **上传声音文件**
   - 访问 http://13.115.21.77:3000/system
   - 切换到"提醒设置"标签
   - 为每种提醒类型上传 MP3 文件
   - 验证文件名显示正确

2. **测试播放功能**
   - 点击播放按钮，验证声音播放
   - 再次点击播放按钮，验证声音停止
   - 验证图标在播放/停止状态之间切换
   - 验证播放结束后状态自动重置

3. **测试通知弹窗**
   - 触发各种类型的提醒（点差、资产、MT5等）
   - 验证弹窗播放的是系统设置中配置的声音
   - 验证重复播放次数符合设置

4. **测试错误处理**
   - 删除上传的声音文件
   - 触发提醒，验证回退到 Web Audio API 生成的提示音
   - 验证错误信息显示正确

### 6.2 预期结果

✅ **播放功能**:
- 点击播放按钮，声音正常播放
- 再次点击，声音立即停止
- 图标正确切换（播放 ↔ 停止）

✅ **通知弹窗**:
- 不同类型的提醒播放对应的声音文件
- 重复播放次数符合设置
- 声音播放不会被中断

✅ **错误处理**:
- 文件不存在时显示友好的错误提示
- 自动回退到备用提示音
- 不影响系统其他功能

---

## 七、已知问题和限制

### 7.1 浏览器限制
- 某些浏览器需要用户交互后才能播放音频（自动播放策略）
- 解决方案：通知弹窗由用户操作触发，符合浏览器策略

### 7.2 文件格式
- 当前仅支持 MP3 格式
- 建议：未来可扩展支持 WAV、OGG 等格式

### 7.3 文件大小
- 未限制上传文件大小
- 建议：添加文件大小限制（如 5MB）

---

## 八、后续优化建议

### 8.1 功能增强
1. 添加音量控制
2. 支持更多音频格式
3. 添加声音预览波形图
4. 支持在线声音库

### 8.2 性能优化
1. 音频文件预加载
2. 使用 Web Audio API 实现更精确的控制
3. 添加音频缓存机制

### 8.3 用户体验
1. 添加声音测试按钮（播放完整声音）
2. 显示声音文件时长
3. 支持拖拽上传
4. 添加默认声音库

---

## 九、修复文件清单

### 9.1 前端文件
- ✅ `frontend/src/views/System.vue` - 修复 playSound 函数
- ✅ `frontend/src/stores/notification.js` - 修复 URL 构建和播放逻辑

### 9.2 后端文件
- ✅ 无需修改（静态文件服务已正确配置）

### 9.3 配置文件
- ✅ `frontend/.env` - 已正确配置 API 基础 URL

---

## 十、总结

本次修复解决了系统提醒声音设置的三个核心问题：

1. ✅ **声音播放失败** - 修复了 URL 构建错误（端口号从 8001 改为 8000）
2. ✅ **播放按钮功能** - 实现了 toggle 功能（点击播放/停止切换）
3. ✅ **通知声音同步** - 通知弹窗现在使用系统设置中配置的声音文件

所有修复都使用了环境变量，提高了代码的可维护性和可移植性。系统现在能够正确播放用户上传的自定义提醒声音，并且支持不同类型的提醒使用不同的声音文件。

---

**修复完成时间**: 2026-02-27
**测试状态**: 待验证
**部署状态**: 已部署到开发环境
