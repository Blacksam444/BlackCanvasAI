const historyInput = document.querySelector("#chatgptExport");
const historyBrowser = document.querySelector("#historyBrowser");
const historyCandidates = document.querySelector("#historyCandidates");
const historySearch = document.querySelector("#historySearch");
const historyCount = document.querySelector("#historyCount");
let promptCandidates = [];
let historyFilter = "likely";
const selectedCandidateIds = new Set();

const imageWords = ["image", "artwork", "portrait", "painting", "illustration", "photograph", "visual", "canvas", "midjourney", "dall-e", "afronova", "quiet nova", "graffitix", "afrofutur", "cosmic", "street art"];
const businessWords = ["business", "etsy", "tiktok", "content", "caption", "marketing", "pricing", "price", "listing", "product", "brand", "sales", "social media", "video", "reel", "customer"];
const actionPattern = /^\s*(create|generate|write|design|develop|draft|make|give me|help me|act as|produce|build|compose|turn|rewrite|analyze|suggest|brainstorm|imagine|describe|plan|outline|list)\b/i;
const conversationPattern = /^\s*(okay|ok|yes|no|thanks|thank you|continue|done|nice|looks good|i see|i got it|what'?s next|where do i|i don'?t see|it says|when i click|let'?s work)\b/i;

function classifyCandidate(item) {
  const text = item.text.toLowerCase();
  const imageHits = imageWords.filter(word => text.includes(word)).length;
  const businessHits = businessWords.filter(word => text.includes(word)).length;
  let score = 0;
  if (actionPattern.test(item.text)) score += 2;
  if (item.text.length >= 120) score += 1;
  if (/\b(prompt|include|style|format|requirements?|instructions?|concept|ideas?)\b/i.test(item.text)) score += 1;
  if (imageHits) score += 2;
  if (businessHits) score += 1;
  if (conversationPattern.test(item.text) && item.text.length < 180) score -= 3;
  return {
    ...item,
    prompt_type: imageHits ? "image" : businessHits ? "business" : score >= 2 ? "general" : "conversation",
    prompt_score: score,
  };
}

function filteredCandidates() {
  const query = historySearch.value.trim().toLowerCase();
  return promptCandidates.filter(item => {
    const matchesType = historyFilter === "all"
      || (historyFilter === "likely" && item.prompt_type !== "conversation")
      || item.prompt_type === historyFilter;
    return matchesType && (!query || `${item.conversation} ${item.text}`.toLowerCase().includes(query));
  });
}

function typeLabel(type) {
  return type === "image" ? "Image & art" : type === "business" ? "Business & content" : type === "general" ? "Likely prompt" : "Conversation";
}

function renderHistoryCandidates() {
  const visible = filteredCandidates();
  historyCount.textContent = `${visible.length} shown · ${selectedCandidateIds.size} selected`;
  if (!visible.length) {
    historyCandidates.innerHTML = '<p class="history-empty">No matching prompt candidates.</p>';
    return;
  }
  historyCandidates.replaceChildren(...visible.map(item => {
    const label = document.createElement("label");
    label.className = "history-candidate";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = item.id;
    checkbox.checked = selectedCandidateIds.has(item.id);
    checkbox.onchange = () => {
      if (checkbox.checked) selectedCandidateIds.add(item.id);
      else selectedCandidateIds.delete(item.id);
      historyCount.textContent = `${visible.length} shown · ${selectedCandidateIds.size} selected`;
    };
    const copy = document.createElement("div");
    const heading = document.createElement("div");
    heading.className = "history-candidate-head";
    const title = document.createElement("strong");
    title.textContent = item.conversation;
    const badge = document.createElement("span");
    badge.className = `prompt-type ${item.prompt_type}`;
    badge.textContent = typeLabel(item.prompt_type);
    heading.append(title, badge);
    const text = document.createElement("p");
    text.textContent = item.text;
    copy.append(heading, text);
    label.append(checkbox, copy);
    return label;
  }));
}

function showCandidateResults(result) {
  promptCandidates = result.candidates.map(classifyCandidate);
  historyBrowser.hidden = false;
  renderHistoryCandidates();
  historyBrowser.scrollIntoView({ behavior: "smooth", block: "start" });
}

historyInput.onchange = async event => {
  const file = event.target.files[0];
  if (!file) return;
  historyBrowser.hidden = false;
  historyCandidates.innerHTML = '<p class="history-empty">Scanning the conversation files inside your export...</p>';
  historyBrowser.scrollIntoView({ behavior: "smooth", block: "start" });
  const body = new FormData();
  body.append("export_file", file);
  try {
    const response = await fetch("/api/chatgpt/import-preview", { method: "POST", body });
    const result = await response.json();
    if (!response.ok) throw Error(result.detail || "The export could not be scanned.");
    showCandidateResults(result);
    notify(`${result.count} messages reviewed. Likely prompts are shown first.`);
  } catch (error) {
    promptCandidates = [];
    const message = document.createElement("p");
    message.className = "history-empty";
    message.textContent = error.message;
    historyCandidates.replaceChildren(message);
  }
};

historySearch.oninput = renderHistoryCandidates;
document.querySelectorAll("#historyFilters button").forEach(button => {
  button.onclick = () => {
    document.querySelectorAll("#historyFilters button").forEach(item => item.classList.remove("active"));
    button.classList.add("active");
    historyFilter = button.dataset.historyFilter;
    renderHistoryCandidates();
  };
});
document.querySelector("#closeHistoryBrowser").onclick = () => { historyBrowser.hidden = true; };
document.querySelector("#importSelectedHistory").onclick = async () => {
  const candidate_ids = [...selectedCandidateIds];
  if (!candidate_ids.length) return notify("Select at least one prompt first.");
  const response = await fetch("/api/chatgpt/import-selected", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidate_ids }),
  });
  const result = await response.json();
  if (!response.ok) return notify(result.detail || "Those prompts could not be imported.");
  notify(`${result.imported} prompt${result.imported === 1 ? "" : "s"} added to your library.`);
};

fetch("/api/chatgpt/import-candidates")
  .then(response => response.json())
  .then(result => { if (result.count) showCandidateResults(result); })
  .catch(() => {});
