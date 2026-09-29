const state = {
  threadId: localStorage.getItem("aftercare.threadId"),
  messages: [],
  toolEvents: [],
  pendingConfirmation: null,
  pendingStaffApproval: null,
  busy: false,
  adminToken: sessionStorage.getItem("aftercare.adminToken") || "",
};

const $ = (selector) => document.querySelector(selector);
const messageList = $("#message-list");
const welcome = $("#welcome");
const pendingArea = $("#pending-area");
const conversation = $("#conversation");
const chatInput = $("#chat-input");
const sendButton = $("#send-button");

const toolNames = {
  search_policy: "检索售后政策",
  lookup_order: "查询模拟订单",
  create_support_ticket: "创建售后工单",
  request_refund: "准备退款申请",
  execute_mock_refund: "执行模拟退款",
};

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatTime(value) {
  if (!value) return "";
  return new Date(value).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
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
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const response = await fetch(path, { ...options, headers });
  let body = {};
  try { body = await response.json(); } catch { /* A useful HTTP error may have no JSON body. */ }
  if (!response.ok) {
    const error = new Error(body.detail || `请求失败（${response.status}）`);
    error.status = response.status;
    throw error;
  }
  return body;
}

function setBusy(busy) {
  state.busy = busy;
  const waiting = Boolean(state.pendingConfirmation || state.pendingStaffApproval);
  chatInput.disabled = busy || waiting;
  sendButton.disabled = busy || waiting;
  if (state.pendingConfirmation) chatInput.placeholder = "请先确认或取消当前退款申请…";
  else if (state.pendingStaffApproval) chatInput.placeholder = "退款申请正在等待人工审批…";
  else chatInput.placeholder = "描述你遇到的问题，或输入订单号…";
  if (busy) sendButton.querySelector("span:first-child").textContent = "处理中";
  else sendButton.querySelector("span:first-child").textContent = "发送";
}

function renderMessages() {
  messageList.replaceChildren();
  const hasContent = state.messages.length > 0 || state.pendingConfirmation || state.pendingStaffApproval;
  welcome.hidden = hasContent;
  for (const item of state.messages) {
    const row = make("div", `message-row ${item.role === "user" ? "user" : "assistant"}`);
    const avatar = make("div", "message-avatar", item.role === "user" ? "林" : "✳");
    const body = make("div", "message-body");
    body.append(make("div", "message-name", item.role === "user" ? "你" : "小满 · 售后 Agent"));
    body.append(make("div", "message-bubble", item.content));
    body.append(make("div", "message-time", "演示会话"));
    row.append(avatar, body);
    messageList.append(row);
  }
  if (state.busy) {
    const row = make("div", "message-row assistant");
    row.append(make("div", "message-avatar", "✳"));
    const body = make("div", "message-body");
    body.append(make("div", "message-name", "小满 · 正在处理"));
    const dots = make("div", "typing-indicator");
    for (let i = 0; i < 3; i++) dots.append(document.createElement("i"));
    body.append(dots);
    row.append(body);
    messageList.append(row);
  }
  renderPending();
  conversation.scrollTop = conversation.scrollHeight;
  setBusy(state.busy);
}

function renderPending() {
  pendingArea.replaceChildren();
  if (state.pendingConfirmation) {
    const request = state.pendingConfirmation;
    const card = make("div", "pending-card");
    const head = make("div", "pending-card-head");
    head.append(make("div", "pending-card-icon", "↩"));
    const heading = make("div");
    heading.append(make("strong", "", "确认模拟退款申请"));
    heading.append(make("small", "", "确认后会进入人工审批，暂时不会执行退款"));
    head.append(heading);
    const body = make("div", "pending-card-body");
    const details = [
      ["订单", request.order_id],
      ["商品", request.product_name],
      ["申请金额", `¥${(request.amount_cents / 100).toFixed(2)}`],
      ["申请原因", request.reason || "用户申请退款"],
    ];
    for (const [label, value] of details) {
      const row = make("div", "pending-detail");
      row.append(make("span", "", label), make("strong", "", value));
      body.append(row);
    }
    const actions = make("div", "pending-actions");
    const confirm = make("button", "confirm-button", "确认申请并进入审批");
    confirm.type = "button";
    confirm.addEventListener("click", () => submitCustomerDecision(true));
    const cancel = make("button", "reject-button", "取消申请");
    cancel.type = "button";
    cancel.addEventListener("click", () => submitCustomerDecision(false));
    actions.append(confirm, cancel);
    card.append(head, body, actions);
    pendingArea.append(card);
  } else if (state.pendingStaffApproval) {
    const note = make("div", "pending-wait");
    note.append(make("strong", "", "申请已进入人工审批"));
    note.append(document.createTextNode("退款尚未执行。请在右上角打开审批工作台，由演示管理员处理。"));
    pendingArea.append(note);
  }
}

