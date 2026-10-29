import { WORKSPACE_KEY, restoreWorkspace, selectSingleRemix, arrangeRemixGroups } from "./think-tank-state.js?v=4";
import { initCreativeKits } from "./creative-kits.js?v=1";

const $ = (selector) => document.querySelector(selector);
let generatedBrief = null;
let variation = 0;
let ideas = [];
let busy = false;
let options = null;
let kitsController = null;
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
    other_materials: $("#otherMaterials").value, style_direction: $("#styleDirection").value,
    palette: $("#palette").value, mood: $("#mood").value, avoid: $("#avoid").value,
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
  kitsController?.setDisabled();
  $("#generateIdeas").disabled = busy || !options;
  $("#remixIdeas").disabled = busy || ideas.length !== 3;
  $("#results").setAttribute("aria-busy", String(busy));
  document.querySelectorAll(".idea-card").forEach((card, index) => {
    card.querySelector(".save-idea").disabled = busy || ideas[index].saved;
    card.querySelector(".remix-idea").disabled = busy;
    card.querySelector(".start-project").disabled = busy;
    card.querySelectorAll(".refine-form input, .refine-form textarea, .refine-form button")
      .forEach((control) => { control.disabled = busy; });
  });
}

function createIdeaCard(idea, index) {
  const brief = idea.brief || generatedBrief;
  const refinement = idea.refineDraft || {
    direction: brief.direction, palette: idea.palette, mood: idea.mood, studio_notes: brief.studio_notes || "",
    style_direction: brief.style_direction || "", avoid: brief.avoid || "",
  };
  const card = document.createElement("article");
  card.className = "idea-card";
  card.innerHTML = `<span class="idea-number">IDEA 0${index + 1} · ${escapeHtml(idea.category)}</span>
    <h3>${escapeHtml(idea.title)}</h3><p>${escapeHtml(idea.composition)}</p>
    <h4>Materials &amp; surface</h4><p>${escapeHtml(idea.materials.join(" · "))}<br>${escapeHtml(idea.surface)}</p>
    <h4>Palette &amp; mood</h4><p>${escapeHtml(idea.palette || "Not specified")}<br>${escapeHtml(idea.mood || "Not specified")}</p>
    ${brief.style_direction ? `<h4>Your style direction</h4><p>${escapeHtml(brief.style_direction)}</p>` : ""}
    ${idea.style_ingredients ? `<h4>Style Bible ingredients</h4><p>${escapeHtml(idea.style_ingredients)}</p>` : ""}
    ${idea.always ? `<h4>Always include</h4><p>${escapeHtml(idea.always)}</p>` : ""}
    ${idea.avoid ? `<h4>Avoid</h4><p>${escapeHtml(idea.avoid)}</p>` : ""}
    <h4>Try it on the worktable</h4><ol>${idea.steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ol>
    ${brief.studio_notes ? `<h4>Studio notes</h4><p class="studio-notes">${escapeHtml(brief.studio_notes)}</p>` : ""}
    <details><summary>Optional image reference prompt</summary><p>${escapeHtml(idea.reference_prompt)}</p></details>
    <details class="idea-refine" ${idea.refineDraft ? "open" : ""}><summary>Develop this idea</summary>
      <p>Keep this composition, materials, surface, and collection. Shape the direction below.</p>
      <form class="refine-form">
        <label for="refineDirection${index}">Creative direction</label><textarea id="refineDirection${index}" name="direction" rows="3" minlength="3" maxlength="600" required>${escapeHtml(refinement.direction)}</textarea>
        <label for="refineMood${index}">Mood</label><input id="refineMood${index}" name="mood" maxlength="2600" value="${escapeHtml(refinement.mood)}" placeholder="For example: warm, hopeful, reflective">
        <label for="refinePalette${index}">Palette</label><input id="refinePalette${index}" name="palette" maxlength="2600" value="${escapeHtml(refinement.palette)}" placeholder="For example: indigo, copper, soft cream">
        <label for="refineStyle${index}">Your style / influences</label><input id="refineStyle${index}" name="style_direction" maxlength="600" value="${escapeHtml(refinement.style_direction)}" placeholder="Describe the visual approach you prefer">
        <label for="refineAvoid${index}">Things to avoid</label><textarea id="refineAvoid${index}" name="avoid" rows="2" maxlength="1200">${escapeHtml(refinement.avoid)}</textarea>
        <label for="refineNotes${index}">Studio notes</label><textarea id="refineNotes${index}" name="studio_notes" rows="3" maxlength="1200" placeholder="Your scale, texture, symbols, or finishing notes">${escapeHtml(refinement.studio_notes)}</textarea>
        <p class="tank-hint">Apply updates this card. Save the revision to add a new library entry.</p>
        <div class="refine-actions"><button class="tank-primary" type="submit">Apply refinement</button><button class="tank-secondary cancel-refine" type="button">Cancel edits</button></div>
        <p class="refine-status" role="status" aria-live="polite"></p>
      </form>
    </details>
    <div class="idea-actions"><button class="tank-primary save-idea" type="button">${idea.saved ? "Saved ✓" : "Save to Prompt Library"}</button><button class="tank-secondary start-project" type="button">${idea.projectId ? "Open project →" : "Start project →"}</button><button class="tank-secondary remix-idea" type="button">↻ Remix this idea</button><a href="/prompts" ${idea.saved ? "" : "hidden"}>View library ↗</a></div>`;
  const form = card.querySelector(".refine-form");
  const readRefinement = () => Object.fromEntries(["direction", "mood", "palette", "studio_notes", "style_direction", "avoid"]
    .map((name) => [name, form.elements.namedItem(name).value]));
  form.addEventListener("input", () => {
    idea.refineDraft = readRefinement();
    rememberWorkspace();
  });
  form.onsubmit = (event) => {
    event.preventDefault();
    refineOne(index, readRefinement());
  };
  form.querySelector(".cancel-refine").onclick = () => {
    delete idea.refineDraft;
    const replacement = createIdeaCard(idea, index);
    card.replaceWith(replacement);
    rememberWorkspace();
    replacement.querySelector(".idea-refine summary").focus({ preventScroll: true });
  };
  const save = card.querySelector(".save-idea");
  save.disabled = idea.saved || busy;
  save.onclick = async () => {
    if (busy || idea.saved) return;
    setBusy(true);
    save.textContent = "Saving…";
    try {
      const result = await ensureIdeaSaved(idea);
      save.textContent = result.existing ? "Already saved ✓" : "Saved ✓";
      card.querySelector(".idea-actions a").hidden = false;
      showStatus("Idea and studio plan saved to your Prompt Library.");
    } catch (error) {
      save.textContent = "Retry save";
      showStatus(error.message);
    } finally {
      rememberWorkspace();
      setBusy(false);
    }
  };
  card.querySelector(".remix-idea").disabled = busy;
  card.querySelector(".remix-idea").onclick = () => remixOne(index);
  const start = card.querySelector(".start-project");
  start.disabled = busy;
  start.onclick = async () => {
    if (busy) return;
    if (idea.projectId) { location.href = `/projects?project=${encodeURIComponent(idea.projectId)}`; return; }
    if (idea.refineDraft) { showStatus("Apply or cancel the refinement edits before starting this project."); return; }
    setBusy(true);
    start.textContent = "Starting project…";
    try {
      const saved = await ensureIdeaSaved(idea);
      save.textContent = "Saved ✓";
      card.querySelector(".idea-actions a").hidden = false;
      const result = await request("/api/projects", { prompt_id: saved.id, seed: {
        materials: idea.materials, surface: idea.surface, notes: (idea.brief || generatedBrief).studio_notes || "",
        checklist: idea.steps.map((text, step) => ({ id: `step_${Date.now().toString(36)}_${step}`, text, done: false })),
      } });
      idea.projectId = result.project.id;
      rememberWorkspace();
      location.href = `/projects?project=${encodeURIComponent(idea.projectId)}`;
    } catch (error) {
      showStatus(error.message);
      start.textContent = "Retry starting project";
      rememberWorkspace();
    } finally { setBusy(false); }
  };
  return card;
}

