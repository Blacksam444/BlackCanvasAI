const openaiStatus = document.querySelector("#openaiStatus");
const openaiAction = document.querySelector("#openaiAction");
const openaiSetup = document.querySelector("#openaiSetup");
const openaiApiKey = document.querySelector("#openaiApiKey");
const openaiUsage = document.querySelector("#openaiUsage");

async function loadOpenAIAgentStatus() {
  try {
    const response = await fetch("/api/openai/status");
    if (!response.ok) throw new Error();
    const status = await response.json();
    if (status.connected) {
      openaiStatus.textContent = `Connected · ${status.model}`;
      openaiStatus.classList.add("connected");
      openaiAction.textContent = "Live Agent connected";
      openaiAction.disabled = true;
      openaiSetup.hidden = true;
      openaiUsage.textContent = `${status.calls_used} of ${status.calls_limit} monthly live requests used.`;
    } else {
      openaiStatus.textContent = "Not connected";
      openaiStatus.classList.remove("connected");
      openaiAction.textContent = "Connect Live Agent";
      openaiAction.disabled = false;
      openaiUsage.textContent = `Your Black Canvas AI safety limit is ${status.calls_limit} live requests each month.`;
    }
  } catch {
    openaiStatus.textContent = "Setup unavailable";
  }
}

openaiAction.onclick = () => {
  openaiSetup.hidden = false;
  openaiApiKey.focus();
};

document.querySelector("#cancelOpenaiSetup").onclick = () => {
  openaiApiKey.value = "";
  openaiSetup.hidden = true;
};

document.querySelector("#saveOpenaiKey").onclick = async () => {
  const api_key = openaiApiKey.value.trim();
  if (!api_key) return notify("Paste your API key first.");
  const button = document.querySelector("#saveOpenaiKey");
  button.disabled = true;
  button.textContent = "Saving...";
  try {
    const response = await fetch("/api/openai/key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || "Could not save that key.");
    openaiApiKey.value = "";
    notify("Live Black Canvas Agent is connected.");
    await loadOpenAIAgentStatus();
  } catch (error) {
    notify(error.message || "Could not save that key.");
  } finally {
    button.disabled = false;
    button.textContent = "Save Live Agent key";
  }
};

loadOpenAIAgentStatus();
