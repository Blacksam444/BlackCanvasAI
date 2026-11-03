/* Direct project creation shares the existing project editor and server store. */
(() => {
  const dialog = $("#newProjectDialog");
  const form = $("#newProjectForm");
  const storageKey = "blackCanvasNewProjectDraft";
  const fields = {
    title: $("#newProjectTitle"), status: $("#newProjectStatus"), surface: $("#newProjectSurface"),
    materials: $("#newProjectMaterials"), steps: $("#newProjectSteps"), notes: $("#newProjectNotes"),
  };
  let creationId = null;
  let creating = false;
  let conflict = false;
  let restored = false;
  let draftStored = false;

  function newId() {
    const bytes = new Uint8Array(16);
    // getRandomValues works on the private HTTP preview as well as HTTPS.
    if (globalThis.crypto?.getRandomValues) crypto.getRandomValues(bytes);
    else for (let index = 0; index < bytes.length; index++) bytes[index] = Math.floor(Math.random() * 256);
    return `direct_${Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("")}`;
  }

  function readDraft() {
    return { schema: 1, id: creationId, ...Object.fromEntries(Object.entries(fields).map(([key, input]) => [key, input.value])) };
  }

  function hasWork() {
    return fields.status.value !== "planned" || ["title", "surface", "materials", "steps", "notes"].some((key) => fields[key].value.length > 0);
  }

  function validDraft(draft) {
    const lengths = { title: 200, surface: 240, materials: 7500, steps: 120060, notes: 5000 };
    return draft?.schema === 1 && typeof draft.id === "string" && /^direct_[a-f0-9]{32}$/.test(draft.id)
      && Object.hasOwn(statuses, draft.status)
      && Object.entries(lengths).every(([key, length]) => typeof draft[key] === "string" && draft[key].length <= length);
  }

  function remember() {
    if (creating) return;
    creationId ||= newId();
    try {
      if (hasWork()) localStorage.setItem(storageKey, JSON.stringify(readDraft()));
      else localStorage.removeItem(storageKey);
      draftStored = true;
    } catch {
      draftStored = false;
      $("#newProjectDraftNote").textContent = "This browser cannot keep an unfinished form after the page closes. Your fields stay here while this page is open; create the project to save them.";
    }
  }

  function clearDraft() {
    form.reset();
    $("#newProjectPlan").open = false;
    creationId = null;
    restored = false;
    draftStored = false;
    conflict = false;
    $("#newProjectConflict").hidden = true;
    $("#newProject").textContent = "＋ New project";
    try { localStorage.removeItem(storageKey); } catch { /* A retry still uses its saved creation ID. */ }
  }

  function pending(value) {
    creating = value;
    form.querySelectorAll("input,select,textarea,button").forEach((input) => { input.disabled = value; });
    $("#createProject").disabled = value || conflict;
  }

  function open() {
    creationId ||= newId();
    $("#newProjectMessage").textContent = conflict ? "This creation was already saved. Choose whether to open it or create a separate project."
      : hasWork() ? "Your unfinished form is here. Create project when ready." : "";
    dialog.showModal();
    fields.title.focus();
  }

  function close() {
    if (creating) return;
    remember();
    $("#newProject").textContent = hasWork() ? "Resume new project" : "＋ New project";
    dialog.close();
  }

  async function showSaved(project, created) {
    // Use the confirmed response rather than a follow-up request that could fail.
    await loadProject(project.id, false, project);
    projects = [project, ...projects.filter((item) => item.id !== project.id)];
    history.replaceState(null, "", `/projects?project=${encodeURIComponent(project.id)}`);
    clearDraft();
    dialog.close();
    $("#saveStatus").textContent = created ? "Project created and saved. Add photos or keep shaping your plan below."
      : "Your project was already saved. Opened the saved plan without creating another project.";
    $("#projectHeading").focus();
    window.scrollTo({ top: 0, behavior: "auto" });
  }

  form.addEventListener("input", remember);
  form.addEventListener("change", remember);
  form.onsubmit = async (event) => {
    event.preventDefault();
    if (creating || conflict) return;
    const title = fields.title.value.trim();
    const materials = fields.materials.value.split("\n").map((value) => value.trim()).filter(Boolean);
    const steps = fields.steps.value.split("\n").map((value) => value.trim()).filter(Boolean);
    if (!title) { $("#newProjectMessage").textContent = "Give your project a title."; fields.title.focus(); return; }
    if (materials.length > 30 || materials.some((value) => value.length > 240)) {
      $("#newProjectMessage").textContent = "Use up to 30 materials, each up to 240 characters.";
      $("#newProjectPlan").open = true; fields.materials.focus(); return;
    }
    if (steps.length > 60 || steps.some((value) => value.length > 2000)) {
      $("#newProjectMessage").textContent = "Use up to 60 steps, each up to 2,000 characters.";
      $("#newProjectPlan").open = true; fields.steps.focus(); return;
    }
    remember();
    const payload = {
      id: creationId, title, status: fields.status.value, surface: fields.surface.value, materials,
      notes: fields.notes.value,
      // Stable within this form so an identical retry also has identical steps.
      checklist: steps.map((text, index) => ({ id: `step_${index + 1}`, text, done: false })),
    };
    pending(true);
    $("#newProjectMessage").textContent = "Creating your project…";
    try {
      const result = await photoRequest("/api/projects/direct", "POST", payload);
      await showSaved(result.project, result.created);
    } catch (error) {
      $("#newProjectMessage").textContent = error.status === 409 ? error.message
        : `${error.message} Your form is kept; retrying this creation will not add a second project.`;
      if (error.status === 409) {
        conflict = true;
        $("#newProjectConflict").hidden = false;
      }
    } finally { pending(false); }
  };

  $("#newProject").onclick = open;
  $("#closeNewProject").onclick = close;
  $("#cancelNewProject").onclick = close;
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
  dialog.addEventListener("close", () => {
    if (!$("#overview").hidden) $("#newProject").focus();
    else $("#projectHeading").focus();
  });
  $("#discardNewProject").onclick = () => {
    if (creating || (hasWork() && !confirm("Discard this unfinished project form? Saved projects will stay in your studio."))) return;
    clearDraft();
    dialog.close();
  };
  $("#openCreatedProject").onclick = async () => {
    if (creating || !creationId) return;
    pending(true);
    $("#newProjectMessage").textContent = "Opening the saved project…";
    try { await showSaved(await request(`/api/projects/${encodeURIComponent(creationId)}`), false); }
    catch (error) { $("#newProjectMessage").textContent = error.message; }
    finally { pending(false); }
  };
  $("#createSeparateProject").onclick = () => {
    if (creating) return;
    creationId = newId();
    conflict = false;
    $("#newProjectConflict").hidden = true;
    $("#createProject").disabled = false;
    remember();
    form.requestSubmit();
  };
  window.addEventListener("beforeunload", (event) => {
    if (creating || (hasWork() && !draftStored)) { event.preventDefault(); event.returnValue = ""; }
  });

  try {
    const draft = JSON.parse(localStorage.getItem(storageKey) || "null");
    if (validDraft(draft)) {
      creationId = draft.id;
      Object.entries(fields).forEach(([key, input]) => { input.value = draft[key]; });
      $("#newProjectPlan").open = ["surface", "materials", "steps", "notes"].some((key) => draft[key].length > 0);
      restored = true;
      draftStored = true;
    }
  } catch {
    $("#newProjectDraftNote").textContent = "Browser draft storage is unavailable or could not be read. You can still create and save a project here.";
  }
  if (restored) $("#newProject").textContent = "Resume new project";
  if (location.hash === "#newProject" && !new URLSearchParams(location.search).has("project")) open();
})();
