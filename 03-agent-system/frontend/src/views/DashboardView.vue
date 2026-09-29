<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ChatDotRound,
  Collection,
  Connection,
  Cpu,
  DataAnalysis,
  DocumentCopy,
  MagicStick,
  Messages,
  Odometer,
  Tickets,
} from '@element-plus/icons-vue'
import api from '../api'
import StatTile from '../components/StatTile.vue'
import { store } from '../store/app'

const router = useRouter()
const loadingSample = ref(false)

const modules = [
  {
    key: 'A',
    name: 'app_core · 框架底座',
    desc: '配置 / 日志 / 强类型模型 / safe_call 重试降级 / LLM 客户端',
    icon: Cpu,
    to: '',
  },
  {
    key: 'B',
    name: 'data_pipeline · 数据管道',
    desc: '清洗 → 去重 → PII 脱敏，产出 MaskReport',
    icon: DataAnalysis,
    to: '/pipeline',
  },
  {
    key: 'C',
    name: 'retrieval · 混合检索',
    desc: 'FTS5 全文 + 向量双路召回，加权融合排序',
    icon: Collection,
    to: '/knowledge',
  },
  {
    key: 'D',
    name: 'pre_sale · 售前咨询 Agent',
    desc: 'ReAct 状态机：think → act → respond，失败降级',
    icon: ChatDotRound,
    to: '/chat',
  },
  {
    key: 'E',
    name: 'content · 内容生成 Agent',
    desc: 'LangGraph 三阶段工作流，Checkpointer 断点续跑',
    icon: MagicStick,
    to: '/content',
  },
  {
    key: 'F',
    name: 'frontend · 可视化前端',
    desc: 'Vue 3 + FastAPI，会话隔离（G-4）',
    icon: Odometer,
    to: '',
  },
]

const stats = computed(() => store.stats || {})
const health = computed(() => store.health || {})
const embedding = computed(() => health.value.embedding || null)

const embeddingName = computed(() => {
  const e = embedding.value
  if (!e) return '—'
  const names = { local: '本地模型', api: 'API', hash: '特征哈希' }
  const base = names[e.mode] || e.mode
  return e.fallback ? `${base} · 已降级` : base
})

const embeddingTagType = computed(() => {
  const e = embedding.value
  if (!e) return 'info'
  if (e.fallback) return 'warning'
  return { local: 'success', api: 'success', hash: 'info' }[e.mode] || 'info'
})

async function loadSample() {
  loadingSample.value = true
  try {
    const res = await api.ingestSample()
    await Promise.all([
      store.refreshKnowledge(),
      store.refreshStats(),
      store.refreshProducts(),
    ])
    ElMessage.success(`已入库 4 篇文档,共 ${res.total_chunks} 个切片`)
  } finally {
    loadingSample.value = false
  }
}
</script>

