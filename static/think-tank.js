import { WORKSPACE_KEY, restoreWorkspace, selectSingleRemix, arrangeBatchRemix } from "./think-tank-state.js?v=2";

const $ = (selector) => document.querySelector(selector);
let generatedBrief = null;
let variation = 0;
let ideas = [];
let busy = false;
let options = null;
const escapeHtml = (text = "") => String(text).replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
}[character]));

async function request(url, payload) {
  let response;
  try {
    response = await fetch(url, payload === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
  } catch {
    throw new Error("Could not reach the studio. Your current ideas are still here; please try again.");
  }
  let result;
  try { result = await response.json(); }
  catch { throw new Error("The studio could not finish that request. Please try again."); }
  if (!response.ok) {
    const error = new Error(typeof result.detail === "string" ? result.detail : "Check your materials and direction, then try again.");
    error.status = response.status;
    throw error;
  }
  return result;
}

function showStatus(message) { $("#tankStatus").textContent = message; }

function formBrief() {
  return {
    materials: [...document.querySelectorAll('input[name="material"]:checked')].map((input) => input.value),
    surface: $("#surface").value, direction: $("#direction").value, collection: $("#collection").value,
  };
}

function rememberWorkspace() {
  if (!options) return;
  try {
    localStorage.setItem(WORKSPACE_KEY, JSON.stringify({
      version: 1, form: formBrief(), brief: generatedBrief, variation, ideas,
    }));
  } catch {
    $("#workspaceNote").textContent = "This browser can’t remember your workspace. Save ideas to Prompt Library before leaving.";
  }
}

function setBusy(value) {
  busy = value;
  $("#generateIdeas").disabled = busy || !options;
  $("#remixIdeas").disabled = busy || ideas.length !== 3;
  $("#results").setAttribute("aria-busy", String(busy));
  document.querySelectorAll(".idea-card").forEach((card, index) => {
    card.querySelector(".save-idea").disabled = busy || ideas[index].saved;
    card.querySelector(".remix-idea").disabled = busy;
  });
}

function createIdeaCard(idea, index) {
  const card = document.createElement("article");
  card.className = "idea-card";
  card.innerHTML = `<span class="idea-number">IDEA 0${index + 1} · ${escapeHtml(idea.category)}</span>
    <h3>${escapeHtml(idea.title)}</h3><p>${escapeHtml(idea.composition)}</p>
    <h4>Materials &amp; surface</h4><p>${escapeHtml(idea.materials.join(" · "))}<br>${escapeHtml(idea.surface)}</p>
    <h4>Palette &amp; mood</h4><p>${escapeHtml(idea.palette)}<br>${escapeHtml(idea.mood)}</p>
    ${idea.style_ingredients ? `<h4>Style Bible ingredients</h4><p>${escapeHtml(idea.style_ingredients)}</p>` : ""}
    ${idea.always ? `<h4>Always include</h4><p>${escapeHtml(idea.always)}</p>` : ""}
    ${idea.avoid ? `<h4>Avoid</h4><p>${escapeHtml(idea.avoid)}</p>` : ""}
    <h4>Try it on the worktable</h4><ol>${idea.steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ol>
    <details><summary>Optional image reference prompt</summary><p>${escapeHtml(idea.reference_prompt)}</p></details>
    <div class="idea-actions"><button class="tank-primary save-idea" type="button">${idea.saved ? "Saved ✓" : "Save to Prompt Library"}</button><button class="tank-secondary remix-idea" type="button">↻ Remix this idea</button><a href="/prompts" ${idea.saved ? "" : "hidden"}>View library ↗</a></div>`;
  const save = card.querySelector(".save-idea");
  save.disabled = idea.saved || busy;
  save.onclick = async () => {
    if (busy || idea.saved) return;
    setBusy(true);
    save.textContent = "Saving…";
    try {
      const result = await request("/api/prompts", { title: idea.title, category: idea.category, text: idea.text, favorite: false });
      idea.saved = true;
      idea.savedId = result.id;
      save.textContent = "Saved ✓";
      card.querySelector(".idea-actions a").hidden = false;
      showStatus("Idea and studio plan saved to your Prompt Library.");
    } catch (error) {
      if (error.status === 409) {
        idea.saved = true;
        save.textContent = "Already saved ✓";
        card.querySelector(".idea-actions a").hidden = false;
        showStatus("This idea is already in your Prompt Library.");
      } else {
        save.textContent = "Retry save";
        showStatus(error.message);
      }
    } finally {
      rememberWorkspace();
      setBusy(false);
    }
  };
  card.querySelector(".remix-idea").disabled = busy;
  card.querySelector(".remix-idea").onclick = () => remixOne(index);
  return card;
}

function renderIdeas() {
  $("#ideaGrid").replaceChildren(...ideas.map(createIdeaCard));
  if (ideas.length !== 3) return;
  $("#resultSummary").textContent = `${generatedBrief.collection} · ${ideas[0].materials.join(" + ")} · ${ideas[0].surface}`;
  $("#results").hidden = false;
}

const newIdea = (idea, nextVariation) => ({ ...idea, variation: nextVariation, saved: false, savedId: null });

async function generate(brief, nextVariation, remix = false) {
  if (busy) return;
  setBusy(true);
  showStatus("Shaping three directions for your worktable…");
  try {
    const result = await request("/api/think-tank/generate", { ...brief, variation: nextVariation });
    const nextIdeas = remix ? arrangeBatchRemix(result.ideas, ideas) : result.ideas;
    generatedBrief = brief;
    variation = nextVariation;
    ideas = nextIdeas.map((idea) => newIdea(idea, nextVariation));
    renderIdeas();
    rememberWorkspace();
    $("#resultsTitle").focus();
    showStatus("Three ideas ready. Save a starting point or remix an individual idea.");
  } catch (error) {
    showStatus(error.message);
  } finally {
    setBusy(false);
  }
}

async function remixOne(index) {
  if (busy || !generatedBrief) return;
  const nextVariation = (ideas[index].variation + 1) % 6;
  setBusy(true);
  showStatus(`Remixing idea ${index + 1}. Your other ideas will stay in place…`);
  try {
    const result = await request("/api/think-tank/generate", { ...generatedBrief, variation: nextVariation });
    const candidate = selectSingleRemix(result.ideas, ideas, index);
    if (!candidate) throw new Error("Could not find a distinct remix. Your ideas are still here; please try again.");
    ideas[index] = newIdea(candidate, nextVariation);
    const replacement = createIdeaCard(ideas[index], index);
    $("#ideaGrid").children[index].replaceWith(replacement);
    rememberWorkspace();
    showStatus(`Idea ${index + 1} remixed. The other two are unchanged.`);
  } catch (error) {
    showStatus(error.message);
  } finally {
    setBusy(false);
    $("#ideaGrid").children[index].querySelector(".remix-idea").focus({ preventScroll: true });
  }
}

$("#tankForm").onsubmit = (event) => {
  event.preventDefault();
  const brief = formBrief();
  brief.direction = brief.direction.trim();
  if (!brief.materials.length) {
    showStatus("Choose at least one material.");
    $("#materialOptions input").focus();
    return;
  }
  if (brief.direction.length < 3) {
    showStatus("Add a direction of at least three characters.");
    $("#direction").focus();
    return;
  }
  generate(brief, 0);
};
$("#tankForm").addEventListener("input", rememberWorkspace);
$("#tankForm").addEventListener("change", rememberWorkspace);
$("#remixIdeas").onclick = () => {
  if (generatedBrief) generate(generatedBrief, (variation + 1) % 6, true);
};
$("#menuButton").onclick = () => {
  const open = $("#sidebar").classList.toggle("open");
  $("#menuButton").setAttribute("aria-expanded", String(open));
  if (open) $("#closeMenu").focus();
};
const closeMenu = () => {
  $("#sidebar").classList.remove("open");
  $("#menuButton").setAttribute("aria-expanded", "false");
  $("#menuButton").focus();
};
$("#closeMenu").onclick = closeMenu;
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && $("#sidebar").classList.contains("open")) closeMenu();
});

