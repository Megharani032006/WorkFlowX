// WorkFlowX front-end. All data moves through fetch() calls to the Flask API.
const $ = (s) => document.querySelector(s);
const REFRESH_MS = 15000; // auto-refresh. To add WebSockets later, replace this timer with a socket "tasks_changed" event that calls loadAll().

function esc(v) {
  const d = document.createElement("div");
  d.textContent = v == null ? "" : String(v);
  return d.innerHTML;
}

async function api(url, options = {}) {
  const res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  if (res.status === 401) { location.href = "/login"; throw new Error("Please log in."); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Something went wrong.");
  return data;
}

function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (isError ? " err" : "");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.className = ""), 2500);
}

function query() {
  const p = new URLSearchParams({
    q: $("#search").value, status: $("#f-status").value, priority: $("#f-priority").value,
    category: $("#f-category").value, sort: $("#f-sort").value,
  });
  return p.toString();
}

async function loadStats() {
  const s = await api("/api/stats");
  $("#st-total").textContent = s.total;
  $("#st-pending").textContent = s.pending;
  $("#st-progress").textContent = s.in_progress;
  $("#st-done").textContent = s.completed;
  $("#st-overdue").textContent = s.overdue;
  const sel = $("#f-category"), current = sel.value;
  sel.innerHTML = '<option value="">All categories</option>' +
    s.categories.map((c) => `<option>${esc(c)}</option>`).join("");
  sel.value = s.categories.includes(current) ? current : "";
}

function statusInfo(t) {
  if (t.status === "Completed") return ["st-done", "b-done"];
  if (t.status === "In Progress") return ["st-progress", "b-progress"];
  return ["", "b-pending"];
}

function render(tasks) {
  const box = $("#task-list");
  if (!tasks.length) {
    box.innerHTML = '<div class="empty">No tasks match. Click “Add task” to create one.</div>';
    return;
  }
  box.innerHTML = tasks.map((t) => {
    const [cardCls, badgeCls] = statusInfo(t);
    return `<article class="task ${cardCls} ${t.overdue ? "overdue" : ""}">
      <h3>${esc(t.title)}</h3>
      ${t.description ? `<p>${esc(t.description)}</p>` : ""}
      <div class="badges">
        <span class="badge ${badgeCls}">${esc(t.status)}</span>
        <span class="badge ${t.priority === "High" ? "b-high" : ""}">${esc(t.priority)} priority</span>
        ${t.overdue ? '<span class="badge b-overdue">Overdue</span>' : ""}
        ${t.category ? `<span class="badge">${esc(t.category)}</span>` : ""}
      </div>
      <div class="meta">Due ${esc(t.due_date)}</div>
      <div class="actions">
        ${t.status !== "Completed" ? `<button class="btn sm ok" data-act="done" data-id="${t.id}">✓ Complete</button>` : ""}
        <button class="btn sm ghost" data-act="edit" data-id="${t.id}">✎ Edit</button>
        <button class="btn sm ghost danger" data-act="del" data-id="${t.id}">🗑 Delete</button>
      </div>
    </article>`;
  }).join("");
  box._tasks = tasks;
}

async function loadAll() {
  try {
    const [tasks] = await Promise.all([api("/api/tasks?" + query()), loadStats()]);
    render(tasks);
  } catch (e) { toast(e.message, true); }
}

// ---- Modal ----
const modal = $("#task-modal");
function openModal(task) {
  $("#form-error").hidden = true;
  $("#modal-title").textContent = task ? "Edit task" : "Add task";
  $("#task-id").value = task ? task.id : "";
  $("#t-title").value = task ? task.title : "";
  $("#t-desc").value = task ? task.description : "";
  $("#t-priority").value = task ? task.priority : "Medium";
  $("#t-status").value = task ? task.status : "Pending";
  $("#t-due").value = task ? task.due_date : new Date().toISOString().slice(0, 10);
  $("#t-cat").value = task ? task.category : "";
  modal.showModal();
}

$("#add-btn").onclick = () => openModal(null);
$("#cancel-btn").onclick = () => modal.close();

$("#task-form").onsubmit = async (e) => {
  e.preventDefault();
  const id = $("#task-id").value;
  const body = JSON.stringify({
    title: $("#t-title").value, description: $("#t-desc").value, priority: $("#t-priority").value,
    status: $("#t-status").value, due_date: $("#t-due").value, category: $("#t-cat").value,
  });
  try {
    await api(id ? `/api/tasks/${id}` : "/api/tasks", { method: id ? "PUT" : "POST", body });
    modal.close();
    toast(id ? "Task updated." : "Task created.");
    loadAll();
  } catch (err) {
    const box = $("#form-error");
    box.textContent = err.message;
    box.hidden = false;
  }
};

// ---- Card buttons ----
$("#task-list").onclick = async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const id = btn.dataset.id;
  try {
    if (btn.dataset.act === "edit") {
      openModal($("#task-list")._tasks.find((t) => String(t.id) === id));
    } else if (btn.dataset.act === "done") {
      await api(`/api/tasks/${id}/complete`, { method: "PATCH" });
      toast("Task completed."); loadAll();
    } else if (btn.dataset.act === "del" && confirm("Delete this task?")) {
      await api(`/api/tasks/${id}`, { method: "DELETE" });
      toast("Task deleted."); loadAll();
    }
  } catch (err) { toast(err.message, true); loadAll(); }
};

// ---- Search / filters ----
let timer;
$("#search").oninput = () => { clearTimeout(timer); timer = setTimeout(loadAll, 250); };
["#f-status", "#f-priority", "#f-category", "#f-sort"].forEach((s) => ($(s).onchange = loadAll));

loadAll();
setInterval(() => { if (!modal.open) loadAll(); }, REFRESH_MS);
