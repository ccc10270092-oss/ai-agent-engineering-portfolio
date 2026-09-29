<script setup>
const props = defineProps({
  trace: { type: Array, default: () => [] },
})

const STAGE_LABELS = {
  thinking: '思考',
  acting: '调用工具',
  observing: '观察结果',
  responding: '生成回答',
}
</script>

<template>
  <div v-if="trace.length" class="trace">
    <template v-for="(t, i) in trace" :key="i">
      <div class="trace-node">
        <span class="dot" :class="`s-${t.stage}`" />
        <span class="stage">{{ STAGE_LABELS[t.stage] || t.stage }}</span>
        <span v-if="t.tool" class="tool mono">{{ t.tool }}</span>
      </div>
      <span v-if="i < trace.length - 1" class="sep">›</span>
    </template>
  </div>
</template>

<style scoped>
.trace {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-3);
}

.trace-node {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border: 1px solid var(--border-hairline);
  border-radius: 999px;
  background: var(--bg-inset);
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-3);
}

.dot.s-acting {
  background: #22d3ee;
  box-shadow: 0 0 6px rgba(34, 211, 238, 0.7);
}

.dot.s-observing {
  background: #7c8cf8;
}

.dot.s-responding {
  background: #34c759;
}

.dot.s-thinking {
  background: #fab219;
}

.stage {
  color: var(--text-2);
}

.tool {
  padding: 1px 7px;
  border-radius: 5px;
  background: rgba(34, 211, 238, 0.1);
  color: #22d3ee;
  font-size: 11px;
}

.sep {
  color: var(--text-3);
  margin: 0 2px;
}
</style>
