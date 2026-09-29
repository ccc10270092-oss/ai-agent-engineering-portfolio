<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import api from '../api'
import StatTile from '../components/StatTile.vue'
import VChart from '../components/VChart.vue'
import { funnelOption, piiOption } from '../utils/charts'

const tab = ref('sample')
const running = ref(false)
const result = ref(null)
const pasteText = ref('')
const pasting = ref(false)

const sampleRecordsPreview = [
  '6 条内置客服记录:含手机号 / 身份证 / 邮箱三类 PII、1 条重复、1 条空值',
]

async function run(transform) {
  running.value = true
  try {
    result.value = await transform()
  } finally {
    running.value = false
  }
}

function runSample() {
  run(() => api.pipelineSample())
}

function customUpload({ file }) {
  run(() => api.pipelineUpload(file))
}

function beforeUpload(file) {
  const ok = /\.(csv|json|jsonl)$/i.test(file.name || '')
  if (!ok) ElMessage.error('仅支持 .csv / .json / .jsonl 文件')
  return ok
}

async function runPaste() {
  let records
  try {
    records = JSON.parse(pasteText.value)
  } catch {
    ElMessage.error('JSON 解析失败,请检查格式(数组,每条含 content/text 字段)')
    return
  }
  if (!Array.isArray(records) || !records.length) {
    ElMessage.warning('请粘贴至少一条记录(JSON 数组)')
    return
  }
  pasting.value = true
  try {
    await run(() => api.pipelineRun(records))
  } finally {
    pasting.value = false
  }
}

const report = computed(() => result.value?.report || null)
const stats = computed(() => report.value?.stage_stats || {})

const funnelOpt = computed(() => funnelOption(stats.value))
const piiOpt = computed(() => piiOption(report.value?.mask_hits || {}))

/** 脱敏后预览:动态列(取首条记录的键,最多 8 列) */
const previewRows = computed(() => (result.value?.masked || []).slice(0, 20))
const previewCols = computed(() => {
  const first = previewRows.value[0]
  return first ? Object.keys(first).slice(0, 8) : []
})

const piiSamples = computed(() => report.value?.samples || [])
</script>

