<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
interface ReportEvent {
  seq: number
  stop_name: string
  earlier_trip: string
  later_trip: string
  gap_min: number
  status_code: string
  suggestion_text: string
  status_drift: boolean
  text_drift: boolean
}
interface Report {
  id: number
  line_id: number
  stop_name: string
  created_at: string | null
  events: ReportEvent[]
  thresholds: { planned_headway_min: number; bunch_threshold: number; large_threshold: number }
}
const reports = ref<Report[]>([])
const selected = ref<Report | null>(null)
const loading = ref(false)
const error = ref('')

async function refresh() {
  reports.value = await api('/reports?line_id=1')
  if (selected.value) {
    const keep = reports.value.find(r => r.id === selected.value!.id)
    selected.value = keep ?? reports.value[0] ?? null
  } else {
    selected.value = reports.value[0] ?? null
  }
}
async function run() {
  loading.value = true
  error.value = ''
  try {
    const fresh: Report = await api('/reports/run?line_id=1', { method: 'POST' })
    await refresh()
    selected.value = reports.value.find(r => r.id === fresh.id) ?? fresh
  } catch (e: any) {
    error.value = e?.message ? String(e.message) : '固化失败'
  } finally { loading.value = false }
}
function open(r: Report) { selected.value = r }
function stripClass(code: string) {
  return code === 'bunching' ? 'bg-bunch' : code === 'large_gap' ? 'bg-large' : ''
}
function label(code: string) {
  return code === 'bunching' ? '串车' : code === 'large_gap' ? '大间隔' : '正常'
}
function badgeClass(code: string) {
  return code === 'bunching' ? 'badge-bad' : code === 'large_gap' ? 'badge-warn' : 'badge-ok'
}
onMounted(refresh)
</script>
<template>
  <h1>串车报告</h1>
  <p class="sub">检测成功时原子固化「状态码」「建议文句」两列 · 读出只呈库内快照，阈值再调不刷旧报告</p>
  <button class="btn" :disabled="loading" @click="run">{{ loading ? '检测中…' : '新增检测（写入新快照）' }}</button>
  <p v-if="error" class="muted" style="color:var(--bg-red)">整次写入失败，报告行数未增：{{ error }}</p>
  <div class="bg-split" style="margin-top:1rem">
    <aside class="bg-trip-col">
      <h2>历史报告（{{ reports.length }}）</h2>
      <div v-for="r in reports" :key="r.id" class="bg-trip-row"
           :style="selected && selected.id === r.id ? 'background:rgba(46,196,255,0.12)' : ''"
           @click="open(r)">
        <div>
          <div>#{{ r.id }} · {{ r.stop_name }}</div>
          <div class="bg-trip-meta">{{ r.events.length }} 条事件 · 串车阈 {{ r.thresholds.bunch_threshold }}</div>
        </div>
        <div class="bg-trip-meta">{{ r.created_at }}</div>
      </div>
      <p v-if="!reports.length" class="muted" style="padding:0.9rem">暂无报告，先跑一次检测</p>
    </aside>
    <div class="bg-strip-col" v-if="selected">
      <article
        v-for="e in selected.events"
        :key="e.seq"
        class="bg-gap-strip"
        :class="stripClass(e.status_code)"
      >
        <header>{{ e.stop_name }}</header>
        <div class="bg-gap-body">
          <div class="bg-gap-val">{{ e.gap_min }}′</div>
          <div>{{ e.earlier_trip }} → {{ e.later_trip }}</div>
          <span class="badge" :class="badgeClass(e.status_code)">{{ label(e.status_code) }}</span>
          <!-- 只展示库内建议文句，不按现行阈值重拼 -->
          <p style="margin:0.2rem 0 0; line-height:1.45">{{ e.suggestion_text }}</p>
          <!-- 库内快照被改脏时跟库读出，仅打标，不回写 -->
          <span v-if="e.status_drift" class="badge badge-bad">状态漂移</span>
          <span v-if="e.text_drift" class="badge badge-warn">文句漂移</span>
        </div>
      </article>
      <p v-if="!selected.events.length" class="muted">该报告无事件</p>
    </div>
    <div v-else class="bg-strip-col"><p class="muted">选择左侧报告查看快照</p></div>
  </div>
</template>
