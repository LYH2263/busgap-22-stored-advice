<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const trips = ref<any[]>([])
const events = ref<any[]>([])
onMounted(async () => {
  trips.value = await api('/trips')
  // 只读最新一份已固化报告，不在浏览时触发新检测
  const reports = await api('/reports?line_id=1')
  events.value = reports.length ? reports[0].events : []
})
function stripClass(code: string) {
  return code === 'bunching' ? 'bg-bunch' : code === 'large_gap' ? 'bg-large' : ''
}
function label(code: string) {
  return code === 'bunching' ? '串车' : code === 'large_gap' ? '大间隔' : '正常'
}
</script>
<template>
  <h1>班次 · 间隔条带</h1>
  <p class="sub">左侧班次清单，右侧为最新报告库内固化的状态码快照</p>
  <div class="bg-split">
    <aside class="bg-trip-col">
      <h2>班次列表</h2>
      <div v-for="r in trips" :key="r.id ?? r.trip_no" class="bg-trip-row">
        <div>
          <div>{{ r.trip_no }}</div>
          <div class="bg-trip-meta">线路 {{ r.line_id }} · 车 {{ r.vehicle_no }}</div>
        </div>
        <div class="bg-trip-meta">{{ r.planned_depart }}</div>
      </div>
    </aside>
    <div class="bg-strip-col">
      <article
        v-for="e in events"
        :key="e.seq"
        class="bg-gap-strip"
        :class="stripClass(e.status_code)"
      >
        <header>{{ e.stop_name }}</header>
        <div class="bg-gap-body">
          <div class="bg-gap-val">{{ e.gap_min }}′</div>
          <div>{{ e.earlier_trip }} → {{ e.later_trip }}</div>
          <span class="badge" :class="e.status_code === 'bunching' ? 'badge-bad' : e.status_code === 'large_gap' ? 'badge-warn' : 'badge-ok'">
            {{ label(e.status_code) }}
          </span>
        </div>
      </article>
      <p v-if="!events.length" class="muted">暂无间隔事件（先在串车报告页跑一次检测）</p>
    </div>
  </div>
</template>
