const $ = (selector) => document.querySelector(selector);
const statuses = { planned: "Planned", in_progress: "In progress", paused: "Paused", completed: "Completed" };
let projects = [];
let current = null;
let dirty = false;
let busy = false;
let staleDraft = null;
const escapeHtml = (value = "") => String(value).replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
}[character]));
const draftKey = () => `blackCanvasProjectDraft:${current.id}`;

async function request(url, payload) {
  let response;
  try {
    response = await fetch(url, payload === undefined ? {} : { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  } catch { throw new Error("Could not reach the studio. Your edits are still here; try again when connected."); }
  let result;
  try { result = await response.json(); }
  catch { throw new Error("The studio could not finish that request. Please try again."); }
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Check the project fields, then try again.");
  return result;
}

function readForm() {
  return {
    title: $("#projectTitle").value.trim(), status: $("#projectStatus").value, surface: $("#projectSurface").value,
    materials: $("#projectMaterials").value.split("\n").map((value) => value.trim()).filter(Boolean),
    notes: $("#projectNotes").value, revision: current.revision,
    checklist: [...document.querySelectorAll("#projectChecklist li")].map((row) => ({
      id: row.dataset.id, text: row.querySelector("textarea").value, done: row.querySelector("input").checked,
    })),
  };
}

function updateProgress() {
  const rows = [...document.querySelectorAll("#projectChecklist li")];
  rows.forEach((row, index) => {
    row.querySelector("input").setAttribute("aria-label", `Step ${index + 1} completed`);
    row.querySelector("textarea").setAttribute("aria-label", `Studio step ${index + 1}`);
    row.querySelector("button").setAttribute("aria-label", `Remove step ${index + 1}`);
  });
  const done = rows.filter((row) => row.querySelector("input").checked).length;
  $("#projectProgress").textContent = rows.length ? `${done} of ${rows.length} studio steps checked` : "Add the studio steps that work for you.";
  $("#projectProgressBar").value = rows.length ? Math.round(done / rows.length * 100) : 0;
  $("#projectStatusBadge").textContent = statuses[$("#projectStatus").value];
}

function resizeSteps() {
  document.querySelectorAll("#projectChecklist textarea").forEach((input) => {
    input.style.height = "auto";
    input.style.height = `${Math.max(64, input.scrollHeight + 2)}px`;
  });
}

function rememberDraft() {
  if (!current || busy) return;
  dirty = true;
  $("#saveStatus").textContent = "Unsaved edits. Save project to keep progress across your connected devices.";
  try { localStorage.setItem(draftKey(), JSON.stringify(readForm())); }
  catch { $("#draftNote").textContent = "This browser can’t keep an unsaved draft. Save project before leaving."; }
  updateProgress();
}

function makeStep(step) {
  const row = document.createElement("li");
  row.dataset.id = step.id;
  row.innerHTML = `<input type="checkbox" aria-label="Step completed" ${step.done ? "checked" : ""}><textarea rows="2" maxlength="2000" required aria-label="Studio step">${escapeHtml(step.text)}</textarea><button class="remove-step" type="button" aria-label="Remove this step">×</button>`;
  row.querySelector("button").onclick = () => { row.remove(); rememberDraft(); };
  return row;
}

function applyForm(project) {
  $("#projectTitle").value = project.title;
  $("#projectStatus").value = project.status;
  $("#projectSurface").value = project.surface;
  $("#projectMaterials").value = project.materials.join("\n");
  $("#projectNotes").value = project.notes;
  $("#projectChecklist").replaceChildren(...project.checklist.map(makeStep));
  resizeSteps();
  updateProgress();
}

function validDraft(value) {
  return value && Number.isInteger(value.revision) && value.revision > 0 && typeof value.title === "string" && value.title.length <= 200
    && Object.hasOwn(statuses, value.status) && typeof value.surface === "string" && value.surface.length <= 240
    && typeof value.notes === "string" && value.notes.length <= 5000
    && Array.isArray(value.materials) && value.materials.length <= 30 && value.materials.every((item) => typeof item === "string" && item.length <= 240)
    && Array.isArray(value.checklist) && value.checklist.length <= 60
    && new Set(value.checklist.map((step) => step?.id)).size === value.checklist.length
    && value.checklist.every((step) => step && typeof step.id === "string" && /^[A-Za-z0-9_-]{1,80}$/.test(step.id)
      && typeof step.text === "string" && step.text.length <= 2000 && typeof step.done === "boolean");
}

async function loadProject(id, recover = true) {
  const project = await request(`/api/projects/${encodeURIComponent(id)}`);
  current = project;
  dirty = false;
  staleDraft = null;
  $("#recoverDraft").hidden = true;
  $("#projectHeading").textContent = project.title;
  $("#overview").hidden = true;
  $("#projectDetail").hidden = false;
  $("#pageStatus").textContent = "Project saved in your studio. Changes below are saved when you choose Save project.";
  const source = project.source_prompt;
  $("#sourceTitle").textContent = source?.title || "Source idea unavailable";
  $("#sourceText").textContent = source?.text || "Your project checklist and notes are kept even if its source idea is unavailable.";
  $("#sourceState").textContent = source?.trashed ? "The original idea is in Trash. Your project is still available." : (source?.category || "");
  $("#sourceLink").href = source ? `/prompts?prompt=${encodeURIComponent(source.id)}` : "/prompts";
  applyForm(project);
  $("#saveStatus").textContent = `Saved ${new Date(project.updated_at).toLocaleString()}.`;
  if (recover) {
    let draft;
    try { draft = JSON.parse(localStorage.getItem(draftKey()) || "null"); } catch { /* Ignore unavailable or invalid browser storage. */ }
    if (validDraft(draft)) {
      if (draft.revision === project.revision) {
        applyForm(draft);
        dirty = true;
        $("#saveStatus").textContent = "Your unsaved edits were restored on this device. Save project when ready.";
      } else {
        staleDraft = draft;
        $("#recoverDraft").hidden = false;
        $("#saveStatus").textContent = "A newer version is saved in the studio. Your older unsaved draft is kept on this device for review.";
      }
    }
  }
}

function renderProjects() {
  const query = $("#projectSearch").value.trim().toLowerCase();
  const filter = $("#projectFilter").value;
  const shown = projects.filter((project) => (filter === "all" || project.status === filter)
    && `${project.title} ${project.materials.join(" ")} ${project.notes}`.toLowerCase().includes(query));
  $("#projectGrid").innerHTML = shown.map((project) => `<a class="project-card" href="/projects?project=${encodeURIComponent(project.id)}"><span class="project-badge">${statuses[project.status]}</span><h2>${escapeHtml(project.title)}</h2><p>${escapeHtml(project.materials.join(" · ") || "Choose your project materials")}</p><progress max="100" value="${project.progress.percent}" aria-label="${project.progress.percent}% of checklist complete"></progress><small>${project.progress.done} of ${project.progress.total} steps · Open project →</small></a>`).join("");
  $("#projectEmpty").hidden = shown.length > 0;
  $("#projectEmpty h2").textContent = projects.length ? "No matching projects" : "No projects here yet";
}

async function load() {
  try {
    projects = await request("/api/projects");
    renderProjects();
    const id = new URLSearchParams(location.search).get("project");
    if (id) await loadProject(id);
    else $("#pageStatus").textContent = projects.length ? `${projects.length} saved ${projects.length === 1 ? "project" : "projects"}.` : "Start a project from a Think Tank idea or a saved library prompt.";
  } catch (error) {
    $("#pageStatus").textContent = error.message;
  }
}

$("#projectForm").addEventListener("input", () => { resizeSteps(); rememberDraft(); });
$("#projectForm").addEventListener("change", rememberDraft);
$("#projectForm").onsubmit = async (event) => {
  event.preventDefault();
  if (busy || !current) return;
  const payload = readForm();
  if (payload.materials.length > 30 || payload.materials.some((value) => value.length > 240)) {
    $("#saveStatus").textContent = "Use up to 30 materials, each under 240 characters.";
    return;
  }
  busy = true;
  $("#projectForm").querySelectorAll("input,select,textarea,button").forEach((control) => { control.disabled = true; });
  $("#saveStatus").textContent = "Saving your project…";
  try {
    const saved = await request(`/api/projects/${encodeURIComponent(current.id)}`, payload);
    current = saved;
    dirty = false;
    try { localStorage.removeItem(draftKey()); } catch { /* The server save succeeded. */ }
    applyForm(saved);
    $("#projectHeading").textContent = saved.title;
    $("#recoverDraft").hidden = true;
    $("#saveStatus").textContent = "Project saved. You can reopen this progress on your other connected devices.";
  } catch (error) {
    $("#saveStatus").textContent = error.message;
  } finally {
    busy = false;
    $("#projectForm").querySelectorAll("input,select,textarea,button").forEach((control) => { control.disabled = false; });
  }
};
$("#addStep").onclick = () => {
  if ($("#projectChecklist").children.length >= 60) {
    $("#saveStatus").textContent = "Use up to 60 studio steps per project.";
    return;
  }
  const row = makeStep({ id: `step_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`, text: "", done: false });
  $("#projectChecklist").appendChild(row);
  resizeSteps();
  row.querySelector("textarea").focus();
  rememberDraft();
};
$("#reloadProject").onclick = async () => {
  if (dirty && !confirm("Discard your unsaved edits and load the saved project?")) return;
  try {
    await loadProject(current.id, false);
    try { localStorage.removeItem(draftKey()); } catch { /* Browser drafts are optional. */ }
  } catch (error) { $("#saveStatus").textContent = error.message; }
};
$("#recoverDraft").onclick = () => {
  if (!staleDraft) return;
  applyForm(staleDraft);
  rememberDraft();
  $("#recoverDraft").hidden = true;
  $("#saveStatus").textContent = "Older edits loaded for review. Saving will replace the latest saved version with the fields shown here.";
};
$("#projectSearch").oninput = renderProjects;
$("#projectFilter").onchange = renderProjects;
$("#refreshProjects").onclick = load;
const closeMenu = () => {
  $("#sidebar").classList.remove("open");
  $("#menuButton").setAttribute("aria-expanded", "false");
  $("#menuButton").focus();
};
$("#menuButton").onclick = () => {
  $("#sidebar").classList.add("open");
  $("#menuButton").setAttribute("aria-expanded", "true");
  $("#closeMenu").focus();
};
$("#closeMenu").onclick = closeMenu;
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && $("#sidebar").classList.contains("open")) closeMenu(); });
window.addEventListener("beforeunload", (event) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } });
window.addEventListener("resize", resizeSteps);
load();
