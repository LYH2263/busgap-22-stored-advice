<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
interface Suggestion {
  stop_name: string
  earlier_trip: string
  later_trip: string
  gap_min: number
  status_code: string
  suggestion_text: string
  status_drift: boolean
  text_drift: boolean
}
const tips = ref<Suggestion[]>([])
const reportId = ref<number | null>(null)
onMounted(async () => {
  const data = await api('/reports/suggestions?line_id=1')
  tips.value = data.suggestions || []
  reportId.value = data.report_id
})
</script>
<template>
  <h1>建议</h1>
  <p class="sub">只读最新报告（#{{ reportId ?? '—' }}）库内固化的状态码与建议文句，不按现行阈值重判</p>
  <div class="card" v-for="(t, i) in tips" :key="i">
    <div>
      <strong>{{ t.stop_name }}</strong> · {{ t.earlier_trip }} → {{ t.later_trip }} · 间隔 {{ t.gap_min }} 分
      <span class="badge" :class="t.status_code === 'bunching' ? 'badge-bad' : 'badge-warn'">
        {{ t.status_code === 'bunching' ? '串车' : '大间隔' }}
      </span>
      <span v-if="t.status_drift" class="badge badge-bad">状态漂移</span>
      <span v-if="t.text_drift" class="badge badge-warn">文句漂移</span>
    </div>
    <p class="muted" style="margin:0.4rem 0 0">{{ t.suggestion_text }}</p>
  </div>
  <p v-if="!tips.length" class="muted">暂无异常建议（先在串车报告页跑一次检测）</p>
</template>
