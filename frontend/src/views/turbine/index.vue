<template>
  <section class="page" data-module="turbine">
    <header class="page-head">
      <div>
        <h2>风电机组管理</h2>
        <p class="page-desc">维护风电机组，围绕机组编号、机组机型、额定功率、轮毂高度做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记风电机组</button>
        <button class="btn" type="button" @click="exportRows">导出风电机组清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="applyFilters">
      <label class="filter-item">
        <span>编号/机型</span>
        <input
          v-model="draft.keyword"
          placeholder="按机组编号或机型模糊检索"
          aria-label="机组编号或机组机型"
        />
      </label>
      <label class="filter-item">
        <span>运行状态</span>
        <select v-model="draft.status" aria-label="运行状态">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <label class="filter-item filter-item--num">
        <span>轮毂高度（米）</span>
        <div class="range-inputs">
          <input
            v-model="draft.heightMin"
            inputmode="decimal"
            placeholder="下限"
            aria-label="轮毂高度下限"
          />
          <span class="range-sep">至</span>
          <input
            v-model="draft.heightMax"
            inputmode="decimal"
            placeholder="上限"
            aria-label="轮毂高度上限"
          />
        </div>
      </label>
      <button class="btn primary" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="warningMessage" class="notice notice--warn" role="alert">
      <span>{{ warningMessage }}</span>
    </div>
    <div v-if="errorMessage" class="notice notice--error" role="alert">
      <span>{{ errorMessage }}</span>
      <button class="btn" type="button" :disabled="loading" @click="reload">
        {{ loading ? '正在取数…' : '重新取数' }}
      </button>
    </div>

    <table class="data-table" :class="{ 'data-table--stale': !loading && Boolean(errorMessage) }">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="loading">
          <td :colspan="columns.length + 1" class="empty-state">正在读取风电机组…</td>
        </tr>
        <tr v-else-if="!rows.length && warningMessage">
          <td :colspan="columns.length + 1" class="empty-state">{{ warningMessage }}，请调整筛选条件</td>
        </tr>
        <tr v-else-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">
            {{ hasAppliedFilters ? '当前条件下没有匹配的风电机组，可放宽条件或重置' : '暂无风电机组数据，可先登记风电机组' }}
          </td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条风电机组记录</span>
      <div class="pager">
        <button class="btn" type="button" :disabled="loading || page <= 1" @click="goToPage(page - 1)">
          上一页
        </button>
        <span class="pager-info">第 {{ page }} 页 / 共 {{ totalPages }} 页</span>
        <button
          class="btn"
          type="button"
          :disabled="loading || page >= totalPages"
          @click="goToPage(page + 1)"
        >
          下一页
        </button>
      </div>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Summary = { running: number; fault: number; total: number }

const ENDPOINT = '/api/turbine'
const PAGE_SIZE = 20
const columns = ['机组编号', '机组机型', '额定功率', '轮毂高度', '所属场站', '投运日期', '累计发电量', '机组状态']
const actions = ['投运机组', '登记停机', '办理退役']
const statuses = ['待投运', '运行中', '故障停机', '已退役']

type Filters = { keyword: string; status: string; heightMin: string; heightMax: string }

const emptyFilters = (): Filters => ({ keyword: '', status: '', heightMin: '', heightMax: '' })

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const errorMessage = ref('')
const warningMessage = ref('')

// draft 是筛选条里正在编辑的值；applied 是服务端最近一次真正使用的一版条件。
// 重复检索只认最新一版：请求序号更靠后的结果才会落到页面上。
const draft = ref<Filters>(emptyFilters())
const applied = ref<Filters>(emptyFilters())
let requestSeq = 0

const stats = ref([
  { label: '在运机组', value: 0 },
  { label: '故障停机台数', value: 0 },
  { label: '当前台账台数', value: 0 },
])

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const hasAppliedFilters = computed(() =>
  Boolean(
    applied.value.keyword.trim()
      || applied.value.status
      || applied.value.heightMin.trim()
      || applied.value.heightMax.trim(),
  ),
)

function buildQuery(conditions: Filters, targetPage: number) {
  const params = new URLSearchParams()
  const keyword = conditions.keyword.trim()
  if (keyword) params.set('keyword', keyword)
  if (conditions.status) params.set('status', conditions.status)
  if (conditions.heightMin.trim()) params.set('height_min', conditions.heightMin.trim())
  if (conditions.heightMax.trim()) params.set('height_max', conditions.heightMax.trim())
  params.set('page', String(targetPage))
  params.set('size', String(PAGE_SIZE))
  return params.toString()
}

