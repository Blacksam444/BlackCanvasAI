const historyInput = document.querySelector("#chatgptExport");
const historyBrowser = document.querySelector("#historyBrowser");
const historyCandidates = document.querySelector("#historyCandidates");
const historySearch = document.querySelector("#historySearch");
const historyCount = document.querySelector("#historyCount");
let promptCandidates = [];

function renderHistoryCandidates() {
  const query = historySearch.value.trim().toLowerCase();
  const visible = promptCandidates.filter(item => !query || `${item.conversation} ${item.text}`.toLowerCase().includes(query));
  historyCount.textContent = `${visible.length} shown`;
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
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = item.conversation;
    const text = document.createElement("p");
    text.textContent = item.text;
    copy.append(title, text);
    label.append(checkbox, copy);
    return label;
  }));
}

historyInput.onchange = async event => {
  const file = event.target.files[0];
  if (!file) return;
  historyBrowser.hidden = false;
  historyCandidates.innerHTML = '<p class="history-empty">Scanning your export locally...</p>';
  historyBrowser.scrollIntoView({ behavior: "smooth", block: "start" });
  const body = new FormData();
  body.append("export_file", file);
  try {
    const response = await fetch("/api/chatgpt/import-preview", { method: "POST", body });
    const result = await response.json();
    if (!response.ok) throw Error(result.detail || "The export could not be scanned.");
    promptCandidates = result.candidates;
    renderHistoryCandidates();
    notify(`${result.count} possible prompts found. Nothing has been imported yet.`);
  } catch (error) {
    promptCandidates = [];
    historyCandidates.innerHTML = `<p class="history-empty"></p>`;
    historyCandidates.firstElementChild.textContent = error.message;
  }
};

historySearch.oninput = renderHistoryCandidates;
document.querySelector("#closeHistoryBrowser").onclick = () => { historyBrowser.hidden = true; };
document.querySelector("#importSelectedHistory").onclick = async () => {
  const candidate_ids = [...historyCandidates.querySelectorAll('input[type="checkbox"]:checked')].map(input => input.value);
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