async function ensureIdeaSaved(idea) {
  if (idea.savedId && idea.saved) {
    const library = await request("/api/prompts");
    const saved = library.find((prompt) => prompt.id === idea.savedId && prompt.title === idea.title && prompt.text === idea.text);
    if (saved) {
      if (saved.trashed) await request("/api/prompts/bulk-restore", { prompt_ids: [saved.id] });
      return { id: saved.id, existing: true };
    }
    idea.saved = false;
    idea.savedId = null;
  }
  try {
    const result = await request("/api/prompts", { title: idea.title, category: idea.category, text: idea.text, favorite: false });
    idea.saved = true;
    idea.savedId = result.id;
    idea.text = result.text;
    return { id: result.id, existing: false };
  } catch (error) {
    if (error.status !== 409) throw error;
    const library = await request("/api/prompts");
    const saved = library.find((prompt) => prompt.title === idea.title && prompt.text === idea.text);
    if (!saved) throw new Error("This idea already exists in the library. Open it there to start the project.");
    if (saved.trashed) await request("/api/prompts/bulk-restore", { prompt_ids: [saved.id] });
    idea.saved = true;
    idea.savedId = saved.id;
    return { id: saved.id, existing: true };
  }
}

function renderIdeas() {
  $("#ideaGrid").replaceChildren(...ideas.map(createIdeaCard));
  if (ideas.length !== 3) return;
  $("#resultSummary").textContent = `${generatedBrief.collection} · ${ideas[0].materials.join(" + ")} · ${ideas[0].surface}`;
  $("#results").hidden = false;
}

