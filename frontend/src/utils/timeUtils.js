/**
 * 时间工具函数 - UTC标准化
 * 用途：提供统一的UTC时间处理函数，确保前端时间显示一致性
 * 作者：系统架构团队
 * 版本：1.0.0
 */

/**
 * 格式化UTC时间为本地时间显示
 * @param {string|Date} utcTime - UTC时间（ISO格式或Date对象）
 * @param {string} format - 显示格式（'datetime' | 'date' | 'time'）
 * @param {boolean} showTimezone - 是否显示时区
 * @returns {string} 格式化后的时间字符串
 *
 * @example
 * formatUTCTime('2026-02-24T10:30:00Z') // "2026-02-24 18:30:00 (UTC+8)"
 * formatUTCTime('2026-02-24T10:30:00Z', 'date') // "2026-02-24"
 * formatUTCTime('2026-02-24T10:30:00Z', 'datetime', false) // "2026-02-24 18:30:00"
 */
export function formatUTCTime(utcTime, format = 'datetime', showTimezone = true) {
  if (!utcTime) return '-'

  const date = typeof utcTime === 'string' ? new Date(utcTime) : utcTime

  // 检查是否为有效日期
  if (isNaN(date.getTime())) {
    console.error('Invalid date:', utcTime)
    return '-'
  }

  const options = {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  }

  if (format === 'date') {
    delete options.hour
    delete options.minute
    delete options.second
  } else if (format === 'time') {
    delete options.year
    delete options.month
    delete options.day
  }

  const formatted = date.toLocaleString('zh-CN', options)

  if (showTimezone && format !== 'time') {
    const offset = -date.getTimezoneOffset() / 60
    const tzStr = offset >= 0 ? `UTC+${offset}` : `UTC${offset}`
    return `${formatted} (${tzStr})`
  }

  return formatted
}

/**
 * 将本地时间转换为UTC ISO字符串
 * @param {Date} localTime - 本地时间
 * @returns {string} UTC ISO字符串
 *
 * @example
 * toUTCString(new Date()) // "2026-02-24T10:30:00.000Z"
 */
export function toUTCString(localTime) {
  return localTime.toISOString()
}

/**
 * 获取当前UTC时间
 * @returns {string} UTC ISO字符串
 *
 * @example
 * nowUTC() // "2026-02-24T10:30:00.000Z"
 */
export function nowUTC() {
  return new Date().toISOString()
}

/**
 * 计算时间差（人类可读格式）
 * @param {string|Date} utcTime - UTC时间
 * @returns {string} 如 "2小时前"、"3天前"
 *
 * @example
 * timeAgo('2026-02-24T08:30:00Z') // "2小时前"
 */
export function timeAgo(utcTime) {
  const date = typeof utcTime === 'string' ? new Date(utcTime) : utcTime
  const now = new Date()
  const diffMs = now - date
  const diffSec = Math.floor(diffMs / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)

  if (diffSec < 60) return '刚刚'
  if (diffMin < 60) return `${diffMin}分钟前`
  if (diffHour < 24) return `${diffHour}小时前`
  if (diffDay < 30) return `${diffDay}天前`
  return formatUTCTime(date, 'date', false)
}

/**
 * 解析UTC时间字符串为Date对象
 * @param {string} utcTimeStr - UTC时间字符串（ISO格式）
 * @returns {Date} Date对象
 *
 * @example
 * parseUTCTime('2026-02-24T10:30:00Z') // Date对象
 */
export function parseUTCTime(utcTimeStr) {
  if (!utcTimeStr) return null

  // 确保字符串以Z结尾或包含时区信息
  if (!utcTimeStr.endsWith('Z') && !utcTimeStr.includes('+') && !utcTimeStr.includes('T')) {
    // 如果是纯日期时间字符串，假设为UTC
    utcTimeStr = utcTimeStr.replace(' ', 'T') + 'Z'
  }

  return new Date(utcTimeStr)
}

/**
 * 格式化时间为紧凑格式（用于图表等）
 * @param {string|Date} utcTime - UTC时间
 * @param {string} format - 格式类型（'short' | 'medium' | 'long'）
 * @returns {string} 格式化后的时间字符串
 *
 * @example
 * formatCompact('2026-02-24T10:30:00Z', 'short') // "10:30"
 * formatCompact('2026-02-24T10:30:00Z', 'medium') // "02-24 10:30"
 * formatCompact('2026-02-24T10:30:00Z', 'long') // "2026-02-24 10:30"
 */
