import { bitable, FieldType } from '@lark-base-open/js-sdk'
const SUPPORT_TEXTS = [
  'Formula',
  'AutoNumber',
  'Barcode',
  'CreatedTime',
  'SingleSelect',
  'MultiSelect',
  'CreatedUser',
  'DateTime',
  'Location',
  'ModifiedTime',
  'ModifiedUser',
  'Number',
  'Phone',
  'Text',
  'Url',
  'User'
]
export const SUPPORT_TYPES = SUPPORT_TEXTS.map((e) => FieldType[e])

/**
 * 并发控制辅助函数 - 限制同时执行的异步任务数量
 * @param {Array} items - 需要处理的数据数组
 * @param {Number} limit - 最大并发数
 * @param {Function} fn - 处理函数
 */
async function asyncPoolLimit(items, limit, fn) {
  const results = []
  const executing = []

  for (const [index, item] of items.entries()) {
    const promise = Promise.resolve().then(() => fn(item, index))
    results.push(promise)

    if (limit <= items.length) {
      const e = promise.then(() => executing.splice(executing.indexOf(e), 1))
      executing.push(e)
      if (executing.length >= limit) {
        await Promise.race(executing)
      }
    }
  }

  return Promise.all(results)
}

// 根据tableMetaList，输出对应的fieldMetaList（优化版：限制并发数）
export async function getInfoByTableMetaList(tableMetaList) {
  // 限制最大并发数为 3，避免大量请求阻塞
  const MAX_CONCURRENT = 3
  const results = []

  await asyncPoolLimit(tableMetaList, MAX_CONCURRENT, async(tableMeta, index) => {
    const tableId = tableMeta.id
    const tableName = tableMeta.name
    const table = await bitable.base.getTableById(tableId)
    const fieldMetaList = await table.getFieldMetaList()
    const viewMetaList = await table.getViewMetaList()
    results[index] = {
      tableId,
      tableName,
      fieldMetaList,
      viewMetaList
    }
  })

  return results
}

export function sortByOrder(arrayA, arrayB) {
  // 创建一个映射，以B数组的id为键，值为它们在B数组中的索引
  const orderMap = new Map(arrayB.map((item, index) => [item.id, index]))

  // 使用排序函数对A数组进行排序
  return arrayA.sort((a, b) => {
    // 获取A数组中对象在B数组中的索引
    const indexA = orderMap.has(a.id) ? orderMap.get(a.id) : Infinity
    const indexB = orderMap.has(b.id) ? orderMap.get(b.id) : Infinity

    // 根据B数组中的索引进行排序
    return indexA - indexB
  })
}