async function loadOptions() {
  try {
    options = await request("/api/think-tank/options");
    $("#materialOptions").innerHTML = Object.entries(options.materials).map(([value, label]) =>
      `<label class="material-choice"><input type="checkbox" name="material" value="${escapeHtml(value)}" ${value === "acrylic" ? "checked" : ""}>${escapeHtml(label)}</label>`).join("");
    $("#surface").innerHTML = Object.entries(options.surfaces).map(([value, label]) =>
      `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`).join("");
    let restored;
    try { restored = restoreWorkspace(localStorage.getItem(WORKSPACE_KEY), options); }
    catch { $("#workspaceNote").textContent = "This browser can’t remember your workspace. Save ideas to Prompt Library before leaving."; }
    if (restored) {
      generatedBrief = restored.brief;
      variation = restored.variation;
      ideas = restored.ideas;
      document.querySelectorAll('input[name="material"]').forEach((input) => { input.checked = restored.form.materials.includes(input.value); });
      $("#surface").value = restored.form.surface;
      $("#direction").value = restored.form.direction;
      $("#collection").value = restored.form.collection;
      if (ideas.some((idea) => idea.saved)) {
        try {
          const library = await request("/api/prompts");
          ideas.forEach((idea) => {
            if (!idea.saved) return;
            const saved = library.find((prompt) => !prompt.trashed && (idea.savedId
              ? prompt.id === idea.savedId && prompt.text === idea.text
              : prompt.title === idea.title && prompt.text === idea.text));
            idea.saved = Boolean(saved);
            idea.savedId = saved?.id || null;
          });
        } catch {
          // Duplicate protection makes retrying an unverified save safe.
          ideas.forEach((idea) => { idea.saved = false; idea.savedId = null; });
        }
      }
      renderIdeas();
      rememberWorkspace();
      showStatus(ideas.length ? "Your workspace is restored. Continue with an idea or remix one." : "Your direction is restored. Create three ideas when you’re ready.");
    } else {
      showStatus("Choose your materials, then give the piece a direction.");
    }
    setBusy(false);
  } catch {
    options = null;
    setBusy(false);
    showStatus("Could not load materials. Reload this page to try again.");
  }
}
loadOptions();
