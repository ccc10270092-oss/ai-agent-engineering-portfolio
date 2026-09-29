<script setup>
import { Plus } from '@element-plus/icons-vue'
import { fmtTime, shortId, store } from '../store/app'

function onChange(id) {
  store.setCurrent(id)
}

async function onNew() {
  await store.createSession()
}
</script>

<template>
  <div class="session-picker">
    <span class="sp-label">当前会话</span>
    <el-select
      :model-value="store.currentSessionId"
      style="width: 230px"
      filterable
      placeholder="选择会话"
      @change="onChange"
    >
      <el-option
        v-for="s in store.sortedSessions"
        :key="s.session_id"
        :value="s.session_id"
        :label="shortId(s.session_id)"
      >
        <div class="sp-option">
          <span class="mono">{{ shortId(s.session_id) }}…</span>
          <span class="sp-time">{{ fmtTime(s.created_at) }}</span>
        </div>
      </el-option>
    </el-select>
    <el-button :icon="Plus" @click="onNew">新建会话</el-button>
  </div>
</template>

<style scoped>
.session-picker {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sp-label {
  font-size: 12.5px;
  color: var(--text-3);
}

.sp-option {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.sp-option .mono {
  color: var(--text-1);
}

.sp-time {
  font-size: 12px;
  color: var(--text-3);
}
</style>
