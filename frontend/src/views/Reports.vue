<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'

interface RepoEvent {
  stop_name: string
  earlier_trip: string
  later_trip: string
  gap_min: number
  planned_headway_min: number
  status: string
  suggestion: string
  text_drift: boolean
  status_drift: boolean
}
interface ReportHead {
  run_id: number
  line_id: number
  stop_scope: string
  created_at: string
  events: RepoEvent[]
}
const reports = ref<ReportHead[]>([])
const openId = ref<number | null>(null)
const detail = ref<ReportHead | null>(null)
const loading = ref(false)
const errorMsg = ref('')

async function loadList() {
  reports.value = await api('/reports')
}
async function run() {
  loading.value = true
  errorMsg.value = ''
  try {
    await api('/reports/run?line_id=1', { method: 'POST' })
    await loadList()
  } catch (e) {
    errorMsg.value = String(e)
  } finally {
    loading.value = false
  }
}
async function toggle(head: ReportHead) {
  if (openId.value === head.run_id) {
    openId.value = null
    detail.value = null
    return
  }
  // 点开走读接口，原样取库内快照，不经现行阈值重判
  detail.value = await api(`/reports/${head.run_id}`)
  openId.value = head.run_id
}
function stripClass(s: string) {
  return s === 'bunching' ? 'bg-bunch' : s === 'large_gap' ? 'bg-large' : ''
}
function label(s: string) {
  return s === 'bunching' ? '串车' : s === 'large_gap' ? '大间隔' : s === 'normal' ? '正常' : `未知码(${s || '空'})`
}

onMounted(loadList)
</script>
<template>
  <h1>串车报告</h1>
  <p class="sub">每次检测原子固化「分类状态码 + 建议文句」 · 列表只展示库内快照，不按现行阈值重判</p>
  <button class="btn" :disabled="loading" @click="run">重新检测</button>
  <p v-if="errorMsg" class="muted" style="color:var(--bg-red)">{{ errorMsg }}</p>

  <div v-for="r in reports" :key="r.run_id" class="card" style="margin-top:.8rem">
    <div style="display:flex;justify-content:space-between;align-items:center;cursor:pointer" @click="toggle(r)">
      <div>
        <strong>#{{ r.run_id }}</strong>
        <span class="bg-trip-meta"> · 检测于 {{ r.created_at }} · 范围 {{ r.stop_scope }} · {{ r.events.length }} 条</span>
      </div>
      <span class="muted">{{ openId === r.run_id ? '收起' : '展开' }}</span>
    </div>

    <template v-if="openId === r.run_id && detail">
      <div class="bg-strip-col" style="margin-top:.8rem">
        <article
          v-for="(e, i) in detail.events"
          :key="i"
          class="bg-gap-strip"
          :class="stripClass(e.status)"
        >
          <header>{{ e.stop_name }}</header>
          <div class="bg-gap-body">
            <div class="bg-gap-val">{{ e.gap_min }}′</div>
            <div>计划 {{ e.planned_headway_min }}′</div>
            <div>{{ e.earlier_trip }} → {{ e.later_trip }}</div>
            <span class="badge" :class="e.status === 'bunching' ? 'badge-bad' : e.status === 'large_gap' ? 'badge-warn' : 'badge-ok'">
              {{ label(e.status) }}
            </span>
            <span v-if="e.text_drift" class="badge badge-warn drift-tag">文句漂移</span>
            <span v-if="e.status_drift" class="badge badge-bad drift-tag">状态漂移</span>
          </div>
          <p class="muted" style="margin:.4rem 0 0">{{ e.suggestion || '（库内文句为空）' }}</p>
        </article>
      </div>
    </template>
  </div>
  <p v-if="!reports.length" class="muted">暂无报告</p>
</template>

<style scoped>
.drift-tag { margin-left: .35rem; }
</style>
