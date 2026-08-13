const updateDialog = document.querySelector("#updateDialog");
const updateList = document.querySelector("#styleUpdateList");
const updateText = document.querySelector("#updateText");
const spellingReview = document.querySelector("#spellingReview");
const spellingSummary = document.querySelector("#spellingSummary");
const spellingChanges = document.querySelector("#spellingChanges");
const checkSpelling = document.querySelector("#checkSpelling");
let correctedSpellingText = "";
const fieldNames = { ingredients: "Visual ingredients", language: "Prompt language", dos: "Always include", donts: "Avoid" };
const inboxEscape = (text = "") => text.replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
}[character]));
const inboxNotify = (message) => {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 1900);
};

function suggestionMarkup(field, values) {
  if (!values.length) return "";
  return `<div class="suggestion-group" data-field="${field}"><strong>${fieldNames[field]}</strong>${values.map((value) => `<label class="suggestion-option"><input type="checkbox" checked value="${inboxEscape(value)}"><span>${inboxEscape(value)}</span></label>`).join("")}</div>`;
}

function renderUpdates(updates) {
  const pending = updates.filter((update) => update.status === "pending");
  if (!pending.length) {
    updateList.innerHTML = '<p class="update-empty">No updates waiting for review.</p>';
    return;
  }
  updateList.innerHTML = pending.map((update) => `<article class="update-card" data-id="${update.id}"><div class="update-card-head"><div><strong>${inboxEscape(update.style_name)}</strong><small>${inboxEscape(update.created_at)}</small></div><span class="update-status">Waiting for review</span></div><p class="update-source">${inboxEscape(update.source_text)}</p>${Object.entries(fieldNames).map(([field]) => suggestionMarkup(field, update.suggestions[field] || [])).join("")}<div class="update-actions"><button class="approve-update">✓ Approve selected</button><button class="dismiss-update">Dismiss</button></div></article>`).join("");
  updateList.querySelectorAll(".approve-update").forEach((button) => { button.onclick = () => approveUpdate(button.closest(".update-card")); });
  updateList.querySelectorAll(".dismiss-update").forEach((button) => { button.onclick = () => dismissUpdate(button.closest(".update-card")); });
}

async function loadUpdates() {
  const response = await fetch("/api/style-updates");
  if (!response.ok) throw new Error();
  renderUpdates(await response.json());
}

async function approveUpdate(card) {
  const suggestions = { ingredients: [], language: [], dos: [], donts: [] };
  card.querySelectorAll(".suggestion-group").forEach((group) => {
    suggestions[group.dataset.field] = [...group.querySelectorAll("input:checked")].map((input) => input.value);
  });
  const selectedCount = Object.values(suggestions).flat().length;
  if (!selectedCount) return inboxNotify("Choose at least one suggestion first.");
  card.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  const response = await fetch(`/api/style-updates/${card.dataset.id}/approve`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ suggestions }),
  });
  if (!response.ok) { card.querySelectorAll("button").forEach((button) => { button.disabled = false; }); return inboxNotify("Could not approve the update."); }
  const result = await response.json();
  styles[result.style_name] = result.content;
  if (current === result.style_name) render();
  await loadUpdates();
  inboxNotify(`${result.style_name} Style Bible updated.`);
}

async function dismissUpdate(card) {
  card.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  const response = await fetch(`/api/style-updates/${card.dataset.id}/dismiss`, { method: "POST" });
  if (!response.ok) return inboxNotify("Could not dismiss the update.");
  await loadUpdates();
  inboxNotify("Style update dismissed.");
}

document.querySelector("#openStyleUpdate").onclick = () => {
  document.querySelector("#updateForm").reset();
  document.querySelector("#updateStyle").value = current;
  spellingReview.hidden = true;
  correctedSpellingText = "";
  updateDialog.showModal();
  updateText.focus();
};
updateText.addEventListener("input", () => {
  spellingReview.hidden = true;
  correctedSpellingText = "";
});
checkSpelling.onclick = async () => {
  const text = updateText.value.trim();
  if (!text) return updateText.focus();
  checkSpelling.disabled = true;
  checkSpelling.textContent = "Checking...";
  try {
    const response = await fetch("/api/spellcheck", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
    });
    if (!response.ok) throw new Error();
    const result = await response.json();
    correctedSpellingText = result.corrected_text;
    spellingSummary.textContent = result.changes.length
      ? `${result.changes.length} possible correction${result.changes.length === 1 ? "" : "s"} found. Nothing changes until you apply them.`
      : "No spelling changes found.";
    spellingChanges.innerHTML = result.changes.map((change) => `<span class="spelling-change">${inboxEscape(change.original)} &rarr; ${inboxEscape(change.replacement)}</span>`).join("");
    document.querySelector("#applySpelling").hidden = !result.changes.length;
    spellingReview.hidden = false;
  } catch {
    inboxNotify("Could not check spelling just now.");
  } finally {
    checkSpelling.disabled = false;
    checkSpelling.textContent = "Check spelling";
  }
};
document.querySelector("#applySpelling").onclick = () => {
  if (!correctedSpellingText) return;
  updateText.value = correctedSpellingText;
  spellingReview.hidden = true;
  correctedSpellingText = "";
  updateText.focus();
  inboxNotify("Spelling corrections applied.");
};
document.querySelector("#reviewUpdate").onclick = async (event) => {
  event.preventDefault();
  const text = updateText.value.trim();
  if (!text) return updateText.focus();
  const response = await fetch("/api/style-updates", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ style_name: document.querySelector("#updateStyle").value, text }),
  });
  if (!response.ok) return inboxNotify("Could not prepare the style update.");
  updateDialog.close();
  await loadUpdates();
  inboxNotify("Update ready for your review.");
};

loadUpdates().catch(() => { updateList.innerHTML = '<p class="update-empty">Could not load style updates just now.</p>'; });
