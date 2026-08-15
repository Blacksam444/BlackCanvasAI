let prompts = [];
let filter = "All";
let query = "";
let editingId = null;
const selectedIds = new Set();
const grid = document.querySelector("#promptGrid");
const empty = document.querySelector("#empty");
const toast = document.querySelector("#toast");
const dialog = document.querySelector("#promptDialog");
const canonicalCategories = ["AfroNova", "Quiet Nova", "GraffitiX", "Content", "Business", "Unsorted"];

const notify = message => {
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2200);
};
const escape = text => (text || "").replace(/[&<>"']/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"})[character]);
const normalizedText = text => (text || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

function duplicateGroups() {
  const groups = new Map();
  prompts.forEach(prompt => {
    const key = normalizedText(prompt.text);
    if (!key) return;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(prompt.id);
  });
  return [...groups.values()].filter(group => group.length > 1);
}

function duplicateIds() {
  return new Set(duplicateGroups().flat());
}

function duplicateExtraIds() {
  return duplicateGroups().flatMap(group => {
    const ordered = group
      .map(id => prompts.find(prompt => prompt.id === id))
      .filter(Boolean)
      .sort((a, b) => Number(b.favorite) - Number(a.favorite) || a.id - b.id);
    return ordered.slice(1).map(prompt => prompt.id);
  });
}

function sourceLabel(source) {
  return source === "chatgpt" ? "ChatGPT" : source === "drive" ? "Google Drive" : "Manual";
}

function visiblePrompts() {
  const duplicates = duplicateIds();
  return prompts.filter(prompt => {
    const matchesFilter = filter === "All"
      || (filter === "Unreviewed" && !prompt.reviewed)
      || (filter === "Duplicates" && duplicates.has(prompt.id))
      || (filter === "Syntax issues" && prompt.syntax_issues?.length)
      || (filter === "Favorites" && prompt.favorite)
      || (filter === "ChatGPT" && prompt.source === "chatgpt")
      || prompt.category === filter;
    const searchable = `${prompt.title} ${prompt.category} ${prompt.text} ${sourceLabel(prompt.source)}`.toLowerCase();
    return matchesFilter && searchable.includes(query);
  });
}

function updateBulkToolbar() {
  const toolbar = document.querySelector("#bulkToolbar");
  toolbar.hidden = selectedIds.size === 0;
  document.querySelector("#selectedCount").textContent = `${selectedIds.size} selected`;
}

async function load() {
  const response = await fetch("/api/prompts");
  prompts = await response.json();
  for (const id of [...selectedIds]) if (!prompts.some(prompt => prompt.id === id)) selectedIds.delete(id);
  render();
}

async function migrate() {
  const saved = JSON.parse(localStorage.getItem("blackCanvasPrompts") || "null");
  if (!saved) return;
  for (const prompt of saved) {
    await fetch("/api/prompts", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({title:prompt.title, category:prompt.category, text:prompt.text, favorite:Boolean(prompt.favorite)}),
    });
  }
  localStorage.removeItem("blackCanvasPrompts");
}

function render() {
  const shown = visiblePrompts();
  const duplicates = duplicateIds();
  grid.innerHTML = "";
  shown.forEach(prompt => {
    const card = document.createElement("article");
    card.className = `prompt-card${selectedIds.has(prompt.id) ? " selected" : ""}${!prompt.reviewed ? " unreviewed" : ""}`;
    card.innerHTML = `<div class="card-top"><label class="select-prompt"><input type="checkbox" ${selectedIds.has(prompt.id) ? "checked" : ""}><span></span></label><div class="card-badges"><span class="category">${escape(prompt.category)}</span><span class="source ${escape(prompt.source)}">${sourceLabel(prompt.source)}</span>${!prompt.reviewed ? '<span class="review-badge">Unreviewed</span>' : ""}${duplicates.has(prompt.id) ? '<span class="duplicate-badge">Duplicate</span>' : ""}${prompt.syntax_issues?.length ? '<span class="syntax-badge">Syntax issue</span>' : ""}</div><button class="favorite ${prompt.favorite ? "on" : ""}" title="Favorite">★</button></div><h2>${escape(prompt.title)}</h2><p class="prompt-preview">${escape(prompt.text)}</p><div class="card-bottom"><button class="view">Review & edit</button><button class="copy">Copy prompt</button></div>`;
    const checkbox = card.querySelector('input[type="checkbox"]');
    checkbox.onchange = () => {
      if (checkbox.checked) selectedIds.add(prompt.id);
      else selectedIds.delete(prompt.id);
      render();
    };
    card.querySelector(".favorite").onclick = async () => {
      prompt.favorite = !prompt.favorite;
      await fetch(`/api/prompts/${prompt.id}/favorite?favorite=${prompt.favorite}`, {method:"PATCH"});
      render();
    };
    card.querySelector(".copy").onclick = async () => {
      await navigator.clipboard.writeText(prompt.text);
      notify("Prompt copied.");
    };
    card.querySelector(".view").onclick = () => openEditor(prompt);
    grid.appendChild(card);
  });
  empty.hidden = shown.length > 0;
  document.querySelector("#promptCount").textContent = prompts.length;
  document.querySelector("#unreviewedCount").textContent = prompts.filter(prompt => !prompt.reviewed).length;
  const groups = duplicateGroups();
  const duplicateTools = document.querySelector("#duplicateTools");
  duplicateTools.hidden = filter !== "Duplicates";
  document.querySelector("#duplicateSummary").textContent = groups.length
    ? `${duplicateIds().size} prompts in ${groups.length} duplicate ${groups.length === 1 ? "group" : "groups"}`
    : "No duplicate prompts found";
  document.querySelector("#selectDuplicateExtras").disabled = groups.length === 0;
  updateBulkToolbar();
}

