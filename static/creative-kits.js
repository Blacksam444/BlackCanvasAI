const fields = ["materials", "surface", "collection", "other_materials", "style_direction", "palette", "mood", "avoid"];
const pick = (brief) => Object.fromEntries(fields.map((key) => [key, Array.isArray(brief[key]) ? [...brief[key]] : brief[key]]));

export function initCreativeKits({ getBrief, applyPreferences, canAct, options }) {
  const $ = (selector) => document.querySelector(selector);
  let kits = [];
  let working = false;
  let previous = null;
  const selected = () => kits.find((kit) => kit.id === $("#kitSelect").value);
  const status = (message) => { $("#kitStatus").textContent = message; };
  function controls() {
    $("#creativeKits").querySelectorAll("input,select,button").forEach((control) => { control.disabled = working || !canAct(); });
    for (const id of ["applyKit", "updateKit", "removeKit"]) $("#" + id).disabled ||= !selected();
    $("#undoKit").hidden = previous === null;
  }
  async function request(url, method = "GET", payload) {
    let response;
    try { response = await fetch(url, { method, ...(payload === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }) }); }
    catch { throw new Error("Could not reach saved kits. Your current Think Tank fields are still here; please try again."); }
    let result;
    try { result = await response.json(); } catch { throw new Error("Saved kits could not finish that request. Please try again."); }
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Check the kit name and preferences, then try again.");
    return result;
  }
  function preview() {
    const kit = selected();
    $("#kitPreview").hidden = !kit;
    $("#kitPreview").replaceChildren();
    if (kit) {
      const preferences = kit.preferences;
      const values = [
        ["Materials", [...preferences.materials.map((name) => options.materials[name]), preferences.other_materials].filter(Boolean).join(" · ")],
        ["Surface", options.surfaces[preferences.surface]], ["Collection preset", preferences.collection],
        ["Style / influences", preferences.style_direction], ["Colors", preferences.palette],
        ["Mood", preferences.mood], ["Things to avoid", preferences.avoid],
      ];
      for (const [label, value] of values) {
        const term = document.createElement("dt"); term.textContent = label;
        const description = document.createElement("dd"); description.textContent = value || "Not specified";
        $("#kitPreview").append(term, description);
      }
    }
    controls();
  }
  function render(id = "") {
    $("#kitSelect").replaceChildren(new Option(kits.length ? "Choose a saved kit" : "No kits saved yet", ""),
      ...kits.map((kit) => new Option(kit.name, kit.id)));
    $("#kitSelect").value = kits.some((kit) => kit.id === id) ? id : "";
    preview();
  }
  async function refresh() {
    if (working || !canAct()) return;
    working = true; controls(); status("Loading saved kits…");
    const id = $("#kitSelect").value;
    try {
      kits = await request("/api/creative-kits");
      render(id);
      status(kits.length ? "Saved kits refreshed. Choose one to review or apply." : "Save your first set of creative preferences below.");
    } catch (error) { status(error.message); }
    finally { working = false; controls(); }
  }
  $("#kitSelect").onchange = () => {
    preview();
    if (selected()) $("#kitName").value = selected().name;
    status(selected() ? "Review this kit, then apply it to the form when you want." : "Choose a kit, or save the preferences in your form.");
  };
  $("#applyKit").onclick = () => {
    if (working || !canAct() || !selected()) return;
    previous = pick(getBrief());
    applyPreferences(selected().preferences);
    status(`Applied “${selected().name}” to the form. Create new ideas when ready.`);
    controls();
  };
  $("#undoKit").onclick = () => {
    if (working || !canAct() || !previous) return;
    applyPreferences(previous); previous = null;
    status("Your previous form preferences are restored."); controls();
  };
  async function save(update) {
    if (working || !canAct() || (update && !selected())) return;
    if (!$("#kitSaveForm").reportValidity()) return;
    const name = $("#kitName").value.trim();
    if (!name) { status("Give this kit a name before saving."); $("#kitName").focus(); return; }
    const kit = selected();
    const payload = { name, preferences: pick(getBrief()), ...(update ? { revision: kit.revision } : {}) };
    working = true; controls(); status("Saving creative preferences…");
    try {
      const result = await request(update ? `/api/creative-kits/${encodeURIComponent(kit.id)}` : "/api/creative-kits", update ? "PUT" : "POST", payload);
      const saved = update ? result : result.kit;
      kits = [...kits.filter((item) => item.id !== saved.id), saved].sort((a, b) => a.name.localeCompare(b.name));
      render(saved.id); $("#kitName").value = saved.name;
      status(`${update ? "Updated" : "Saved"} “${saved.name}” in this studio. It is available on your connected devices.`);
    } catch (error) { status(error.message); }
    finally { working = false; controls(); }
  }
  $("#kitSaveForm").onsubmit = (event) => { event.preventDefault(); save(false); };
  $("#updateKit").onclick = () => save(true);
  $("#refreshKits").onclick = refresh;
  $("#removeKit").onclick = async () => {
    if (working || !canAct() || !selected()) return;
    const kit = selected();
    if (!confirm(`Remove “${kit.name}” from saved kits? Your current form, ideas, and projects will be kept.`)) return;
    working = true; controls();
    try {
      await request(`/api/creative-kits/${encodeURIComponent(kit.id)}?revision=${kit.revision}`, "DELETE");
      kits = kits.filter((item) => item.id !== kit.id); render();
      status(`Removed “${kit.name}” from saved kits.`);
    } catch (error) { status(error.message); }
    finally { working = false; controls(); }
  };
  $("#tankForm").addEventListener("input", (event) => {
    if (event.target.id !== "direction") { previous = null; controls(); }
  });
  $("#tankForm").addEventListener("change", (event) => {
    if (event.target.id !== "direction") { previous = null; controls(); }
  });
  refresh();
  return { setDisabled: controls };
}
