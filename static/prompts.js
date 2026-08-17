let prompts = [];
let filter = "All";
let query = "";
const requestedFilter = new URLSearchParams(window.location.search).get("filter");
const supportedSorts = new Set(["newest", "oldest", "title", "collection", "favorites"]);
let sortMode = localStorage.getItem("blackCanvasPromptSort") || "newest";
if (!supportedSorts.has(sortMode)) sortMode = "newest";
let editingId = null;
const selectedIds = new Set();
const grid = document.querySelector("#promptGrid");
const empty = document.querySelector("#empty");
const toast = document.querySelector("#toast");
const dialog = document.querySelector("#promptDialog");
const canonicalCategories = ["AfroNova", "Quiet Nova", "GraffitiX", "Content", "Business", "Unsorted"];
document.querySelectorAll("#filters button").forEach(button => {
  button.dataset.label = button.textContent;
  button.insertAdjacentHTML("beforeend", '<span class="filter-count">0</span>');
});
const requestedFilterButton = [...document.querySelectorAll("#filters button")]
  .find(button => button.dataset.filter === requestedFilter);
if (requestedFilterButton) {
  filter = requestedFilter;
  document.querySelectorAll("#filters button").forEach(button => button.classList.toggle("active", button === requestedFilterButton));
}

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
    if (prompt.trashed) return;
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
  const visible = prompts.filter(prompt => {
    const matchesFilter = (filter === "Trash" && prompt.trashed)
      || (!prompt.trashed && (filter === "All"
      || (filter === "Unreviewed" && !prompt.reviewed)
      || (filter === "Duplicates" && duplicates.has(prompt.id))
      || (filter === "Syntax issues" && prompt.syntax_issues?.length)
      || (filter === "Version copies" && prompt.parent_prompt_id)
      || (filter === "Untested copies" && prompt.parent_prompt_id && !prompt.version_test_result)
      || (filter === "Active preferred" && prompt.version_test_result === "active")
      || (filter === "Original preferred" && prompt.version_test_result === "original")
      || (filter === "No clear winner" && prompt.version_test_result === "tie")
      || (filter === "Favorites" && prompt.favorite)
      || (filter === "ChatGPT" && prompt.source === "chatgpt")
      || prompt.category === filter));
    const searchable = `${prompt.title} ${prompt.category} ${prompt.text} ${sourceLabel(prompt.source)}`.toLowerCase();
    return matchesFilter && searchable.includes(query);
  });
  const byTitle = (a, b) => a.title.localeCompare(b.title, undefined, {sensitivity:"base"}) || b.id - a.id;
  if (sortMode === "oldest") return visible.sort((a, b) => a.id - b.id);
  if (sortMode === "title") return visible.sort(byTitle);
  if (sortMode === "collection") return visible.sort((a, b) => a.category.localeCompare(b.category, undefined, {sensitivity:"base"}) || byTitle(a, b));
  if (sortMode === "favorites") return visible.sort((a, b) => Number(b.favorite) - Number(a.favorite) || b.id - a.id);
  return visible.sort((a, b) => b.id - a.id);
}

