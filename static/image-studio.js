const $ = (selector) => document.querySelector(selector);
let artworks = [];
let filter = new URLSearchParams(location.search).get("filter") === "favorites" ? "Favorites" : "All";
let query = "";
let pendingFile = null;
let previewUrl = null;
let selectedArtwork = null;
let editBase = null;
let reviewedDetails = null;
let busy = false;
let loading = false;
let loaded = false;
let openedLinkedArtwork = false;
let attachmentProjects = [];
let attachmentLoading = false;
const favoritePending = new Set();
const stageLabels = { reference: "Reference", progress: "Work in progress", finished: "Finished piece" };
const projectStatuses = { planned: "Planned", in_progress: "In progress", paused: "Paused", completed: "Completed" };
const collectionDetails = {
  AfroNova: { tags: "afrofuturism, cosmic, regal, Black identity, gold, visionary", notes: "A bold AfroNova piece blending Black identity, imagined futures, ancestral power, and celestial elegance." },
  "Quiet Nova": { tags: "reflective, calm, minimal, soft light, intimate, earth tones", notes: "A contemplative Quiet Nova piece centered on stillness, emotional depth, soft light, and grounded beauty." },
  GraffitiX: { tags: "street art, graffiti, urban, neon, expressive, mixed media", notes: "An energetic GraffitiX piece combining urban expression, layered marks, bold color, and raw creative movement." },
};
const escapeHtml = (value = "") => String(value).replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[character]));
function notify(message) { $("#toast").textContent = message; $("#toast").classList.add("show"); setTimeout(() => $("#toast").classList.remove("show"), 2200); }
function pageStatus(message) { $("#studioStatus").textContent = message; }
async function request(url, method = "GET", payload) {
  let response;
  try { response = await fetch(url, { method, cache: "no-store", ...(payload === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }) }); }
  catch { throw new Error("Could not reach the studio. Your current selection and edits are still here; please try again."); }
  let result;
  try { result = await response.json(); } catch { throw new Error("The studio could not finish that request. Please try again."); }
  if (!response.ok) { const error = new Error(typeof result.detail === "string" ? result.detail : "Check the artwork details, then try again."); error.status = response.status; throw error; }
  return result;
}
function controls() {
  document.querySelectorAll("#artForm input,#artForm textarea,#artForm button,#editForm input,#editForm textarea,#editForm button,#detailDialog button,#attachArtworkForm input,#attachArtworkForm select,#attachArtworkForm button,#uploadButton,#dropButton").forEach((control) => { control.disabled = busy; });
  $("#refreshArtwork").disabled = busy || loading || favoritePending.size > 0;
  $("#linkArtworkProject").disabled = busy || attachmentLoading || !$("#attachmentProject").value;
  $("#refreshAttachmentProjects").disabled = busy || attachmentLoading;
  $("#attachmentSearch").disabled = busy || attachmentLoading;
  $("#attachmentProject").disabled = busy || attachmentLoading;
  document.querySelectorAll(".art-favorite").forEach((button) => { button.disabled = busy || favoritePending.has(Number(button.dataset.id)); });
}
function setBusy(value) { busy = value; controls(); }
function syncItem(item) {
  const index = artworks.findIndex((artwork) => artwork.id === item.id);
  if (index >= 0) artworks[index] = { ...artworks[index], ...item };
  else artworks.unshift({ projects: [], ...item });
  render();
}
function render() {
  $("#artFilters").querySelectorAll("[data-collection]").forEach((button) => button.remove());
  const collections = [...new Set(artworks.map((artwork) => artwork.collection))].sort();
  if (!["All", "Favorites", ...collections.map((collection) => `collection:${collection}`)].includes(filter)) filter = "All";
  collections.forEach((collection) => {
    const button = document.createElement("button"); button.type = "button"; button.dataset.filter = `collection:${collection}`; button.dataset.collection = "true";
    button.textContent = ["All", "Favorites"].includes(collection) ? `Collection: ${collection}` : collection; $("#artFilters").appendChild(button);
  });
  $("#artFilters").querySelectorAll("button").forEach((button) => button.classList.toggle("active", button.dataset.filter === filter));
  const shown = artworks.filter((artwork) => (filter === "All" || (filter === "Favorites" ? artwork.favorite : artwork.collection === filter.slice(11)))
    && `${artwork.title} ${artwork.collection} ${artwork.tags} ${artwork.notes}`.toLowerCase().includes(query));
  $("#artGrid").replaceChildren(...shown.map((artwork) => {
    const card = document.createElement("article"); card.className = "art-card";
    card.innerHTML = `<a class="art-open" href="/image-studio?artwork=${artwork.id}"><img alt="${escapeHtml(artwork.title)}"><div class="art-meta"><h2>${escapeHtml(artwork.title)}</h2><p>${escapeHtml(artwork.collection)}${artwork.tags ? " · " + escapeHtml(artwork.tags) : ""}</p></div></a><button class="art-favorite ${artwork.favorite ? "on" : ""}" data-id="${artwork.id}" aria-pressed="${Boolean(artwork.favorite)}" aria-label="Favorite ${escapeHtml(artwork.title)}">★</button>`;
    card.querySelector("img").src = artwork.url;
    card.querySelector("a").onclick = (event) => { event.preventDefault(); showDetail(artwork); };
    card.querySelector(".art-favorite").onclick = async () => {
      if (busy || favoritePending.has(artwork.id)) return;
      favoritePending.add(artwork.id); controls();
      try { const result = await request(`/api/artworks/${artwork.id}/favorite?favorite=${!artwork.favorite}`, "PATCH"); if (artworks.some((item) => item.id === artwork.id)) syncItem({ id: artwork.id, favorite: result.favorite }); }
      catch (error) { pageStatus(error.message); }
      finally { favoritePending.delete(artwork.id); controls(); }
    };
    return card;
  }));
  $("#dropZone").hidden = !loaded || artworks.length > 0;
  $("#artEmpty").hidden = shown.length > 0 || artworks.length === 0;
  $("#artCount").textContent = loaded ? artworks.length : "—";
  controls();
}
async function load() {
  if (loading) return;
  loading = true; controls(); pageStatus("Loading your artwork…");
  try {
    artworks = await request("/api/artworks"); loaded = true; render();
    pageStatus(artworks.length ? `${artworks.length} saved ${artworks.length === 1 ? "image" : "images"}. Open one to edit its details or add it to a project.` : "Add your first image, then connect it to your studio work.");
    if (!openedLinkedArtwork) {
      openedLinkedArtwork = true;
      const id = new URLSearchParams(location.search).get("artwork");
      if (id) { const artwork = artworks.find((item) => String(item.id) === id); if (artwork) showDetail(artwork); else pageStatus("That image is no longer in Image Studio."); }
    }
  } catch (error) { pageStatus(loaded ? "Could not refresh. Your last loaded artwork is still shown; try Refresh artwork again." : error.message); }
  finally { loading = false; controls(); }
}
function releasePreview() { if (previewUrl) URL.revokeObjectURL(previewUrl); previewUrl = null; $("#artPreview").removeAttribute("src"); }
function prepare(file) {
  if (busy || !file) return;
  if (!["image/jpeg", "image/png", "image/webp", "image/gif"].includes(file.type) || !file.size || file.size > 10 * 1024 * 1024) { pageStatus("Choose a JPEG, PNG, WebP, or GIF up to 10 MB."); return; }
  releasePreview(); pendingFile = file; $("#artForm").reset(); $("#artTitle").value = file.name.replace(/\.[^.]+$/, "").slice(0, 200);
  previewUrl = URL.createObjectURL(file); $("#artPreview").src = previewUrl; $("#uploadStatus").textContent = ""; $("#artDialog").showModal();
}
function showDetail(artwork) {
  selectedArtwork = { projects: [], ...artwork };
  $("#detailImage").src = artwork.url; $("#detailImage").alt = artwork.title;
  $("#detailCollection").textContent = artwork.collection; $("#detailTitle").textContent = artwork.title;
  $("#detailNotes").textContent = artwork.notes || "No notes added yet."; $("#detailStatus").textContent = "";
  $("#detailTags").innerHTML = (artwork.tags || "").split(",").filter(Boolean).map((tag) => `<span>${escapeHtml(tag.trim())}</span>`).join("");
  $("#artworkProjects").replaceChildren(...selectedArtwork.projects.map((project) => { const link = document.createElement("a"); link.href = `/projects?project=${encodeURIComponent(project.project_id)}`; link.textContent = `${stageLabels[project.stage]} · ${project.title} →`; return link; }));
  $("#artworkDeleteNote").hidden = !selectedArtwork.projects.length;
  if (!$("#detailDialog").open) $("#detailDialog").showModal();
}
const readEdit = () => ({ title: $("#editTitle").value, collection: $("#editCollection").value, tags: $("#editTags").value, notes: $("#editNotes").value });
const details = (item) => ({ title: item.title, collection: item.collection, tags: item.tags || "", notes: item.notes || "" });
const editDirty = () => editBase && JSON.stringify(readEdit()) !== JSON.stringify(details(editBase));
function fillEdit(item) { for (const key of ["title", "collection", "tags", "notes"]) $("#edit" + key[0].toUpperCase() + key.slice(1)).value = item[key] || ""; }
function closeUpload() { if (busy || (pendingFile && !confirm("Discard this upload and its details?"))) return; $("#artDialog").close(); }
function closeEdit() { if (busy || (editDirty() && !confirm("Discard your unsaved artwork edits?"))) return; $("#editDialog").close(); }
document.querySelectorAll('[data-close="upload"]').forEach((button) => { button.onclick = closeUpload; });
document.querySelectorAll('[data-close="edit"]').forEach((button) => { button.onclick = closeEdit; });
$("#artDialog").addEventListener("cancel", (event) => { event.preventDefault(); closeUpload(); });
$("#editDialog").addEventListener("cancel", (event) => { event.preventDefault(); closeEdit(); });
$("#artDialog").addEventListener("close", () => { pendingFile = null; $("#fileInput").value = ""; releasePreview(); });
$("#editDialog").addEventListener("close", () => { editBase = null; reviewedDetails = null; });
for (const id of ["detailDialog", "attachArtworkDialog"]) $("#" + id).addEventListener("cancel", (event) => { if (busy) event.preventDefault(); });
const choose = () => { if (!busy) { $("#fileInput").value = ""; $("#fileInput").click(); } };
$("#uploadButton").onclick = choose; $("#dropButton").onclick = choose;
$("#fileInput").onchange = (event) => prepare(event.target.files[0]);
$("#dropZone").ondragover = (event) => { event.preventDefault(); $("#dropZone").classList.add("dragging"); };
$("#dropZone").ondragleave = () => $("#dropZone").classList.remove("dragging");
$("#dropZone").ondrop = (event) => { event.preventDefault(); $("#dropZone").classList.remove("dragging"); prepare(event.dataTransfer.files[0]); };
for (const prefix of ["art", "edit"]) $("#" + prefix + "Collection").onchange = (event) => { const suggestion = collectionDetails[event.target.value]; if (suggestion) for (const key of ["tags", "notes"]) { const input = $("#" + prefix + key[0].toUpperCase() + key.slice(1)); if (!input.value.trim()) input.value = suggestion[key]; } };
$("#artForm").onsubmit = async (event) => {
  event.preventDefault(); if (busy || !pendingFile) return;
  const payload = { title: $("#artTitle").value.trim(), collection: $("#artCollection").value.trim() || "Unsorted", tags: $("#artTags").value.trim(), notes: $("#artNotes").value.trim() };
  if (!payload.title) { $("#uploadStatus").textContent = "Give this artwork a title."; return; }
  setBusy(true); $("#uploadStatus").textContent = "Saving artwork…";
  try {
    payload.data_url = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(new Error("Could not read that image. Choose it again.")); reader.readAsDataURL(pendingFile); });
    const saved = await request("/api/artworks", "POST", payload);
    syncItem(saved); pendingFile = null; $("#artDialog").close();
    $("#lastSavedArtwork").href = `/image-studio?artwork=${saved.id}`; $("#lastSavedArtwork").hidden = false;
    pageStatus("Artwork saved. Open it to add it to a project."); notify("Artwork saved.");
  } catch (error) { $("#uploadStatus").textContent = error.message; }
  finally { setBusy(false); }
};
$("#editArtwork").onclick = () => {
  if (busy || !selectedArtwork) return;
  editBase = { ...selectedArtwork }; reviewedDetails = null; fillEdit(editBase);
  $("#latestDetails").hidden = true; $("#editStatus").textContent = "Changes are saved when you choose Save changes.";
  $("#detailDialog").close(); $("#editDialog").showModal();
};
$("#editForm").onsubmit = async (event) => {
  event.preventDefault(); if (busy || !editBase) return;
  if (!editBase.details_version) { $("#editStatus").textContent = "Review the latest saved details before saving this image."; return; }
  const payload = { ...readEdit(), expected_details_version: editBase.details_version };
  if (!payload.title.trim()) { $("#editStatus").textContent = "Give this artwork a title."; return; }
  setBusy(true); $("#editStatus").textContent = "Saving artwork details…";
  try {
    const saved = await request(`/api/artworks/${editBase.id}`, "PUT", payload); syncItem(saved);
    selectedArtwork = { ...selectedArtwork, ...saved }; editBase = null; $("#editDialog").close();
    pageStatus("Artwork details saved. Linked projects use the updated title and notes."); notify("Artwork details updated.");
  } catch (error) { $("#editStatus").textContent = error.message; }
  finally { setBusy(false); }
};
$("#reviewLatestDetails").onclick = async () => {
  if (busy || !editBase) return;
  setBusy(true); $("#editStatus").textContent = "Loading saved details for review…";
  try {
    const items = await request("/api/artworks"); const latest = items.find((item) => item.id === editBase.id);
    if (!latest) throw new Error("This image is no longer in the catalog. Your edits are still shown here.");
    artworks = items; render();
    reviewedDetails = latest; $("#latestDetailsFields").replaceChildren();
    for (const [label, value] of [["Title", latest.title], ["Collection", latest.collection], ["Tags", latest.tags], ["Notes", latest.notes]]) { const term = document.createElement("dt"); term.textContent = label; const description = document.createElement("dd"); description.textContent = value || "Not specified"; $("#latestDetailsFields").append(term, description); }
    $("#latestDetails").hidden = false; $("#editStatus").textContent = "Review the saved version below. Load it, or keep your edits for the next save.";
  } catch (error) { $("#editStatus").textContent = error.message; }
  finally { setBusy(false); }
};
$("#useSavedDetails").onclick = () => { if (!reviewedDetails || busy) return; editBase = { ...reviewedDetails }; fillEdit(editBase); $("#latestDetails").hidden = true; $("#editStatus").textContent = "The saved details are loaded."; };
$("#keepArtworkEdits").onclick = () => { if (!reviewedDetails || busy) return; editBase = { ...reviewedDetails }; $("#latestDetails").hidden = true; $("#editStatus").textContent = "Your edits are kept. The next Save changes will replace the saved details you just reviewed."; };
$("#reloadArtwork").onclick = async () => {
  if (busy || !selectedArtwork) return;
  setBusy(true);
  try { const latest = (await request("/api/artworks")).find((item) => item.id === selectedArtwork.id); if (!latest) throw new Error("This image is no longer in Image Studio."); syncItem(latest); showDetail(latest); $("#detailStatus").textContent = "Saved details reloaded."; }
  catch (error) { $("#detailStatus").textContent = error.message; }
  finally { setBusy(false); }
};
$("#removeArtwork").onclick = async () => {
  if (busy || !selectedArtwork) return;
  const item = selectedArtwork;
  if (!item.details_version) { $("#detailStatus").textContent = "Reload the saved details before removing this image."; return; }
  if (!confirm(`Remove “${item.title}” from Image Studio? Any project links to this image will also be removed.`)) return;
  setBusy(true);
  try { await request(`/api/artworks/${item.id}?expected_details_version=${encodeURIComponent(item.details_version)}`, "DELETE"); artworks = artworks.filter((artwork) => artwork.id !== item.id); render(); selectedArtwork = null; $("#detailDialog").close(); pageStatus("Artwork removed from the catalog and any linked projects."); }
  catch (error) { $("#detailStatus").textContent = error.message; }
  finally { setBusy(false); }
};
$("#detailClose").onclick = () => { if (!busy) $("#detailDialog").close(); };
$("#createArtworkPrompt").onclick = () => { if (!selectedArtwork) return; const art = selectedArtwork; const description = [art.notes, art.tags ? `Visual details: ${art.tags}` : ""].filter(Boolean).join(". "); location.href = `/chat?q=${encodeURIComponent(`Create an image prompt for ${art.title} in the ${art.collection} style${description ? `. Use this creative direction: ${description}` : ""}.`)}`; };

