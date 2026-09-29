<script setup>
import { nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Promotion } from '@element-plus/icons-vue'
import api from '../api'
import SourceChunkCard from '../components/SourceChunkCard.vue'
import TraceSteps from '../components/TraceSteps.vue'
import { store } from '../store/app'

const messages = ref([])
const input = ref('')
const pending = ref(false)
const msgBox = ref(null)

const SUGGESTIONS = [
  '智能门锁 S1 的价格和参数？',
  '智能音箱 M2 有库存吗？',
  '你们的售后政策是什么？',
]

async function loadHistory() {
  if (!store.currentSessionId) return
  messages.value = await api.history(store.currentSessionId)
  scrollToBottom()
}

function scrollToBottom() {
  nextTick(() => {
    const box = msgBox.value
    if (box) box.scrollTop = box.scrollHeight
  })
}

async function send(text) {
  const query = (text ?? input.value).trim()
  if (!query || pending.value || !store.currentSessionId) return
  input.value = ''
  messages.value.push({ role: 'user', content: query, _key: `u-${Date.now()}` })
  pending.value = true
  scrollToBottom()
  try {
    const ans = await api.ask({ session_id: store.currentSessionId, query })
    messages.value.push({
      role: 'assistant',
      content: ans.answer,
      source_chunks: ans.source_chunks || [],
      trace: ans.trace || [],
      degraded: ans.degraded,
      reason: ans.reason,
      _key: `a-${Date.now()}`,
    })
  } finally {
    pending.value = false
    scrollToBottom()
    store.refreshStats()
  }
}

function useSuggestion(q) {
  send(q)
}

watch(
  () => store.currentSessionId,
  () => loadHistory(),
  { immediate: true },
)
</script>

<template>
  <div class="chat-page">
    <div class="chat-shell card">
      <!-- 消息区 -->
      <div ref="msgBox" class="messages">
        <!-- 空状态引导 -->
        <div v-if="!messages.length && !pending" class="empty">
          <div class="empty-icon">
            <el-icon :size="30"><Promotion /></el-icon>
          </div>
          <div class="empty-title">向售前咨询 Agent 提问</div>
          <p class="empty-desc">
            ReAct 状态机:思考 → 调用工具(知识检索 / 商品信息 / 库存) → 生成回答;
            回答附引用来源与推理轨迹。
          </p>
          <div class="suggestions">
            <el-button v-for="q in SUGGESTIONS" :key="q" round @click="useSuggestion(q)">
              {{ q }}
            </el-button>
          </div>
          <el-alert
            v-if="!store.knowledge.total_docs"
            class="empty-warn"
            type="info"
            :closable="false"
            show-icon
          >
            知识库为空,建议先到「知识入库」载入示例知识库,否则知识类问题无法引用文档。
          </el-alert>
        </div>

        <template v-for="m in messages" :key="m._key || m.message_id">
          <!-- 用户消息 -->
          <div v-if="m.role === 'user'" class="msg user">
            <div class="bubble user-bubble">{{ m.content }}</div>
          </div>

          <!-- 助手消息 -->
          <div v-else class="msg assistant">
            <div class="avatar">AI</div>
            <div class="assistant-body">
              <el-alert
                v-if="m.degraded"
                class="degraded"
                type="warning"
                :closable="false"
                show-icon
                :title="`本次回答已降级：${m.reason || '模型暂不可用'}`"
              />
              <div class="bubble assistant-bubble">{{ m.content }}</div>
              <TraceSteps v-if="m.trace?.length" :trace="m.trace" class="msg-trace" />
              <el-collapse v-if="m.source_chunks?.length" class="sources">
                <el-collapse-item :title="`引用来源 · ${m.source_chunks.length} 条`">
                  <SourceChunkCard
                    v-for="(c, i) in m.source_chunks"
                    :key="i"
                    :chunk="c"
                  />
                </el-collapse-item>
              </el-collapse>
            </div>
          </div>
        </template>

        <!-- 思考中 -->
        <div v-if="pending" class="msg assistant">
          <div class="avatar">AI</div>
          <div class="bubble assistant-bubble thinking">
            <span class="tdot" /><span class="tdot" /><span class="tdot" />
            <span class="thinking-label">Agent 推理中…</span>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="composer">
        <el-input
          v-model="input"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 4 }"
          resize="none"
          placeholder="输入售前咨询问题… (Enter 发送,Shift + Enter 换行)"
          @keydown.enter.exact.prevent="send()"
        />
        <el-button
          type="primary"
          class="send-btn"
          :loading="pending"
          :disabled="!input.trim()"
          @click="send()"
        >
          发送
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-page {
  height: 100%;
  display: flex;
}

.chat-shell {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

/* ---------- 消息区 ---------- */
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.msg {
  display: flex;
  gap: 12px;
  max-width: 86%;
  animation: pop-in 0.22s ease;
}

.msg.user {
  align-self: flex-end;
}

.msg.assistant {
  align-self: flex-start;
}

@keyframes pop-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }

  to {
    opacity: 1;
    transform: none;
  }
}

.bubble {
  padding: 10px 16px;
  border-radius: 14px;
  font-size: 14px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}

.user-bubble {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: #f0f6ff;
  border-bottom-right-radius: 4px;
}

.assistant-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.assistant-bubble {
  background: var(--bg-raised);
  border: 1px solid var(--border-hairline);
  color: var(--text-1);
  border-bottom-left-radius: 4px;
}

.avatar {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: var(--grad-accent);
  color: #071022;
  font-size: 12px;
  font-weight: 800;
  flex: none;
}

.degraded {
  border-radius: 10px;
}

.msg-trace {
  padding-left: 2px;
}

.sources {
  border: none;
  max-width: 640px;
}

.sources :deep(.el-collapse-item__header) {
  font-size: 12.5px;
  color: var(--text-3);
  height: 34px;
  line-height: 34px;
  background: transparent;
}

/* ---------- 思考中 ---------- */
.thinking {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 14px 18px;
}

.tdot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-3);
  animation: blink 1.2s infinite ease-in-out;
}

.tdot:nth-child(2) {
  animation-delay: 0.2s;
}

.tdot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes blink {
  0%,
  80%,
  100% {
    opacity: 0.25;
  }

  40% {
    opacity: 1;
  }
}

.thinking-label {
  margin-left: 8px;
  font-size: 12.5px;
  color: var(--text-3);
}

/* ---------- 空状态 ---------- */
.empty {
  margin: auto;
  max-width: 520px;
  text-align: center;
  padding: 30px 0;
}

.empty-icon {
  display: grid;
  place-items: center;
  width: 64px;
  height: 64px;
  margin: 0 auto 16px;
  border-radius: 18px;
  background: rgba(34, 211, 238, 0.08);
  border: 1px solid rgba(34, 211, 238, 0.25);
  color: #22d3ee;
}

.empty-title {
  font-size: 17px;
  font-weight: 600;
  margin-bottom: 8px;
}

.empty-desc {
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-2);
  margin: 0 0 20px;
}

.suggestions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
  margin-bottom: 18px;
}

.empty-warn {
  border-radius: 10px;
}

/* ---------- 输入区 ---------- */
.composer {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  padding: 14px 18px;
  border-top: 1px solid var(--border-hairline);
  background: var(--bg-inset);
}

.composer :deep(.el-textarea__inner) {
  background: var(--bg-surface);
  border-radius: 10px;
  padding: 10px 14px;
  line-height: 1.6;
}

.send-btn {
  height: 42px;
  padding: 0 22px;
  border-radius: 10px;
}
</style>
