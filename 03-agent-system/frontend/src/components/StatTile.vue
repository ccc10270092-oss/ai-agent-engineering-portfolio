<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], required: true },
  unit: { type: String, default: '' },
  icon: { type: String, default: '' },
  tone: {
    type: String,
    default: 'blue',
    validator: (v) => ['blue', 'cyan', 'violet', 'green', 'amber', 'rose'].includes(v),
  },
})
</script>

<template>
  <div class="stat-tile">
    <div v-if="icon" class="tile-icon" :class="`tone-${tone}`">
      <el-icon :size="18"><component :is="icon" /></el-icon>
    </div>
    <div class="tile-body">
      <div class="tile-label">{{ label }}</div>
      <div class="tile-value">
        {{ value }}<span v-if="unit" class="tile-unit">{{ unit }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stat-tile {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
  background: var(--bg-surface);
  border: 1px solid var(--border-hairline);
  border-radius: 12px;
  transition: border-color 0.15s ease;
}

.stat-tile:hover {
  border-color: var(--border-strong);
}

.tile-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  flex: none;
}

.tile-icon.tone-blue {
  background: rgba(64, 158, 255, 0.12);
  color: #79bbff;
}

.tile-icon.tone-cyan {
  background: rgba(34, 211, 238, 0.1);
  color: #22d3ee;
}

.tile-icon.tone-violet {
  background: rgba(124, 140, 248, 0.12);
  color: #9da8fa;
}

.tile-icon.tone-green {
  background: rgba(12, 163, 12, 0.14);
  color: #34c759;
}

.tile-icon.tone-amber {
  background: rgba(250, 178, 25, 0.12);
  color: #fab219;
}

.tile-icon.tone-rose {
  background: rgba(208, 59, 59, 0.14);
  color: #e66767;
}

.tile-label {
  font-size: 12.5px;
  color: var(--text-2);
  margin-bottom: 2px;
}

.tile-value {
  font-size: 26px;
  font-weight: 600;
  line-height: 1.1;
  color: var(--text-1);
}

.tile-unit {
  margin-left: 4px;
  font-size: 13px;
  font-weight: 400;
  color: var(--text-3);
}
</style>
