
export const debouncedSort = (func, delay) => {
  let timeoutId
  return (...args) => {
    clearTimeout(timeoutId)
    timeoutId = setTimeout(() => {
      func(...args)
    }, delay)
  }
}
export const getFileSize = (size) => {
  if (size >= 1073741824) return (size / 1073741824).toFixed(2) + 'G'
  if (size >= 1048576) return (size / 1048576).toFixed(2) + 'M'
  if (size >= 1024) return (size / 1024).toFixed(2) + 'K'
  return size.toFixed(2) + 'B'
}
export const removeSpecialChars = (str) =>
  str.replace(/[\n\t\r]/g, '').replace(/\//g, '-')

export const getFolderName = (value, multiSelectSeparator = null) => {
  if (!value) return ''
  if (Array.isArray(value) && value.length) {
    // 如果提供了分隔符，则将所有值用分隔符连接
    if (multiSelectSeparator !== null) {
      const names = value.map(item => item?.text || item?.name || '').filter(Boolean)
      return names.join(multiSelectSeparator)
    }
    // 默认行为：只返回第一个值
    return value[0]?.text || value[0]?.name
  }
  if (typeof value === 'object') return value.text || value.name
  return value
}

export const replaceFileName = (originalName, newName, emptyName = '') => {
  const extension = originalName.split('.').pop()
  return newName
    ? `${newName}.${extension}`
    : `${emptyName}.${extension}`
}

export const chunkArrayByMaxSize = (items, maxSize) => {
  const chunks = []
  const maxChunks = []
  let total = 0
  while (items.length > 0) {
    const currentChunk = []
    let currentSize = 0

    // Try to fit as many items as possible into the current chunk
    for (let i = 0; i < items.length; i++) {
      if (items[i].size >= maxSize) {
        total++
        maxChunks.push(items[i])
        items.splice(i, 1) // Remove the item from the list
        i-- // Adjust the index after removing an item
      } else if (currentSize + items[i].size <= maxSize) {
        total++
        currentChunk.push(items[i])
        currentSize += items[i].size
        items.splice(i, 1) // Remove the item from the list
        i-- // Adjust the index after removing an item
      }
    }

    chunks.push(currentChunk)
  }

  return {
    total,
    chunks,
    maxChunks
  }
}

/**
 * 比较语义化版本号，返回 -1/0/1（仅比较前三段数字）。
 */
export const compareSemanticVersions = (left, right) => {
  const parse = (value) => {
    const parts = String(value || '')
      .trim()
      .replace(/^v/i, '')
      .split('.')
      .map((item) => Number.parseInt(item, 10))
    return [parts[0] || 0, parts[1] || 0, parts[2] || 0]
  }
  const a = parse(left)
  const b = parse(right)
  for (let i = 0; i < 3; i += 1) {
    if (a[i] > b[i]) return 1
    if (a[i] < b[i]) return -1
  }
  return 0
}
