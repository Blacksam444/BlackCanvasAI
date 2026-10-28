const $ = (selector) => document.querySelector(selector);
let generatedBrief = null;
let variation = 0;
let busy = false;
const escapeHtml = (text = "") => String(text).replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
}[character]));

async function request(url, payload) {
  const response = await fetch(url, payload === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(typeof result.detail === "string" ? result.detail : "Check your materials and direction, then try again.");
    error.status = response.status;
    throw error;
  }
  return result;
}

function showStatus(message) { $("#tankStatus").textContent = message; }

function renderIdeas(ideas) {
  $("#ideaGrid").replaceChildren();
  ideas.forEach((idea, index) => {
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
      <div class="idea-actions"><button class="tank-primary" type="button">Save to Prompt Library</button><a href="/prompts" hidden>View library ↗</a></div>`;
    const save = card.querySelector("button");
    save.onclick = async () => {
      save.disabled = true;
      save.textContent = "Saving…";
      try {
        await request("/api/prompts", { title: idea.title, category: idea.category, text: idea.text, favorite: false });
        save.textContent = "Saved ✓";
        card.querySelector(".idea-actions a").hidden = false;
        showStatus("Idea and studio plan saved to your Prompt Library.");
      } catch (error) {
        if (error.status === 409) {
          save.textContent = "Already saved ✓";
          card.querySelector(".idea-actions a").hidden = false;
          showStatus("This idea is already in your Prompt Library.");
        } else {
          save.disabled = false;
          save.textContent = "Retry save";
          showStatus(error.message || "Could not save. Your ideas are still here; please try again.");
        }
      }
    };
    $("#ideaGrid").appendChild(card);
  });
}

async function generate(brief, nextVariation) {
  if (busy) return;
  busy = true;
  $("#generateIdeas").disabled = true;
  $("#remixIdeas").disabled = true;
  $("#results").setAttribute("aria-busy", "true");
  showStatus("Shaping three directions for your worktable…");
  try {
    const result = await request("/api/think-tank/generate", { ...brief, variation: nextVariation });
    generatedBrief = brief;
    variation = nextVariation;
    renderIdeas(result.ideas);
    $("#resultSummary").textContent = `${brief.collection} · ${result.ideas[0].materials.join(" + ")} · ${result.ideas[0].surface}`;
    $("#results").hidden = false;
    $("#resultsTitle").focus();
    showStatus("Three ideas ready. Save a starting point or remix the compositions.");
  } catch (error) {
    showStatus(error.message || "Could not generate ideas. Please try again.");
  } finally {
    busy = false;
    $("#generateIdeas").disabled = false;
    $("#remixIdeas").disabled = false;
    $("#results").setAttribute("aria-busy", "false");
  }
}

$("#tankForm").onsubmit = (event) => {
  event.preventDefault();
  const materials = [...document.querySelectorAll('input[name="material"]:checked')].map((input) => input.value);
  const direction = $("#direction").value.trim();
  if (!materials.length) {
    showStatus("Choose at least one material.");
    $("#materialOptions input").focus();
    return;
  }
  if (direction.length < 3) {
    showStatus("Add a direction of at least three characters.");
    $("#direction").focus();
    return;
  }
  generate({ materials, surface: $("#surface").value, direction, collection: $("#collection").value }, 0);
};
$("#remixIdeas").onclick = () => {
  if (generatedBrief) generate(generatedBrief, (variation + 1) % 6);
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
    const options = await request("/api/think-tank/options");
    $("#materialOptions").innerHTML = Object.entries(options.materials).map(([value, label]) =>
      `<label class="material-choice"><input type="checkbox" name="material" value="${escapeHtml(value)}" ${value === "acrylic" ? "checked" : ""}>${escapeHtml(label)}</label>`).join("");
    $("#surface").innerHTML = Object.entries(options.surfaces).map(([value, label]) =>
      `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`).join("");
    $("#generateIdeas").disabled = false;
    showStatus("Choose your materials, then give the piece a direction.");
  } catch {
    showStatus("Could not load materials. Reload this page to try again.");
  }
}
loadOptions();