/** 提交前自查一遍高度区间，矛盾条件直接说明，不拿空表应付。 */
function validateHeights(conditions: Filters): string {
  const minText = conditions.heightMin.trim()
  const maxText = conditions.heightMax.trim()
  const minimum = minText ? Number(minText) : null
  const maximum = maxText ? Number(maxText) : null
  if ((minText && Number.isNaN(minimum)) || (maxText && Number.isNaN(maximum))) {
    return '轮毂高度需要填写数字（单位米），请检查区间输入后再查询'
  }
  if (minimum !== null && minimum < 0) {
    return '轮毂高度下限不能为负数，请重新填写'
  }
  if (maximum !== null && maximum < 0) {
    return '轮毂高度上限不能为负数，请重新填写'
  }
  if (minimum !== null && maximum !== null && minimum > maximum) {
    return `轮毂高度区间互相矛盾：下限 ${minimum} 米高于上限 ${maximum} 米，请调整后再查询`
  }
  return ''
}

async function loadList(conditions: Filters, targetPage: number) {
  const seq = ++requestSeq
  loading.value = true
  errorMessage.value = ''
  warningMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}?${buildQuery(conditions, targetPage)}`)
    if (!response.ok) {
      let detail = '风电机组列表读取失败'
      try {
        const body = await response.json()
        if (typeof body?.detail === 'string') detail = body.detail
      } catch {
        // 非 JSON 错误体时沿用默认说明
      }
      throw new Error(detail)
    }
    const payload: { items?: Row[]; total?: number; summary?: Summary } = await response.json()
    // 过期响应（又检索了一次或重置过）直接丢弃，只留最新一版条件的结果。
    if (seq !== requestSeq) return
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    applied.value = { ...conditions }
    // 服务端按同一份过滤结果汇总，卡片条数与台账保持一致。
    const summary: Summary = payload.summary
      ?? { running: 0, fault: 0, total: total.value }
    stats.value = [
      { label: '在运机组', value: summary.running },
      { label: '故障停机台数', value: summary.fault },
      { label: '当前台账台数', value: summary.total },
    ]
    // 条件变化后总数可能缩小，超出末页时收回末页，避免停在空白页。
    const lastPage = Math.max(1, Math.ceil(total.value / PAGE_SIZE))
    if (targetPage > lastPage) {
      page.value = lastPage
      void loadList(conditions, lastPage)
      return
    }
    page.value = targetPage
  } catch (error) {
    if (seq !== requestSeq) return
    // 取数失败不清空 rows：上一批结果保留在表里并置灰，提示用户重新取数。
    errorMessage.value = error instanceof Error ? error.message : '风电机组列表读取失败'
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

/** 重新取数：沿用最近一版条件与页码接着走，不顶掉旧结果直到新结果到达。 */
function reload() {
  void loadList(applied.value, page.value)
}

/** 改条件后查询一律回到第 1 页。 */
function applyFilters() {
  const conditions = { ...draft.value }
  const conflict = validateHeights(conditions)
  if (conflict) {
    warningMessage.value = conflict
    errorMessage.value = ''
    return
  }
  void loadList(conditions, 1)
}

/** 翻页只换页码，沿用最近一版已生效条件。 */
function goToPage(target: number) {
  if (target < 1 || target > totalPages.value || target === page.value) return
  void loadList({ ...applied.value }, target)
}

/** 重置后条件清空并回到第 1 页，列表恢复全量。 */
function resetFilters() {
  draft.value = emptyFilters()
  void loadList(emptyFilters(), 1)
}

/** 导出沿用最近一版条件，保证导出条数与当前台账一致。 */
function exportRows() {
  window.open(`${ENDPOINT}/export?${buildQuery(applied.value, 1)}`, '_blank')
}

function openCreate() {
  errorMessage.value = '风电机组登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  warningMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('风电机组动作未生效，请稍后重试')
    }
    await loadList({ ...applied.value }, page.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '风电机组操作失败'
  }
}

onMounted(() => {
  void loadList(emptyFilters(), 1)
})
</script>