<template>
  <div class="page dashboard">
    <!-- 欢迎横幅 -->
    <section class="hero card">
      <div class="hero-body">
        <div class="hero-tag">PRE-SALES AGENT SYSTEM</div>
        <h2>智能 AI Agent 售前服务系统</h2>
        <p>
          数据脱敏管道 → 混合检索 → 售前咨询 Agent → 内容生成 Agent → 可视化前端,
          覆盖 FR-01 ~ FR-07 全部功能需求。
        </p>
      </div>
      <div class="hero-actions">
        <el-button type="primary" size="large" :icon="ChatDotRound" @click="router.push('/chat')">
          开始咨询
        </el-button>
        <el-button size="large" :icon="DocumentCopy" :loading="loadingSample" @click="loadSample">
          载入示例知识库
        </el-button>
      </div>
    </section>

    <!-- 关键指标 -->
    <section class="kpi-row">
      <StatTile label="知识文档" :value="stats.total_docs ?? '—'" unit="篇" icon="Collection" tone="cyan" />
      <StatTile label="知识切片" :value="stats.total_chunks ?? '—'" unit="个" icon="Tickets" tone="blue" />
      <StatTile label="商品数量" :value="stats.total_products ?? '—'" unit="件" icon="Goods" tone="rose" />
      <StatTile label="咨询会话" :value="stats.total_sessions ?? '—'" unit="个" icon="Connection" tone="violet" />
      <StatTile label="会话消息" :value="stats.total_messages ?? '—'" unit="条" icon="Messages" tone="green" />
      <StatTile label="生成任务" :value="stats.total_tasks ?? '—'" unit="次" icon="MagicStick" tone="amber" />
    </section>

    <!-- 六大模块 -->
    <section class="card card-pad modules-card">
      <h3 class="card-title">六大模块 · 运行状态</h3>
      <p class="card-desc">架构依赖方向 F → D/E/B/C → A,无环依赖;点击卡片跳转对应功能</p>
      <div class="modules-grid">
        <component
          :is="m.to ? 'router-link' : 'div'"
          v-for="m in modules"
          :key="m.key"
          :to="m.to || undefined"
          class="module-item"
          :class="{ linked: !!m.to }"
        >
          <div class="module-badge">{{ m.key }}</div>
          <div class="module-info">
            <div class="module-name">{{ m.name }}</div>
            <div class="module-desc">{{ m.desc }}</div>
          </div>
          <span class="module-status"><span class="ok-dot" />运行中</span>
        </component>
      </div>
    </section>

    <!-- 运行环境 -->
    <section class="card card-pad env-card">
      <h3 class="card-title">运行环境</h3>
      <p class="card-desc">配置优先级:环境变量 &gt; .env &gt; config.yaml &gt; 默认值</p>
      <div class="env-grid">
        <div class="env-item">
          <div class="env-label">LLM 模式</div>
          <div class="env-value">
            <el-tag :type="health.llm_mode === 'real' ? 'success' : 'warning'" effect="dark" size="small">
              {{ health.llm_mode === 'real' ? '真实模型' : '离线 Mock' }}
            </el-tag>
          </div>
        </div>
        <div class="env-item">
          <div class="env-label">模型</div>
          <div class="env-value mono">{{ health.llm_model || '—' }}</div>
        </div>
        <div class="env-item">
          <div class="env-label">Embedding</div>
          <div class="env-value">
            <el-tag :type="embeddingTagType" effect="dark" size="small">{{ embeddingName }}</el-tag>
          </div>
        </div>
        <div class="env-item">
          <div class="env-label">向量模型</div>
          <div class="env-value mono">
            {{ embedding && embedding.mode !== 'hash' ? embedding.model || '—' : '—' }}
          </div>
        </div>
        <div class="env-item">
          <div class="env-label">检索 Top-K</div>
          <div class="env-value mono">{{ health.retrieval?.top_k ?? '—' }}</div>
        </div>
        <div class="env-item">
          <div class="env-label">融合权重 FTS / 向量</div>
          <div class="env-value mono">
            {{ health.retrieval ? `${health.retrieval.fts_weight} / ${health.retrieval.vector_weight}` : '—' }}
          </div>
        </div>
        <div class="env-item">
          <div class="env-label">切片窗口</div>
          <div class="env-value mono">
            {{ health.retrieval ? `${health.retrieval.chunk_size} 字符` : '—' }}
          </div>
        </div>
        <div class="env-item">
          <div class="env-label">向量后端</div>
          <div class="env-value mono">ChromaDB · 本地持久化</div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.dashboard {
  max-width: 1280px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* ---------- 横幅 ---------- */
.hero {
  position: relative;
  overflow: hidden;
  padding: 30px 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
}

.hero::before {
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(560px 240px at 88% -40%, rgba(124, 140, 248, 0.16), transparent 65%),
    radial-gradient(480px 220px at 0% 120%, rgba(34, 211, 238, 0.1), transparent 60%);
  pointer-events: none;
}

.hero-body {
  position: relative;
  max-width: 640px;
}

.hero-tag {
  display: inline-block;
  font-size: 11px;
  letter-spacing: 2.5px;
  color: #22d3ee;
  font-family: var(--font-mono);
  margin-bottom: 10px;
}

.hero h2 {
  margin: 0 0 10px;
  font-size: 26px;
  font-weight: 700;
  background: linear-gradient(100deg, #e6edf7 30%, #9db9ff 75%, #22d3ee);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.hero p {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.8;
  color: var(--text-2);
}

.hero-actions {
  position: relative;
  display: flex;
  gap: 12px;
  flex: none;
}

/* ---------- KPI ---------- */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 14px;
}

/* ---------- 模块 ---------- */
.modules-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.module-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid var(--border-hairline);
  border-radius: 10px;
  background: var(--bg-inset);
  text-decoration: none;
  color: inherit;
  transition: border-color 0.15s ease, transform 0.15s ease;
}

.module-item.linked {
  cursor: pointer;
}

.module-item.linked:hover {
  border-color: rgba(34, 211, 238, 0.45);
  transform: translateY(-2px);
}

.module-badge {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: var(--grad-accent);
  color: #071022;
  font-weight: 800;
  font-size: 14px;
  flex: none;
}

.module-name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-1);
}

.module-desc {
  font-size: 12px;
  color: var(--text-3);
  margin-top: 3px;
  line-height: 1.6;
}

.module-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
  font-size: 11.5px;
  color: #34c759;
  flex: none;
  padding-top: 2px;
}

.ok-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #34c759;
  box-shadow: 0 0 6px rgba(52, 199, 89, 0.7);
}

/* ---------- 环境 ---------- */
.env-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.env-item {
  padding: 12px 14px;
  border: 1px solid var(--border-hairline);
  border-radius: 10px;
  background: var(--bg-inset);
}

.env-label {
  font-size: 12px;
  color: var(--text-3);
  margin-bottom: 6px;
}

.env-value {
  font-size: 14px;
  color: var(--text-1);
}

@media (max-width: 1100px) {
  .kpi-row {
    grid-template-columns: repeat(3, 1fr);
  }

  .modules-grid,
  .env-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
