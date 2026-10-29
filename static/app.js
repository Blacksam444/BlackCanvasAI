const $ = (selector) => document.querySelector(selector);
let featuredPrompt = null;
let loading = false;
let hasLoaded = false;
const statuses = { planned: "Planned", in_progress: "In progress", paused: "Paused", completed: "Completed" };
const escapeHtml = (value = "") => String(value).replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
}[character]));
const showToast = (message) => {
  $("#toast").textContent = message;
  $("#toast").classList.add("show");
  window.setTimeout(() => $("#toast").classList.remove("show"), 2200);
};
const hour = new Date().getHours();
$("#greeting").textContent = `${hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening"}.`;

$("#askForm").onsubmit = (event) => {
  event.preventDefault();
  if (!$("#askInput").value.trim()) return $("#askInput").focus();
  location.href = `/chat?q=${encodeURIComponent($("#askInput").value.trim())}`;
};

function manualCopy(text) {
  $("#manualPromptCopy").value = text;
  $("#copyPromptDialog").showModal();
  $("#manualPromptCopy").focus();
  $("#manualPromptCopy").select();
}
$("#copyPrompt").onclick = async () => {
  if (!featuredPrompt) return;
  const text = featuredPrompt.text;
  try {
    if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
    await navigator.clipboard.writeText(text);
    showToast("Prompt copied.");
    return;
  } catch { /* Private HTTP previews can use the selection fallback below. */ }
  const input = document.createElement("textarea");
  input.value = text;
  input.readOnly = true;
  input.style.position = "fixed";
  input.style.opacity = "0";
  input.style.top = "0";
  document.body.appendChild(input);
  input.select();
  let copied = false;
  try { copied = document.execCommand("copy"); } catch { /* Offer manual selection. */ }
  input.remove();
  if (copied) { $("#copyPrompt").focus({ preventScroll: true }); showToast("Prompt copied."); }
  else manualCopy(text);
};
$("#closeCopyDialog").onclick = () => $("#copyPromptDialog").close();
$("#selectPromptText").onclick = () => { $("#manualPromptCopy").focus(); $("#manualPromptCopy").select(); };

function closeMenu() {
  $("#sidebar").classList.remove("open");
  $("#menuButton").setAttribute("aria-expanded", "false");
  $("#menuButton").focus();
}
$("#menuButton").onclick = () => {
  $("#sidebar").classList.add("open");
  $("#menuButton").setAttribute("aria-expanded", "true");
  $("#closeMenu").focus();
};
$("#closeMenu").onclick = closeMenu;
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && $("#sidebar").classList.contains("open")) closeMenu(); });

function renderProjects(overview) {
  $("#resumeProjectGrid").replaceChildren(...overview.recent.map((project) => {
    const link = document.createElement("a");
    link.className = "resume-project-card";
    link.href = `/projects?project=${encodeURIComponent(project.id)}`;
    link.innerHTML = `<div class="resume-project-body"><span class="resume-status">${statuses[project.status]}</span><h3>${escapeHtml(project.title)}</h3><p>${escapeHtml(project.materials.join(" · ") || project.surface || "Your studio plan")}</p><progress max="100" value="${project.progress.percent}" aria-label="${project.progress.done} of ${project.progress.total} steps checked"></progress><small>${project.progress.done} of ${project.progress.total} steps checked</small><span class="resume-open">Continue project →</span></div>`;
    if (project.cover) {
      const image = document.createElement("img");
      image.src = project.cover.url;
      image.alt = project.cover.title;
      image.loading = "lazy";
      image.onerror = () => image.remove();
      link.prepend(image);
    }
    return link;
  }));
  $("#resumeEmpty").hidden = overview.recent.length > 0;
  $("#resumeEmpty h3").textContent = overview.counts.total ? "Your projects are marked complete" : "Your next piece starts here";
  $("#resumeEmpty p").textContent = overview.counts.total ? "Revisit your finished projects, or find an idea for your next piece." : "Explore an idea, save it, and make a studio plan that suits you.";
}

function renderLibrary(selector, items, artwork) {
  if (!items.length) {
    const message = document.createElement("p"); message.className = "activity-loading";
    message.textContent = artwork ? "Your saved artwork will appear here." : "Save an idea from Think Tank or your Prompt Library to see it here.";
    $(selector).replaceChildren(message);
    return;
  }
  $(selector).replaceChildren(...items.map((item) => {
    const link = document.createElement("a");
    link.href = artwork ? `/image-studio?artwork=${encodeURIComponent(item.id)}` : `/prompts?prompt=${encodeURIComponent(item.id)}`;
    link.innerHTML = `<span class="conversation-icon ${artwork ? "purple" : "amber"}" aria-hidden="true">${artwork ? "✦" : "▤"}</span><span class="home-library-entry"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml((artwork ? item.notes || item.collection : item.text).slice(0, 140))}</small></span><b aria-hidden="true">›</b>`;
    return link;
  }));
}

