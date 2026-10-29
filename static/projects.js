const $ = (selector) => document.querySelector(selector);
const statuses = { planned: "Planned", in_progress: "In progress", paused: "Paused", completed: "Completed" };
let projects = [];
let current = null;
let dirty = false;
let busy = false;
let staleDraft = null;
let photos = [];
let catalog = [];
let photoBusy = false;
let previewUrl = null;
const photoStages = { reference: "Reference", progress: "Work in progress", finished: "Finished piece" };
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
  photos = project.artworks;
  renderPhotos();
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

function renderPhotos() {
  const shown = photos.filter((photo) => $("#photoFilter").value === "all" || photo.stage === $("#photoFilter").value);
  $("#projectPhotoGrid").replaceChildren(...shown.map((photo) => {
    const card = document.createElement("article");
    card.className = "project-photo-card";
    card.innerHTML = `<a class="photo-image-link" href="/image-studio?artwork=${encodeURIComponent(photo.id)}"><img loading="lazy" alt="${escapeHtml(photo.title)}"></a><div class="photo-card-body"><span class="project-badge">${photoStages[photo.stage]}</span><h4>${escapeHtml(photo.title)}</h4><p>${escapeHtml(photo.notes || "")}</p><small>Added ${escapeHtml(new Date(photo.created_at).toLocaleDateString())}</small><div class="photo-card-actions"><a href="/image-studio?artwork=${encodeURIComponent(photo.id)}">View in Image Studio ↗</a><button type="button" class="secondary unlink-photo">Unlink</button></div></div>`;
    card.querySelector("img").src = photo.url;
    card.querySelector(".unlink-photo").setAttribute("aria-label", `Unlink ${photo.title} from this project`);
    card.querySelector(".unlink-photo").disabled = photoBusy;
    card.querySelector(".unlink-photo").onclick = async () => {
      if (photoBusy) return;
      setPhotoBusy(true);
      try {
        const result = await photoRequest(`/api/projects/${encodeURIComponent(current.id)}/artworks/${photo.id}`, "DELETE");
        photos = result.artworks;
        renderPhotos();
        $("#photoStatus").textContent = "Photo unlinked. It is still saved in Image Studio.";
      } catch (error) { $("#photoStatus").textContent = error.message; }
      finally { setPhotoBusy(false); }
    };
    return card;
  }));
  $("#photoEmpty").hidden = shown.length > 0;
  $("#photoEmpty").textContent = photos.length ? "No photos with this label. Try another filter or add a photo." : "Add your first photo, or choose one you already saved in Image Studio.";
}

function setPhotoBusy(value) {
  photoBusy = value;
  document.querySelectorAll("#addProjectPhoto,#refreshProjectPhotos,.unlink-photo").forEach((control) => { control.disabled = value; });
}

async function photoRequest(url, method = "GET", payload) {
  let response;
  try {
    response = await fetch(url, { method, ...(payload === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }) });
  } catch { throw new Error("Could not reach the studio. Your photo selection is still here; please try again."); }
  let result;
  try { result = await response.json(); } catch { throw new Error("The photo request could not finish. Please try again."); }
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "The photo could not be saved. Check the details and try again.");
  return result;
}

function releasePreview() {
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null;
  $("#projectPhotoPreview").hidden = true;
  $("#projectPhotoPreview").removeAttribute("src");
}

function previewExisting() {
  releasePreview();
  const photo = catalog.find((item) => String(item.id) === $("#existingPhoto").value);
  if (photo) { $("#projectPhotoPreview").src = photo.url; $("#projectPhotoPreview").hidden = false; }
}

function filterCatalog() {
  const query = $("#photoSearch").value.trim().toLowerCase();
  const selected = $("#existingPhoto").value;
  const shown = catalog.filter((photo) => !photos.some((linked) => linked.id === photo.id)
    && `${photo.title} ${photo.collection} ${photo.notes}`.toLowerCase().includes(query));
  $("#existingPhoto").replaceChildren(...shown.map((photo) => new Option(`${photo.title} · ${photo.collection}`, String(photo.id))));
  if (shown.some((photo) => String(photo.id) === selected)) $("#existingPhoto").value = selected;
  $("#existingPhotoNote").textContent = shown.length ? "Only images not already linked to this project are listed." : "No matching images available. Try another search or upload a photo.";
  previewExisting();
}

async function changePhotoSource() {
  releasePreview();
  const upload = $("#photoSource").value === "upload";
  $("#photoUploadFields").hidden = !upload;
  $("#photoExistingFields").hidden = upload;
  $("#photoUploadFields").querySelectorAll("input,textarea").forEach((input) => { input.disabled = !upload; });
  $("#existingPhoto").required = !upload;
  $("#photoDialogStatus").textContent = "";
  if (upload) { previewFile(); return; }
  $("#saveProjectPhoto").disabled = true;
  $("#photoDialogStatus").textContent = "Loading Image Studio…";
  try {
    catalog = await photoRequest("/api/artworks");
    if ($("#photoSource").value === "existing") {
      filterCatalog();
      $("#photoDialogStatus").textContent = "";
    }
  } catch (error) { $("#photoDialogStatus").textContent = error.message; }
  finally { $("#saveProjectPhoto").disabled = false; }
}