<template>
  <div class="page pipeline">
    <!-- 数据入口 -->
    <section class="card card-pad">
      <h3 class="card-title">原始数据</h3>
      <p class="card-desc">管道:清洗(空值/无效) → 精确去重 → PII 脱敏(身份证/手机号/邮箱)</p>

      <el-tabs v-model="tab">
        <el-tab-pane label="示例数据" name="sample">
          <div class="tab-body">
            <div class="sample-desc">
              <span class="dot" />{{ sampleRecordsPreview[0] }}
            </div>
            <el-button type="primary" :loading="running && tab === 'sample'" @click="runSample">
              运行示例管道
            </el-button>
          </div>
        </el-tab-pane>

        <el-tab-pane label="上传文件" name="upload">
          <el-upload
            drag
            accept=".csv,.json,.jsonl"
            :show-file-list="false"
            :http-request="customUpload"
            :before-upload="beforeUpload"
          >
            <div class="upload-inner">
              <el-icon :size="40" class="upload-icon"><UploadFilled /></el-icon>
              <div class="upload-text">拖拽文件到此处,或点击上传</div>
              <div class="upload-hint">支持 .csv / .json / .jsonl,上限 5MB / 5000 条</div>
            </div>
          </el-upload>
        </el-tab-pane>

        <el-tab-pane label="粘贴 JSON" name="paste">
          <div class="tab-body paste-body">
            <el-input
              v-model="pasteText"
              type="textarea"
              :rows="5"
              placeholder='[{"content": "我的手机号是 13812345678"}, {"content": "邮箱 a@b.com"}]'
              class="mono"
            />
            <el-button type="primary" :loading="pasting" @click="runPaste">解析并运行</el-button>
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>

    <template v-if="result && report">
      <!-- 指标行 -->
      <section class="kpi-row">
        <StatTile label="输入记录" :value="stats.input ?? 0" unit="条" icon="Files" tone="blue" />
        <StatTile label="清洗丢弃" :value="stats.clean_dropped ?? 0" unit="条" icon="Delete" tone="rose" />
        <StatTile label="重复删除" :value="stats.dedupe_removed ?? 0" unit="条" icon="CopyDocument" tone="amber" />
        <StatTile label="脱敏输出" :value="stats.output ?? 0" unit="条" icon="Finished" tone="green" />
      </section>

      <!-- 图表行 -->
      <section class="charts-row">
        <div class="card card-pad">
          <h3 class="card-title">管道漏斗</h3>
          <p class="card-desc">各阶段存留记录数;悬停查看丢弃明细</p>
          <VChart :option="funnelOpt" height="230px" />
        </div>
        <div class="card card-pad">
          <h3 class="card-title">PII 命中分布</h3>
          <p class="card-desc">三类敏感信息在原始数据中的命中次数</p>
          <VChart :option="piiOpt" height="230px" />
        </div>
      </section>

      <!-- 脱敏对照 -->
      <section class="card card-pad">
        <h3 class="card-title">脱敏对照样本</h3>
        <p class="card-desc">敏感字段脱敏前 → 后对照(最多采样 5 条)</p>
        <el-table v-if="piiSamples.length" :data="piiSamples" size="default">
          <el-table-column prop="field" label="字段" width="140" />
          <el-table-column prop="pii_type" label="PII 类型" width="110">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" type="warning">{{ row.pii_type }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="脱敏前" min-width="220">
            <template #default="{ row }">
              <code class="mono before">{{ row.before }}</code>
            </template>
          </el-table-column>
          <el-table-column label="" width="40" align="center">
            <template #default>→</template>
          </el-table-column>
          <el-table-column label="脱敏后" min-width="220">
            <template #default="{ row }">
              <code class="mono after">{{ row.after }}</code>
            </template>
          </el-table-column>
        </el-table>
        <div v-else class="no-samples">本次数据未命中 PII 字段</div>
      </section>

      <!-- 脱敏后预览 -->
      <section class="card card-pad">
        <h3 class="card-title">脱敏后数据预览</h3>
        <p class="card-desc">共 {{ result.masked_total }} 条,展示前 {{ previewRows.length }} 条</p>
        <el-table v-if="previewRows.length" :data="previewRows" size="small">
          <el-table-column
            v-for="col in previewCols"
            :key="col"
            :prop="col"
            :label="col"
            min-width="140"
            show-overflow-tooltip
          />
        </el-table>
      </section>

      <!-- 原始报告 -->
      <section class="card card-pad">
        <h3 class="card-title">完整报告</h3>
        <p class="card-desc">MaskReport 原始 JSON(report_id: {{ report.report_id }})</p>
        <el-collapse>
          <el-collapse-item title="展开 / 收起 JSON">
            <pre class="report-json mono">{{ JSON.stringify(report, null, 2) }}</pre>
          </el-collapse-item>
        </el-collapse>
      </section>
    </template>

    <!-- 空状态 -->
    <section v-else class="card card-pad pipeline-empty">
      <div class="pe-icon">🛡️</div>
      <div class="pe-title">运行管道后查看可视化结果</div>
      <p class="pe-desc">漏斗 · PII 命中 · 脱敏对照 · 数据预览 · 完整报告</p>
    </section>
  </div>
</template>

<style scoped>
.pipeline {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.tab-body {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 8px 0 4px;
  flex-wrap: wrap;
}

.sample-desc {
  flex: 1;
  min-width: 280px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--text-2);
  padding: 12px 16px;
  border: 1px dashed var(--border-hairline);
  border-radius: 10px;
  background: var(--bg-inset);
}

.sample-desc .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--grad-accent);
  flex: none;
}

.paste-body {
  align-items: flex-start;
}

.paste-body .el-textarea {
  flex: 1;
}

/* ---------- 上传 ---------- */
.upload-inner {
  padding: 26px 0;
}

.upload-icon {
  color: var(--text-3);
}

.upload-text {
  margin-top: 10px;
  font-size: 14px;
  color: var(--text-2);
}

.upload-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-3);
}

/* ---------- 指标与图表 ---------- */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

.charts-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

/* ---------- 表格 ---------- */
.mono.before {
  color: #e66767;
  background: rgba(208, 59, 59, 0.08);
  padding: 2px 8px;
  border-radius: 6px;
}

.mono.after {
  color: #34c759;
  background: rgba(52, 199, 89, 0.08);
  padding: 2px 8px;
  border-radius: 6px;
}

.no-samples {
  padding: 26px 0;
  text-align: center;
  font-size: 13px;
  color: var(--text-3);
  border: 1px dashed var(--border-hairline);
  border-radius: 10px;
}

.report-json {
  margin: 0;
  padding: 14px 16px;
  background: var(--bg-page);
  border: 1px solid var(--border-hairline);
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-2);
  max-height: 380px;
  overflow: auto;
}

/* ---------- 空状态 ---------- */
.pipeline-empty {
  text-align: center;
  padding: 52px 20px;
}

.pe-icon {
  font-size: 40px;
  margin-bottom: 12px;
}

.pe-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-1);
}

.pe-desc {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--text-3);
}

@media (max-width: 1000px) {
  .kpi-row {
    grid-template-columns: repeat(2, 1fr);
  }

  .charts-row {
    grid-template-columns: 1fr;
  }
}
</style>