function renderTrace() {
  const flow = $("#trace-flow");
  flow.replaceChildren();
  const events = state.toolEvents || [];
  $("#trace-summary-text").textContent = events.length ? `${events.length} 个模型与工具步骤` : "等待对话开始";
  if (!events.length) {
    const empty = make("div", "empty-trace");
    empty.append(make("div", "empty-trace-icon", "⌁"));
    empty.append(make("strong", "", "还没有执行记录"));
    empty.append(make("span", "", "Agent 调用的模型和工具会显示在这里。"));
    flow.append(empty);
    return;
  }

  for (const event of [...events].reverse().slice(0, 18)) {
    const card = make("div", "trace-event");
    card.dataset.kind = event.kind || "tool";
    card.dataset.name = event.name || "";
    const top = make("div", "trace-event-top");
    const glyph = event.kind === "llm" ? "✳" : "⌘";
    top.append(make("div", "trace-kind", glyph));
    top.append(make("div", "trace-event-title", event.kind === "llm" ? `模型 · ${event.name}` : (toolNames[event.name] || event.name)));
    const statusLabel = event.status === "demo" ? "演示" : event.status === "error" ? "失败" : "完成";
    const status = make("span", `trace-status ${event.status === "demo" ? "demo" : ""}`, statusLabel);
    top.append(status);
    card.append(top);
    const meta = make("div", "trace-meta");
    let duration = `${event.duration_ms ?? 0} ms`;
    if (event.kind === "llm" && event.usage?.total_tokens) duration += ` · ${event.usage.total_tokens} tokens`;
    meta.append(make("span", "", event.kind === "llm" ? "生成步骤" : "工具调用"), make("span", "", duration));
    card.append(meta);

    const detail = make("pre", "trace-detail", JSON.stringify({ arguments: event.arguments || undefined, result: event.result || undefined, usage: event.usage || undefined }, null, 2));
    const toggle = make("button", "trace-detail-toggle", "查看输入 / 输出");
    toggle.type = "button";
    toggle.addEventListener("click", () => card.classList.toggle("expanded"));
    card.append(toggle, detail);

    if (event.name === "search_policy" && event.result?.results?.length) {
      for (const citation of event.result.results.slice(0, 2)) {
        const source = make("div", "citation-item");
        source.append(make("strong", "", `${citation.title} · ${citation.id}`));
        source.append(make("span", "", `${citation.source}：${citation.quote}`));
        card.append(source);
      }
    }
    flow.append(card);
  }
}

function syncPayload(payload) {
  state.threadId = payload.thread_id || state.threadId;
  if (state.threadId) localStorage.setItem("aftercare.threadId", state.threadId);
  state.messages = payload.messages || [];
  state.toolEvents = payload.tool_events || [];
  state.pendingConfirmation = payload.pending_confirmation || null;
  state.pendingStaffApproval = payload.pending_staff_approval || null;
  renderMessages();
  renderTrace();
  refreshApprovalCount();
}

async function sendMessage(text) {
  const message = text.trim();
  if (!message || state.busy || state.pendingConfirmation || state.pendingStaffApproval) return;
  state.messages.push({ role: "user", content: message });
  chatInput.value = "";
  resizeInput();
  setBusy(true);
  renderMessages();
  try {
    const payload = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ thread_id: state.threadId, message }),
    });
    syncPayload(payload);
  } catch (error) {
    state.messages.push({ role: "assistant", content: `这次请求没有完成：${error.message}` });
    toast(error.message, true);
  } finally {
    setBusy(false);
    renderMessages();
    chatInput.focus();
  }
}

