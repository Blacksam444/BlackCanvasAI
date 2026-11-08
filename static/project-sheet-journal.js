/* Sheet choices read saved entries only; browser journal drafts stay untouched. */
const projectSheetJournal = (() => {
  const el = (id) => document.getElementById(id);
  let projectId = null;
  let entries = [];
  let selected = new Set();
  let loading = false;
  let building = false;
  let known = false;
  let requestId = 0;
  let controller = null;

  function controls() {
    el("refreshSheetJournal").disabled = loading || building;
    el("sheetJournalChoices").querySelectorAll("input").forEach((input) => { input.disabled = loading || building; });
  }
  function count() {
    el("sheetJournalCount").textContent = known ? `(${selected.size} selected · ${entries.length} available)` : loading ? "(loading…)" : "";
  }
  function render(changedIds = new Set()) {
    el("sheetJournalChoices").replaceChildren(...entries.map((entry) => {
      const article = document.createElement("article");
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox"; input.value = entry.id; input.checked = selected.has(entry.id);
      const time = document.createElement("time");
      time.dateTime = entry.entry_date;
      time.textContent = new Date(`${entry.entry_date}T12:00:00`).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
      label.append(input, time); article.append(label);
      const body = document.createElement("p"); body.className = "sheet-entry-body"; body.textContent = entry.body;
      if (entry.body.length > 200) {
        const excerpt = document.createElement("p"); excerpt.textContent = `${entry.body.slice(0, 160)}…`;
        const details = document.createElement("details");
        const summary = document.createElement("summary"); summary.textContent = "Read full saved entry";
        details.append(summary, body); article.append(excerpt, details);
      } else article.append(body);
      if (changedIds.has(entry.id)) {
        const note = document.createElement("p"); note.className = "sheet-entry-changed";
        note.textContent = "Changed since your selection. Review this saved version and select it again to include it.";
        article.append(note);
      }
      input.onchange = () => { if (input.checked) selected.add(entry.id); else selected.delete(entry.id); count(); };
      return article;
    }));
    el("sheetNoJournal").hidden = !known || entries.length > 0;
    count(); controls();
  }
  async function refresh() {
    if (!projectId || loading || building) return;
    const token = ++requestId;
    const id = projectId;
    const previous = new Map(entries.map((entry) => [entry.id, entry]));
    if (selected.size) {
      clearSheet();
      el("sheetStatus").textContent = "Journal choices are refreshing. Make preview again after reviewing the saved entries.";
    }
    loading = true; controller = new AbortController(); count(); controls();
    el("sheetJournalStatus").textContent = "Loading saved journal entries…";
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(id)}/journal`, { cache: "no-store", signal: controller.signal });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Saved entries could not be loaded.");
      if (token !== requestId || id !== projectId) return;
      const latest = new Map(result.map((entry) => [entry.id, entry]));
      const changedIds = new Set();
      let removed = 0;
      for (const entryId of selected) {
        if (!latest.has(entryId)) { selected.delete(entryId); removed++; }
        else if (latest.get(entryId).revision !== previous.get(entryId)?.revision) {
          selected.delete(entryId); changedIds.add(entryId);
        }
      }
      entries = result; known = true; render(changedIds);
      el("sheetJournalStatus").textContent = changedIds.size || removed
        ? `${changedIds.size} changed and ${removed} removed selections were unchecked. Review and select saved entries again before making your copy.`
        : "Saved entries refreshed. Your selections are kept where the entries have not changed.";
    } catch (error) {
      if (token === requestId && error.name !== "AbortError") {
        el("sheetJournalStatus").textContent = "Could not load saved journal entries. Your choices are kept; try Refresh saved entries again. You can still make a copy of the plan and photos.";
      }
    } finally {
      if (token === requestId) { loading = false; controller = null; count(); controls(); }
    }
  }
  el("refreshSheetJournal").onclick = refresh;
  return {
    open(id) {
      ++requestId; controller?.abort(); controller = null;
      projectId = id; entries = []; selected = new Set(); known = false; loading = false; building = false;
      el("sheetJournalOptions").open = false;
      render(); refresh();
    },
    close() {
      ++requestId; controller?.abort(); controller = null;
      projectId = null; loading = false; building = false;
    },
    selection() {
      if (loading && selected.size) return null;
      return entries.filter((entry) => selected.has(entry.id)).map((entry) => ({ id: entry.id, revision: entry.revision }));
    },
    setBusy(value) { building = value; controls(); },
  };
})();
