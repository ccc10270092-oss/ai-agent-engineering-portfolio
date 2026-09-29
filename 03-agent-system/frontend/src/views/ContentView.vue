<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CircleCheckFilled, CircleCloseFilled, CopyDocument, Delete, Edit, Plus, RefreshRight, Setting } from '@element-plus/icons-vue'
import api from '../api'
import { fmtTime, shortId, store } from '../store/app'

const STAGE_META = {
  topic: { title: '选题建议', desc: '面向目标人群的传播主题与角度' },
  copy: { title: '营销文案', desc: '可直接投放的短文案' },
  script: { title: '话术脚本', desc: '客服 / 直播场景的对讲话术' },
}

const form = reactive({ product_id: '', stage: 'all' })
const starting = ref(false)
const current = ref(null)
const resuming = ref(false)
let pollTimer = null

const stages = computed(() => current.value?.stages || [])
const failedStages = computed(() => stages.value.filter((s) => s.status === 'failed'))

onMounted(async () => {
  // 商品目录可能刚被知识页入库登记 / 管理操作更新,进入本页刷新
  await Promise.all([store.refreshTasks(), store.refreshProducts()])
  // 恢复最近一个未完成任务的关注
  const running = store.tasks.find((t) => t.status === 'running')
  if (running) watchTask(running.task_id, false)
})

onBeforeUnmount(stopPoll)

async function generate() {
  if (!form.product_id) {
    ElMessage.warning('请先选择产品')
    return
  }
  const product = store.products.find((p) => p.product_id === form.product_id)
  starting.value = true
  try {
    const task = await api.generate({
      session_id: store.currentSessionId,
      product_id: form.product_id,
      name: product?.name || form.product_id,
      stage: form.stage,
    })
    current.value = task
    watchTask(task.task_id)
    store.refreshTasks()
  } finally {
    starting.value = false
  }
}

async function resume() {
  if (!current.value) return
  resuming.value = true
  try {
    const task = await api.resumeTask(current.value.task_id)
    current.value = task
    watchTask(task.task_id)
  } finally {
    resuming.value = false
  }
}

function watchTask(taskId, notify = true) {
  stopPoll()
  pollTimer = setInterval(async () => {
    try {
      const task = await api.task(taskId)
      current.value = task
      if (task.status !== 'running') {
        stopPoll()
        store.refreshTasks()
        store.refreshStats()
        if (notify) {
          if (task.error) ElMessage.error(`生成失败:${task.error}`)
          else if (failedStages.value.length) ElMessage.warning('部分阶段失败,可点击「续跑失败阶段」重试')
          else ElMessage.success('内容生成完成')
        }
      }
    } catch {
      stopPoll()
    }
  }, 1500)
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function openTask(taskId) {
  current.value = await api.task(taskId)
  if (current.value.status === 'running') watchTask(taskId, false)
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败,请手动选择复制')
  }
}

// ---------- 商品目录管理 ----------
const manageOpen = ref(false)
const formOpen = ref(false)
const formMode = ref('create') // create | edit
const editingId = ref('')
const saving = ref(false)
const productForm = reactive({ name: '', category: '', price: null, stock: 100, specs: '' })

const ORIGIN_META = {
  seed: { label: '内置', type: 'info' },
  doc: { label: '知识库文档', type: 'success' },
  manual: { label: '手动', type: 'warning' },
}

function openCreate() {
  formMode.value = 'create'
  editingId.value = ''
  Object.assign(productForm, { name: '', category: '', price: null, stock: 100, specs: '' })
  formOpen.value = true
}

function openEdit(p) {
  formMode.value = 'edit'
  editingId.value = p.product_id
  Object.assign(productForm, {
    name: p.name,
    category: p.category,
    price: p.price,
    stock: p.stock,
    specs: p.specs,
  })
  formOpen.value = true
}

async function saveProduct() {
  if (!productForm.name.trim()) {
    ElMessage.warning('请填写商品名称')
    return
  }
  saving.value = true
  try {
    const fields = {
      name: productForm.name.trim(),
      category: productForm.category.trim(),
      price: productForm.price,
      stock: productForm.stock,
      specs: productForm.specs.trim(),
    }
    if (formMode.value === 'create') {
      await api.createProduct(fields)
      ElMessage.success(`商品「${fields.name}」已创建`)
    } else {
      await api.updateProduct(editingId.value, fields)
      ElMessage.success(`商品「${fields.name}」已更新`)
    }
    formOpen.value = false
    await store.refreshProducts()
  } finally {
    saving.value = false
  }
}