function renderProjectChoices() {
  const selected = $("#attachmentProject").value;
  const search = $("#attachmentSearch").value.trim().toLowerCase();
  const available = attachmentProjects.filter((project) => !selectedArtwork.projects.some((link) => link.project_id === project.id));
  const shown = available.filter((project) => `${project.title} ${project.materials.join(" ")}`.toLowerCase().includes(search));
  $("#attachmentProject").replaceChildren(new Option("Choose a project", ""), ...shown.map((project) => new Option(`${project.title} · ${projectStatuses[project.status]}`, project.id)));
  if (shown.some((project) => project.id === selected)) $("#attachmentProject").value = selected;
  $("#attachmentEmpty").hidden = attachmentProjects.length > 0;
  $("#attachmentHint").textContent = shown.length ? "Choose the project and how you want to use this image. Existing links are kept." : (attachmentProjects.length ? "No matching unlinked projects. Try another search, or use an existing project link in the artwork details." : "Create a project first, then return here to connect this image.");
  controls();
}
async function loadAttachmentProjects() {
  if (busy || attachmentLoading) return;
  attachmentLoading = true; controls(); $("#attachmentStatus").textContent = "Loading projects…";
  try { attachmentProjects = await request("/api/projects"); if ($("#attachArtworkDialog").open && selectedArtwork) { renderProjectChoices(); $("#attachmentStatus").textContent = ""; } }
  catch (error) { $("#attachmentStatus").textContent = error.message; }
  finally { attachmentLoading = false; controls(); }
}
$("#addArtworkToProject").onclick = () => {
  if (busy || !selectedArtwork) return;
  $("#detailDialog").close(); $("#attachArtworkForm").reset(); attachmentProjects = [];
  $("#attachmentProject").replaceChildren(new Option("Choose a project", "")); $("#attachmentEmpty").hidden = true;
  $("#attachArtworkTitle").textContent = selectedArtwork.title; $("#attachArtworkDialog").showModal(); loadAttachmentProjects();
};
$("#closeAttachArtwork").onclick = () => { if (!busy) { $("#attachArtworkDialog").close(); showDetail(selectedArtwork); } };
$("#attachArtworkDialog").addEventListener("cancel", (event) => { event.preventDefault(); if (!busy) { $("#attachArtworkDialog").close(); showDetail(selectedArtwork); } });
$("#attachmentSearch").oninput = renderProjectChoices;
$("#attachmentProject").onchange = controls;
$("#refreshAttachmentProjects").onclick = loadAttachmentProjects;
$("#attachArtworkForm").onsubmit = async (event) => {
  event.preventDefault(); if (busy || !selectedArtwork || !$("#attachmentProject").value) return;
  const project = attachmentProjects.find((item) => item.id === $("#attachmentProject").value);
  const stage = $("#attachmentStage").value;
  setBusy(true); $("#attachmentStatus").textContent = "Adding image to the project…";
  try {
    const result = await request(`/api/projects/${encodeURIComponent(project.id)}/artworks`, "POST", { artwork_id: selectedArtwork.id, stage });
    const actual = result.artworks.find((item) => item.id === selectedArtwork.id);
    selectedArtwork.projects = [...selectedArtwork.projects.filter((item) => item.project_id !== project.id), { project_id: project.id, title: project.title, stage: actual.stage }];
    syncItem(selectedArtwork); $("#attachArtworkDialog").close(); showDetail(selectedArtwork);
    $("#detailStatus").textContent = `Image ${result.created ? "added" : "already linked"} as ${stageLabels[actual.stage].toLowerCase()}. Open the project above to continue.`;
  } catch (error) { $("#attachmentStatus").textContent = error.message; }
  finally { setBusy(false); }
};
$("#artSearch").oninput = (event) => { query = event.target.value.trim().toLowerCase(); render(); };
$("#artFilters").onclick = (event) => { const button = event.target.closest("button[data-filter]"); if (button) { filter = button.dataset.filter; render(); } };
$("#refreshArtwork").onclick = load;
function closeMenu() { $("#sidebar").classList.remove("open"); $("#menuButton").setAttribute("aria-expanded", "false"); $("#menuButton").focus(); }
$("#menuButton").onclick = () => { $("#sidebar").classList.add("open"); $("#menuButton").setAttribute("aria-expanded", "true"); $("#closeMenu").focus(); };
$("#closeMenu").onclick = closeMenu;
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && $("#sidebar").classList.contains("open")) closeMenu(); });
window.addEventListener("beforeunload", (event) => { if (busy || pendingFile || editDirty()) { event.preventDefault(); event.returnValue = ""; } });
load();
