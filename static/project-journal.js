/* Loaded before projects.js. Journal requests never replace the plan editor. */
const projectJournalUI = (() => {
  const el = (id) => document.getElementById(id);
  const dialog = el("journalDialog");
  const dateInput = el("journalDate");
  const bodyInput = el("journalBody");
  let projectId = null;
  let entries = [];
  let loaded = false;
  let loading = false;
  let listRequest = 0;
  let saving = false;
  let editor = null;
  let changed = false;
  let draftStored = false;
  let draftStamp = null;
  let conflict = false;
  let savedReview = null;
  const key = () => `blackCanvasJournalDraft:${projectId}`;
  const message = (text) => { el("journalDialogStatus").textContent = text; };
  const base = () => `/api/projects/${encodeURIComponent(projectId)}/journal`;
  const entryUrl = () => `${base()}/${encodeURIComponent(editor.id)}`;

  function newId() {
    const bytes = new Uint8Array(16);
    if (globalThis.crypto?.getRandomValues) crypto.getRandomValues(bytes);
    else for (let index = 0; index < bytes.length; index++) bytes[index] = Math.floor(Math.random() * 256);
    return `journal_${Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("")}`;
  }
  function today() {
    const date = new Date();
    return `${date.getFullYear().toString().padStart(4, "0")}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  }
  function formatDate(value) {
    // A calendar date must not shift when viewed in another time zone.
    return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
  }
  function validDate(value) {
    return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)
      && value.slice(0, 4) !== "0000" && !Number.isNaN(Date.parse(`${value}T12:00:00Z`))
      && new Date(`${value}T12:00:00Z`).toISOString().slice(0, 10) === value;
  }
  function readDraft() {
    try {
      const raw = localStorage.getItem(key());
      const value = JSON.parse(raw || "null");
      if (value?.schema === 1 && /^journal_[a-f0-9]{32}$/.test(value.id) && (value.entry_date === "" || validDate(value.entry_date))
        && typeof value.body === "string" && value.body.length <= 5000
        && (value.revision === null || (Number.isInteger(value.revision) && value.revision > 0))) return { value, raw };
    } catch { /* A browser draft is optional; confirmed server saves still work. */ }
    return null;
  }
  function draft() {
    return { schema: 1, id: editor.id, revision: editor.revision, entry_date: dateInput.value, body: bodyInput.value };
  }
  function draftHint() {
    el("journalDraftNote").textContent = changed
      ? draftStored ? "Unfinished text is kept in this browser. Save entry to make it available on your connected devices."
        : "Browser draft storage is unavailable. Keep this page open until you save, or copy your text before leaving."
      : "Save entry to keep it in this project. Your plan fields stay as you left them.";
  }
  function remember() {
    if (!editor || saving) return;
    changed = true;
    draftStored = false;
    try {
      const candidate = JSON.stringify(draft());
      localStorage.setItem(key(), candidate); draftStamp = candidate; draftStored = true;
    } catch { /* Keep the previous stored stamp so discard/save can clear that older draft. */ }
    draftHint();
    el("resumeJournalDraft").hidden = !readDraft();
  }
  function clearDraft() {
    try {
      // Another tab may have written a different unfinished entry in the meantime.
      if (draftStamp && localStorage.getItem(key()) === draftStamp) localStorage.removeItem(key());
    } catch { /* The confirmed server result remains saved. */ }
    changed = false; draftStored = false; draftStamp = null;
    el("resumeJournalDraft").hidden = !readDraft();
  }
  async function api(url, method = "GET", payload) {
    let response;
    try {
      response = await fetch(url, { method, cache: "no-store", ...(payload ? {
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      } : {}) });
    } catch { throw new Error("Could not reach the studio. Your journal text is still here; try again when connected."); }
    let result;
    try { result = await response.json(); } catch { throw new Error("The studio could not finish that request. Please try again."); }
    if (!response.ok) {
      const error = new Error(typeof result.detail === "string" ? result.detail : "Check the date and entry text, then try again.");
      error.status = response.status; throw error;
    }
    return result;
  }
  function controls() {
    el("refreshJournal").disabled = loading || saving;
    el("addJournalEntry").disabled = saving;
    el("resumeJournalDraft").disabled = saving;
    el("journalForm").querySelectorAll("input,textarea,button").forEach((control) => { control.disabled = saving; });
    el("saveJournalEntry").disabled = saving || conflict;
    el("removeJournalEntry").hidden = !editor?.revision;
    el("removeJournalEntry").disabled = saving || conflict;
    el("journalHeading").textContent = editor?.revision ? "Edit journal entry" : "New journal entry";
  }
  function render() {
    el("journalEntries").replaceChildren(...entries.map((entry) => {
      const item = document.createElement("li");
      item.className = "journal-entry";
      const header = document.createElement("header");
      const time = document.createElement("time");
      time.dateTime = entry.entry_date; time.textContent = formatDate(entry.entry_date);
      const edit = document.createElement("button");
      edit.type = "button"; edit.className = "secondary"; edit.textContent = "Edit entry";
      edit.setAttribute("aria-label", `Edit entry from ${formatDate(entry.entry_date)}`);
      edit.onclick = () => openEntry(entry);
      header.append(time, edit);
      const body = document.createElement("p"); body.textContent = entry.body;
      const updated = document.createElement("small"); updated.textContent = `Saved ${new Date(entry.updated_at).toLocaleString()}`;
      item.append(header, body, updated); return item;
    }));
    el("journalCount").textContent = loaded ? `(${entries.length})` : "";
    el("journalEmpty").hidden = !loaded || entries.length > 0;
    el("resumeJournalDraft").hidden = !readDraft();
    controls();
  }
  function accept(entry) {
    ++listRequest; loading = false;
    entries = entries.filter((item) => item.id !== entry.id).concat(entry).sort((a, b) =>
      b.entry_date.localeCompare(a.entry_date) || b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id));
    // A failed initial list may have hidden other entries. Do not call this a full list.
    render();
  }
  async function refresh() {
    if (!projectId || saving) return;
    const id = projectId;
    const token = ++listRequest;
    loading = true; controls();
    el("journalStatus").textContent = "Loading journal…";
    try {
      const result = await api(base());
      if (id !== projectId || token !== listRequest) return;
      entries = result; loaded = true;
      el("journalStatus").textContent = "Journal refreshed. Your plan edits are kept.";
      render();
    } catch (error) {
      if (id === projectId && token === listRequest) el("journalStatus").textContent = error.message;
    } finally {
      if (id === projectId && token === listRequest) { loading = false; controls(); }
    }
  }
  function resetReview() {
    conflict = false; savedReview = null;
    el("journalConflict").hidden = true;
    el("reviewJournalEntry").hidden = true;
    el("journalAsNew").hidden = true;
  }
  function prepare(value, stored = null) {
    editor = { id: value.id, revision: value.revision };
    dateInput.value = value.entry_date; bodyInput.value = value.body;
    changed = !!stored; draftStored = !!stored; draftStamp = stored;
    resetReview(); draftHint(); controls();
    dialog.showModal();
    bodyInput.focus();
  }
  function mayReplace(id = null) {
    const saved = readDraft();
    return !saved || saved.value.id === id || confirm("Replace the unfinished journal entry in this browser? Its text will be discarded.");
  }
  async function openEntry(entry) {
    if (saving) return;
    const saved = readDraft();
    if (saved?.value.id === entry.id) { resume(); return; }
    if (!mayReplace(entry.id)) return;
    if (saved) { draftStamp = saved.raw; clearDraft(); }
    prepare(entry);
    message("Edit this entry, then Save entry. Remove saved entry removes it from this project's journal.");
  }
  function handleConflict(error) {
    message(error.message);
    if (error.status === 409 || error.status === 404) {
      conflict = true;
      el("reviewJournalEntry").hidden = false;
      el("journalConflict").hidden = true;
    }
  }
  async function review() {
    if (saving || !editor) return;
    saving = true; controls();
    try {
      savedReview = await api(entryUrl());
      accept(savedReview);
      conflict = true;
      el("journalSavedDate").textContent = formatDate(savedReview.entry_date);
      el("journalSavedBody").textContent = savedReview.body;
      el("journalConflict").hidden = false;
      el("journalAsNew").hidden = true;
      el("reviewJournalEntry").hidden = true;
      message("Review the saved entry below. Your date and text above have not changed.");
    } catch (error) {
      handleConflict(error);
      if (error.status === 404) {
        entries = entries.filter((item) => item.id !== editor.id); render();
        el("journalAsNew").hidden = false;
        el("reviewJournalEntry").hidden = true;
      }
    } finally { saving = false; controls(); }
  }
  function resume() {
    if (saving) return;
    const saved = readDraft();
    if (!saved) { render(); return; }
    prepare(saved.value, saved.raw);
    message("Your unfinished journal entry was restored in this browser.");
    if (editor.revision !== null) {
      // Explicit review prevents an old browser draft from overwriting newer text.
      conflict = true; controls();
      review();
    }
  }
  function close() {
    if (saving) return;
    if (changed && !draftStored) {
      if (!confirm("This browser cannot keep the unfinished entry. Close and discard its text?")) return;
      clearDraft();
    }
    dialog.close();
  }

  el("addJournalEntry").onclick = () => {
    if (saving || !mayReplace()) return;
    const saved = readDraft();
    if (saved) { draftStamp = saved.raw; clearDraft(); }
    prepare({ id: newId(), revision: null, entry_date: today(), body: "" });
    message("Record what matters to your practice. Save entry when ready.");
  };
  el("resumeJournalDraft").onclick = resume;
  el("refreshJournal").onclick = refresh;
  [dateInput, bodyInput].forEach((input) => input.addEventListener("input", remember));
  el("reviewJournalEntry").onclick = review;
  el("keepJournalEdits").onclick = () => {
    if (saving || !savedReview) return;
    editor.revision = savedReview.revision;
    resetReview(); remember(); controls();
    message("Your edits are ready for review. Save entry to replace the version you just reviewed.");
  };
  el("useSavedJournal").onclick = () => {
    if (saving || !savedReview) return;
    const saved = savedReview;
    clearDraft(); editor.revision = saved.revision;
    dateInput.value = saved.entry_date; bodyInput.value = saved.body;
    resetReview(); draftHint(); controls(); message("Saved entry loaded. Your unfinished edits were discarded.");
  };
  el("journalAsNew").onclick = () => {
    if (saving) return;
    editor = { id: newId(), revision: null };
    resetReview(); remember(); controls(); message("Your text is ready as a new entry. Review it, then Save entry.");
  };
  el("closeJournal").onclick = close;
  el("keepJournalLater").onclick = close;
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
  dialog.addEventListener("close", () => { el("resumeJournalDraft").hidden = !readDraft(); el("addJournalEntry").focus(); });
  el("discardJournalDraft").onclick = () => {
    if (saving || (changed && !confirm("Discard this unfinished journal entry? The saved entry, if any, stays in the journal."))) return;
    clearDraft(); dialog.close();
  };
  el("journalForm").onsubmit = async (event) => {
    event.preventDefault();
    if (saving || conflict || !editor) return;
    if (!bodyInput.value.trim() || !validDate(dateInput.value)) { message("Choose a valid date and write an entry before saving."); return; }
    // Capture even an unchanged edit for retry and browser recovery.
    remember();
    const payload = { entry_date: dateInput.value, body: bodyInput.value.trim() };
    saving = true; ++listRequest; loading = false; controls(); message("Saving journal entry…");
    try {
      const result = editor.revision === null ? await api(base(), "POST", { ...payload, id: editor.id })
        : await api(entryUrl(), "PUT", { ...payload, revision: editor.revision });
      const entry = result.entry || result;
      accept(entry); clearDraft();
      el("journalStatus").textContent = loaded ? "Journal entry saved. Your plan edits are kept."
        : "Entry saved. Refresh journal to load the rest of your saved entries.";
      saving = false; dialog.close();
    } catch (error) { handleConflict(error); }
    finally { saving = false; controls(); }
  };
  el("removeJournalEntry").onclick = async () => {
    if (saving || conflict || !editor?.revision || !confirm("Remove this saved journal entry and discard any unfinished edits to it? Your plan and photos will stay saved.")) return;
    saving = true; ++listRequest; loading = false; controls(); message("Removing journal entry…");
    try {
      await api(entryUrl(), "DELETE", { revision: editor.revision });
      entries = entries.filter((item) => item.id !== editor.id); clearDraft(); render();
      el("journalStatus").textContent = "Journal entry removed. Your plan edits are kept.";
      saving = false; dialog.close();
    } catch (error) { handleConflict(error); }
    finally { saving = false; controls(); }
  };
  window.addEventListener("beforeunload", (event) => {
    if (saving || (changed && !draftStored)) { event.preventDefault(); event.returnValue = ""; }
  });
  return {
    load(id) {
      if (projectId !== id) {
        projectId = id; entries = []; loaded = false; editor = null; changed = false;
        draftStored = false; draftStamp = null; el("projectJournal").open = false;
      }
      render(); refresh();
    },
  };
})();
