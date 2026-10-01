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
        <span>机组编号 / 机组机型</span>
        <input v-model="draft.keyword" placeholder="编号或机型模糊检索" />
      </label>
      <label class="filter-item">
        <span>运行状态</span>
        <select v-model="draft.status">
          <option value="">全部状态</option>
          <option v-for="option in statusOptions" :key="option" :value="option">{{ option }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>轮毂高度（米）</span>
        <span class="range-inputs">
          <input v-model="draft.hubMin" type="number" min="0" placeholder="下限" />
          <em>至</em>
          <input v-model="draft.hubMax" type="number" min="0" placeholder="上限" />
        </span>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
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
        <tr v-if="!rows.length && !loading">
          <td :colspan="columns.length + 1" class="empty-state">{{ emptyHint }}</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条风电机组记录</span>
      <span class="pager">
        <button class="btn" type="button" :disabled="page <= 1 || loading" @click="goPage(-1)">上一页</button>
        <span>第 {{ page }} / {{ totalPages }} 页</span>
        <button class="btn" type="button" :disabled="page >= totalPages || loading" @click="goPage(1)">下一页</button>
      </span>
      <span v-if="loading">读取中…</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <button v-if="loadFailed" class="btn" type="button" @click="retryLoad">重新取数</button>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

type FilterState = {
  keyword: string
  status: string
  hubMin: string
  hubMax: string
}

const ENDPOINT = '/api/turbine'
const PAGE_SIZE = 10
const columns = ["机组编号", "机组机型", "额定功率", "轮毂高度", "所属场站", "投运日期", "累计发电量", "机组状态"]
const actions = ["投运机组", "登记停机", "办理退役"]
const statusOptions = ["待投运", "运行中", "故障停机", "已退役"]

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const loadFailed = ref(false)
const errorMessage = ref('')
const summary = ref<Record<string, number>>({})

// draft 是正在填写的条件；applied 是已提交给服务端的条件，翻页时沿用 applied
const draft = reactive<FilterState>({ keyword: '', status: '', hubMin: '', hubMax: '' })
const applied = reactive<FilterState>({ keyword: '', status: '', hubMin: '', hubMax: '' })

const stats = computed(() => [
  { label: '在运机组', value: summary.value['在运机组'] ?? 0 },
  { label: '故障停机台数', value: summary.value['故障停机台数'] ?? 0 },
  { label: '待投运台数', value: summary.value['待投运台数'] ?? 0 },
])

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

const hasConditions = computed(
  () => Boolean(applied.keyword || applied.status || applied.hubMin !== '' || applied.hubMax !== ''),
)

const emptyHint = computed(() => {
  if (loadFailed.value) return '本次取数失败，列表已清空，请点击页脚“重新取数”再试'
  if (hasConditions.value) return '没有符合当前条件的风电机组，条件已保留，可调整后重新查询'
  return '暂无风电机组数据，可先登记风电机组'
})

function parseHub(raw: string, label: string): number | null {
  const text = raw.trim()
  if (text === '') return null
  const value = Number(text)
  if (Number.isNaN(value)) {
    throw new Error(`${label}需要填数字，当前填写的是「${text}」`)
  }
  return value
}

function applyFilters() {
  errorMessage.value = ''
  let hubMin: number | null
  let hubMax: number | null
  try {
    hubMin = parseHub(draft.hubMin, '轮毂高度下限')
    hubMax = parseHub(draft.hubMax, '轮毂高度上限')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '轮毂高度填写有误'
    return
  }
  if (hubMin !== null && hubMax !== null && hubMin > hubMax) {
    errorMessage.value = `轮毂高度区间互相矛盾：下限 ${hubMin} 米大于上限 ${hubMax} 米，请调整后再查询`
    return
  }
  applied.keyword = draft.keyword.trim()
  applied.status = draft.status
  applied.hubMin = hubMin === null ? '' : String(hubMin)
  applied.hubMax = hubMax === null ? '' : String(hubMax)
  page.value = 1
  void load()
}

function resetFilters() {
  draft.keyword = ''
  draft.status = ''
  draft.hubMin = ''
  draft.hubMax = ''
  applied.keyword = ''
  applied.status = ''
  applied.hubMin = ''
  applied.hubMax = ''
  page.value = 1
  errorMessage.value = ''
  void load()
}

function goPage(step: number) {
  const next = page.value + step
  if (next < 1 || next > totalPages.value || loading.value) return
  page.value = next
  void load()
}

function retryLoad() {
  void load()
}

function buildQuery(): string {
  const params = new URLSearchParams()
  if (applied.keyword) params.set('keyword', applied.keyword)
  if (applied.status) params.set('status', applied.status)
  if (applied.hubMin !== '') params.set('hub_min', applied.hubMin)
  if (applied.hubMax !== '') params.set('hub_max', applied.hubMax)
  params.set('page', String(page.value))
  params.set('size', String(PAGE_SIZE))
  return params.toString()
}

// 重复检索只留最新一版条件：新请求发出时中止旧请求，并用序号挡掉迟到的旧响应
let loadSeq = 0
let inflight: AbortController | null = null

async function readDetail(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
    if (Array.isArray(body?.detail)) {
      const text = body.detail
        .map((item: { msg?: string }) => item?.msg ?? '')
        .filter(Boolean)
        .join('；')
      if (text) return text
    }
  } catch {
    // 响应体不是 JSON 时退回状态码说明
  }
  return `接口返回 ${response.status}`
}

async function load() {
  loadSeq += 1
  const seq = loadSeq
  inflight?.abort()
  const controller = new AbortController()
  inflight = controller
  loading.value = true
  errorMessage.value = ''
  loadFailed.value = false
  try {
    const response = await request(`${ENDPOINT}?${buildQuery()}`, { signal: controller.signal })
    if (!response.ok) {
      const detail = await readDetail(response)
      if (seq !== loadSeq) return
      if (response.status === 400 || response.status === 422) {
        // 条件本身有问题：保留当前列表，只说明该怎么改
        errorMessage.value = detail
        return
      }
      throw new Error(detail)
    }
    const payload = await response.json()
    if (seq !== loadSeq) return
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    summary.value = payload.summary ?? {}
  } catch (error) {
    if (controller.signal.aborted || seq !== loadSeq) return
    // 取数失败：清空上一批结果，避免旧数据冒充当前条件的结果
    rows.value = []
    total.value = 0
    summary.value = {}
    loadFailed.value = true
    errorMessage.value = error instanceof Error ? error.message : '风电机组列表读取失败'
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '风电机组登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('风电机组动作未生效，请稍后重试')
    }
    await load()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '风电机组操作失败'
  }
}

onMounted(load)
onBeforeUnmount(() => inflight?.abort())
</script>
