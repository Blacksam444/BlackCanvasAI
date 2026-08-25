const toast = document.querySelector("#toast");
let promptSpotlights = [];
let currentSpotlight = 0;
const showToast = (message) => {
  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 2200);
};

const hour = new Date().getHours();
const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
document.querySelector("#greeting").textContent = `${greeting}, Jeffrey.`;

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    showToast(`${button.dataset.view} is next on our build list.`);
    document.querySelector("#sidebar").classList.remove("open");
  });
});

document.querySelectorAll("[data-action]").forEach((button) => {
  button.addEventListener("click", () => showToast(`${button.dataset.action} is ready for the next sprint.`));
});

document.querySelector("#askForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.querySelector("#askInput");
  if (!input.value.trim()) return input.focus();
  window.location.href = `/chat?q=${encodeURIComponent(input.value.trim())}`;
});

document.querySelector("#copyPrompt").addEventListener("click", async () => {
  const prompt = document.querySelector("#dailyPrompt").textContent.replace(/[“”]/g, "");
  await navigator.clipboard.writeText(prompt);
  showToast("Prompt copied.");
});

function showPromptSpotlight(index) {
  if (!promptSpotlights.length) return;
  currentSpotlight = (index + promptSpotlights.length) % promptSpotlights.length;
  const prompt = promptSpotlights[currentSpotlight];
  document.querySelector("#dailyPrompt").textContent = prompt.text;
  document.querySelector("#dailyCategory").textContent = prompt.category;
}

document.querySelector("#anotherPrompt").addEventListener("click", () => {
  showPromptSpotlight(currentSpotlight + 1);
  showToast("A new creative spark from your library.");
});

document.querySelector("#menuButton").addEventListener("click", () => {
  document.querySelector("#sidebar").classList.toggle("open");
});

const escapeDashboardHtml = (value = "") => String(value).replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
}[character]));

async function loadDashboard() {
  try {
    const response = await fetch("/api/dashboard");
    if (!response.ok) throw new Error();
    const data = await response.json();
    document.querySelector("#promptCount").textContent = data.counts.prompts;
    document.querySelector("#artworkCount").textContent = data.counts.artworks;
    document.querySelector("#favoriteCount").textContent = data.counts.favorites;
    document.querySelector("#reviewCount").textContent = data.counts.to_review ? `${data.counts.to_review} to review` : "All organized";
    const dashboardMoney = (value) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value || 0);
    document.querySelector("#studioCatalogValue").textContent = dashboardMoney(data.studio.catalog_value);
    document.querySelector("#studioSalesRevenue").textContent = dashboardMoney(data.studio.sales_revenue);
    document.querySelector("#studioActiveOrders").textContent = data.studio.active_orders;
    document.querySelector("#studioReadyToList").textContent = data.studio.ready_to_list;
    document.querySelector("#studioCompletedOrders").textContent = data.studio.completed_orders;
    document.querySelector("#studioExpenses").textContent = dashboardMoney(data.studio.expenses);
    document.querySelector("#studioNetProfit").textContent = dashboardMoney(data.studio.net_profit);
    document.querySelector("#goalRevenue").textContent = dashboardMoney(data.studio.monthly_revenue);
    document.querySelector("#goalTarget").textContent = dashboardMoney(data.studio.monthly_goal);
    document.querySelector("#goalBar").style.width = `${data.studio.goal_percent}%`;
    const goalRemaining = Math.max(data.studio.monthly_goal - data.studio.monthly_revenue, 0);
    document.querySelector("#goalRemaining").textContent = goalRemaining ? `${dashboardMoney(goalRemaining)} remaining this month` : "Monthly goal reached!";
    document.querySelector("#studioPriorities").innerHTML = data.priorities.map((priority) => `<a href="${priority.href}" class="priority-card ${priority.tone}"><span>${escapeDashboardHtml(priority.icon)}</span><div><strong>${escapeDashboardHtml(priority.title)}</strong><small>${escapeDashboardHtml(priority.detail)}</small></div>${priority.count ? `<b>${priority.count}</b>` : ""}<em>›</em></a>`).join("");
    promptSpotlights = data.prompt_spotlights || (data.prompt_of_day ? [data.prompt_of_day] : []);
    if (promptSpotlights.length) {
      showPromptSpotlight(0);
      document.querySelector("#anotherPrompt").disabled = promptSpotlights.length < 2;
    } else {
      document.querySelector("#dailyPrompt").textContent = "Save your first prompt to see it featured here.";
      document.querySelector("#copyPrompt").disabled = true;
      document.querySelector("#anotherPrompt").disabled = true;
    }
    const activity = document.querySelector("#recentActivity");
    if (!data.recent.length) {
      activity.innerHTML = '<p class="activity-loading">Your newest prompts and artwork will appear here.</p>';
      return;
    }
    activity.innerHTML = data.recent.map((item) => {
      const href = item.kind === "artwork" ? "/image-studio" : "/prompts";
      const icon = item.kind === "artwork" ? "✦" : "▤";
      const description = item.description || item.detail;
      return `<a href="${href}"><span class="conversation-icon ${item.kind === "artwork" ? "purple" : "amber"}">${icon}</span><span><strong>${escapeDashboardHtml(item.title)}</strong><small>${escapeDashboardHtml(description).slice(0, 100)}</small></span><time>${escapeDashboardHtml(item.detail)}</time><b>›</b></a>`;
    }).join("");
  } catch {
    document.querySelector("#recentActivity").innerHTML = '<p class="activity-loading">Could not load the library just now.</p>';
  }
}

async function loadAgentNextStep() {
  try {
    const response = await fetch("/api/agent-brief");
    if (!response.ok) throw new Error();
    const brief = await response.json();
    document.querySelector("#agentNextStepText").textContent = brief.next_step;
    const link = document.querySelector("#agentNextStepLink");
    link.textContent = brief.action.label;
    link.href = brief.action.href;
  } catch {
    document.querySelector("#agentNextStepText").textContent = "Open your Studio Brief to choose the next move for your workspace.";
  }
}

loadDashboard();
loadAgentNextStep();
