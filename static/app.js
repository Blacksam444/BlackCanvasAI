const toast = document.querySelector("#toast");
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
    const testing = data.version_testing;
    const rules = data.midjourney_rules;
    const rulesStatus = document.querySelector("#midjourneyRulesStatus");
    const verifiedDate = rules.verified_at
      ? new Date(`${rules.verified_at}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
      : "not recorded";
    rulesStatus.textContent = `MidJourney v${rules.version} · ${rules.verification_label} ${verifiedDate}`;
    rulesStatus.dataset.status = rules.verification_status;
    rulesStatus.title = rules.next_review ? `Next rules review: ${rules.next_review}` : "Open the Style Bible to verify these rules";
    document.querySelector("#versionTestProgress").textContent = testing.total ? `${testing.completion_percent}% tested` : "No copies yet";
    document.querySelector("#versionTestBar").style.width = `${testing.completion_percent}%`;
    document.querySelector("#versionTestTotal").textContent = testing.total;
    document.querySelector("#versionTestUntested").textContent = testing.untested;
    document.querySelector("#versionTestActive").textContent = testing.active;
    document.querySelector("#versionTestOriginal").textContent = testing.original;
    document.querySelector("#versionTestTie").textContent = testing.tie;
    document.querySelector("#versionTestRetest").textContent = testing.retest_recommended;
    document.querySelector("#retestQueueLink").hidden = testing.retest_recommended === 0;
    if (data.prompt_of_day) {
      document.querySelector("#dailyPrompt").textContent = data.prompt_of_day.text;
      document.querySelector("#dailyCategory").textContent = data.prompt_of_day.category;
    } else {
      document.querySelector("#dailyPrompt").textContent = "Save your first prompt to see it featured here.";
      document.querySelector("#copyPrompt").disabled = true;
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

loadDashboard();
