<script setup>
import { useRoute } from 'vue-router'
import {
  ChatDotRound,
  Collection,
  DataAnalysis,
  MagicStick,
  Monitor,
} from '@element-plus/icons-vue'
import SessionPicker from './components/SessionPicker.vue'
import { store } from './store/app'

const route = useRoute()

const nav = [
  { to: '/', label: '系统总览', desc: '运行状态与指标', icon: Monitor },
  { to: '/chat', label: '智能问答', desc: '售前咨询 Agent', icon: ChatDotRound },
  { to: '/knowledge', label: '知识入库', desc: '文档与检索验证', icon: Collection },
  { to: '/content', label: '内容生成', desc: '选题·文案·脚本', icon: MagicStick },
  { to: '/pipeline', label: '数据管道', desc: '清洗·去重·脱敏', icon: DataAnalysis },
]
</script>

<template>
  <div class="shell">
    <!-- ============ 侧边导航 ============ -->
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">AI</div>
        <div class="brand-text">
          <div class="brand-name">智能 AI Agent</div>
          <div class="brand-sub">售前服务系统</div>
        </div>
      </div>

      <nav class="nav">
        <router-link
          v-for="item in nav"
          :key="item.to"
          :to="item.to"
          class="nav-item"
          :class="{ active: route.path === item.to }"
        >
          <el-icon class="nav-icon" :size="17"><component :is="item.icon" /></el-icon>
          <div class="nav-text">
            <div class="nav-label">{{ item.label }}</div>
            <div class="nav-desc">{{ item.desc }}</div>
          </div>
        </router-link>
      </nav>

      <div class="sidebar-foot">
        <div class="llm-badge" :class="store.health?.llm_mode">
          <span class="dot" />
          <span class="llm-text">
            {{
              store.health
                ? store.health.llm_mode === 'real'
                  ? `真实模型 · ${store.health.llm_model}`
                  : '离线演示模式'
                : '连接中…'
            }}
          </span>
        </div>
        <div class="ver">v1.0 · 六模块架构 A–F</div>
      </div>
    </aside>

    <!-- ============ 主区域 ============ -->
    <div class="main">
      <header class="topbar">
        <div class="page-title">
          <h1>{{ route.meta.title }}</h1>
          <span class="page-sub">{{ route.meta.subtitle }}</span>
        </div>
        <SessionPicker />
      </header>

      <main v-loading="!store.ready" class="content" element-loading-background="rgba(10,15,30,.6)">
        <router-view v-slot="{ Component }">
          <transition name="fade-slide" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  height: 100%;
  overflow: hidden;
}

/* ---------- 侧栏 ---------- */
.sidebar {
  display: flex;
  flex-direction: column;
  width: 232px;
  flex: none;
  padding: 18px 14px;
  background: rgba(13, 21, 38, 0.72);
  border-right: 1px solid var(--border-hairline);
  backdrop-filter: blur(10px);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 8px 18px;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 11px;
  background: var(--grad-accent);
  color: #071022;
  font-weight: 800;
  font-size: 15px;
  letter-spacing: 0.5px;
  box-shadow: 0 4px 16px rgba(34, 211, 238, 0.25);
}

.brand-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-1);
}

.brand-sub {
  font-size: 12px;
  color: var(--text-3);
  margin-top: 1px;
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  border-left: 3px solid transparent;
  color: var(--text-2);
  text-decoration: none;
  transition: background 0.15s ease, color 0.15s ease;
}

.nav-item:hover {
  background: rgba(148, 163, 184, 0.06);
  color: var(--text-1);
}

.nav-item.active {
  background: linear-gradient(90deg, rgba(34, 211, 238, 0.1), rgba(124, 140, 248, 0.06));
  border-left-color: #22d3ee;
  color: var(--text-1);
}

.nav-item.active .nav-icon {
  color: #22d3ee;
}

.nav-icon {
  flex: none;
  color: var(--text-3);
}

.nav-label {
  font-size: 14px;
  font-weight: 500;
  line-height: 1.2;
}

.nav-desc {
  font-size: 11px;
  color: var(--text-3);
  margin-top: 1px;
}

.sidebar-foot {
  padding: 12px 8px 0;
  border-top: 1px solid var(--border-hairline);
}

.llm-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  background: var(--bg-inset);
  border: 1px solid var(--border-hairline);
  font-size: 12px;
  color: var(--text-2);
}

.llm-badge .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-3);
  flex: none;
}

.llm-badge.real .dot {
  background: #34c759;
  box-shadow: 0 0 6px rgba(52, 199, 89, 0.8);
}

.llm-badge.mock .dot {
  background: #fab219;
  box-shadow: 0 0 6px rgba(250, 178, 25, 0.7);
}

.llm-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ver {
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-3);
  text-align: center;
}

/* ---------- 主区 ---------- */
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 14px 28px;
  border-bottom: 1px solid var(--border-hairline);
  background: rgba(10, 15, 30, 0.6);
  backdrop-filter: blur(10px);
}

.page-title {
  display: flex;
  align-items: baseline;
  gap: 12px;
  min-width: 0;
}

.page-title h1 {
  margin: 0;
  font-size: 19px;
  font-weight: 700;
  letter-spacing: 0.3px;
}

.page-sub {
  font-size: 12.5px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.content {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px 40px;
}

:deep(.el-loading-mask) {
  backdrop-filter: blur(2px);
}
</style>