const newIdea = (idea, nextVariation, previous = null) => ({
  ...idea, variation: nextVariation, saved: false, savedId: null,
  ...(previous?.refineDraft ? { refineDraft: previous.refineDraft } : {}),
});

async function generate(brief, nextVariation) {
  if (busy) return;
  setBusy(true);
  showStatus("Shaping three directions for your worktable…");
  try {
    const result = await request("/api/think-tank/generate", { ...brief, variation: nextVariation });
    generatedBrief = brief;
    variation = nextVariation;
    ideas = result.ideas.map((idea) => newIdea(idea, nextVariation));
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

async function remixAll() {
  if (busy || !generatedBrief) return;
  setBusy(true);
  showStatus("Remixing three ideas with their individual directions and refinements…");
  try {
    const nextVariations = ideas.map((idea) => (idea.variation + 1) % 6);
    const results = await Promise.all(ideas.map((idea, index) => request("/api/think-tank/generate", {
      ...(idea.brief || generatedBrief), variation: nextVariations[index],
    })));
    const selected = arrangeRemixGroups(results.map((result) => result.ideas), ideas);
    if (!selected) throw new Error("Could not find three distinct remixes. Your ideas are still here; please try again.");
    ideas = selected.map((idea, index) => newIdea(idea, nextVariations[index], ideas[index]));
    variation = (variation + 1) % 6;
    renderIdeas();
    rememberWorkspace();
    $("#resultsTitle").focus();
    showStatus("Three remixes ready. Each keeps its own creative direction, palette, mood, and notes.");
  } catch (error) {
    showStatus(error.message);
  } finally {
    setBusy(false);
  }
}

async function refineOne(index, refinement) {
  if (busy || !generatedBrief) return;
  const idea = ideas[index];
  const card = $("#ideaGrid").children[index];
  const status = card.querySelector(".refine-status");
  if (refinement.direction.trim().length < 3) {
    status.textContent = "Add a creative direction of at least three characters.";
    card.querySelector('[name="direction"]').focus();
    return;
  }
  setBusy(true);
  status.textContent = "Applying your refinement…";
  try {
    const result = await request("/api/think-tank/refine", {
      ...(idea.brief || generatedBrief), ...refinement, variation: idea.variation,
      composition_index: idea.composition_index ?? options.compositions.indexOf(idea.composition),
    });
    ideas[index] = newIdea(result.idea, idea.variation);
    const replacement = createIdeaCard(ideas[index], index);
    card.replaceWith(replacement);
    rememberWorkspace();
    showStatus(`Idea ${index + 1} refined. Save the revision when you’re ready.`);
    replacement.querySelector("h3").tabIndex = -1;
    replacement.querySelector("h3").focus({ preventScroll: true });
  } catch (error) {
    status.textContent = error.message;
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
    const result = await request("/api/think-tank/generate", { ...(ideas[index].brief || generatedBrief), variation: nextVariation });
    const candidate = selectSingleRemix(result.ideas, ideas, index);
    if (!candidate) throw new Error("Could not find a distinct remix. Your ideas are still here; please try again.");
    ideas[index] = newIdea(candidate, nextVariation, ideas[index]);
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
  if (!brief.materials.length && !brief.other_materials.trim()) {
    showStatus("Choose at least one material or describe your own materials.");
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
$("#remixIdeas").onclick = remixAll;
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
      `<label class="material-choice"><input type="checkbox" name="material" value="${escapeHtml(value)}">${escapeHtml(label)}</label>`).join("");
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
      for (const [id, key] of [["otherMaterials", "other_materials"], ["styleDirection", "style_direction"],
        ["palette", "palette"], ["mood", "mood"], ["avoid", "avoid"]]) $("#" + id).value = restored.form[key] || "";
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
    kitsController = initCreativeKits({
      getBrief: formBrief, canAct: () => !busy && Boolean(options), options,
      applyPreferences(preferences) {
        document.querySelectorAll('input[name="material"]').forEach((input) => { input.checked = preferences.materials.includes(input.value); });
        $("#surface").value = preferences.surface;
        $("#collection").value = preferences.collection;
        for (const [id, key] of [["otherMaterials", "other_materials"], ["styleDirection", "style_direction"],
          ["palette", "palette"], ["mood", "mood"], ["avoid", "avoid"]]) $("#" + id).value = preferences[key];
        rememberWorkspace();
      },
    });
    if (location.hash === "#creativeKits") {
      $("#creativeKits").open = true;
      $("#creativeKits").scrollIntoView({ block: "start" });
    }
  } catch {
    options = null;
    setBusy(false);
    showStatus("Could not load materials. Reload this page to try again.");
  }
}
loadOptions();