export function formatCompact(utcTime, format = 'medium') {
  if (!utcTime) return '-'

  const date = typeof utcTime === 'string' ? new Date(utcTime) : utcTime

  if (isNaN(date.getTime())) {
    return '-'
  }

  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hour = String(date.getHours()).padStart(2, '0')
  const minute = String(date.getMinutes()).padStart(2, '0')

  switch (format) {
    case 'short':
      return `${hour}:${minute}`
    case 'medium':
      return `${month}-${day} ${hour}:${minute}`
    case 'long':
      return `${year}-${month}-${day} ${hour}:${minute}`
    default:
      return `${month}-${day} ${hour}:${minute}`
  }
}

/**
 * 获取今日UTC时间范围
 * @returns {Object} 包含start和end的对象
 *
 * @example
 * getTodayUTCRange() // { start: "2026-02-24T00:00:00.000Z", end: "2026-02-24T23:59:59.999Z" }
 */
export function getTodayUTCRange() {
  const now = new Date()
  const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 0, 0, 0, 0))
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 23, 59, 59, 999))

  return {
    start: start.toISOString(),
    end: end.toISOString()
  }
}

/**
 * 转换为Unix时间戳（毫秒）
 * @param {string|Date} utcTime - UTC时间
 * @returns {number} Unix时间戳（毫秒）
 *
 * @example
 * toTimestampMs('2026-02-24T10:30:00Z') // 1740394200000
 */
export function toTimestampMs(utcTime) {
  const date = typeof utcTime === 'string' ? new Date(utcTime) : utcTime
  return date.getTime()
}

/**
 * 从Unix时间戳（毫秒）转换为UTC时间字符串
 * @param {number} timestamp - Unix时间戳（毫秒）
 * @returns {string} UTC ISO字符串
 *
 * @example
 * fromTimestampMs(1740394200000) // "2026-02-24T10:30:00.000Z"
 */
export function fromTimestampMs(timestamp) {
  return new Date(timestamp).toISOString()
}

/**
 * 格式化时间范围
 * @param {string|Date} startTime - 开始时间
 * @param {string|Date} endTime - 结束时间
 * @returns {string} 格式化的时间范围字符串
 *
 * @example
 * formatTimeRange('2026-02-24T10:00:00Z', '2026-02-24T12:00:00Z') // "10:00 - 12:00"
 */
export function formatTimeRange(startTime, endTime) {
  if (!startTime || !endTime) return '-'

  const start = typeof startTime === 'string' ? new Date(startTime) : startTime
  const end = typeof endTime === 'string' ? new Date(endTime) : endTime

  const startStr = formatCompact(start, 'short')
  const endStr = formatCompact(end, 'short')

  return `${startStr} - ${endStr}`
}

/**
 * 检查时间是否为今天
 * @param {string|Date} utcTime - UTC时间
 * @returns {boolean} 是否为今天
 *
 * @example
 * isToday('2026-02-24T10:30:00Z') // true (如果今天是2026-02-24)
 */
export function isToday(utcTime) {
  const date = typeof utcTime === 'string' ? new Date(utcTime) : utcTime
  const now = new Date()

  return date.getUTCFullYear() === now.getUTCFullYear() &&
         date.getUTCMonth() === now.getUTCMonth() &&
         date.getUTCDate() === now.getUTCDate()
}

// 向后兼容的别名
export const formatTime = formatUTCTime
export const getTimeAgo = timeAgo
export const parseTime = parseUTCTime

/**
 * 将UTC时间戳转换为北京时间字符串（完整格式）
 * 专用于后端返回的UTC时间戳，统一显示为北京时间
 * @param {string|number|Date} timestamp - UTC时间戳
 * @returns {string} 北京时间字符串 (YYYY-MM-DD HH:mm:ss)
 */
export function formatDateTimeBeijing(timestamp) {
  if (!timestamp) return '-'

  const date = new Date(timestamp)

  // 检查是否为有效日期
  if (isNaN(date.getTime())) {
    console.error('Invalid date:', timestamp)
    return '-'
  }

  return date.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}

/**
 * 将UTC时间戳转换为北京时间字符串（仅时间）
 * @param {string|number|Date} timestamp - UTC时间戳
 * @returns {string} 北京时间字符串 (HH:mm:ss)
 */
export function formatTimeBeijing(timestamp) {
  if (!timestamp) return '-'

  const date = new Date(timestamp)

  // 检查是否为有效日期
  if (isNaN(date.getTime())) {
    return '-'
  }

  return date.toLocaleTimeString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}

/**
 * 将UTC时间戳转换为北京时间字符串（日期+时间，短格式）
 * @param {string|number|Date} timestamp - UTC时间戳
 * @returns {string} 北京时间字符串 (MM-DD HH:mm:ss)
 */
export function formatShortDateTimeBeijing(timestamp) {
  if (!timestamp) return '-'

  const date = new Date(timestamp)

  // 检查是否为有效日期
  if (isNaN(date.getTime())) {
    return '-'
  }

  const formatted = date.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })

  // 格式化为 MM-DD HH:mm:ss
  return formatted.replace(/\//g, '-')
}