function openEditor(prompt = null) {
  editingId = prompt?.id || null;
  document.querySelector("#promptForm").reset();
  document.querySelector("#dialogEyebrow").textContent = prompt ? "REVIEW CREATIVE RECIPE" : "NEW CREATIVE RECIPE";
  document.querySelector("#dialogTitle").textContent = prompt ? "Review and organize" : "Add a prompt";
  document.querySelector("#savePrompt").textContent = prompt ? "Save changes" : "Save prompt";
  document.querySelector("#deletePrompt").hidden = !prompt;
  const syntaxRepair = document.querySelector("#syntaxRepair");
  syntaxRepair.hidden = !prompt?.syntax_issues?.length;
  document.querySelector("#syntaxRepairMessage").textContent = prompt?.syntax_issues?.join(" · ") || "";
  if (prompt) {
    document.querySelector("#promptTitle").value = prompt.title;
    document.querySelector("#promptCategory").value = canonicalCategories.includes(prompt.category) ? prompt.category : "Unsorted";
    document.querySelector("#promptText").value = prompt.text;
  }
  dialog.showModal();
}

document.querySelector("#searchInput").oninput = event => { query = event.target.value.toLowerCase().trim(); render(); };
document.querySelectorAll("#filters button").forEach(button => button.onclick = () => {
  document.querySelectorAll("#filters button").forEach(item => item.classList.remove("active"));
  button.classList.add("active");
  filter = button.dataset.filter;
  render();
});
document.querySelector("#addPrompt").onclick = () => openEditor();
document.querySelector("#savePrompt").onclick = async event => {
  event.preventDefault();
  const title = document.querySelector("#promptTitle").value.trim();
  const text = document.querySelector("#promptText").value.trim();
  if (!title || !text) return;
  const payload = {title, category:document.querySelector("#promptCategory").value, text, favorite:prompts.find(prompt => prompt.id === editingId)?.favorite || false};
  const response = await fetch(editingId ? `/api/prompts/${editingId}` : "/api/prompts", {
    method: editingId ? "PUT" : "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify(payload),
  });
  if (!response.ok) return notify("That prompt is already saved.");
  dialog.close();
  await load();
  notify(editingId ? "Prompt reviewed and updated." : "Prompt saved permanently.");
};
document.querySelector("#deletePrompt").onclick = async () => {
  if (!editingId || !window.confirm("Remove this prompt from the library?")) return;
  await fetch(`/api/prompts/${editingId}`, {method:"DELETE"});
  selectedIds.delete(editingId);
  dialog.close();
  await load();
  notify("Prompt removed from the library.");
};
document.querySelector("#repairSyntax").onclick = async () => {
  if (!editingId) return;
  const response = await fetch(`/api/prompts/${editingId}/repair-midjourney-syntax`, {method:"PATCH"});
  const result = await response.json();
  if (!response.ok) return notify(result.detail || "The syntax could not be repaired.");
  document.querySelector("#promptText").value = result.text;
  document.querySelector("#syntaxRepair").hidden = true;
  await load();
  notify("MidJourney syntax repaired with --raw.");
};

async function bulkUpdate(changes, successMessage) {
  const response = await fetch("/api/prompts/bulk-update", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({prompt_ids:[...selectedIds], ...changes}),
  });
  const result = await response.json();
  if (!response.ok) return notify(result.detail || "Those prompts could not be updated.");
  selectedIds.clear();
  await load();
  notify(`${result.updated} ${successMessage}`);
}
document.querySelector("#applyCategory").onclick = () => {
  const category = document.querySelector("#bulkCategory").value;
  if (!category) return notify("Choose a collection first.");
  bulkUpdate({category, reviewed:true}, "prompts organized.");
};
document.querySelector("#markReviewed").onclick = () => bulkUpdate({reviewed:true}, "prompts marked reviewed.");
document.querySelector("#selectDuplicateExtras").onclick = () => {
  selectedIds.clear();
  duplicateExtraIds().forEach(id => selectedIds.add(id));
  render();
  notify(selectedIds.size ? `${selectedIds.size} extra ${selectedIds.size === 1 ? "copy" : "copies"} selected for review.` : "No extra copies found.");
};
document.querySelector("#removeSelected").onclick = async () => {
  if (!selectedIds.size || !window.confirm(`Remove ${selectedIds.size} selected ${selectedIds.size === 1 ? "prompt" : "prompts"} from the library? This cannot be undone.`)) return;
  const response = await fetch("/api/prompts/bulk-delete", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({prompt_ids:[...selectedIds]}),
  });
  const result = await response.json();
  if (!response.ok) return notify(result.detail || "Those prompts could not be removed.");
  selectedIds.clear();
  await load();
  notify(`${result.deleted} ${result.deleted === 1 ? "prompt" : "prompts"} removed.`);
};
document.querySelector("#clearSelection").onclick = () => { selectedIds.clear(); render(); };
document.querySelector("#menuButton").onclick = () => document.querySelector("#sidebar").classList.toggle("open");
migrate().then(load).catch(() => notify("Could not load the prompt library."));
