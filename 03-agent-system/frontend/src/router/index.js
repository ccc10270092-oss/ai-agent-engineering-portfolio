import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'dashboard',
    component: () => import('../views/DashboardView.vue'),
    meta: { title: '系统总览', subtitle: '六模块运行状态与关键指标' },
  },
  {
    path: '/chat',
    name: 'chat',
    component: () => import('../views/ChatView.vue'),
    meta: { title: '智能问答', subtitle: '售前咨询 Agent · ReAct 推理链路' },
  },
  {
    path: '/knowledge',
    name: 'knowledge',
    component: () => import('../views/KnowledgeView.vue'),
    meta: { title: '知识入库', subtitle: '文档切片 → FTS5 全文 + 向量双路索引' },
  },
  {
    path: '/content',
    name: 'content',
    component: () => import('../views/ContentView.vue'),
    meta: { title: '内容生成', subtitle: '选题 → 文案 → 话术脚本 三阶段工作流' },
  },
  {
    path: '/pipeline',
    name: 'pipeline',
    component: () => import('../views/PipelineView.vue'),
    meta: { title: '数据管道', subtitle: '清洗 → 去重 → PII 脱敏 可视化' },
  },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
