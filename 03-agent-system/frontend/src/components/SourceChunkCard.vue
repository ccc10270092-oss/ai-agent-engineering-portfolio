<script setup>
defineProps({
  chunk: { type: Object, required: true },
  showScores: { type: Boolean, default: false },
})
</script>

<template>
  <div class="chunk-card">
    <div class="chunk-head">
      <span class="rank">#{{ chunk.rank }}</span>
      <span v-if="showScores" class="score mono">
        fts {{ (chunk.fts_score || 0).toFixed(3) }} · vec
        {{ (chunk.vector_score || 0).toFixed(3) }}
      </span>
      <div class="score-bar">
        <div class="fill" :style="{ width: `${Math.min(100, (chunk.final_score || 0) * 100)}%` }" />
      </div>
      <span class="final mono">{{ (chunk.final_score || 0).toFixed(3) }}</span>
    </div>
    <p class="chunk-text">{{ chunk.text }}</p>
  </div>
</template>

<style scoped>
.chunk-card {
  padding: 12px 14px;
  border: 1px solid var(--border-hairline);
  border-radius: 10px;
  background: var(--bg-inset);
}

.chunk-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.rank {
  flex: none;
  min-width: 32px;
  height: 20px;
  display: grid;
  place-items: center;
  border-radius: 6px;
  background: rgba(64, 158, 255, 0.14);
  color: #79bbff;
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-mono);
}

.score {
  flex: none;
  font-size: 11px;
  color: var(--text-3);
}

.score-bar {
  flex: 1;
  height: 4px;
  border-radius: 2px;
  background: rgba(148, 163, 184, 0.12);
  overflow: hidden;
}

.fill {
  height: 100%;
  border-radius: 2px;
  background: linear-gradient(90deg, #22d3ee, #7c8cf8);
}

.final {
  flex: none;
  font-size: 12px;
  color: var(--text-2);
}

.chunk-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-2);
  white-space: pre-wrap;
}
</style>
