const state = {
  sessions: [],
  activeThreadId: null,
  activeResume: localStorage.getItem("activeResume") || null,
  busy: false,
};

const list = document.querySelector("#sessionList");
const messages = document.querySelector("#messages");
const empty = document.querySelector("#emptyState");
const composer = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const send = document.querySelector("#sendButton");
const toast = document.querySelector("#toast");
const resumeModal = document.querySelector("#resumeModal");
const resumeDropzone = document.querySelector("#resumeDropzone");
const resumeFile = document.querySelector("#resumeFile");
const resumeList = document.querySelector("#resumeList");
const activeResume = document.querySelector("#activeResume");
const activeResumeName = document.querySelector("#activeResumeName");

function showToast(text) {
  toast.textContent = text;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 4200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function setActiveResume(filename) {
  state.activeResume = filename;
  if (filename) {
    localStorage.setItem("activeResume", filename);
    activeResumeName.textContent = filename;
    activeResume.classList.remove("hidden");
  } else {
    localStorage.removeItem("activeResume");
    activeResumeName.textContent = "";
    activeResume.classList.add("hidden");
  }
}

async function renderResumes() {
  const data = await api("/api/resumes");
  resumeList.replaceChildren();
  if (state.activeResume && !data.files.includes(state.activeResume)) {
    setActiveResume(null);
  }
  if (!data.files.length) {
    resumeList.textContent = "暂无简历";
    return;
  }

  for (const filename of data.files) {
    const item = document.createElement("div");
    item.className = `resume-item ${filename === state.activeResume ? "active" : ""}`;

    const name = document.createElement("span");
    name.className = "resume-name";
    name.textContent = filename;

    const actions = document.createElement("div");
    actions.className = "resume-actions";

    const use = document.createElement("button");
    use.type = "button";
    use.textContent = filename === state.activeResume ? "使用中" : "使用";
    use.disabled = filename === state.activeResume;
    use.onclick = () => {
      setActiveResume(filename);
      renderResumes().catch((error) => showToast(error.message));
    };

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "删除";
    remove.onclick = () => deleteResume(filename);

    actions.append(use, remove);
    item.append(name, actions);
    resumeList.appendChild(item);
  }
}

async function deleteResume(filename) {
  if (!window.confirm(`确认删除简历“${filename}”吗？删除后无法恢复。`)) return;
  await api(`/api/resumes/${encodeURIComponent(filename)}`, { method: "DELETE" });
  if (state.activeResume === filename) setActiveResume(null);
  await renderResumes();
  showToast(`简历已删除：${filename}`);
}

async function uploadResume(file) {
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  resumeDropzone.classList.add("uploading");
  composer.classList.add("uploading");
  try {
    const response = await fetch("/api/resumes/upload", { method: "POST", body });
    if (!response.ok) throw new Error(await response.text());
    const uploaded = await response.json();
    setActiveResume(uploaded.filename);
    await renderResumes();
    showToast(`简历已上传并选中：${uploaded.filename}`);
  } finally {
    resumeDropzone.classList.remove("uploading");
    composer.classList.remove("uploading");
    resumeFile.value = "";
  }
}

function renderSessions() {
  list.innerHTML = "";
  for (const session of state.sessions) {
    const row = document.createElement("div");
    row.className = `session ${session.thread_id === state.activeThreadId ? "active" : ""}`;

    const title = document.createElement("button");
    title.className = "session-title";
    title.title = session.name;
    title.textContent = session.name;
    title.onclick = () => selectSession(session.thread_id);

    const remove = document.createElement("button");
    remove.className = "delete-session";
    remove.title = "删除会话";
    remove.textContent = "×";
    remove.onclick = async (event) => {
      event.stopPropagation();
      await deleteSession(session.thread_id);
    };

    row.append(title, remove);
    list.appendChild(row);
  }
}

function appendMessage(role, content = "") {
  empty.classList.add("hidden");
  messages.classList.remove("hidden");
  const item = document.createElement("div");
  item.className = `message ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.dataset.raw = content;
  item.appendChild(bubble);
  renderBubble(bubble);
  messages.appendChild(item);
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  return bubble;
}

function renderBubble(bubble) {
  const content = bubble.dataset.raw || "";
  if (!bubble.closest(".assistant")) {
    bubble.textContent = content;
    return;
  }

  const html = marked.parse(content, { breaks: true, gfm: true });
  bubble.innerHTML = DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ["img"],
  });
  for (const link of bubble.querySelectorAll("a")) {
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }
}

function addContent(bubble, content) {
  bubble.dataset.raw = (bubble.dataset.raw || "") + content;
  renderBubble(bubble);
}

async function loadSessions() {
  state.sessions = await api("/api/sessions");
  if (!state.activeThreadId && state.sessions.length) {
    state.activeThreadId = state.sessions[0].thread_id;
  }
  if (!state.activeThreadId) await createSession();
  renderSessions();
  await loadMessages();
}

async function createSession() {
  const session = await api("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ name: "新对话" }),
  });
  state.activeThreadId = session.thread_id;
  state.sessions = await api("/api/sessions");
  renderSessions();
  messages.innerHTML = "";
  messages.classList.add("hidden");
  empty.classList.remove("hidden");
}

async function selectSession(threadId) {
  state.activeThreadId = threadId;
  renderSessions();
  await loadMessages();
}

async function deleteSession(threadId) {
  await api(`/api/sessions/${threadId}`, { method: "DELETE" });
  if (state.activeThreadId === threadId) state.activeThreadId = null;
  await loadSessions();
}

async function loadMessages() {
  if (!state.activeThreadId) return;
  const data = await api(`/api/sessions/${state.activeThreadId}/messages`);
  messages.innerHTML = "";
  if (!data.messages.length) {
    messages.classList.add("hidden");
    empty.classList.remove("hidden");
    return;
  }
  for (const item of data.messages) appendMessage(item.role, item.content);
}

async function sendMessage(text) {
  if (!text || state.busy) return;
  state.busy = true;
  send.disabled = true;
  appendMessage("user", text);
  const answer = appendMessage("assistant", "");
  input.value = "";
  input.style.height = "auto";

  try {
    const response = await fetch("/api/chat/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        thread_id: state.activeThreadId,
        message: text,
        resume_name: state.activeResume,
      }),
    });
    if (!response.ok) throw new Error(await response.text());

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split(/\r?\n\r?\n/);
      buffer = chunks.pop();
      for (const chunk of chunks) {
        const event = chunk.match(/^event: (.+)$/m)?.[1];
        const raw = chunk.match(/^data: (.+)$/m)?.[1];
        if (!raw) continue;
        const payload = JSON.parse(raw);
        if (event === "message") addContent(answer, payload.content || "");
        if (event === "error") addContent(answer, `\n\n[错误] ${payload.error || "未知错误"}`);
        window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
      }
    }
    state.sessions = await api("/api/sessions");
    renderSessions();
  } catch (error) {
    addContent(answer, `\n\n[错误] ${error.message}`);
  } finally {
    state.busy = false;
    send.disabled = false;
    input.focus();
  }
}

document.querySelector("#chatForm").onsubmit = (event) => {
  event.preventDefault();
  sendMessage(input.value.trim());
};

document.querySelector("#newSession").onclick = createSession;

document.querySelector("#clearActiveResume").onclick = () => {
  setActiveResume(null);
  renderResumes().catch((error) => showToast(error.message));
};

document.querySelector("#resumeUpload").onclick = async () => {
  resumeModal.classList.remove("hidden");
  await renderResumes();
};

document.querySelector("#resumeModalClose").onclick = () => resumeModal.classList.add("hidden");

resumeModal.onclick = (event) => {
  if (event.target === resumeModal) resumeModal.classList.add("hidden");
};

resumeFile.onchange = () => uploadResume(resumeFile.files[0]).catch((error) => showToast(error.message));

for (const eventName of ["dragenter", "dragover"]) {
  resumeDropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    resumeDropzone.classList.add("dragging");
  });
}

for (const eventName of ["dragleave", "drop"]) {
  resumeDropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    resumeDropzone.classList.remove("dragging");
  });
}

resumeDropzone.addEventListener("drop", (event) => {
  uploadResume(event.dataTransfer.files[0]).catch((error) => showToast(error.message));
});

for (const eventName of ["dragenter", "dragover"]) {
  composer.addEventListener(eventName, (event) => {
    event.preventDefault();
    composer.classList.add("dragging");
  });
}

for (const eventName of ["dragleave", "drop"]) {
  composer.addEventListener(eventName, (event) => {
    event.preventDefault();
    composer.classList.remove("dragging");
  });
}

composer.addEventListener("drop", (event) => {
  uploadResume(event.dataTransfer.files[0]).catch((error) => showToast(error.message));
});

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.onclick = () => sendMessage(button.dataset.prompt);
});

input.oninput = () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
};

input.onkeydown = (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    document.querySelector("#chatForm").requestSubmit();
  }
};

setActiveResume(state.activeResume);
loadSessions().catch((error) => showToast(error.message));
