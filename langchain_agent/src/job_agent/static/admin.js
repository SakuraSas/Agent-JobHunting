const sources = document.querySelector("#sources");
const logs = document.querySelector("#logs");
const jobs = document.querySelector("#jobs");
const reviews = document.querySelector("#reviews");
const sourceSummary = document.querySelector("#sourceSummary");
const jobSummary = document.querySelector("#jobSummary");
const reviewSummary = document.querySelector("#reviewSummary");

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function reviewReasons(reasons) {
  return (reasons || []).join("、") || "-";
}

async function reviewAction(jobId, action) {
  const label = action === "approve" ? "批准入库" : "忽略";
  if (!confirm(`确认${label}该岗位？`)) return;
  await api(`/api/admin/reviews/${encodeURIComponent(jobId)}/${action}`, { method: "POST" });
  await load();
}

function actionButton(label, className, handler) {
  const button = document.createElement("button");
  button.className = className;
  button.textContent = label;
  button.onclick = handler;
  return button;
}

function renderReviews(data) {
  reviews.replaceChildren();
  reviewSummary.textContent = `${data.length} 条待审核`;
  if (!data.length) {
    reviews.innerHTML = '<tr><td class="empty" colspan="9">没有待审核岗位。</td></tr>';
    return;
  }
  for (const item of data) {
    const row = document.createElement("tr");
    const link = document.createElement("a");
    link.href = item.source_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "核实";
    const actions = document.createElement("div");
    actions.className = "row-actions";
    actions.append(
      actionButton("批准", "approve-button", () => reviewAction(item.job_id, "approve")),
      actionButton("忽略", "ignore-button", () => reviewAction(item.job_id, "ignore")),
    );
    cell(row, item.source);
    cell(row, item.title, "title");
    cell(row, item.company);
    cell(row, item.city);
    cell(row, item.confidence.toFixed(2));
    cell(row, reviewReasons(item.review_reasons), "reason");
    cell(row, time(item.updated_at));
    cell(row, link);
    cell(row, actions);
    reviews.appendChild(row);
  }
}

function text(value) {
  return value ?? "-";
}

function time(value) {
  if (!value) return "-";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN", { hour12: false });
}

function badge(status) {
  const span = document.createElement("span");
  span.className = `badge ${status}`;
  span.textContent = status;
  return span;
}

function cell(row, value, className = "") {
  const td = document.createElement("td");
  td.className = className;
  if (value instanceof Node) td.appendChild(value);
  else td.textContent = text(value);
  row.appendChild(td);
}

function renderSources(data) {
  sources.replaceChildren();
  sourceSummary.textContent = `${data.length} 个来源`;
  if (!data.length) {
    sources.innerHTML = '<div class="empty">尚无同步记录。请先运行 browser_agent/scripts/browser_sync_jobs.py。</div>';
    return;
  }
  for (const item of data) {
    const card = document.createElement("article");
    card.className = "card";
    const title = document.createElement("h3");
    title.textContent = item.source;
    const dl = document.createElement("dl");
    const fields = [
      ["最后同步", time(item.last_sync_at)],
      ["最后成功", time(item.last_success_at)],
      ["状态", item.last_status],
      ["抓取岗位", item.crawled_count],
      ["变化", item.changed_count],
      ["失效", item.inactive_count],
      ["过期", item.expired_count],
      ["重复", item.duplicate_count],
      ["错误", item.last_error],
    ];
    for (const [label, value] of fields) {
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      dt.textContent = label;
      dd.textContent = text(value);
      dl.append(dt, dd);
    }
    card.append(title, dl);
    sources.appendChild(card);
  }
}

function renderLogs(data) {
  logs.replaceChildren();
  if (!data.length) {
    logs.innerHTML = '<tr><td class="empty" colspan="10">尚无同步日志。</td></tr>';
    return;
  }
  for (const item of data) {
    const row = document.createElement("tr");
    cell(row, item.source);
    cell(row, badge(item.status));
    cell(row, time(item.started_at));
    cell(row, time(item.finished_at));
    cell(row, item.crawled_count);
    cell(row, item.changed_count);
    cell(row, item.inactive_count);
    cell(row, item.expired_count);
    cell(row, item.duplicate_count);
    cell(row, item.error, "error");
    logs.appendChild(row);
  }
}

function renderJobs(data) {
  jobs.replaceChildren();
  const active = data.filter((item) => item.status === "active").length;
  jobSummary.textContent = `${data.length} 条岗位，active ${active}，inactive ${data.length - active}`;
  if (!data.length) {
    jobs.innerHTML = '<tr><td class="empty" colspan="9">尚无岗位数据。</td></tr>';
    return;
  }
  for (const item of data) {
    const row = document.createElement("tr");
    const link = document.createElement("a");
    link.href = item.source_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "打开";
    cell(row, item.source);
    cell(row, item.title, "title");
    cell(row, item.company);
    cell(row, item.city);
    cell(row, item.published_at);
    cell(row, time(item.last_seen_at));
    cell(row, badge(item.status));
    cell(row, item.inactive_reason);
    cell(row, link);
    jobs.appendChild(row);
  }
}

async function load() {
  const [sourceData, logData, reviewData, jobData] = await Promise.all([
    api("/api/admin/sources"),
    api("/api/admin/sync-logs"),
    api("/api/admin/reviews"),
    api("/api/admin/jobs"),
  ]);
  renderSources(sourceData.sources);
  renderLogs(logData.logs);
  renderReviews(reviewData.reviews);
  renderJobs(jobData.jobs);
}

document.querySelector("#refresh").onclick = () => load().catch((error) => alert(error.message));
load().catch((error) => alert(error.message));
