const state = {
  lastResult: null,
  busy: false,
  adminToken: sessionStorage.getItem("dataAgent.adminToken") || "",
};

const $ = (selector) => document.querySelector(selector);
const SVG_NS = "http://www.w3.org/2000/svg";
const toolNames = {
  "run_readonly_query": "执行只读 SQL",
  "演示查询规划器": "规划分析问题",
};

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function svgElement(name, attrs = {}, text) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  if (text !== undefined) node.textContent = text;
  return node;
}

function toast(message, isError = false) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.toggle("error", isError);
  node.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => node.classList.remove("show"), 2800);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  let body = {};
  try { body = await response.json(); } catch { /* Surface the status code if there is no JSON body. */ }
  if (!response.ok) {
    const error = new Error(body.detail || `请求失败（${response.status}）`);
    error.status = response.status;
    throw error;
  }
  return body;
}

function setBusy(busy) {
  state.busy = busy;
  $("#run-button").disabled = busy;
  $("#followup-submit").disabled = busy;
  $("#question-input").disabled = busy;
  $("#followup-input").disabled = busy;
  $("#run-button span:first-child").textContent = busy ? "分析中" : "开始分析";
}

async function runAnalysis(question) {
  const cleanQuestion = question.trim();
  if (!cleanQuestion || state.busy) return;
  $("#question-input").value = cleanQuestion;
  $("#question-label").textContent = cleanQuestion;
  $("#analysis-section").hidden = false;
  $("#answer-copy").textContent = "Agent 正在规划并校验查询…";
  $("#answer-mode").textContent = "运行中";
  $("#trace-list").replaceChildren(make("span", "loading-summary", "正在启动模型和只读查询工具…"));
  $("#table-wrap").hidden = true;
  $("#chart-wrap").hidden = true;
  setBusy(true);
  $("#analysis-section").scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const payload = await api("/api/analyze", { method: "POST", body: JSON.stringify({ question: cleanQuestion }) });
    state.lastResult = payload.result || null;
    $("#answer-copy").textContent = payload.answer || "本次没有生成分析结论。";
    $("#answer-mode").textContent = payload.mode === "demo" ? "规则演示 Agent · 未调用模型 API" : "模型工具调用 · SQL 安全校验";
    renderResult(payload.result);
    renderTrace(payload.trace || []);
  } catch (error) {
    state.lastResult = null;
    $("#answer-copy").textContent = `分析没有完成：${error.message}`;
    $("#answer-mode").textContent = "请求失败";
    $("#trace-list").replaceChildren();
    toast(error.message, true);
  } finally {
    setBusy(false);
  }
}

function renderResult(result) {
  const tableWrap = $("#table-wrap");
  const chartWrap = $("#chart-wrap");
  if (!result || !Array.isArray(result.rows) || !Array.isArray(result.columns)) {
    tableWrap.hidden = true;
    chartWrap.hidden = true;
    return;
  }

  const table = $("#result-table");
  table.replaceChildren();
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const column of result.columns) headRow.append(make("th", "", column));
  head.append(headRow);
  const body = document.createElement("tbody");
  for (const row of result.rows) {
    const tr = document.createElement("tr");
    for (const column of result.columns) {
      const value = row[column];
      const td = make("td", typeof value === "number" ? "numeric" : "", formatValue(value));
      tr.append(td);
    }
    body.append(tr);
  }
  table.append(head, body);
  $("#table-count").textContent = `${result.row_count} 行${result.truncated ? " · 已截断" : ""}`;
  $("#truncation-note").hidden = !result.truncated;
  tableWrap.hidden = false;

  if (result.chart_type && result.chart_type !== "none" && result.rows.length) {
    drawChart(result);
    chartWrap.hidden = false;
  } else {
    chartWrap.hidden = true;
  }
}

function formatValue(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    if (Number.isInteger(value)) return value.toLocaleString("zh-CN");
    return value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  }
  return String(value);
}

