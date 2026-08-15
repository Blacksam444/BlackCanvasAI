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
let reviewQueue = [];
let reviewPosition = 0;
let reviewStats = {kept: 0, favorited: 0, skipped: 0, removed: 0};
let reviewBusy = false;

const notify = message => {
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2200);
};
const escape = text => (text || "").replace(/[&<>"']/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"})[character]);
const normalizedText = text => (text || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

function duplicateIds() {
  const groups = new Map();
  prompts.forEach(prompt => {
    const key = normalizedText(prompt.text);
    if (!key) return;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(prompt.id);
  });
  return new Set([...groups.values()].filter(group => group.length > 1).flat());
}

function sourceLabel(source) {
  return source === "chatgpt" ? "ChatGPT" : source === "drive" ? "Google Drive" : "Manual";
}

function reviewInsight(prompt) {
  const key = normalizedText(prompt.text);
  const matches = key ? prompts.filter(item => normalizedText(item.text) === key).length : 0;
  if (matches > 1) return {tone: "warning", text: `Possible duplicate · ${matches} matching copies are in your library`};
  if ((prompt.text || "").length < 80) return {tone: "caution", text: "Short entry · Check that this is a complete reusable prompt"};
  if ((prompt.text || "").length > 1200) return {tone: "strong", text: "Detailed prompt · Good candidate for your permanent library"};
  return {tone: "ready", text: "Ready to review · No exact duplicate found"};
}

function matchingCopies(prompt) {
  const key = normalizedText(prompt.text);
  if (!key) return [];
  return prompts.filter(item => item.id !== prompt.id && normalizedText(item.text) === key);
}

function suggestedCategory(prompt) {
  if (canonicalCategories.includes(prompt.category)) return prompt.category;
  const text = `${prompt.title} ${prompt.text}`.toLowerCase();
  const categorySignals = [
    ["Content", ["tiktok", "instagram", "caption", "video", "social media", "content idea", "hashtag", "reel"]],
    ["Business", ["price", "pricing", "etsy", "sell", "sales", "profit", "business", "marketing", "customer", "money"]],
    ["GraffitiX", ["graffiti", "street art", "urban", "spray paint", "mural", "neon tag"]],
    ["Quiet Nova", ["quiet nova", "peaceful", "calm", "stillness", "minimal", "soft light", "reflective", "intimate"]],
    ["AfroNova", ["afronova", "afro nova", "afrofutur", "cosmic", "celestial", "future king", "future queen", "regal black", "ancestral"]],
  ];
  let bestCategory = "Unsorted";
  let bestScore = 0;
  categorySignals.forEach(([category, words]) => {
    const score = words.reduce((total, word) => total + (text.includes(word) ? 1 : 0), 0);
    if (score > bestScore) {
      bestScore = score;
      bestCategory = category;
    }
  });
  return bestCategory;
}

function visiblePrompts() {
  const duplicates = duplicateIds();
  return prompts.filter(prompt => {
    const matchesFilter = filter === "All"
      || (filter === "Unreviewed" && !prompt.reviewed)
      || (filter === "Duplicates" && duplicates.has(prompt.id))
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
    card.innerHTML = `<div class="card-top"><label class="select-prompt"><input type="checkbox" ${selectedIds.has(prompt.id) ? "checked" : ""}><span></span></label><div class="card-badges"><span class="category">${escape(prompt.category)}</span><span class="source ${escape(prompt.source)}">${sourceLabel(prompt.source)}</span>${!prompt.reviewed ? '<span class="review-badge">Unreviewed</span>' : ""}${duplicates.has(prompt.id) ? '<span class="duplicate-badge">Duplicate</span>' : ""}</div><button class="favorite ${prompt.favorite ? "on" : ""}" title="Favorite">★</button></div><h2>${escape(prompt.title)}</h2><p class="prompt-preview">${escape(prompt.text)}</p><div class="card-bottom"><button class="view">Review & edit</button><button class="copy">Copy prompt</button></div>`;
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
  updateBulkToolbar();
}

function openEditor(prompt = null) {
  editingId = prompt?.id || null;
  document.querySelector("#promptForm").reset();
  document.querySelector("#dialogEyebrow").textContent = prompt ? "REVIEW CREATIVE RECIPE" : "NEW CREATIVE RECIPE";
  document.querySelector("#dialogTitle").textContent = prompt ? "Review and organize" : "Add a prompt";
  document.querySelector("#savePrompt").textContent = prompt ? "Save changes" : "Save prompt";
  document.querySelector("#deletePrompt").hidden = !prompt;
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
document.querySelector("#clearSelection").onclick = () => { selectedIds.clear(); render(); };
function showReviewPrompt() {
  if (!reviewQueue.length || reviewPosition >= reviewQueue.length) {
    document.querySelector("#reviewDialog").close();
    const handled = reviewStats.kept + reviewStats.favorited + reviewStats.removed;
    notify(`Session complete: ${handled} handled, ${reviewStats.skipped} skipped.`);
    return;
  }
  const prompt = reviewQueue[reviewPosition];
  document.querySelector("#reviewProgress").textContent = `${reviewPosition + 1} of ${reviewQueue.length} in this session`;
  document.querySelector("#reviewSessionStats").textContent = `${reviewStats.kept} kept · ${reviewStats.favorited} favorited · ${reviewStats.skipped} skipped · ${reviewStats.removed} removed`;
  document.querySelector("#reviewSource").textContent = sourceLabel(prompt.source);
  document.querySelector("#reviewTitle").textContent = prompt.title;
  document.querySelector("#reviewPrompt").textContent = prompt.text;
  const insight = reviewInsight(prompt);
  const insightElement = document.querySelector("#reviewInsight");
  insightElement.className = `review-insight ${insight.tone}`;
  insightElement.textContent = insight.text;
  const copies = matchingCopies(prompt);
  const duplicatePanel = document.querySelector("#reviewDuplicates");
  duplicatePanel.hidden = copies.length === 0;
  document.querySelector("#duplicateTitles").textContent = copies.map(copy => copy.title).join(" · ");
  const removeCopiesButton = document.querySelector("#removeMatchingCopies");
  removeCopiesButton.textContent = `Keep this one & remove ${copies.length} extra ${copies.length === 1 ? "copy" : "copies"}`;
  const suggestion = suggestedCategory(prompt);
  document.querySelector("#reviewCategory").value = suggestion;
  document.querySelector("#reviewSuggestion").textContent = suggestion === "Unsorted" ? "No strong match" : `Suggested: ${suggestion}`;
}
document.querySelector("#startReviewQueue").onclick = () => {
  reviewQueue = prompts.filter(prompt => !prompt.reviewed);
  reviewPosition = 0;
  reviewStats = {kept: 0, favorited: 0, skipped: 0, removed: 0};
  if (!reviewQueue.length) return notify("Every prompt has been reviewed.");
  showReviewPrompt();
  document.querySelector("#reviewDialog").showModal();
};
document.querySelector("#closeReviewQueue").onclick = () => document.querySelector("#reviewDialog").close();
document.querySelector("#skipReviewPrompt").onclick = () => {
  if (reviewBusy) return;
  reviewStats.skipped += 1;
  reviewPosition += 1;
  showReviewPrompt();
};
async function keepReviewPrompt(favorite = false) {
  if (reviewBusy) return;
  const prompt = reviewQueue[reviewPosition];
  if (!prompt) return;
  reviewBusy = true;
  const category = document.querySelector("#reviewCategory").value;
  const response = await fetch("/api/prompts/bulk-update", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({prompt_ids:[prompt.id], category, reviewed:true}),
  });
  if (!response.ok) {
    reviewBusy = false;
    return notify("Could not update this prompt.");
  }
  if (favorite && !prompt.favorite) await fetch(`/api/prompts/${prompt.id}/favorite?favorite=true`, {method:"PATCH"});
  if (favorite) reviewStats.favorited += 1;
  else reviewStats.kept += 1;
  reviewPosition += 1;
  await load();
  reviewBusy = false;
  showReviewPrompt();
  notify(favorite ? "Prompt kept and favorited." : "Prompt kept.");
}
document.querySelector("#keepReviewPrompt").onclick = () => keepReviewPrompt(false);
document.querySelector("#favoriteReviewPrompt").onclick = () => keepReviewPrompt(true);
document.querySelector("#removeReviewPrompt").onclick = async () => {
  if (reviewBusy) return;
  const prompt = reviewQueue[reviewPosition];
  if (!prompt || !window.confirm("Remove this prompt from the library?")) return;
  reviewBusy = true;
  const response = await fetch(`/api/prompts/${prompt.id}`, {method:"DELETE"});
  if (!response.ok) {
    reviewBusy = false;
    return notify("Could not remove this prompt.");
  }
  reviewStats.removed += 1;
  reviewPosition += 1;
  await load();
  reviewBusy = false;
  showReviewPrompt();
  notify("Prompt removed.");
};
document.querySelector("#removeMatchingCopies").onclick = async () => {
  if (reviewBusy) return;
  const prompt = reviewQueue[reviewPosition];
  const copies = prompt ? matchingCopies(prompt) : [];
  if (!prompt || !copies.length) return;
  if (!window.confirm(`Keep this prompt and remove ${copies.length} exact ${copies.length === 1 ? "copy" : "copies"}?`)) return;
  reviewBusy = true;
  const category = document.querySelector("#reviewCategory").value;
  const keepResponse = await fetch("/api/prompts/bulk-update", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({prompt_ids:[prompt.id], category, reviewed:true}),
  });
  if (!keepResponse.ok) {
    reviewBusy = false;
    return notify("Could not keep this prompt.");
  }
  const results = await Promise.all(copies.map(copy => fetch(`/api/prompts/${copy.id}`, {method:"DELETE"})));
  const removedIds = new Set(copies.filter((copy, index) => results[index].ok).map(copy => copy.id));
  const processedRemaining = reviewQueue.slice(0, reviewPosition).filter(item => !removedIds.has(item.id)).length;
  reviewQueue = reviewQueue.filter(item => item.id !== prompt.id && !removedIds.has(item.id));
  reviewStats.kept += 1;
  reviewStats.removed += removedIds.size;
  reviewPosition = processedRemaining;
  await load();
  reviewBusy = false;
  showReviewPrompt();
  notify(`Kept one prompt and removed ${removedIds.size} extra ${removedIds.size === 1 ? "copy" : "copies"}.`);
};
document.addEventListener("keydown", event => {
  const reviewDialog = document.querySelector("#reviewDialog");
  if (!reviewDialog.open || ["SELECT", "INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
  const key = event.key.toLowerCase();
  if (key === "k") { event.preventDefault(); keepReviewPrompt(false); }
  if (key === "f") { event.preventDefault(); keepReviewPrompt(true); }
  if (key === "s") { event.preventDefault(); document.querySelector("#skipReviewPrompt").click(); }
});
document.querySelector("#menuButton").onclick = () => document.querySelector("#sidebar").classList.toggle("open");
migrate().then(load).catch(() => notify("Could not load the prompt library."));
