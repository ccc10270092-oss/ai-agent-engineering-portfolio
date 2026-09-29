<script setup>
import * as echarts from 'echarts'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: String, default: '240px' },
})

const el = ref(null)
let chart = null
let observer = null

const render = () => {
  if (chart && props.option) chart.setOption(props.option, true)
}

onMounted(() => {
  chart = echarts.init(el.value)
  render()
  // 容器尺寸变化时自适应(布局切换、侧栏收起等)
  observer = new ResizeObserver(() => chart && chart.resize())
  observer.observe(el.value)
})

watch(() => props.option, render, { deep: true })

onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="el" class="v-chart" :style="{ height, width: '100%' }" />
</template>
