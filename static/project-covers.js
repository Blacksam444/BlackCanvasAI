/* Loaded before projects.js; event callbacks share its existing project state. */
function coverFields(value) {
  return { cover: value.cover, cover_artwork_id: value.cover_artwork_id,
    cover_revision: value.cover_revision, cover_unavailable: value.cover_unavailable };
}
function acceptProjectCover(value) {
  if (!current || !Number.isInteger(value.cover_revision) || value.cover_revision < current.cover_revision) return;
  Object.assign(current, coverFields(value));
  projects = projects.map((item) => item.id === current.id ? { ...item, ...coverFields(current) } : item);
  renderProjectCover();
}
function renderProjectCover() { projectCoverUI.render(); }

const projectCoverUI = (() => {
  const element = (id) => document.getElementById(id);
  const dialog = element("projectCoverDialog");
  const select = element("coverPhotoChoice");
  const preview = element("coverChoicePreview");
  let busyCover = false;
  let conflict = false;
  let previewFailed = false;
  let previewLoading = false;

  function controls() {
    element("chooseProjectCover").disabled = busyCover || photoBusy;
    element("refreshProjectCover").disabled = busyCover || photoBusy;
    dialog.querySelectorAll("button,select").forEach((control) => { control.disabled = busyCover; });
    element("saveProjectCover").disabled = busyCover || conflict || (select.value !== "" && (previewFailed || previewLoading));
  }
  function savedDescription() {
    if (current.cover_artwork_id === null) return "Automatic · latest available progress or finished photo";
    return current.cover ? `Chosen photo · ${current.cover.title}` : "Your chosen cover is unavailable. Choose another photo or Automatic.";
  }
  function render() {
    if (!current) return;
    const img = element("projectCoverImage");
    element("projectCoverDescription").textContent = savedDescription();
    element("projectCoverPlaceholder").hidden = !!current.cover;
    element("projectCoverPlaceholder").textContent = current.cover_unavailable ? "Cover unavailable" : "Your project photo";
    img.hidden = !current.cover;
    img.onerror = () => { img.hidden = true; element("projectCoverPlaceholder").hidden = false; element("projectCoverPlaceholder").textContent = "Cover image unavailable"; };
    if (current.cover) { img.alt = current.cover.title; img.src = current.cover.url; }
    else img.removeAttribute("src");
    controls();
  }
  function showPreview() {
    previewFailed = false;
    previewLoading = false;
    preview.hidden = true;
    preview.removeAttribute("src");
    const photo = select.value === "" ? (current.cover_artwork_id === null ? current.cover : null)
      : photos.find((item) => String(item.id) === select.value);
    element("coverChoiceCaption").textContent = photo ? photo.title
      : "Automatic uses the latest available progress or finished photo. Choose any linked photo to set your own cover.";
    if (photo) {
      previewLoading = true;
      preview.onload = () => { previewLoading = false; preview.hidden = false; controls(); };
      preview.onerror = () => {
        previewLoading = false; previewFailed = true; preview.hidden = true;
        element("coverChoiceCaption").textContent = "This image is unavailable. Choose another photo or Automatic.";
        controls();
      };
      preview.alt = photo.title;
      preview.src = photo.url;
    }
    controls();
  }
  function fillChoices(selected) {
    select.replaceChildren(new Option("Automatic · latest progress or finished photo", ""),
      ...photos.map((photo) => new Option(`${photo.title} · ${photoStages[photo.stage]}`, String(photo.id))));
    const kept = !selected || photos.some((photo) => String(photo.id) === selected);
    select.value = kept ? selected : "";
    element("coverChoiceEmpty").hidden = photos.length > 0;
    element("savedCoverChoice").textContent = `Saved cover: ${savedDescription()}`;
    showPreview();
    return kept;
  }
  function open() {
    if (!current || busyCover || photoBusy) return;
    conflict = false;
    element("coverChoiceStatus").textContent = "The cover saves separately from your plan. Your current plan fields stay in place.";
    fillChoices(current.cover_artwork_id === null ? "" : String(current.cover_artwork_id));
    dialog.showModal();
  }
  function close() { if (!busyCover) dialog.close(); }

  element("chooseProjectCover").onclick = open;
  element("closeProjectCover").onclick = close;
  element("cancelProjectCover").onclick = close;
  dialog.addEventListener("cancel", (event) => { if (busyCover) event.preventDefault(); });
  dialog.addEventListener("close", () => { preview.removeAttribute("src"); element("chooseProjectCover").focus(); });
  select.onchange = () => { element("coverChoiceStatus").textContent = conflict ? "Refresh the saved cover and photos before saving your choice." : "Choice changed. Save cover to use it."; showPreview(); };
  element("refreshProjectCover").onclick = async () => {
    if (!current || busyCover || photoBusy) return;
    busyCover = true; controls();
    try {
      acceptProjectCover(await request(`/api/projects/${encodeURIComponent(current.id)}/cover`));
      element("coverStatus").textContent = "Cover refreshed. Your plan edits are kept.";
    } catch (error) { element("coverStatus").textContent = error.message; }
    finally { busyCover = false; controls(); }
  };
  element("refreshCoverChoices").onclick = async () => {
    if (!current || busyCover) return;
    const selected = select.value;
    busyCover = true; controls();
    try {
      const project = await request(`/api/projects/${encodeURIComponent(current.id)}`);
      photos = project.artworks;
      acceptProjectCover(project);
      renderPhotos();
      conflict = false;
      const kept = fillChoices(selected);
      element("coverChoiceStatus").textContent = kept
        ? "Saved cover and photos refreshed for review. Your choice is still shown. Save cover to apply it."
        : "The selected photo is no longer linked. Choose another photo or Automatic. Your plan edits are kept.";
    } catch (error) { element("coverChoiceStatus").textContent = error.message; }
    finally { busyCover = false; controls(); }
  };
  element("projectCoverForm").onsubmit = async (event) => {
    event.preventDefault();
    if (!current || busyCover || conflict || element("saveProjectCover").disabled) return;
    const payload = { artwork_id: select.value === "" ? null : Number(select.value), cover_revision: current.cover_revision };
    busyCover = true; controls();
    element("coverChoiceStatus").textContent = "Saving project cover…";
    let saved = false;
    try {
      acceptProjectCover(await request(`/api/projects/${encodeURIComponent(current.id)}/cover`, payload));
      element("coverStatus").textContent = "Project cover saved. Your plan edits are kept.";
      saved = true;
    } catch (error) {
      element("coverChoiceStatus").textContent = error.message;
      conflict = error.status === 409 || error.status === 404;
    } finally {
      busyCover = false; controls();
      if (saved) dialog.close();
    }
  };
  return { render };
})();
