const STATUS_LABELS = {
  ready: '可编辑',
  active: '进行中',
  missing: '待创建',
}

function isValidOutlineItem(item) {
  return Boolean(item?.outline_type && item?.outline_ref)
}

function normalizeSelection(selection) {
  const outlineType = selection?.outline_type || selection?.outlineType || ''
  const outlineRef = selection?.outline_ref || selection?.outlineRef || ''
  if (!outlineType || !outlineRef) return null
  return {
    outline_type: outlineType,
    outline_ref: outlineRef,
  }
}

function createItemId(outlineType, outlineRef) {
  return `${outlineType}:${outlineRef}`
}

export function resolveOutlineWorkbenchSelection(items = [], selection = null) {
  const normalizedSelection = normalizeSelection(selection)
  const normalizedItems = (Array.isArray(items) ? items : []).filter(isValidOutlineItem)
  const itemIds = new Set(
    normalizedItems.map((item) => createItemId(item?.outline_type, item?.outline_ref))
  )

  if (normalizedSelection) {
    const currentId = createItemId(normalizedSelection.outline_type, normalizedSelection.outline_ref)
    if (itemIds.has(currentId)) return normalizedSelection
  }

  const synopsis = normalizedItems.find(
    (item) => item?.outline_type === 'synopsis' && item?.outline_ref === 'synopsis'
  )
  if (synopsis) {
    return {
      outline_type: synopsis.outline_type,
      outline_ref: synopsis.outline_ref,
    }
  }

  const firstItem = normalizedItems[0]
  if (!firstItem) return null
  return {
    outline_type: firstItem.outline_type,
    outline_ref: firstItem.outline_ref,
  }
}

export function buildOutlineWorkbenchItems({ items = [], currentItem = null } = {}) {
  const resolvedCurrentItem = resolveOutlineWorkbenchSelection(items, currentItem)
  const currentItemId = resolvedCurrentItem
    ? createItemId(resolvedCurrentItem.outline_type, resolvedCurrentItem.outline_ref)
    : ''

  return (Array.isArray(items) ? items : []).map((item) => {
    const itemId = createItemId(item?.outline_type, item?.outline_ref)
    return {
      ...item,
      key: itemId,
      itemId,
      outlineType: item?.outline_type || '',
      outlineRef: item?.outline_ref || '',
      statusLabel: STATUS_LABELS[item?.status] || '待处理',
      isCurrent: itemId === currentItemId,
    }
  })
}