function previewFile() {
  releasePreview();
  const file = $("#projectPhotoFile").files[0];
  if (!file) return;
  if (!["image/jpeg", "image/png", "image/webp", "image/gif"].includes(file.type) || file.size > 10 * 1024 * 1024 || !file.size) {
    $("#photoDialogStatus").textContent = "Choose a JPEG, PNG, WebP, or GIF up to 10 MB.";
    $("#projectPhotoFile").value = "";
    return;
  }
  $("#photoDialogStatus").textContent = "";
  if (!$("#projectPhotoTitle").value.trim()) $("#projectPhotoTitle").value = file.name.replace(/\.[^.]+$/, "").slice(0, 200);
  previewUrl = URL.createObjectURL(file);
  $("#projectPhotoPreview").src = previewUrl;
  $("#projectPhotoPreview").hidden = false;
}

function closePhotoDialog() { if (!photoBusy) $("#projectPhotoDialog").close(); }
$("#addProjectPhoto").onclick = () => {
  $("#projectPhotoForm").reset();
  $("#photoDialogStatus").textContent = "";
  $("#projectPhotoDialog").showModal();
  changePhotoSource();
};
$("#closePhotoDialog").onclick = closePhotoDialog;
$("#cancelPhotoDialog").onclick = closePhotoDialog;
$("#projectPhotoDialog").addEventListener("cancel", (event) => { if (photoBusy) event.preventDefault(); });
$("#projectPhotoDialog").addEventListener("close", releasePreview);
$("#projectPhotoFile").onchange = previewFile;
$("#photoSource").onchange = changePhotoSource;
$("#existingPhoto").onchange = previewExisting;
$("#photoSearch").oninput = filterCatalog;
$("#photoFilter").onchange = renderPhotos;
$("#projectPhotoForm").onsubmit = async (event) => {
  event.preventDefault();
  if (photoBusy || !current) return;
  const upload = $("#photoSource").value === "upload";
  const file = $("#projectPhotoFile").files[0];
  if (upload && (!file || !$("#projectPhotoTitle").value.trim())) return;
  if (!upload && !$("#existingPhoto").value) return;
  const payload = upload ? { title: $("#projectPhotoTitle").value.trim(), collection: $("#projectPhotoCollection").value.trim() || "Unsorted",
    notes: $("#projectPhotoNotes").value, project_id: current.id, project_stage: $("#projectPhotoStage").value }
    : { artwork_id: Number($("#existingPhoto").value), stage: $("#projectPhotoStage").value };
  setPhotoBusy(true);
  const controls = [...$("#projectPhotoForm").querySelectorAll("input,textarea,select,button")];
  const disabled = controls.map((control) => control.disabled);
  controls.forEach((control) => { control.disabled = true; });
  $("#photoDialogStatus").textContent = "Saving photo…";
  let saved = false;
  try {
    if (upload) {
      payload.data_url = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error("Could not read the selected photo. Choose it again."));
        reader.readAsDataURL(file);
      });
      const result = await photoRequest("/api/artworks", "POST", payload);
      // Update only the gallery so unsaved plan fields remain in place.
      photos = [{ id: result.id, title: payload.title, collection: payload.collection, notes: payload.notes,
        url: result.url, stage: payload.project_stage, created_at: new Date().toISOString() }, ...photos];
    } else {
      const result = await photoRequest(`/api/projects/${encodeURIComponent(current.id)}/artworks`, "POST", payload);
      photos = result.artworks;
    }
    saved = true;
    $("#photoFilter").value = "all";
    renderPhotos();
    $("#photoStatus").textContent = "Photo saved and linked to this project. Your plan edits are still as you left them.";
  } catch (error) { $("#photoDialogStatus").textContent = error.message; }
  finally {
    setPhotoBusy(false);
    controls.forEach((control, index) => { control.disabled = disabled[index]; });
    if (saved) $("#projectPhotoDialog").close();
  }
};
$("#refreshProjectPhotos").onclick = async () => {
  if (!current || photoBusy) return;
  setPhotoBusy(true);
  try {
    const project = await request(`/api/projects/${encodeURIComponent(current.id)}`);
    photos = project.artworks;
    renderPhotos();
    $("#photoStatus").textContent = "Photos refreshed. Your plan edits are still as you left them.";
  } catch (error) { $("#photoStatus").textContent = error.message; }
  finally { setPhotoBusy(false); }
};