async function submitCustomerDecision(approved) {
  if (!state.threadId || state.busy) return;
  setBusy(true);
  renderMessages();
  try {
    const payload = await api(`/api/threads/${encodeURIComponent(state.threadId)}/customer-confirm`, {
      method: "POST",
      body: JSON.stringify({ approved }),
    });
    syncPayload(payload);
    if (approved) toast("申请已确认，等待人工审批。打开右上角审批工作台。 ");
    else toast("已取消申请，没有执行退款。");
  } catch (error) {
    toast(error.message, true);
    if (state.threadId) await loadThread(state.threadId);
  } finally {
    setBusy(false);
    renderMessages();
  }
}

async function loadThread(threadId) {
  if (!threadId) return;
  try {
    const payload = await api(`/api/threads/${encodeURIComponent(threadId)}`);
    syncPayload(payload);
  } catch (error) {
    if (error.status === 404) {
      localStorage.removeItem("aftercare.threadId");
      state.threadId = null;
    }
  }
}

function startNewChat() {
  state.threadId = null;
  state.messages = [];
  state.toolEvents = [];
  state.pendingConfirmation = null;
  state.pendingStaffApproval = null;
  localStorage.removeItem("aftercare.threadId");
  renderMessages();
  renderTrace();
  setBusy(false);
  chatInput.focus();
}

function resizeInput() {
  chatInput.style.height = "auto";
  chatInput.style.height = `${Math.min(chatInput.scrollHeight, 118)}px`;
}

async function loadOrders() {
  const list = $("#order-list");
  try {
    const payload = await api("/api/demo/orders");
    list.replaceChildren();
    const glyphs = ["▧", "◉", "⌨", "▤"];
    for (const [index, order] of payload.orders.entries()) {
      const button = make("button", "order-row");
      button.type = "button";
      const glyph = make("span", "order-glyph", glyphs[index % glyphs.length]);
      const copy = make("span", "order-copy");
      copy.append(make("strong", "", order.product_name));
      copy.append(make("small", "", order.order_id));
      const status = make("span", `order-status ${order.status === "delivered" ? "delivered" : ""}`, order.status_label);
      button.append(glyph, copy, status);
      button.addEventListener("click", () => {
        document.querySelectorAll(".order-row").forEach((node) => node.classList.remove("is-active"));
        button.classList.add("is-active");
        const prefix = order.status === "delivered" ? "帮我查一下订单" : "帮我查一下订单";
        sendMessage(`${prefix} ${order.order_id} 的物流和商品状态`);
      });
      list.append(button);
    }
  } catch {
    list.replaceChildren(make("div", "sidebar-hint", "模拟订单暂时无法加载。"));
  }
}

function ensureAdminToken() {
  if (state.adminToken) return state.adminToken;
  const token = window.prompt("请输入 .env 中配置的 ADMIN_TOKEN：");
  if (!token) return "";
  state.adminToken = token.trim();
  sessionStorage.setItem("aftercare.adminToken", state.adminToken);
  return state.adminToken;
}

function setDrawerOpen(open) {
  const drawer = $("#approval-drawer");
  drawer.classList.toggle("open", open);
  drawer.setAttribute("aria-hidden", String(!open));
  $("#drawer-backdrop").classList.toggle("open", open);
  if (open) loadApprovals();
}

function showMetrics(metrics = {}) {
  const target = $("#drawer-metrics");
  target.replaceChildren();
  const items = [
    ["待审批", metrics.pending_approvals ?? 0],
    ["开放工单", metrics.open_tickets ?? 0],
    ["模拟退款", metrics.simulated_refunds ?? 0],
  ];
  for (const [label, value] of items) {
    const card = make("div", "metric-card");
    card.append(make("span", "", label), make("strong", "", String(value)));
    target.append(card);
  }
}

async function loadApprovals() {
  const list = $("#approval-list");
  const token = ensureAdminToken();
  if (!token) return;
  try {
    const payload = await api("/api/admin/approvals", { headers: { "X-Admin-Token": token } });
    showMetrics(payload.metrics);
    $("#approval-count").textContent = String(payload.metrics.pending_approvals || 0);
    list.replaceChildren();
    if (!payload.approvals.length) {
      const empty = make("div", "drawer-empty");
      empty.append(make("div", "", "✓"), make("strong", "", "暂无待审批申请"), make("span", "", "完成用户确认后，申请会显示在这里。"));
      list.append(empty);
      return;
    }
    for (const request of payload.approvals) list.append(renderApprovalCard(request));
  } catch (error) {
    toast(error.status === 401 ? "管理员令牌不正确。" : error.message, true);
    if (error.status === 401) {
      sessionStorage.removeItem("aftercare.adminToken");
      state.adminToken = "";
    }
  }
}