function drawChart(result) {
  const wrap = $("#chart-container");
  wrap.replaceChildren();
  const keys = result.columns;
  const labelKey = keys[0];
  const numericKey = keys.slice(1).find((key) => result.rows.some((row) => typeof row[key] === "number")) || keys[0];
  const values = result.rows.map((row) => Number(row[numericKey]) || 0);
  const labels = result.rows.map((row) => String(row[labelKey] ?? ""));
  const width = 690;
  const height = 184;
  const padding = { left: 42, right: 13, top: 17, bottom: 31 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const maxValue = Math.max(...values, 1);
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": `${numericKey} chart` });
  for (let index = 0; index < 4; index++) {
    const y = padding.top + (plotHeight * index) / 3;
    svg.append(svgElement("line", { x1: padding.left, y1: y, x2: width - padding.right, y2: y, class: "chart-gridline" }));
  }

  const slot = plotWidth / Math.max(values.length, 1);
  const points = [];
  values.forEach((value, index) => {
    const xCenter = padding.left + slot * (index + 0.5);
    const y = padding.top + plotHeight - (value / maxValue) * (plotHeight - 7);
    points.push(`${xCenter},${y}`);
    if (result.chart_type === "line") {
      svg.append(svgElement("circle", { cx: xCenter, cy: y, r: 3.5, class: "chart-point" }));
    } else {
      const barWidth = Math.max(7, Math.min(30, slot * 0.55));
      const barHeight = Math.max(2, padding.top + plotHeight - y);
      const rect = svgElement("rect", { x: xCenter - barWidth / 2, y, width: barWidth, height: barHeight, class: "chart-bar" });
      rect.append(svgElement("title", {}, `${labels[index]}: ${formatValue(value)}`));
      svg.append(rect);
    }
    svg.append(svgElement("text", { x: xCenter, y: height - 10, "text-anchor": "middle", class: "chart-axis-label" }, labels[index].slice(0, 10)));
  });
  if (result.chart_type === "line" && points.length > 1) {
    svg.insertBefore(svgElement("polyline", { points: points.join(" "), class: "chart-line" }), svg.firstChild.nextSibling);
  }
  $("#chart-title").textContent = numericKey === "revenue" ? "成交金额" : numericKey;
  $("#chart-subtitle").textContent = `按 ${labelKey} 展示 · ${result.rows.length} 个分组`;
  wrap.append(svg);
}

function renderTrace(events) {
  const list = $("#trace-list");
  list.replaceChildren();
  $("#trace-count").textContent = `${events.length} 个步骤`;
  if (!events.length) {
    list.append(make("span", "loading-summary", "没有模型或工具轨迹。"));
    return;
  }
  for (const event of events) {
    const card = make("article", "trace-event");
    card.dataset.kind = event.kind || "tool";
    const top = make("div", "trace-event-top");
    top.append(make("span", "trace-icon", event.kind === "llm" ? "✳" : event.kind === "agent" ? "⌘" : "▤"));
    top.append(make("span", "trace-event-title", toolNames[event.name] || event.name || "Agent 步骤"));
    top.append(make("span", `trace-status ${event.status === "demo" ? "demo" : ""}`, event.status === "demo" ? "演示" : event.status === "rejected" ? "拦截" : event.status === "error" ? "失败" : "完成"));
    card.append(top);
    const description = event.explanation || (event.kind === "llm" ? "模型生成或总结" : `${event.row_count ?? 0} 行 · ${event.duration_ms ?? 0} ms`);
    card.append(make("small", "", description));
    if (event.usage?.total_tokens) card.append(make("small", "", `输入 ${event.usage.input_tokens ?? "?"} / 输出 ${event.usage.output_tokens ?? "?"} tokens`));
    if (event.sql) {
      const details = document.createElement("details");
      details.append(make("summary", "", `查看 SQL · ${event.tables?.join(", ") || "数据表"}`));
      details.append(make("pre", "trace-sql", event.sql));
      card.append(details);
    }
    if (event.error) card.append(make("span", "trace-error", event.error));
    list.append(card);
  }
}

function renderSchema(tables) {
  const list = $("#schema-list");
  list.replaceChildren();
  const tableEntries = Object.entries(tables);
  $(".count-chip").textContent = String(tableEntries.length);
  const icons = ["▤", "▦", "◇", "♙"];
  for (const [index, [name, columns]] of tableEntries.entries()) {
    const details = document.createElement("details");
    details.className = "schema-item";
    const summary = make("summary", "schema-summary");
    summary.append(make("span", "table-icon", icons[index % icons.length]));
    summary.append(make("span", "schema-name", name));
    summary.append(make("span", "schema-chevron", "⌄"));
    details.append(summary);
    const columnList = make("div", "column-list");
    for (const column of columns) {
      const row = make("div", "column-row");
      row.append(make("strong", "", column.name), make("span", "", `${column.type} · ${column.description}`));
      columnList.append(row);
    }
    details.append(columnList);
    list.append(details);
  }
}

function ensureAdminToken() {
  if (state.adminToken) return state.adminToken;
  const entered = window.prompt("请输入 .env 中配置的 ADMIN_TOKEN：");
  if (!entered) return "";
  state.adminToken = entered.trim();
  sessionStorage.setItem("dataAgent.adminToken", state.adminToken);
  return state.adminToken;
}

async function showDataSummary() {
  const token = ensureAdminToken();
  if (!token) return;
  const dialog = $("#summary-dialog");
  $("#summary-body").replaceChildren(make("span", "loading-summary", "正在读取数据字典…"));
  dialog.showModal();
  try {
    const payload = await api("/api/admin/data-summary", { headers: { "X-Admin-Token": token } });
    const table = make("table", "summary-table");
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    headRow.append(make("th", "", "数据表"), make("th", "", "字段数"), make("th", "", "样例行数"));
    head.append(headRow);
    const body = document.createElement("tbody");
    for (const [name, columns] of Object.entries(payload.tables)) {
      const row = document.createElement("tr");
      row.append(make("td", "", name), make("td", "", String(columns.length)), make("td", "", (payload.row_counts[name] ?? 0).toLocaleString("zh-CN")));
      body.append(row);
    }
    table.append(head, body);
    $("#summary-body").replaceChildren(table);
  } catch (error) {
    $("#summary-body").replaceChildren(make("span", "loading-summary", error.message));
    if (error.status === 401) {
      state.adminToken = "";
      sessionStorage.removeItem("dataAgent.adminToken");
    }
    toast(error.status === 401 ? "管理员令牌不正确。" : error.message, true);
  }
}

function downloadCsv() {
  const result = state.lastResult;
  if (!result?.columns?.length || !result.rows?.length) return;
  const quoteCell = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const lines = [result.columns.map(quoteCell).join(",")];
  for (const row of result.rows) lines.push(result.columns.map((column) => quoteCell(row[column])).join(","));
  const blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "chengxi-query-result.csv";
  link.click();
  URL.revokeObjectURL(url);
}

async function initialize() {
  try {
    const [config, schema] = await Promise.all([api("/api/config"), api("/api/schema")]);
    $("#runtime-label").textContent = config.demo_mode ? "规则演示模式" : `模型在线 · ${config.model}`;
    renderSchema(schema.tables);
  } catch (error) {
    $("#runtime-label").textContent = "服务连接失败";
    toast(error.message, true);
  }
}

$("#ask-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runAnalysis($("#question-input").value);
});
document.querySelectorAll(".suggestion-chip").forEach((button) => {
  button.addEventListener("click", () => runAnalysis(button.dataset.question || ""));
});
$("#followup-submit").addEventListener("click", () => {
  const input = $("#followup-input");
  if (!input.value.trim()) return;
  $("#question-input").value = input.value;
  input.value = "";
  runAnalysis($("#question-input").value);
});
$("#followup-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    $("#followup-submit").click();
  }
});
$("#edit-question").addEventListener("click", () => {
  $("#question-input").focus();
  $("#question-input").scrollIntoView({ behavior: "smooth", block: "center" });
});
$("#export-csv").addEventListener("click", downloadCsv);
$("#data-summary-button").addEventListener("click", showDataSummary);
$("#close-summary").addEventListener("click", () => $("#summary-dialog").close());
$("#summary-dialog").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});

initialize();