function renderTesting(data) {
  const testing = data.version_testing;
  const rules = data.midjourney_rules;
  $("#versionTestingPanel").hidden = !testing.total && !rules.outdated_prompts;
  const verifiedDate = rules.verified_at
    ? new Date(`${rules.verified_at}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "not recorded";
  $("#midjourneyRulesStatus").textContent = `MidJourney v${rules.version} · ${rules.verification_label} ${verifiedDate} · ${rules.review_message}`;
  $("#midjourneyRulesStatus").dataset.status = rules.verification_status;
  $("#midjourneyRulesStatus").title = rules.next_review ? `Next rules review: ${rules.next_review}` : "Open the Style Bible to verify these rules";
  $("#versionTestProgress").textContent = testing.total ? `${testing.completion_percent}% tested` : "No copies yet";
  $("#versionTestBar").style.width = `${testing.completion_percent}%`;
  for (const [id, key] of [["versionTestTotal", "total"], ["versionTestUntested", "untested"], ["versionTestActive", "active"],
    ["versionTestOriginal", "original"], ["versionTestTie", "tie"], ["versionTestRetest", "retest_recommended"]]) $("#" + id).textContent = testing[key];
  $("#retestQueueLink").hidden = testing.retest_recommended === 0;
  $("#outdatedPromptLink").hidden = rules.outdated_prompts === 0;
  $("#outdatedPromptLink").textContent = `Update ${rules.outdated_prompts} older-version ${rules.outdated_prompts === 1 ? "prompt" : "prompts"} →`;
}

async function loadDashboard() {
  if (loading) return;
  loading = true;
  $("#refreshStudio").disabled = true;
  $("#studioOverview").setAttribute("aria-busy", "true");
  $("#dashboardStatus").textContent = hasLoaded ? "Refreshing your studio…" : "Loading your studio…";
  try {
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    if (!response.ok) throw new Error("Studio unavailable");
    const data = await response.json();
    for (const [id, value] of [["promptCount", data.counts.prompts], ["artworkCount", data.counts.artworks],
      ["favoriteCount", data.counts.favorites], ["projectCount", data.counts.projects], ["kitCount", data.counts.creative_kits],
      ["activeProjectCount", data.projects.counts.in_progress], ["completedProjectCount", data.projects.counts.completed]]) $("#" + id).textContent = value;
    $("#reviewCount").textContent = data.counts.to_review ? `${data.counts.to_review} to review` : "All organized";
    renderProjects(data.projects);
    renderLibrary("#recentPrompts", data.recent_prompts, false);
    renderLibrary("#recentArtworks", data.recent_artworks, true);
    renderTesting(data);
    featuredPrompt = data.prompt_of_day;
    $("#copyPrompt").disabled = !featuredPrompt;
    $("#dailyPromptLink").hidden = !featuredPrompt;
    $("#dailyPromptLink").href = featuredPrompt ? `/prompts?prompt=${encodeURIComponent(featuredPrompt.id)}` : "/prompts";
    $("#dailyPrompt").textContent = featuredPrompt?.text || "Save your first prompt or Think Tank idea to feature it here.";
    $("#dailyCategory").textContent = featuredPrompt?.category || "Your library";
    $("#studioConnection").dataset.state = "connected";
    $("#studioConnection span").textContent = "Studio connected";
    $("#dashboardStatus").textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}. Saved work is available across your connected devices.`;
    hasLoaded = true;
  } catch {
    $("#studioConnection").dataset.state = "error";
    $("#studioConnection span").textContent = "Studio unavailable";
    $("#dashboardStatus").textContent = hasLoaded ? "Could not refresh. Showing the last loaded view; try again when connected." : "Could not load your studio. Try Refresh studio when connected. You can still open the tools below.";
    if (!hasLoaded) {
      $("#dailyPrompt").textContent = "Your saved idea will appear when the studio reconnects.";
      $("#recentPrompts").innerHTML = '<p class="activity-loading">Saved ideas could not be loaded.</p>';
      $("#recentArtworks").innerHTML = '<p class="activity-loading">Artwork could not be loaded.</p>';
    }
  } finally {
    loading = false;
    $("#refreshStudio").disabled = false;
    $("#studioOverview").setAttribute("aria-busy", "false");
  }
}
$("#refreshStudio").onclick = loadDashboard;
window.addEventListener("pageshow", (event) => { if (event.persisted) loadDashboard(); });
loadDashboard();