function updateBulkToolbar() {
  const toolbar = document.querySelector("#bulkToolbar");
  toolbar.hidden = selectedIds.size === 0;
  document.querySelector("#selectedCount").textContent = `${selectedIds.size} selected`;
  const selected = prompts.filter(prompt => selectedIds.has(prompt.id));
  const hasTrashed = selected.some(prompt => prompt.trashed);
  const onlyTrashed = selected.length > 0 && selected.every(prompt => prompt.trashed);
  document.querySelector("#restoreSelected").hidden = !onlyTrashed;
  document.querySelector("#removeSelected").hidden = hasTrashed;
  document.querySelector("#bulkCategory").disabled = hasTrashed;
  document.querySelector("#applyCategory").disabled = hasTrashed;
  document.querySelector("#markReviewed").disabled = hasTrashed;
  const allFavorite = selected.length > 0 && selected.every(prompt => prompt.favorite);
  const favoriteSelected = document.querySelector("#favoriteSelected");
  favoriteSelected.disabled = hasTrashed;
  favoriteSelected.textContent = allFavorite ? "☆ Unfavorite selected" : "★ Favorite selected";
  document.querySelector("#downloadPack").disabled = hasTrashed;
  const issueCount = prompts.filter(prompt => selectedIds.has(prompt.id) && prompt.syntax_repairable).length;
  const repairSelected = document.querySelector("#repairSelected");
  repairSelected.disabled = issueCount === 0 || hasTrashed;
  repairSelected.textContent = issueCount ? `Repair syntax (${issueCount})` : "Repair syntax";
  const mismatchCount = prompts.filter(prompt => selectedIds.has(prompt.id) && prompt.version_mismatch).length;
  const copyVersionSelected = document.querySelector("#copyVersionSelected");
  copyVersionSelected.disabled = mismatchCount === 0 || hasTrashed;
  copyVersionSelected.textContent = mismatchCount ? `Copy to active version (${mismatchCount})` : "Copy to active version";
  const reportCount = selected.filter(prompt => prompt.parent_prompt_id).length;
  const downloadVersionReports = document.querySelector("#downloadVersionReports");
  downloadVersionReports.disabled = reportCount === 0 || hasTrashed;
  downloadVersionReports.textContent = reportCount ? `Download test reports (${reportCount})` : "Download test reports";
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
    card.className = `prompt-card${selectedIds.has(prompt.id) ? " selected" : ""}${!prompt.reviewed ? " unreviewed" : ""}${prompt.trashed ? " trashed" : ""}`;
    const cardActions = prompt.trashed ? '<button class="restore">Restore prompt</button>' : `<button class="view">Review & edit</button>${prompt.parent_prompt_id ? '<button class="compare">Compare versions</button>' : ''}<button class="copy">Copy prompt</button>`;
    const verdictLabel = {original:"Original preferred",active:"Active preferred",tie:"No clear winner"}[prompt.version_test_result];
    card.innerHTML = `<div class="card-top"><label class="select-prompt"><input type="checkbox" ${selectedIds.has(prompt.id) ? "checked" : ""}><span></span></label><div class="card-badges"><span class="category">${escape(prompt.category)}</span><span class="source ${escape(prompt.source)}">${sourceLabel(prompt.source)}</span>${prompt.trashed ? '<span class="trash-badge">Trash</span>' : ""}${!prompt.reviewed ? '<span class="review-badge">Unreviewed</span>' : ""}${prompt.parent_prompt_id ? `<span class="migration-badge">From MJ v${escape(prompt.migrated_from_version || "older")}</span>` : ""}${verdictLabel ? `<span class="verdict-badge ${escape(prompt.version_test_result)}">${verdictLabel}</span>` : ""}${duplicates.has(prompt.id) ? '<span class="duplicate-badge">Duplicate</span>' : ""}${prompt.version_mismatch ? '<span class="syntax-badge">Version review</span>' : prompt.syntax_issues?.length ? '<span class="syntax-badge">Syntax issue</span>' : ""}</div><button class="favorite ${prompt.favorite ? "on" : ""}" title="Favorite">★</button></div><h2>${escape(prompt.title)}</h2><p class="prompt-preview">${escape(prompt.text)}</p><div class="card-bottom">${cardActions}</div>`;
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
    if (prompt.trashed) {
      card.querySelector(".restore").onclick = () => restorePrompts([prompt.id]);
    } else {
      card.querySelector(".copy").onclick = async () => {
        await navigator.clipboard.writeText(prompt.text);
        notify("Prompt copied.");
      };
      card.querySelector(".view").onclick = () => openEditor(prompt);
      const compareButton = card.querySelector(".compare");
      if (compareButton) compareButton.onclick = () => openVersionComparison(prompt.id);
    }
    grid.appendChild(card);
  });
  empty.hidden = shown.length > 0;
  document.querySelector("#promptCount").textContent = prompts.filter(prompt => !prompt.trashed).length;
  document.querySelector("#unreviewedCount").textContent = prompts.filter(prompt => !prompt.trashed && !prompt.reviewed).length;
  const activePrompts = prompts.filter(prompt => !prompt.trashed);
  const filterCounts = {
    "All": activePrompts.length,
    "Unreviewed": activePrompts.filter(prompt => !prompt.reviewed).length,
    "Duplicates": duplicates.size,
    "Syntax issues": activePrompts.filter(prompt => prompt.syntax_issues?.length).length,
    "Version copies": activePrompts.filter(prompt => prompt.parent_prompt_id).length,
    "Untested copies": activePrompts.filter(prompt => prompt.parent_prompt_id && !prompt.version_test_result).length,
    "Active preferred": activePrompts.filter(prompt => prompt.version_test_result === "active").length,
    "Original preferred": activePrompts.filter(prompt => prompt.version_test_result === "original").length,
    "No clear winner": activePrompts.filter(prompt => prompt.version_test_result === "tie").length,
    "Favorites": activePrompts.filter(prompt => prompt.favorite).length,
    "ChatGPT": activePrompts.filter(prompt => prompt.source === "chatgpt").length,
    "Trash": prompts.filter(prompt => prompt.trashed).length,
  };
  canonicalCategories.forEach(category => {
    filterCounts[category] = activePrompts.filter(prompt => prompt.category === category).length;
  });
  document.querySelectorAll("#filters button").forEach(button => {
    button.querySelector(".filter-count").textContent = filterCounts[button.dataset.filter] || 0;
  });
  const groups = duplicateGroups();
  const duplicateTools = document.querySelector("#duplicateTools");
  duplicateTools.hidden = filter !== "Duplicates";
  document.querySelector("#duplicateSummary").textContent = groups.length
    ? `${duplicateIds().size} prompts in ${groups.length} duplicate ${groups.length === 1 ? "group" : "groups"}`
    : "No duplicate prompts found";
  document.querySelector("#selectDuplicateExtras").disabled = groups.length === 0;
  const selectVisible = document.querySelector("#selectVisible");
  const allVisibleSelected = shown.length > 0 && shown.every(prompt => selectedIds.has(prompt.id));
  selectVisible.disabled = shown.length === 0;
  selectVisible.textContent = allVisibleSelected ? `Clear visible (${shown.length})` : `Select visible (${shown.length})`;
  selectVisible.classList.toggle("clearing", allVisibleSelected);
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
  document.querySelector("#repairSyntax").hidden = !prompt?.syntax_repairable;
  document.querySelector("#copyActiveVersion").hidden = !prompt?.version_mismatch;
  if (prompt) {
    document.querySelector("#promptTitle").value = prompt.title;
    document.querySelector("#promptCategory").value = canonicalCategories.includes(prompt.category) ? prompt.category : "Unsorted";
    document.querySelector("#promptText").value = prompt.text;
  }
  dialog.showModal();
}

