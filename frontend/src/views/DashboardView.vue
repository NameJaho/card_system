<template>
  <div>
    <div class="stats-grid">
      <div class="stat stat-teal">
        <span class="stat-icon">SW</span>
        <label>活跃软件</label>
        <strong>{{ stats.active }}</strong>
        <small>可用实例总数</small>
      </div>
      <div class="stat stat-blue">
        <span class="stat-icon">REQ</span>
        <label>日访问量</label>
        <strong>{{ stats.visit }}</strong>
        <small>近 24 小时接口访问</small>
      </div>
      <div class="stat stat-amber">
        <span class="stat-icon">ACT</span>
        <label>日激活量</label>
        <strong>{{ stats.activationCount }}</strong>
        <small>当前已激活卡密</small>
      </div>
      <div class="stat stat-violet">
        <span class="stat-icon">LOG</span>
        <label>月访问量</label>
        <strong>{{ stats.monthCount }}</strong>
        <small>近 30 天事件量</small>
      </div>
    </div>
    <div class="dashboard-grid" style="margin-top: 16px">
      <div class="panel">
        <div class="panel-header">
          <h3>24 小时访问趋势</h3>
          <span>{{ stats.visit }} requests</span>
        </div>
        <div ref="lineRef" style="height: 318px"></div>
      </div>
      <div class="panel">
        <div class="panel-header">
          <h3>访问排行</h3>
          <span>{{ visitList.length }} instances</span>
        </div>
        <el-table :data="visitList" height="318">
          <el-table-column prop="name" label="实例" />
          <el-table-column prop="visitCount" label="访问量" width="96" />
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import * as echarts from 'echarts'
import { api } from '../services/api'

const stats = reactive({ active: 0, visit: 0, activationCount: 0, monthCount: 0 })
const visitList = ref([])
const lineRef = ref(null)

async function load() {
  const res = await api.dataCount()
  if (!res.success) return
  const data = res.data
  visitList.value = data.visitList || []
  stats.active = visitList.value.length
  stats.visit = visitList.value.reduce((sum, row) => sum + Number(row.visitCount || 0), 0)
  stats.activationCount = data.activationCount || 0
  stats.monthCount = data.monthCount || 0
  const hours = Array.from({ length: 24 }, (_, i) => `${i}点`)
  const buckets = Array(24).fill(0)
  visitList.value.forEach((item) => (item.visitList || []).forEach((row) => { buckets[row.hours] += row.value || 0 }))
  const chart = echarts.init(lineRef.value)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 38, right: 22, top: 22, bottom: 34 },
    xAxis: { type: 'category', data: hours, axisLine: { lineStyle: { color: '#d9e0e8' } }, axisLabel: { color: '#6d7888' } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#edf1f5' } }, axisLabel: { color: '#6d7888' } },
    color: ['#2364d2'],
    series: [{
      type: 'line',
      smooth: true,
      data: buckets,
      symbolSize: 6,
      lineStyle: { width: 3 },
      areaStyle: { color: 'rgba(35,100,210,.10)' }
    }]
  })
}

onMounted(load)
</script>
