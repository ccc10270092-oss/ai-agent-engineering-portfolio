/**
 * ECharts 配置 · 遵循 dataviz 规范
 * - 条形 ≤24px、数据端 4px 圆角、基线端直角
 * - 网格线实线发丝级、坐标文字用文本令牌(不用系列色)
 * - 漏斗用有序单色渐变(已校验),PII 命中为单系列单色(名义类目不做值渐变)
 */
export const CHART = {
  text1: '#e6edf7',
  text2: '#9fb0cc',
  text3: '#64748b',
  grid: 'rgba(148, 163, 184, 0.10)',
  axis: 'rgba(148, 163, 184, 0.18)',
  tooltipBg: '#17223a',
  blue: '#3987e5',
  funnelRamp: ['#86b5ef', '#5598e7', '#2a78d6', '#184f95'],
}

const baseTooltip = {
  backgroundColor: CHART.tooltipBg,
  borderColor: 'rgba(148, 163, 184, 0.2)',
  textStyle: { color: CHART.text1, fontSize: 12 },
  extraCssText: 'box-shadow: 0 6px 18px rgba(2,6,16,.5); border-radius: 8px;',
}

/** 管道漏斗:输入 → 清洗后 → 去重后 → 脱敏输出(水平条形) */
export function funnelOption(stageStats = {}) {
  const input = stageStats.input || 0
  const cleaned = input - (stageStats.clean_dropped || 0)
  const deduped = cleaned - (stageStats.dedupe_removed || 0)
  const output = stageStats.output || 0
  const stages = [
    { name: '输入记录', value: input, drop: 0, dropLabel: '' },
    { name: '清洗后', value: cleaned, drop: stageStats.clean_dropped || 0, dropLabel: '清洗丢弃' },
    { name: '去重后', value: deduped, drop: stageStats.dedupe_removed || 0, dropLabel: '重复删除' },
    { name: '脱敏输出', value: output, drop: deduped - output, dropLabel: '脱敏丢弃' },
  ]
  return {
    grid: { left: 10, right: 44, top: 10, bottom: 6, containLabel: true },
    xAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: CHART.grid, width: 1 } },
      axisLabel: { color: CHART.text3, fontSize: 11 },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: stages.map((s) => s.name),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: CHART.axis } },
      axisLabel: { color: CHART.text2, fontSize: 12 },
    },
    tooltip: {
      ...baseTooltip,
      formatter: (p) => {
        const s = stages[p.dataIndex]
        const drop = s.drop ? `<br/>${s.dropLabel}: ${s.drop} 条` : ''
        return `${s.name}: <b>${s.value}</b> 条${drop}`
      },
    },
    series: [
      {
        type: 'bar',
        barWidth: 16,
        data: stages.map((s, i) => ({
          value: s.value,
          itemStyle: { color: CHART.funnelRamp[i], borderRadius: [0, 4, 4, 0] },
        })),
        label: { show: true, position: 'right', color: CHART.text2, fontSize: 12 },
      },
    ],
  }
}

/** PII 命中分布:身份证 / 手机号 / 邮箱(单系列 → 单色) */
export function piiOption(maskHits = {}) {
  const items = [
    { name: '身份证', key: 'id_card' },
    { name: '手机号', key: 'phone' },
    { name: '邮箱', key: 'email' },
  ]
  return {
    grid: { left: 10, right: 44, top: 10, bottom: 6, containLabel: true },
    xAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: CHART.grid, width: 1 } },
      axisLabel: { color: CHART.text3, fontSize: 11 },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: items.map((i) => i.name),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: CHART.axis } },
      axisLabel: { color: CHART.text2, fontSize: 12 },
    },
    tooltip: {
      ...baseTooltip,
      formatter: (p) => `${p.name}: <b>${p.value}</b> 处`,
    },
    series: [
      {
        type: 'bar',
        barWidth: 16,
        data: items.map((i) => ({
          value: maskHits[i.key] || 0,
          itemStyle: { color: CHART.blue, borderRadius: [0, 4, 4, 0] },
        })),
        label: { show: true, position: 'right', color: CHART.text2, fontSize: 12 },
      },
    ],
  }
}