document.querySelector("#searchInput").oninput = event => { query = event.target.value.toLowerCase().trim(); render(); };
document.querySelector("#sortPrompts").value = sortMode;
document.querySelector("#sortPrompts").onchange = event => {
  sortMode = event.target.value;
  localStorage.setItem("blackCanvasPromptSort", sortMode);
  render();
};
document.querySelectorAll("#filters button").forEach(button => button.onclick = () => {
  document.querySelectorAll("#filters button").forEach(item => item.classList.remove("active"));
  button.classList.add("active");
  filter = button.dataset.filter;
  const url = new URL(window.location.href);
  if (filter === "All") url.searchParams.delete("filter");
  else url.searchParams.set("filter", filter);
  window.history.replaceState({}, "", url);
  render();
});
document.querySelector("#addPrompt").onclick = () => openEditor();
document.querySelector("#selectVisible").onclick = () => {
  const shown = visiblePrompts();
  const allVisibleSelected = shown.length > 0 && shown.every(prompt => selectedIds.has(prompt.id));
  shown.forEach(prompt => allVisibleSelected ? selectedIds.delete(prompt.id) : selectedIds.add(prompt.id));
  render();
  notify(allVisibleSelected ? `${shown.length} visible selections cleared.` : `${shown.length} visible prompts selected.`);
};
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
  if (!editingId || !window.confirm("Move this prompt to Trash? You can restore it later.")) return;
  await fetch(`/api/prompts/${editingId}`, {method:"DELETE"});
  selectedIds.delete(editingId);
  dialog.close();
  await load();
  notify("Prompt moved to Trash.");
};

