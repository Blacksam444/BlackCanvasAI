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
  let reusedPlan = null;
  let completionTarget = null;

  function newId() {
    const bytes = new Uint8Array(16);
    // getRandomValues works on the private HTTP preview as well as HTTPS.
    if (globalThis.crypto?.getRandomValues) crypto.getRandomValues(bytes);
    else for (let index = 0; index < bytes.length; index++) bytes[index] = Math.floor(Math.random() * 256);
    return `direct_${Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("")}`;
  }

  function readDraft() {
    return { schema: reusedPlan ? 2 : 1, id: creationId,
      ...Object.fromEntries(Object.entries(fields).map(([key, input]) => [key, input.value])),
      ...(reusedPlan ? { reused_plan: reusedPlan } : {}),
    };
  }

  function hasWork() {
    return !!reusedPlan || fields.status.value !== "planned" || ["title", "surface", "materials", "steps", "notes"].some((key) => fields[key].value.length > 0);
  }

  function validDraft(draft) {
    const lengths = { title: 200, surface: 240, materials: 7500, steps: 120060, notes: 5000 };
    const reuse = draft?.reused_plan;
    const validReuse = draft?.schema === 1 || (draft?.schema === 2 && reuse
      && typeof reuse.source_id === "string" && /^[A-Za-z0-9_-]{1,80}$/.test(reuse.source_id)
      && typeof reuse.source_title === "string" && reuse.source_title.length <= 200
      && typeof reuse.includes_edits === "boolean" && Array.isArray(reuse.steps) && reuse.steps.length <= 60
      && reuse.steps.every((text) => typeof text === "string" && text.length <= 2000));
    return validReuse && typeof draft.id === "string" && /^direct_[a-f0-9]{32}$/.test(draft.id)
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
    reusedPlan = null;
    configureReuse();
    $("#newProjectConflict").hidden = true;
    $("#newProject").textContent = "＋ New project";
    try { localStorage.removeItem(storageKey); } catch { /* A retry still uses its saved creation ID. */ }
  }

  function pending(value) {
    creating = value;
    form.querySelectorAll("input,select,textarea,button").forEach((input) => { input.disabled = value; });
    $("#createProject").disabled = value || conflict;
    fields.steps.disabled = value || !!reusedPlan;
    $("#addReusedStep").disabled = value || (reusedPlan?.steps.length || 0) >= 60;
  }

  function open() {
    creationId ||= newId();
    configureReuse();
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
    const keepOriginal = reusedPlan && current?.id === reusedPlan.source_id;
    // Use the confirmed response rather than a follow-up request that could fail.
    if (!keepOriginal) await loadProject(project.id, false, project);
    projects = [project, ...projects.filter((item) => item.id !== project.id)];
    if (keepOriginal) {
      $("#planReuseMessage").textContent = `${created ? "New project saved" : "Previously saved project found"}: ${project.title}`;
      $("#planReuseLink").href = `/projects?project=${encodeURIComponent(project.id)}`;
      $("#planReuseSaved").hidden = false;
      completionTarget = $("#planReuseSaved");
    } else {
      history.replaceState(null, "", `/projects?project=${encodeURIComponent(project.id)}`);
    }
    clearDraft();
    dialog.close();
    if (keepOriginal) {
      $("#planReuseSaved").focus();
      $("#planReuseSaved").scrollIntoView({ block: "center" });
      return;
    }
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
    const steps = reusedPlan ? reusedPlan.steps.map((text) => text.trim())
      : fields.steps.value.split("\n").map((value) => value.trim()).filter(Boolean);
    if (!title) { $("#newProjectMessage").textContent = "Give your project a title."; fields.title.focus(); return; }
    if (materials.length > 30 || materials.some((value) => value.length > 240)) {
      $("#newProjectMessage").textContent = "Use up to 30 materials, each up to 240 characters.";
      $("#newProjectPlan").open = true; fields.materials.focus(); return;
    }
    if (steps.length > 60 || steps.some((value) => !value || value.length > 2000)) {
      $("#newProjectMessage").textContent = "Use up to 60 steps, each with text up to 2,000 characters.";
      $("#newProjectPlan").open = true;
      if (!reusedPlan) fields.steps.focus();
      return;
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
    if (completionTarget) { completionTarget.focus(); completionTarget = null; }
    else if (reusedPlan && reusedPlan.source_id === current?.id) $("#reuseProjectPlan").focus();
    else if (!$("#overview").hidden) $("#newProject").focus();
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
      reusedPlan = draft.schema === 2 ? draft.reused_plan : null;
      Object.entries(fields).forEach(([key, input]) => { input.value = draft[key]; });
      $("#newProjectPlan").open = !!reusedPlan || ["surface", "materials", "steps", "notes"].some((key) => draft[key].length > 0);
      restored = true;
      draftStored = true;
    }
  } catch {
    $("#newProjectDraftNote").textContent = "Browser draft storage is unavailable or could not be read. You can still create and save a project here.";
  }
  configureReuse();
  if (restored) $("#newProject").textContent = "Resume new project";
  if (location.hash === "#newProject" && !new URLSearchParams(location.search).has("project")) open();

  function renderReusedSteps(focusIndex = null) {
    if (!reusedPlan) return;
    $("#reusedStepsList").replaceChildren(...reusedPlan.steps.map((text, index) => {
      const row = document.createElement("li");
      const label = document.createElement("label");
      label.textContent = `Step ${index + 1}`;
      const input = document.createElement("textarea");
      input.rows = 3; input.maxLength = 2000; input.required = true; input.value = text;
      input.oninput = () => { reusedPlan.steps[index] = input.value; };
      label.appendChild(input);
      const remove = document.createElement("button");
      remove.type = "button"; remove.className = "remove-step"; remove.textContent = "×";
      remove.setAttribute("aria-label", `Remove copied step ${index + 1}`);
      remove.onclick = () => {
        reusedPlan.steps.splice(index, 1); renderReusedSteps(); remember(); $("#addReusedStep").focus();
      };
      row.append(label, remove);
      return row;
    }));
    $("#reusedStepsEmpty").hidden = reusedPlan.steps.length > 0;
    $("#addReusedStep").disabled = creating || reusedPlan.steps.length >= 60;
    if (focusIndex !== null) $("#reusedStepsList").querySelectorAll("textarea")[focusIndex]?.focus();
  }

  function configureReuse() {
    const keepsOriginal = reusedPlan?.source_id === current?.id && !!reusedPlan;
    $("#newProjectHeading").textContent = reusedPlan ? "New project from this plan" : "Start your project";
    $("#newProjectReuseNote").hidden = !reusedPlan;
    $("#newProjectStepsField").hidden = !!reusedPlan;
    fields.steps.disabled = !!reusedPlan;
    $("#reusedProjectSteps").hidden = !reusedPlan;
    $("#reusedStepsList").replaceChildren();
    $("#openCreatedProject").textContent = keepsOriginal ? "Use saved project" : "Open saved project";
    $("#newProjectConflictHint").textContent = keepsOriginal
      ? "Use saved project discards this form and gives you its link. Create a separate project saves these fields as another project. Your original plan stays open."
      : "Open saved project discards this form. Create a separate project saves these fields as another project.";
    if (reusedPlan) {
      $("#newProjectReuseNote").textContent = `From ${reusedPlan.source_title}${reusedPlan.includes_edits ? ", including your unsaved edits" : ""}. Review the copied materials, steps, and notes. Photos stay in their existing projects.`;
      renderReusedSteps();
    }
  }

  $("#addReusedStep").onclick = () => {
    if (!reusedPlan || creating || reusedPlan.steps.length >= 60) return;
    reusedPlan.steps.push(""); renderReusedSteps(reusedPlan.steps.length - 1); remember();
  };
  $("#reuseProjectPlan").onclick = () => {
    if (!current || busy || creating) return;
    if (reusedPlan?.source_id === current.id) { open(); return; }
    if (!$("#projectForm").reportValidity()) return;
    const plan = readForm();
    if (!plan.title || plan.materials.length > 30 || plan.materials.some((value) => value.length > 240)) {
      $("#saveStatus").textContent = "Check your title and materials before reusing the plan. Use up to 30 materials, each up to 240 characters.";
      return;
    }
    if (hasWork() && !confirm("Replace the unfinished new-project form with this plan? Any project already saved in the studio will be kept.")) return;
    clearDraft();
    reusedPlan = { source_id: current.id, source_title: plan.title, includes_edits: dirty, steps: plan.checklist.map((step) => step.text) };
    fields.surface.value = plan.surface;
    fields.materials.value = plan.materials.join("\n");
    fields.notes.value = plan.notes;
    $("#newProjectPlan").open = true;
    configureReuse(); remember(); open();
  };
})();