function renderApprovalCard(request) {
  const card = make("article", "approval-card");
  const head = make("div", "approval-card-head");
  head.append(make("strong", "", request.order_id), make("span", "queue-tag", "待人工审批"));
  card.append(head);
  card.append(make("div", "approval-card-subtitle", `${request.customer_name} · ${request.product_name}`));
  const details = make("div", "approval-card-details");
  for (const [label, value] of [["退款金额", `¥${request.amount.toFixed(2)}`], ["创建时间", formatTime(request.created_at)]]) {
    const item = make("div");
    item.append(make("span", "", label), make("strong", "", value));
    details.append(item);
  }
  card.append(details, make("div", "approval-reason", `申请原因：${request.reason || "用户申请退款"}`));
  const actions = make("div", "approval-card-actions");
  const approve = make("button", "review-action approve", "通过并执行模拟退款");
  approve.type = "button";
  approve.addEventListener("click", () => decideStaff(request.request_id, "approve"));
  const reject = make("button", "review-action reject", "拒绝");
  reject.type = "button";
  reject.addEventListener("click", () => decideStaff(request.request_id, "reject"));
  actions.append(approve, reject);
  card.append(actions);
  return card;
}

async function decideStaff(requestId, decision) {
  const token = ensureAdminToken();
  if (!token) return;
  let note = "";
  if (decision === "reject") {
    const enteredNote = window.prompt("填写审批备注（可留空）：", "");
    if (enteredNote === null) return;
    note = enteredNote;
  }
  try {
    const payload = await api(`/api/admin/approvals/${encodeURIComponent(requestId)}`, {
      method: "POST",
      headers: { "X-Admin-Token": token },
      body: JSON.stringify({ decision, note }),
    });
    if (state.threadId === payload.thread_id) syncPayload(payload);
    await loadApprovals();
    toast(decision === "approve" ? "已通过申请，模拟退款已执行。" : "已拒绝申请。", false);
  } catch (error) {
    toast(error.status === 401 ? "管理员令牌不正确。" : error.message, true);
    if (error.status === 401) {
      sessionStorage.removeItem("aftercare.adminToken");
      state.adminToken = "";
    }
    await loadApprovals();
  }
}

async function refreshApprovalCount() {
  try {
    const payload = await api("/api/dashboard");
    $("#approval-count").textContent = String(payload.pending_approvals || 0);
  } catch { /* The count is decorative; keep the previous value if offline. */ }
}

async function initialize() {
  try {
    const config = await api("/api/config");
    $("#runtime-label").textContent = config.demo_mode ? "规则演示模式" : `模型在线 · ${config.model}`;
  } catch {
    $("#runtime-label").textContent = "服务连接失败";
  }
  await Promise.all([loadOrders(), refreshApprovalCount()]);
  if (state.threadId) await loadThread(state.threadId);
  renderMessages();
  renderTrace();
}

$("#chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(chatInput.value);
});

chatInput.addEventListener("input", resizeInput);
chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage(chatInput.value);
  }
});

$("#new-chat-button").addEventListener("click", startNewChat);
document.querySelectorAll(".suggestion-card").forEach((button) => {
  button.addEventListener("click", () => sendMessage(button.dataset.message || ""));
});
$("#approval-toggle").addEventListener("click", () => setDrawerOpen(true));
$("#close-drawer").addEventListener("click", () => setDrawerOpen(false));
$("#drawer-backdrop").addEventListener("click", () => setDrawerOpen(false));
$("#clear-trace").addEventListener("click", () => {
  state.toolEvents = [];
  renderTrace();
  toast("已清空当前展示；服务端运行记录仍保留在对话中。");
});
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    startNewChat();
  }
  if (event.key === "Escape") setDrawerOpen(false);
});

initialize();