async function restorePrompts(promptIds) {
  const response = await fetch("/api/prompts/bulk-restore", {
    method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({prompt_ids:promptIds}),
  });
  const result = await response.json();
  if (!response.ok) return notify(result.detail || "Those prompts could not be restored.");
  promptIds.forEach(id => selectedIds.delete(id));
  await load();
  notify(`${result.restored} ${result.restored === 1 ? "prompt" : "prompts"} restored.`);
}
const versionCompareDialog = document.querySelector("#versionCompareDialog");
let activeVersionComparison = null;
function nextUntestedVersionCopy(currentId) {
  const queue = prompts.filter(prompt => prompt.parent_prompt_id && !prompt.trashed && !prompt.version_test_result);
  return queue.find(prompt => prompt.id !== currentId) || null;
}
function updateNextUntestedButton() {
  const button = document.querySelector("#nextUntestedVersion");
  const migrated = prompts.filter(prompt => prompt.parent_prompt_id && !prompt.trashed);
  const remaining = migrated.filter(prompt => !prompt.version_test_result).length;
  const tested = migrated.length - remaining;
  const next = nextUntestedVersionCopy(activeVersionComparison?.migrated.id);
  button.disabled = !next;
  button.textContent = next ? "Next untested copy →" : "Testing queue complete";
  document.querySelector("#versionQueueProgress").textContent = migrated.length
    ? `${tested} of ${migrated.length} tested · ${remaining} remaining`
    : "No migrated copies to test";
}
async function openVersionComparison(promptId) {
  const response = await fetch(`/api/prompts/${promptId}/version-comparison`);
  const result = await response.json();
  if (!response.ok) return notify(result.detail || "That version comparison is unavailable.");
  activeVersionComparison = result;
  document.querySelector("#originalVersionLabel").textContent = `Original · MJ v${result.original.version || "unknown"}`;
  document.querySelector("#originalVersionTitle").textContent = result.original.title;
  document.querySelector("#originalVersionText").textContent = result.original.text;
  document.querySelector("#migratedVersionLabel").textContent = `Active copy · MJ v${result.migrated.version}`;
  document.querySelector("#migratedVersionTitle").textContent = result.migrated.title;
  document.querySelector("#migratedVersionText").textContent = result.migrated.text;
  const summary = document.querySelector("#comparisonSummary");
  summary.className = `comparison-summary ${result.creative_body_preserved ? "preserved" : "changed"}`;
  const directionStatus = result.creative_body_preserved
    ? "Creative direction preserved."
    : "Creative prompt text changed—review carefully.";
  const changes = result.parameter_changes.length
    ? result.parameter_changes.map(change => `${change.parameter}: ${change.original} → ${change.migrated}`).join(" · ")
    : "No technical parameter changes detected.";
  summary.textContent = `${directionStatus} ${changes}`;
  renderTestVerdict(result.migrated.version_test_result);
  document.querySelector("#versionTestNotes").value = result.migrated.version_test_notes || "";
  updateNextUntestedButton();
  versionCompareDialog.showModal();
}
document.querySelector("#closeVersionCompare").onclick = () => versionCompareDialog.close();
async function copyComparisonText(text, message) {
  if (!text) return;
  await navigator.clipboard.writeText(text);
  notify(message);
}
document.querySelector("#copyOriginalVersion").onclick = () => copyComparisonText(activeVersionComparison?.original.text, "Original prompt copied.");
document.querySelector("#copyMigratedVersion").onclick = () => copyComparisonText(activeVersionComparison?.migrated.text, "Active-version prompt copied.");
document.querySelector("#copyVersionPair").onclick = () => copyComparisonText(activeVersionComparison?.test_pair, "Labeled version test pair copied.");
document.querySelector("#downloadVersionReport").onclick = () => {
  if (activeVersionComparison) window.location.href = `/api/prompts/${activeVersionComparison.migrated.id}/version-report`;
};
document.querySelector("#nextUntestedVersion").onclick = () => {
  const next = nextUntestedVersionCopy(activeVersionComparison?.migrated.id);
  if (next) openVersionComparison(next.id);
};
function renderTestVerdict(result) {
  document.querySelectorAll(".test-verdict button").forEach(button => button.classList.toggle("selected", button.dataset.result === result));
}
document.querySelectorAll(".test-verdict button").forEach(button => button.onclick = async () => {
  if (!activeVersionComparison) return;
  const response = await fetch(`/api/prompts/${activeVersionComparison.migrated.id}/version-test-result`, {
    method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify({result:button.dataset.result}),
  });
  const result = await response.json();
  if (!response.ok) return notify(result.detail || "That test result could not be saved.");
  activeVersionComparison.migrated.version_test_result = result.result;
  renderTestVerdict(result.result);
  await load();
  updateNextUntestedButton();
  notify("MidJourney test result saved.");
});
document.querySelector("#saveVersionTestNotes").onclick = async () => {
  if (!activeVersionComparison) return;
  const notes = document.querySelector("#versionTestNotes").value.trim();
  const response = await fetch(`/api/prompts/${activeVersionComparison.migrated.id}/version-test-notes`, {
    method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify({notes}),
  });
  const result = await response.json();
  if (!response.ok) return notify(result.detail || "Those test notes could not be saved.");
  activeVersionComparison.migrated.version_test_notes = result.notes;
  notify("MidJourney test notes saved.");
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

document.querySelector("#copyActiveVersion").onclick = async () => {
  if (!editingId) return;
  const response = await fetch(`/api/prompts/${editingId}/copy-to-active-midjourney-version`, {method:"POST"});
  const result = await response.json();
  if (!response.ok) return notify(result.detail || "The active-version copy could not be created.");
  dialog.close();
  await load();
  notify("Active-version copy created. The original was kept.");
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
document.querySelector("#favoriteSelected").onclick = () => {
  const selected = prompts.filter(prompt => selectedIds.has(prompt.id));
  const allFavorite = selected.length > 0 && selected.every(prompt => prompt.favorite);
  bulkUpdate({favorite:!allFavorite}, allFavorite ? "prompts unfavorited." : "prompts favorited.");
};
document.querySelector("#repairSelected").onclick = async () => {
  const issueCount = prompts.filter(prompt => selectedIds.has(prompt.id) && prompt.syntax_repairable).length;
  if (!issueCount || !window.confirm(`Repair supported MidJourney syntax in ${issueCount} selected ${issueCount === 1 ? "prompt" : "prompts"}?`)) return;
  const response = await fetch("/api/prompts/bulk-repair-midjourney-syntax", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({prompt_ids:[...selectedIds]}),
  });
  const result = await response.json();
  if (!response.ok) return notify(result.detail || "Those prompts could not be repaired.");
  selectedIds.clear();
  await load();
  const skipped = result.skipped ? ` ${result.skipped} skipped because no change was needed or a duplicate would result.` : "";
  notify(`${result.repaired} ${result.repaired === 1 ? "prompt" : "prompts"} repaired.${skipped}`);
};
document.querySelector("#copyVersionSelected").onclick = async () => {
  const mismatchCount = prompts.filter(prompt => selectedIds.has(prompt.id) && prompt.version_mismatch).length;
  if (!mismatchCount || !window.confirm(`Create active-version copies of ${mismatchCount} selected ${mismatchCount === 1 ? "prompt" : "prompts"}? Originals will be kept.`)) return;
  const response = await fetch("/api/prompts/bulk-copy-to-active-midjourney-version", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({prompt_ids:[...selectedIds]}),
  });
  const result = await response.json();
  if (!response.ok) return notify(result.detail || "Those active-version copies could not be created.");
  selectedIds.clear();
  await load();
  notify(`${result.copied} active-version ${result.copied === 1 ? "copy" : "copies"} created. ${result.skipped} skipped.`);
};
document.querySelector("#downloadVersionReports").onclick = async () => {
  const response = await fetch("/api/prompts/version-reports/export", {
    method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({prompt_ids:[...selectedIds]}),
  });
  if (!response.ok) {
    const result = await response.json();
    return notify(result.detail || "Those version-test reports could not be downloaded.");
  }
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `midjourney-version-tests-${new Date().toISOString().slice(0,10)}.txt`;
  link.click();
  URL.revokeObjectURL(link.href);
  notify("Version-test report bundle downloaded.");
};
document.querySelector("#downloadPack").onclick = async () => {
  const response = await fetch("/api/prompts/export", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({prompt_ids:[...selectedIds]}),
  });
  if (!response.ok) {
    const result = await response.json();
    return notify(result.detail || "The prompt pack could not be created.");
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const filename = disposition.match(/filename="([^"]+)"/)?.[1] || "black-canvas-prompt-pack.txt";
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
  notify(`${selectedIds.size} ${selectedIds.size === 1 ? "prompt" : "prompts"} exported.`);
};
document.querySelector("#selectDuplicateExtras").onclick = () => {
  selectedIds.clear();
  duplicateExtraIds().forEach(id => selectedIds.add(id));
  render();
  notify(selectedIds.size ? `${selectedIds.size} extra ${selectedIds.size === 1 ? "copy" : "copies"} selected for review.` : "No extra copies found.");
};
document.querySelector("#restoreSelected").onclick = () => restorePrompts([...selectedIds]);
document.querySelector("#removeSelected").onclick = async () => {
  if (!selectedIds.size || !window.confirm(`Move ${selectedIds.size} selected ${selectedIds.size === 1 ? "prompt" : "prompts"} to Trash? You can restore them later.`)) return;
  const response = await fetch("/api/prompts/bulk-delete", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({prompt_ids:[...selectedIds]}),
  });
  const result = await response.json();
  if (!response.ok) return notify(result.detail || "Those prompts could not be removed.");
  selectedIds.clear();
  await load();
  notify(`${result.trashed} ${result.trashed === 1 ? "prompt" : "prompts"} moved to Trash.`);
};
document.querySelector("#clearSelection").onclick = () => { selectedIds.clear(); render(); };
document.querySelector("#menuButton").onclick = () => document.querySelector("#sidebar").classList.toggle("open");
migrate().then(load).catch(() => notify("Could not load the prompt library."));
