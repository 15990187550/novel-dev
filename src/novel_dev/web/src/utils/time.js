const BEIJING_TIME_ZONE = 'Asia/Shanghai'

function normalizeIsoTimestamp(value) {
  if (typeof value !== 'string') return value
  const trimmed = value.trim()
  if (!trimmed) return value
  if (/[zZ]$|[+-]\d{2}:\d{2}$/.test(trimmed)) return trimmed
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(trimmed)) return `${trimmed}Z`
  return trimmed
}

export function parseTimestamp(value) {
  if (!value) return null
  const date = new Date(normalizeIsoTimestamp(value))
  return Number.isNaN(date.getTime()) ? null : date
}

export function timestampMs(value) {
  const date = parseTimestamp(value)
  return date ? date.getTime() : 0
}

export function formatBeijingDateTime(value) {
  const date = parseTimestamp(value)
  if (!date) return value || '-'
  return date.toLocaleString('zh-CN', {
    timeZone: BEIJING_TIME_ZONE,
    hour12: false,
  })
}

export function formatBeijingTime(value) {
  const date = parseTimestamp(value)
  if (!date) return value || ''
  return date.toLocaleTimeString('zh-CN', {
    timeZone: BEIJING_TIME_ZONE,
    hour12: false,
  })
}