async function removeProduct(p) {
  try {
    await ElMessageBox.confirm(`确定删除「${p.name}」?仅移除商品目录条目,关联的知识文档不受影响。`, '删除商品', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  await api.deleteProduct(p.product_id)
  ElMessage.success(`已删除「${p.name}」`)
  if (form.product_id === p.product_id) form.product_id = '' // 选中的商品被删,清空选择
  await store.refreshProducts()
}

const stageList = computed(() => {
  const list = current.value?.stages || []
  return list.map((s) => ({
    ...s,
    ...STAGE_META[s.stage],
  }))
})
</script>

<template>
  <div class="page content">
    <!-- 生成配置 -->
    <section class="card card-pad">
      <h3 class="card-title">生成配置</h3>
      <p class="card-desc">三阶段串行执行,每阶段独立调用 LLM;失败阶段自动跳过,可断点续跑</p>

      <div class="cfg-row-head">
        <div class="cfg-label">选择产品</div>
        <el-button size="small" :icon="Setting" @click="manageOpen = true">管理商品</el-button>
      </div>
      <div class="products">
        <div
          v-for="p in store.products"
          :key="p.product_id"
          class="product-card"
          :class="{ selected: form.product_id === p.product_id, 'out-stock': !p.available }"
          @click="form.product_id = p.product_id"
        >
          <div class="p-head">
            <span class="p-name">{{ p.name }}</span>
            <el-tag
              size="small"
              effect="dark"
              :type="p.available ? 'success' : 'danger'"
            >
              {{ p.available ? `有货 ${p.stock} 件` : '缺货' }}
            </el-tag>
          </div>
          <div class="p-specs">{{ p.specs }}</div>
          <div class="p-foot">
            <span class="mono p-id">{{ p.product_id }}</span>
            <span class="p-right">
              <span v-if="p.price != null" class="p-price">¥{{ p.price }}</span>
              <span class="p-cat">{{ p.category }}</span>
            </span>
          </div>
        </div>
      </div>
      <div v-if="!store.products.length" class="products-empty">
        暂无商品;入库产品文档会自动登记,也可
        <el-button size="small" text type="primary" @click="manageOpen = true">手动新增</el-button>
      </div>

      <div class="cfg-label">生成阶段</div>
      <div class="cfg-row">
        <el-radio-group v-model="form.stage">
          <el-radio-button value="all">全部三阶段</el-radio-button>
          <el-radio-button value="topic">仅选题</el-radio-button>
          <el-radio-button value="copy">仅文案</el-radio-button>
          <el-radio-button value="script">仅脚本</el-radio-button>
        </el-radio-group>
        <el-button
          type="primary"
          size="large"
          :loading="starting || current?.status === 'running'"
          :disabled="!form.product_id"
          @click="generate"
        >
          {{ current?.status === 'running' ? '生成中…' : '开始生成' }}
        </el-button>
      </div>
    </section>

    <!-- 当前任务 -->
    <section v-if="current" class="card card-pad task-card">
      <div class="task-head">
        <h3 class="card-title">生成结果</h3>
        <div class="task-meta">
          <span class="mono task-id">{{ shortId(current.task_id) }}…</span>
          <el-tag
            size="small"
            effect="dark"
            :type="current.status === 'done' ? 'success' : current.status === 'failed' ? 'danger' : 'warning'"
          >
            {{ current.status === 'running' ? '进行中' : current.status === 'done' ? '已完成' : '失败' }}
          </el-tag>
        </div>
      </div>

      <!-- 阶段进度 -->
      <div class="stepper">
        <template v-for="(s, i) in stageList" :key="s.stage">
          <div class="step" :class="s.status">
            <div class="step-dot">
              <el-icon v-if="s.status === 'done'" :size="13"><CircleCheckFilled /></el-icon>
              <el-icon v-else-if="s.status === 'failed'" :size="13"><CircleCloseFilled /></el-icon>
              <span v-else-if="s.status === 'running'" class="spin" />
              <span v-else class="step-num">{{ i + 1 }}</span>
            </div>
            <div class="step-name">{{ s.title }}</div>
            <div class="step-desc">
              {{ s.status === 'running' ? '生成中…' : s.status === 'done' ? '完成' : s.status === 'failed' ? '失败' : '待执行' }}
            </div>
          </div>
          <div v-if="i < stageList.length - 1" class="step-line" :class="{ done: stageList[i].status === 'done' }" />
        </template>
      </div>

      <!-- 参考来源(RAG 接地:商品参数 + 知识库检索片段) -->
      <el-collapse v-if="current.sources?.length" :model-value="['sources']" class="sources-box">
        <el-collapse-item name="sources">
          <template #title>
            <span class="sources-title">参考来源 · {{ current.sources.length }} 条</span>
          </template>
          <div v-for="(s, i) in current.sources" :key="`src-${i}`" class="source-item">
            <div class="source-name">{{ s.title || `知识片段 ${i + 1}` }}</div>
            <div class="source-text">{{ s.text }}</div>
          </div>
        </el-collapse-item>
      </el-collapse>

      <!-- 结果卡片 -->
      <div class="results">
        <div v-for="s in stageList" :key="`r-${s.stage}`" class="result-item" :class="{ failed: s.status === 'failed' }">
          <div class="result-head">
            <div>
              <div class="result-title">{{ s.title }}</div>
              <div class="result-sub">{{ s.desc }}</div>
            </div>
            <div class="result-actions">
              <el-tag v-if="s.status !== 'pending'" size="small" effect="plain" :type="s.status === 'done' ? 'success' : 'danger'">
                {{ s.status === 'done' ? '完成' : s.status === 'failed' ? '失败' : s.status }}
              </el-tag>
              <el-button
                v-if="s.content"
                size="small"
                text
                :icon="CopyDocument"
                @click="copyText(s.content)"
              >
                复制
              </el-button>
            </div>
          </div>
          <pre v-if="s.content" class="result-body">{{ s.content }}</pre>
          <div v-else-if="s.status === 'failed'" class="result-failed">该阶段生成失败(重试耗尽已跳过),可续跑重试</div>
          <div v-else class="result-pending">等待执行…</div>
        </div>
      </div>

      <!-- 续跑 -->
      <div v-if="current.status === 'done' && failedStages.length" class="resume-bar">
        <el-button type="warning" :icon="RefreshRight" :loading="resuming" @click="resume">
          续跑失败阶段({{ failedStages.map((s) => s.stage).join(' / ') }})
        </el-button>
        <span class="resume-hint">Checkpointer 已保存完成阶段,仅重跑失败部分</span>
      </div>
    </section>

    <!-- 历史任务 -->
    <section class="card card-pad">
      <h3 class="card-title">历史任务</h3>
      <p class="card-desc">全部会话的生成记录,点击查看</p>
      <div v-if="!store.tasks.length" class="history-empty">暂无生成任务</div>
      <div class="history-list">
        <button
          v-for="t in store.tasks"
          :key="t.task_id"
          class="history-item"
          :class="{ active: current?.task_id === t.task_id }"
          @click="openTask(t.task_id)"
        >
          <span class="h-dot" :class="t.status" />
          <span class="h-name">{{ t.product?.name || t.product?.product_id }}</span>
          <span class="h-stages mono">
            {{ t.stages.filter((s) => s.status === 'done').length }}/{{ t.stages.filter((s) => s.stage).length }} 阶段
          </span>
          <span class="h-time">{{ fmtTime(t.created_at) }}</span>
        </button>
      </div>
    </section>

    <!-- 商品目录管理 -->
    <el-dialog v-model="manageOpen" title="管理商品目录" width="760px" :close-on-click-modal="false">
      <div class="mg-toolbar">
        <span class="mg-hint">产品文档入库时自动登记商品;手动编辑过的商品不再被文档覆盖</span>
        <el-button type="primary" size="small" :icon="Plus" @click="openCreate">新增商品</el-button>
      </div>
      <el-table :data="store.products" size="small">
        <el-table-column label="编号" width="72">
          <template #default="{ row }">
            <span class="mono">{{ row.product_id }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="150" show-overflow-tooltip />
        <el-table-column label="分类" width="92">
          <template #default="{ row }">{{ row.category || '—' }}</template>
        </el-table-column>
        <el-table-column label="价格" width="92" align="right">
          <template #default="{ row }">{{ row.price != null ? `¥${row.price}` : '—' }}</template>
        </el-table-column>
        <el-table-column prop="stock" label="库存" width="68" align="right" />
        <el-table-column label="来源" width="104">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="ORIGIN_META[row.origin]?.type || 'info'">
              {{ ORIGIN_META[row.origin]?.label || row.origin }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="112" align="center">
          <template #default="{ row }">
            <el-button size="small" text type="primary" :icon="Edit" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" text type="danger" :icon="Delete" @click="removeProduct(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 新增 / 编辑商品表单(嵌套弹窗) -->
    <el-dialog
      v-model="formOpen"
      :title="formMode === 'create' ? '新增商品' : `编辑商品 ${editingId}`"
      width="480px"
      :close-on-click-modal="false"
      append-to-body
    >
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="商品名称" required>
          <el-input v-model="productForm.name" placeholder="如:智能净水器 W1" maxlength="128" />
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="分类">
            <el-input v-model="productForm.category" placeholder="如:清洁家电" maxlength="64" />
          </el-form-item>
          <el-form-item label="价格(元,可选)">
            <el-input-number v-model="productForm.price" :min="0" :precision="2" class="w-full" />
          </el-form-item>
        </div>
        <el-form-item label="库存(件)">
          <el-input-number v-model="productForm.stock" :min="0" :step="10" class="w-full" />
        </el-form-item>
        <el-form-item label="参数 / 规格">
          <el-input
            v-model="productForm.specs"
            type="textarea"
            :rows="3"
            placeholder="如:大通量 RO 膜,五级精滤,价格 1599 元"
            maxlength="2000"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveProduct">
          {{ formMode === 'create' ? '创建' : '保存' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.content {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.cfg-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-2);
  margin: 16px 0 10px;
}

.cfg-row-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.cfg-row-head .cfg-label {
  margin: 16px 0 10px;
}

/* ---------- 产品卡片 ---------- */
.products {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.products-empty {
  padding: 26px 0;
  text-align: center;
  font-size: 13px;
  color: var(--text-3);
  border: 1px dashed var(--border-hairline);
  border-radius: 10px;
}

/* ---------- 产品卡片 ---------- */
.products {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.product-card {
  padding: 14px 16px;
  border: 1px solid var(--border-hairline);
  border-radius: 10px;
  background: var(--bg-inset);
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.product-card:hover {
  border-color: var(--border-strong);
}

.product-card.selected {
  border-color: #22d3ee;
  background: rgba(34, 211, 238, 0.06);
  box-shadow: 0 0 0 1px rgba(34, 211, 238, 0.35);
}

/* 缺货卡:弱化 + 红边提示(选中态仍以青色高亮) */
.product-card.out-stock {
  opacity: 0.62;
  border-color: rgba(208, 59, 59, 0.4);
}

.product-card.out-stock.selected {
  border-color: #22d3ee;
}

.p-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.p-name {
  font-size: 14.5px;
  font-weight: 600;
}

.p-specs {
  font-size: 12px;
  line-height: 1.65;
  color: var(--text-2);
  min-height: 40px;
}

.p-foot {
  display: flex;
  justify-content: space-between;
  margin-top: 10px;
  font-size: 11.5px;
  color: var(--text-3);
}

.p-id {
  color: #79bbff;
}

.p-right {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.p-price {
  color: #fab219;
  font-weight: 600;
  font-size: 12.5px;
}

/* ---------- 商品管理弹窗 ---------- */
.mg-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.mg-hint {
  font-size: 12px;
  color: var(--text-3);
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 14px;
}

.w-full {
  width: 100%;
}

.cfg-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

/* ---------- 任务 ---------- */
.task-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.task-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}

.task-id {
  font-size: 12px;
  color: var(--text-3);
}

.stepper {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin: 18px 0 22px;
}

.step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 7px;
  width: 92px;
  flex: none;
}

.step-dot {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 1px solid var(--border-strong);
  background: var(--bg-inset);
  color: var(--text-3);
  font-size: 12px;
  font-family: var(--font-mono);
}

.step.done .step-dot {
  border-color: rgba(52, 199, 89, 0.5);
  background: rgba(52, 199, 89, 0.12);
  color: #34c759;
}

.step.failed .step-dot {
  border-color: rgba(208, 59, 59, 0.5);
  background: rgba(208, 59, 59, 0.12);
  color: #e66767;
}

.step.running .step-dot {
  border-color: rgba(250, 178, 25, 0.5);
  color: #fab219;
}

.spin {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(250, 178, 25, 0.3);
  border-top-color: #fab219;
  border-radius: 50%;
  animation: rotate 0.8s linear infinite;
}

@keyframes rotate {
  to {
    transform: rotate(360deg);
  }
}

.step-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
}

.step.done .step-name {
  color: #34c759;
}

.step.failed .step-name {
  color: #e66767;
}

.step-desc {
  font-size: 11px;
  color: var(--text-3);
}

.step-line {
  flex: 1;
  height: 2px;
  margin-top: 14px;
  border-radius: 1px;
  background: var(--border-hairline);
  min-width: 20px;
}

.step-line.done {
  background: linear-gradient(90deg, rgba(52, 199, 89, 0.6), rgba(52, 199, 89, 0.25));
}

/* ---------- 结果 ---------- */
.sources-box {
  margin: 0 0 18px;
  border: 1px solid var(--border-hairline);
  border-radius: 10px;
  background: var(--bg-inset);
  --el-collapse-border-color: transparent;
  --el-collapse-header-bg-color: transparent;
  --el-collapse-content-bg-color: transparent;
}

.sources-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-2);
}

.source-item {
  padding: 10px 14px;
  border-radius: 8px;
  background: var(--bg-page);
  border: 1px solid var(--border-hairline);
}

.source-item + .source-item {
  margin-top: 8px;
}

.source-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-1);
}

.source-text {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-2);
}

.results {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.result-item {
  border: 1px solid var(--border-hairline);
  border-radius: 10px;
  background: var(--bg-inset);
  padding: 16px 18px;
}

.result-item.failed {
  border-color: rgba(208, 59, 59, 0.3);
}

.result-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.result-title {
  font-size: 14px;
  font-weight: 600;
}

.result-sub {
  font-size: 11.5px;
  color: var(--text-3);
  margin-top: 2px;
}

.result-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
}

.result-body {
  margin: 0;
  padding: 14px 16px;
  border-radius: 8px;
  background: var(--bg-page);
  border: 1px solid var(--border-hairline);
  font-family: var(--font-sans);
  font-size: 13.5px;
  line-height: 1.9;
  color: var(--text-1);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 340px;
  overflow-y: auto;
}

.result-failed {
  padding: 16px;
  border-radius: 8px;
  background: rgba(208, 59, 59, 0.06);
  border: 1px dashed rgba(208, 59, 59, 0.35);
  color: #e66767;
  font-size: 13px;
}

.result-pending {
  padding: 16px;
  color: var(--text-3);
  font-size: 13px;
}

.resume-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 16px;
  padding: 12px 16px;
  border-radius: 10px;
  background: rgba(250, 178, 25, 0.05);
  border: 1px solid rgba(250, 178, 25, 0.25);
}

.resume-hint {
  font-size: 12px;
  color: var(--text-3);
}

/* ---------- 历史 ---------- */
.history-empty {
  padding: 26px 0;
  text-align: center;
  font-size: 13px;
  color: var(--text-3);
  border: 1px dashed var(--border-hairline);
  border-radius: 10px;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 260px;
  overflow-y: auto;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border: 1px solid var(--border-hairline);
  border-radius: 10px;
  background: var(--bg-inset);
  color: var(--text-2);
  font-size: 13px;
  cursor: pointer;
  transition: border-color 0.15s ease;
  text-align: left;
  width: 100%;
}

.history-item:hover {
  border-color: var(--border-strong);
}

.history-item.active {
  border-color: rgba(34, 211, 238, 0.5);
}

.h-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
  background: var(--text-3);
}

.h-dot.done {
  background: #34c759;
}

.h-dot.failed {
  background: #e66767;
}

.h-dot.running {
  background: #fab219;
  animation: blink 1s infinite;
}

@keyframes blink {
  50% {
    opacity: 0.3;
  }
}

.h-name {
  flex: 1;
  color: var(--text-1);
  font-weight: 500;
}

.h-stages {
  font-size: 11.5px;
  color: var(--text-3);
}

.h-time {
  font-size: 11.5px;
  color: var(--text-3);
}

@media (max-width: 1000px) {
  .products {
    grid-template-columns: 1fr;
  }
}
</style>
