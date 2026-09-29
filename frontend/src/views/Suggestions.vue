<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const tips = ref<any[]>([])
const runId = ref<number | null>(null)
onMounted(async () => {
  const data = await api('/reports/suggestions?line_id=1')
  tips.value = data.suggestions
  runId.value = data.run_id
})
function label(s: string) {
  return s === 'bunching' ? '串车' : s === 'large_gap' ? '大间隔' : '正常'
}
</script>
<template>
  <h1>建议</h1>
  <p class="sub">只读最近一次检测（#{{ runId ?? '—' }}）库内固化的文句，不重新检测、不按现行阈值拼句</p>
  <div class="card" v-for="(t,i) in tips" :key="i">
    <div>
      <strong>{{ t.stop_name }}</strong> · {{ t.earlier_trip }} → {{ t.later_trip }} · 间隔 {{ t.gap_min }} 分
      <span class="badge" :class="t.status === 'bunching' ? 'badge-bad' : t.status === 'large_gap' ? 'badge-warn' : 'badge-ok'">
        {{ label(t.status) }}
      </span>
      <span v-if="t.text_drift" class="badge badge-warn" style="margin-left:.35rem">文句漂移</span>
      <span v-if="t.status_drift" class="badge badge-bad" style="margin-left:.35rem">状态漂移</span>
    </div>
    <p class="muted">{{ t.suggestion || '（库内文句为空）' }}</p>
  </div>
  <p v-if="!tips.length" class="muted">暂无异常建议</p>
</template>