let sheetCopy = null;
let sheetRequest = 0;
let sheetController = null;
const sheetActions = () => document.querySelectorAll(".sheet-actions button");
function clearSheet() {
  sheetCopy = null;
  sheetActions().forEach((button) => { button.disabled = true; });
  $("#projectSheetPreview").hidden = true;
  $("#projectSheetPreview").srcdoc = "";
}

$("#openProjectSheet").onclick = () => {
  if (!current || busy) return;
  if (!$("#projectForm").reportValidity()) {
    $("#saveStatus").textContent = "Check the plan fields before making a project sheet.";
    return;
  }
  $("#sheetOptions").reset();
  $("#sheetOptions").querySelectorAll("input,button").forEach((control) => { control.disabled = false; });
  $("#sheetPhotoChoices").replaceChildren(...photos.map((photo) => {
    const label = document.createElement("label");
    label.innerHTML = `<input type="checkbox" value="${photo.id}"><img alt=""><span>${escapeHtml(photo.title)}<small>${photoStages[photo.stage]}</small></span>`;
    label.querySelector("img").src = photo.url;
    return label;
  }));
  $("#sheetPhotoCount").textContent = `(${photos.length} available)`;
  $("#sheetNoPhotos").hidden = photos.length > 0;
  $("#sheetPhotoOptions").open = false;
  $("#sheetDraftNotice").textContent = dirty ? "This copy uses your current edits on this device. Making a copy does not save those changes." : "This copy uses the plan shown on this device. Making a copy does not change the saved project.";
  clearSheet();
  $("#projectSheetDialog").showModal();
  buildSheet();
};

async function buildSheet() {
  const photoIds = [...document.querySelectorAll("#sheetPhotoChoices input:checked")].map((input) => Number(input.value));
  clearSheet();
  if (photoIds.length > 12) { $("#sheetStatus").textContent = "Choose up to 12 photos for one project sheet."; return; }
  const requestId = ++sheetRequest;
  sheetController = new AbortController();
  const payload = { plan: readForm(), include_notes: $("#sheetNotes").checked, include_source: $("#sheetSource").checked, photo_ids: photoIds };
  $("#sheetOptions").querySelectorAll("input,button").forEach((control) => { control.disabled = true; });
  $("#sheetStatus").textContent = "Preparing your project sheet…";
  try {
    const response = await fetch(`/api/projects/${encodeURIComponent(current.id)}/sheet`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal: sheetController.signal,
    });
    let result;
    try { result = await response.json(); } catch { throw new Error("The studio could not prepare the sheet. Please try again."); }
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Check the plan fields and photo selections, then try again.");
    if (requestId !== sheetRequest) return;
    sheetCopy = result;
    $("#projectSheetPreview").srcdoc = result.html;
    $("#projectSheetPreview").hidden = false;
    $("#sheetStatus").textContent = `${result.snapshot}. ${result.warning || "Your copy is ready. Making it does not save plan changes."}`;
  } catch (error) {
    if (requestId === sheetRequest && error.name !== "AbortError") $("#sheetStatus").textContent = error instanceof TypeError ? "Could not reach the studio. Your plan is still here; try making the preview again." : error.message;
  } finally {
    if (requestId === sheetRequest) {
      sheetController = null;
      $("#sheetOptions").querySelectorAll("input,button").forEach((control) => { control.disabled = false; });
    }
  }
}

$("#projectSheetPreview").onload = () => {
  if (sheetCopy && $("#projectSheetPreview").srcdoc === sheetCopy.html) sheetActions().forEach((button) => { button.disabled = false; });
};
$("#sheetOptions").onsubmit = (event) => { event.preventDefault(); buildSheet(); };
$("#sheetOptions").onchange = () => { clearSheet(); $("#sheetStatus").textContent = "Options changed. Make preview to update your copy."; };
$("#closeProjectSheet").onclick = () => $("#projectSheetDialog").close();
$("#projectSheetDialog").addEventListener("close", () => {
  ++sheetRequest;
  sheetController?.abort();
  sheetController = null;
  clearSheet();
});
$("#printProjectSheet").onclick = () => {
  if (!sheetCopy) return;
  try { $("#projectSheetPreview").contentWindow.focus(); $("#projectSheetPreview").contentWindow.print(); }
  catch { $("#sheetStatus").textContent = "Printing is unavailable here. Download the HTML copy, then open it in your browser to print."; }
};
function downloadSheet(format) {
  if (!sheetCopy) return;
  const url = URL.createObjectURL(new Blob([sheetCopy[format === "html" ? "html" : "text"]], { type: format === "html" ? "text/html;charset=utf-8" : "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${sheetCopy.filename}.${format}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
$("#downloadProjectSheet").onclick = () => downloadSheet("html");
$("#downloadProjectText").onclick = () => downloadSheet("txt");
const requestedStatus = new URLSearchParams(location.search).get("status");
if (Object.hasOwn(statuses, requestedStatus)) $("#projectFilter").value = requestedStatus;
load();
