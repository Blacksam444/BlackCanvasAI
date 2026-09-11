let artworks = [];
let filter = "All";
let saleStatusFilter = "All statuses";
let query = "";
let pendingFile = null;
let selectedId = null;
let currentContentKit = {};
let focusMode = new URLSearchParams(window.location.search).get("focus") || "";
const requestedArtworkId = Number(new URLSearchParams(window.location.search).get("artwork")) || null;
const requestedTool = new URLSearchParams(window.location.search).get("tool");

const grid = document.querySelector("#artGrid");
const drop = document.querySelector("#dropZone");
const empty = document.querySelector("#artEmpty");
const toast = document.querySelector("#toast");

const collectionDetails = {
  AfroNova: {
    tags: "afrofuturism, cosmic, regal, Black identity, gold, visionary",
    notes: "A bold AfroNova piece blending Black identity, imagined futures, ancestral power, and celestial elegance.",
  },
  "Quiet Nova": {
    tags: "reflective, calm, minimal, soft light, intimate, earth tones",
    notes: "A contemplative Quiet Nova piece centered on stillness, emotional depth, soft light, and grounded beauty.",
  },
  GraffitiX: {
    tags: "street art, graffiti, urban, neon, expressive, mixed media",
    notes: "An energetic GraffitiX piece combining urban expression, layered marks, bold color, and raw creative movement.",
  },
};

const notify = (message) => {
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 1900);
};
const escapeHtml = (text = "") => text.replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
}[character]));

async function load() {
  const response = await fetch("/api/artworks");
  if (!response.ok) throw new Error();
  artworks = await response.json();
  render();
}

function render() {
  grid.innerHTML = "";
  const shown = artworks.filter((artwork) => {
    const actionable = artwork.sale_status !== "Sold" && artwork.sale_status !== "Not for sale";
    return (
    filter === "All" || (filter === "Favorites" ? artwork.favorite : artwork.collection === filter)
  ) && (saleStatusFilter === "All statuses" || artwork.sale_status === saleStatusFilter)
    && `${artwork.title} ${artwork.collection} ${artwork.tags} ${artwork.notes} ${artwork.medium} ${artwork.dimensions}`.toLowerCase().includes(query)
    && (focusMode !== "unpriced" || (Number(artwork.price) <= 0 && actionable))
    && (focusMode !== "incomplete" || (actionable && (!artwork.dimensions?.trim() || !artwork.medium?.trim() || !artwork.notes?.trim() || !artwork.tags?.trim())))
    && (focusMode !== "ready" || artwork.sale_status === "Ready to list");
  });
  shown.forEach((artwork) => {
    const card = document.createElement("article");
    card.className = "art-card";
    const displayPrice = artwork.sale_status === "Sold" && artwork.sale_price ? artwork.sale_price : artwork.price;
    const missingDetails = [["dimensions", "size"], ["medium", "medium"], ["notes", "story"], ["tags", "tags"]]
      .filter(([field]) => !String(artwork[field] || "").trim())
      .map(([, label]) => label);
    if (Number(artwork.price) <= 0 && artwork.sale_status !== "Sold" && artwork.sale_status !== "Not for sale") missingDetails.push("price");
    const attention = artwork.sale_status !== "Sold" && artwork.sale_status !== "Not for sale" && missingDetails.length
      ? `<small class="art-needs-details">Needs ${escapeHtml(missingDetails.join(", "))}</small>`
      : "";
    card.innerHTML = `<img src="${artwork.url}" alt="${escapeHtml(artwork.title)}"><button class="art-favorite ${artwork.favorite ? "on" : ""}">★</button><span class="inventory-card-status status-${String(artwork.sale_status || "In progress").toLowerCase().replaceAll(" ", "-")}">${escapeHtml(artwork.sale_status || "In progress")}</span><div class="art-meta"><h2>${escapeHtml(artwork.title)}</h2><p>${escapeHtml(artwork.collection)}${displayPrice ? ` · ${money(displayPrice)}` : ""}</p>${attention}</div>`;
    card.querySelector(".art-favorite").onclick = async (event) => {
      event.stopPropagation();
      artwork.favorite = !artwork.favorite;
      await fetch(`/api/artworks/${artwork.id}/favorite?favorite=${artwork.favorite}`, { method: "PATCH" });
      render();
    };
    card.onclick = () => showDetail(artwork);
    grid.appendChild(card);
  });
  drop.hidden = artworks.length > 0;
  empty.hidden = shown.length > 0 || artworks.length === 0;
  document.querySelector("#artCount").textContent = artworks.length;
  document.querySelector("#inventoryInProgress").textContent = artworks.filter((item) => item.sale_status === "In progress").length;
  document.querySelector("#inventoryReady").textContent = artworks.filter((item) => item.sale_status === "Ready to list").length;
  document.querySelector("#inventoryListed").textContent = artworks.filter((item) => item.sale_status === "Listed").length;
  document.querySelector("#inventorySold").textContent = artworks.filter((item) => item.sale_status === "Sold").length;
  document.querySelector("#inventoryValue").textContent = money(artworks.reduce((total, item) => total + (Number(item.price) || 0), 0));
  document.querySelector("#salesRevenue").textContent = money(artworks.reduce((total, item) => total + (Number(item.sale_price) || 0), 0));
}

function choose() { document.querySelector("#fileInput").click(); }
function isUsableImage(file) {
  return file && file.type.startsWith("image/") && file.size <= 10 * 1024 * 1024;
}

function batchTitle(collection, usedTitles, position) {
  const choices = collectionTitles[collection] || collectionTitles.Unsorted;
  const base = choices[position % choices.length];
  let number = position + 1;
  let title = `${base} — ${String(number).padStart(2, "0")}`;
  while (usedTitles.has(title.toLowerCase())) {
    number += 1;
    title = `${base} — ${String(number).padStart(2, "0")}`;
  }
  usedTitles.add(title.toLowerCase());
  return title;
}

function openBatchUploader(files) {
  const usableFiles = files.filter(isUsableImage);
  if (!usableFiles.length) return notify("Choose image files smaller than 10 MB.");
  if (usableFiles.length !== files.length) notify("Some files were skipped because they are not supported images or are over 10 MB.");
  const dialog = document.createElement("dialog");
  dialog.style.cssText = "max-width:520px;border:1px solid #45396a;border-radius:16px;background:#131117;color:#fff;padding:26px;box-shadow:0 25px 80px #000b";
  dialog.innerHTML = `<form method="dialog"><h2 style="margin:0 0 8px;font-family:Manrope">Add ${usableFiles.length} artworks</h2><p style="color:#b4afbe;line-height:1.45">Choose one collection for this group. Each artwork will get its own title, tags, and starter description. You can edit any piece later.</p><label style="display:block;margin:18px 0 8px">Collection<select id="batchCollection" style="display:block;width:100%;margin-top:7px;padding:10px"><option>AfroNova</option><option>Quiet Nova</option><option>GraffitiX</option><option>Unsorted</option></select></label><label style="display:flex;gap:9px;align-items:center;margin:15px 0"><input id="batchGalleryVisible" type="checkbox"> Show all of these on my Gallery Site</label><div style="display:flex;justify-content:flex-end;gap:10px;margin-top:24px"><button value="cancel" style="padding:10px 14px">Cancel</button><button id="saveBatchArtwork" value="default" style="padding:10px 14px;background:#875df4;color:white;border:0;border-radius:8px;font-weight:700">Add all artworks</button></div></form>`;
  document.body.appendChild(dialog);
  dialog.querySelector("#saveBatchArtwork").onclick = async (event) => {
    event.preventDefault();
    const button = event.currentTarget;
    const collection = dialog.querySelector("#batchCollection").value;
    const showOnGallery = dialog.querySelector("#batchGalleryVisible").checked;
    button.disabled = true;
    button.textContent = "Adding artwork…";
    const usedTitles = new Set(artworks.map((item) => String(item.title || "").trim().toLowerCase()));
    const existingCount = artworks.filter((item) => item.collection === collection).length;
    const detail = collectionDetails[collection] || { tags: "original art, contemporary art, Black Canvas", notes: "An original work from the Black Canvas collection." };
    let saved = 0;
    let duplicates = 0;
    let failed = 0;
    for (let index = 0; index < usableFiles.length; index += 1) {
      const file = usableFiles[index];
      const payload = { title: batchTitle(collection, usedTitles, existingCount + index), collection, tags: `${detail.tags}, original art, contemporary Black art`, notes: detail.notes, dimensions: "", medium: "", price: 0, sale_status: "In progress", gallery_visible: showOnGallery, data_url: await toDataUrl(file) };
      const response = await fetch("/api/artworks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (response.ok) {
        saved += 1;
      } else if (response.status === 409) {
        duplicates += 1;
      } else {
        failed += 1;
      }
    }
    dialog.close();
    dialog.remove();
    await load();
    const parts = [`${saved} artwork${saved === 1 ? "" : "s"} added with titles and tags.`];
    if (duplicates) parts.push(`${duplicates} exact duplicate${duplicates === 1 ? " was" : "s were"} skipped.`);
    if (failed) parts.push(`${failed} file${failed === 1 ? " could" : "s could"} not be added.`);
    notify(parts.join(" "));
  };
  dialog.addEventListener("close", () => dialog.remove());
  dialog.showModal();
}

function applySuggestedDetails(collection, tagsInput, notesInput) {
  const suggestion = collectionDetails[collection];
  if (!suggestion) return;
  if (!tagsInput.value.trim()) tagsInput.value = suggestion.tags;
  if (!notesInput.value.trim()) notesInput.value = suggestion.notes;
}
function prepare(file) {
  if (!file || !file.type.startsWith("image/")) return notify("Please choose an image file.");
  if (file.size > 10 * 1024 * 1024) return notify("Please choose an image smaller than 10 MB.");
  pendingFile = file;
  document.querySelector("#artForm").reset();
  document.querySelector("#artTitle").value = file.name.replace(/\.[^.]+$/, "");
  document.querySelector("#artPreview").src = URL.createObjectURL(file);
  document.querySelector("#artDialog").showModal();
}

function showDetail(artwork) {
  selectedId = artwork.id;
  document.querySelector("#detailImage").src = artwork.url;
  document.querySelector("#detailCollection").textContent = artwork.collection;
  document.querySelector("#detailTitle").textContent = artwork.title;
  document.querySelector("#detailInventory").innerHTML = [
    artwork.sale_status ? `<span class="inventory-status">${escapeHtml(artwork.sale_status)}</span>` : "",
    artwork.price ? `<strong>${money(artwork.price)}</strong>` : "",
    artwork.dimensions ? `<span>${escapeHtml(artwork.dimensions)}</span>` : "",
    artwork.medium ? `<span>${escapeHtml(artwork.medium)}</span>` : "",
    artwork.sale_price ? `<strong>Sold for ${money(artwork.sale_price)}</strong>` : "",
    artwork.sold_date ? `<span>${escapeHtml(artwork.sold_date)}</span>` : "",
    artwork.sales_channel ? `<span>${escapeHtml(artwork.sales_channel)}</span>` : "",
    artwork.sale_status === "Sold" ? `<span>Order: ${escapeHtml(artwork.fulfillment_status || "Not started")}</span>` : "",
  ].filter(Boolean).join("");
  const saleButton = document.querySelector("#recordSale");
  saleButton.textContent = artwork.sale_status === "Sold" ? "$ View or update sale" : "$ Record artwork sale";
  saleButton.classList.toggle("sold", artwork.sale_status === "Sold");
  document.querySelector("#downloadSaleReceipt").hidden = artwork.sale_status !== "Sold";
  document.querySelector("#openBuyerKit").hidden = artwork.sale_status !== "Sold";
  document.querySelector("#openFulfillment").hidden = artwork.sale_status !== "Sold";
  document.querySelector("#detailNotes").textContent = artwork.notes || "No notes added yet.";
  document.querySelector("#detailTags").innerHTML = (artwork.tags || "").split(",").filter(Boolean).map((tag) => `<span>${escapeHtml(tag.trim())}</span>`).join("");
  document.querySelector("#detailDialog").showModal();
}

function openEditDialog() {
  const artwork = artworks.find((item) => item.id === selectedId);
  if (!artwork) return;
  document.querySelector("#editTitle").value = artwork.title;
  document.querySelector("#editCollection").value = artwork.collection;
  document.querySelector("#editTags").value = artwork.tags || "";
  document.querySelector("#editNotes").value = artwork.notes || "";
  document.querySelector("#editDimensions").value = artwork.dimensions || "";
  document.querySelector("#editMedium").value = artwork.medium || "";
  document.querySelector("#editPrice").value = artwork.price || 0;
  document.querySelector("#editSaleStatus").value = artwork.sale_status || "In progress";
  document.querySelector("#editGalleryVisible").checked = Boolean(artwork.gallery_visible);
  document.querySelector("#editListingUrl").value = artwork.listing_url || "";
  if (document.querySelector("#detailDialog").open) document.querySelector("#detailDialog").close();
  document.querySelector("#editDialog").showModal();
}

const toDataUrl = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(reader.result);
  reader.onerror = reject;
  reader.readAsDataURL(file);
});

document.querySelectorAll("#uploadButton,#dropButton").forEach((button) => { button.onclick = choose; });
document.querySelector("#fileInput").onchange = (event) => {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (files.length > 1) openBatchUploader(files);
  else if (files.length === 1) prepare(files[0]);
};
document.querySelector("#artSaleStatus").onchange = (event) => {
  if (["Ready to list", "Listed"].includes(event.target.value)) document.querySelector("#artGalleryVisible").checked = true;
};

const collectionTitles = {
  AfroNova: ["Crown of Tomorrow", "Celestial Sovereign", "Golden Orbit", "Ancestral Light", "Future Royalty"],
  "Quiet Nova": ["Stillness in Gold", "Soft Morning", "Held in Light", "Quiet Horizon", "A Place to Breathe"],
  GraffitiX: ["Electric Witness", "Midnight Rhythm", "Concrete Crown", "City Pulse", "Raw Frequency"],
  Unsorted: ["Black Canvas Study", "Untitled Black Canvas Work", "New Visual Direction"],
};

function createTitleAndTags(prefix = "art") {
  const collection = document.querySelector(`#${prefix}Collection`).value;
  const choices = collectionTitles[collection] || collectionTitles.Unsorted;
  const currentCount = artworks.filter((item) => item.collection === collection).length;
  const titleInput = document.querySelector(`#${prefix}Title`);
  const tagsInput = document.querySelector(`#${prefix}Tags`);
  const notesInput = document.querySelector(`#${prefix}Notes`);
  const baseTitle = choices[currentCount % choices.length];
  let artworkNumber = currentCount + 1;
  let generatedTitle = `${baseTitle} — ${String(artworkNumber).padStart(2, "0")}`;
  const usedTitles = new Set(artworks.map((item) => String(item.title || "").trim().toLowerCase()));
  while (usedTitles.has(generatedTitle.toLowerCase())) {
    artworkNumber += 1;
    generatedTitle = `${baseTitle} — ${String(artworkNumber).padStart(2, "0")}`;
  }
  titleInput.value = generatedTitle;
  const baseTags = collectionDetails[collection]?.tags || "original art, contemporary art, Black Canvas";
  tagsInput.value = `${baseTags}, original art, contemporary Black art`;
  if (!notesInput.value.trim() && collectionDetails[collection]) notesInput.value = collectionDetails[collection].notes;
  notify("Title and tags are ready. You can change any wording.");
}
document.querySelector("#editSaleStatus").onchange = (event) => {
  if (["Ready to list", "Listed"].includes(event.target.value)) document.querySelector("#editGalleryVisible").checked = true;
};
const studioDropOverlay = document.querySelector("#studioDropOverlay");
let studioDragDepth = 0;
function droppedArtworkFiles(event) {
  return Array.from(event.dataTransfer?.files || []).filter((file) => file.type.startsWith("image/"));
}
function addDroppedArtwork(event) {
  const files = droppedArtworkFiles(event);
  if (!files.length) return notify("Drop image files here to add them to Image Studio.");
  if (files.length > 1) openBatchUploader(files);
  else prepare(files[0]);
}
function hideStudioDropTarget() {
  studioDragDepth = 0;
  drop.classList.remove("dragging");
  studioDropOverlay.hidden = true;
}
document.querySelector("#closeStudioDropOverlay").onclick = hideStudioDropTarget;
studioDropOverlay.addEventListener("click", (event) => {
  if (event.target === studioDropOverlay) hideStudioDropTarget();
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !studioDropOverlay.hidden) hideStudioDropTarget();
});

// The whole Image Studio accepts a drop, even after the first artwork is added.
window.addEventListener("dragenter", (event) => {
  if (!event.dataTransfer?.types.includes("Files")) return;
  event.preventDefault();
  studioDragDepth += 1;
  drop.classList.add("dragging");
  studioDropOverlay.hidden = false;
});
window.addEventListener("dragover", (event) => {
  if (!event.dataTransfer?.types.includes("Files")) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "copy";
});
window.addEventListener("dragleave", (event) => {
  if (!event.dataTransfer?.types.includes("Files")) return;
  studioDragDepth = Math.max(0, studioDragDepth - 1);
  if (!studioDragDepth) hideStudioDropTarget();
});
window.addEventListener("drop", (event) => {
  if (!event.dataTransfer?.types.includes("Files")) return;
  event.preventDefault();
  hideStudioDropTarget();
  addDroppedArtwork(event);
});
drop.ondragover = (event) => { event.preventDefault(); drop.classList.add("dragging"); };
drop.ondragleave = () => drop.classList.remove("dragging");
drop.ondrop = (event) => {
  event.preventDefault();
  event.stopPropagation();
  hideStudioDropTarget();
  addDroppedArtwork(event);
};
document.querySelector("#artCollection").onchange = (event) => applySuggestedDetails(event.target.value, document.querySelector("#artTags"), document.querySelector("#artNotes"));
const titleTagButton = document.createElement("button");
titleTagButton.type = "button";
titleTagButton.className = "generate-art-details";
titleTagButton.textContent = "✦ Create title & tags";
titleTagButton.title = "Fill in a clean title and matching tags for this collection";
titleTagButton.style.cssText = "margin:2px 0 12px;padding:10px 12px;border:1px solid #7257c8;border-radius:9px;background:#251d38;color:#ded4ff;font-weight:700;cursor:pointer;text-align:left";
titleTagButton.onclick = () => createTitleAndTags("art");
document.querySelector("#artCollection").closest("label").insertAdjacentElement("afterend", titleTagButton);
document.querySelector("#editCollection").onchange = (event) => applySuggestedDetails(event.target.value, document.querySelector("#editTags"), document.querySelector("#editNotes"));
const editTitleTagButton = titleTagButton.cloneNode(true);
editTitleTagButton.textContent = "✦ Create title & tags";
editTitleTagButton.onclick = () => createTitleAndTags("edit");
document.querySelector("#editCollection").closest("label").insertAdjacentElement("afterend", editTitleTagButton);
document.querySelector("#fillCollectionDetails").onclick = () => {
  applySuggestedDetails(document.querySelector("#editCollection").value, document.querySelector("#editTags"), document.querySelector("#editNotes"));
  notify("Blank tags and description filled from the collection.");
};

const artworkSpellLabels = {
  artTitle: "Title", artMedium: "Medium", artTags: "Tags", artNotes: "Description",
  editTitle: "Title", editMedium: "Medium", editTags: "Tags", editNotes: "Description",
};
let artworkSpellCorrections = new Map();
const artworkSpellingDialog = document.querySelector("#artSpellingDialog");
function showArtworkSpellingReview(results) {
  artworkSpellCorrections = new Map(results.filter((result) => result.changes.length).map((result) => [result.id, result.corrected_text]));
  const changes = results.flatMap((result) => result.changes.map((change) => ({ ...change, field: artworkSpellLabels[result.id] })));
  if (!changes.length) return notify("No spelling changes found.");
  document.querySelector("#artSpellingSummary").textContent = `${changes.length} possible correction${changes.length === 1 ? "" : "s"} found.`;
  document.querySelector("#artSpellingChanges").innerHTML = changes.map((change) => `<span><b>${escapeHtml(change.field)}:</b> ${escapeHtml(change.original)} → ${escapeHtml(change.replacement)}</span>`).join("");
  artworkSpellingDialog.showModal();
}
document.querySelectorAll(".check-art-spelling").forEach((button) => {
  if (button.dataset.fields === "artTags,artNotes") button.dataset.fields = "artTitle,artMedium,artTags,artNotes";
  if (button.dataset.fields === "editTags,editNotes") button.dataset.fields = "editTitle,editMedium,editTags,editNotes";
  button.textContent = "✓ Check all writing";
  button.onclick = async () => {
    const ids = button.dataset.fields.split(",");
    const fields = ids.map((id) => ({ id, text: document.querySelector(`#${id}`).value.trim() })).filter((field) => field.text);
    if (!fields.length) return notify("Add tags or a description first.");
    button.disabled = true;
    button.textContent = "Checking...";
    try {
      const results = await Promise.all(fields.map(async (field) => {
        const response = await fetch("/api/spellcheck", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: field.text }),
        });
        if (!response.ok) throw new Error();
        return { ...field, ...(await response.json()) };
      }));
      showArtworkSpellingReview(results);
    } catch {
      notify("Could not check spelling just now.");
    } finally {
      button.disabled = false;
      button.textContent = "✓ Check all writing";
    }
  };
});
const automaticArtworkSpellTimers = new Map();
function watchArtworkSpelling(field) {
  field.addEventListener("input", () => {
    clearTimeout(automaticArtworkSpellTimers.get(field.id));
    document.querySelector(`#autoSpell-${field.id}`)?.remove();
    automaticArtworkSpellTimers.set(field.id, setTimeout(async () => {
      const text = field.value.trim();
      if (text.length < 4) return;
      try {
        const response = await fetch("/api/spellcheck", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
        });
        const result = await response.json();
        if (!response.ok || !result.changes.length || field.value.trim() !== text) return;
        const notice = document.createElement("button");
        notice.type = "button";
        notice.id = `autoSpell-${field.id}`;
        notice.className = "inline-spell-status";
        notice.textContent = `✦ ${result.changes.length} spelling suggestion${result.changes.length === 1 ? "" : "s"} ready`;
        notice.onclick = () => showArtworkSpellingReview([{ id: field.id, text, ...result }]);
        field.insertAdjacentElement("afterend", notice);
      } catch { /* The manual check button remains available if a local request fails. */ }
    }, 900));
  });
}
document.querySelectorAll("#artTitle,#artMedium,#artTags,#artNotes,#editTitle,#editMedium,#editTags,#editNotes").forEach(watchArtworkSpelling);
const closeArtworkSpelling = () => { artworkSpellCorrections.clear(); artworkSpellingDialog.close(); };
document.querySelector("#closeArtSpelling").onclick = closeArtworkSpelling;
document.querySelector("#cancelArtSpelling").onclick = closeArtworkSpelling;
document.querySelector("#applyArtSpelling").onclick = () => {
  artworkSpellCorrections.forEach((text, id) => { document.querySelector(`#${id}`).value = text; });
  closeArtworkSpelling();
  notify("Spelling corrections applied.");
};

document.querySelector("#saveArtwork").onclick = async (event) => {
  event.preventDefault();
  const title = document.querySelector("#artTitle").value.trim();
  if (!title || !pendingFile) return;
  const payload = {
    title,
    collection: document.querySelector("#artCollection").value,
    tags: document.querySelector("#artTags").value.trim(),
    notes: document.querySelector("#artNotes").value.trim(),
    dimensions: document.querySelector("#artDimensions").value.trim(),
    medium: document.querySelector("#artMedium").value.trim(),
    price: Number(document.querySelector("#artPrice").value) || 0,
    sale_status: document.querySelector("#artSaleStatus").value,
    gallery_visible: document.querySelector("#artGalleryVisible").checked,
    data_url: await toDataUrl(pendingFile),
  };
  const response = await fetch("/api/artworks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    return notify(result.detail || "The artwork could not be saved.");
  }
  pendingFile = null;
  document.querySelector("#fileInput").value = "";
  document.querySelector("#artDialog").close();
  await load();
  notify("Artwork saved permanently.");
};

function duplicateArtworkCard(artwork) {
  return `<button class="duplicate-artwork-card" type="button" data-artwork-id="${artwork.id}">
    <img src="${artwork.url}" alt="${escapeHtml(artwork.title)}">
    <span><strong>${escapeHtml(artwork.title)}</strong><small>${escapeHtml(artwork.collection)}</small></span>
    <em>Open</em>
  </button>`;
}

document.querySelector("#findDuplicateArtwork").onclick = async () => {
  const dialog = document.querySelector("#duplicateArtworkDialog");
  const results = document.querySelector("#duplicateArtworkResults");
  results.innerHTML = `<p class="duplicates-loading">Checking your catalog for exact matching image files…</p>`;
  dialog.showModal();
  try {
    const response = await fetch("/api/artworks/duplicates");
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not check the catalog right now.");
    if (!result.groups.length) {
      results.innerHTML = `<div class="duplicates-empty"><strong>No exact duplicates found.</strong><span>Your catalog is clear. Future exact repeat uploads will be skipped automatically.</span></div>`;
      return;
    }
    results.innerHTML = `<p class="duplicate-help">Found ${result.duplicate_groups} duplicate group${result.duplicate_groups === 1 ? "" : "s"}. These are the same uploaded image file—not just similar artwork.</p>${result.groups.map((group, index) => `<section class="duplicate-group"><h3>Duplicate group ${index + 1} <span>${group.length} copies</span></h3><div>${group.map(duplicateArtworkCard).join("")}</div></section>`).join("")}`;
    results.querySelectorAll("[data-artwork-id]").forEach((button) => {
      button.onclick = () => {
        const artwork = artworks.find((item) => item.id === Number(button.dataset.artworkId));
        if (!artwork) return notify("That artwork could not be found.");
        dialog.close();
        showDetail(artwork);
      };
    });
  } catch (error) {
    results.innerHTML = `<div class="duplicates-empty"><strong>Could not check for duplicates.</strong><span>${escapeHtml(error.message || "Please try again.")}</span></div>`;
  }
};
document.querySelector("#closeDuplicateArtwork").onclick = () => document.querySelector("#duplicateArtworkDialog").close();

document.querySelector("#editArtwork").onclick = openEditDialog;
document.querySelector("#createArtworkPrompt").onclick = async () => {
  const artwork = artworks.find((item) => item.id === selectedId);
  if (!artwork) return;
  const button = document.querySelector("#createArtworkPrompt");
  button.disabled = true;
  button.textContent = "Inspecting the actual image…";
  try {
    const response = await fetch(`/api/artworks/${artwork.id}/visual-analysis`, { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "The image could not be analyzed.");
    document.querySelector("#analysisImage").src = artwork.url;
    document.querySelector("#analysisTitle").value = result.title || artwork.title;
    document.querySelector("#analysisCollection").value = result.collection || artwork.collection || "Unsorted";
    document.querySelector("#analysisTags").value = (result.tags || []).join(", ");
    document.querySelector("#analysisDescription").value = result.description || "";
    document.querySelector("#analysisSummary").textContent = result.visual_summary || "";
    document.querySelector("#analysisPrompt").value = result.generated_prompt || "";
    document.querySelector("#detailDialog").close();
    document.querySelector("#visualAnalysisDialog").showModal();
  } catch (error) {
    notify(error.message || "The image could not be analyzed just now.");
  } finally {
    button.disabled = false;
    button.textContent = "✦ Create prompt from artwork";
  }
};
document.querySelector("#closeVisualAnalysis").onclick = () => document.querySelector("#visualAnalysisDialog").close();
document.querySelector("#copyVisualPrompt").onclick = async () => {
  const prompt = document.querySelector("#analysisPrompt").value.trim();
  if (!prompt) return notify("There is no prompt to copy yet.");
  await navigator.clipboard.writeText(prompt);
  notify("Image prompt copied.");
};
document.querySelector("#saveVisualPrompt").onclick = () => {
  const prompt = document.querySelector("#analysisPrompt").value.trim();
  const title = document.querySelector("#analysisTitle").value.trim() || "Artwork image prompt";
  const category = document.querySelector("#analysisCollection").value || "Unsorted";
  if (!prompt) return notify("There is no prompt to save yet.");
  window.location.href = `/prompts?new=1&title=${encodeURIComponent(`${title} — Image Prompt`)}&category=${encodeURIComponent(category)}&text=${encodeURIComponent(prompt)}`;
};
document.querySelector("#applyVisualDetails").onclick = async () => {
  const artwork = artworks.find((item) => item.id === selectedId);
  if (!artwork) return;
  const button = document.querySelector("#applyVisualDetails");
  const payload = {
    title: document.querySelector("#analysisTitle").value.trim(),
    collection: document.querySelector("#analysisCollection").value,
    tags: document.querySelector("#analysisTags").value.trim(),
    notes: document.querySelector("#analysisDescription").value.trim(),
    dimensions: artwork.dimensions || "",
    medium: artwork.medium || "",
    price: Number(artwork.price) || 0,
    sale_status: artwork.sale_status || "In progress",
    gallery_visible: Boolean(artwork.gallery_visible),
    listing_url: artwork.listing_url || "",
  };
  if (!payload.title) return notify("Review the title before applying it.");
  button.disabled = true;
  button.textContent = "Applying…";
  try {
    const response = await fetch(`/api/artworks/${artwork.id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error();
    document.querySelector("#visualAnalysisDialog").close();
    await load();
    notify("Title, tags, and description applied.");
  } catch {
    notify("Those details could not be applied just now.");
  } finally {
    button.disabled = false;
    button.textContent = "Apply title, tags & description";
  }
};

function hasGenericArtworkTitle(artwork) {
  const title = String(artwork.title || "").trim();
  return !title
    || /(?:—|-)\s*\d{1,3}$/i.test(title)
    || /^(untitled|new visual direction|black canvas study)/i.test(title)
    || /[a-f0-9]{8}-[a-f0-9-]{12,}/i.test(title)
    || /^blacksam\d*[_-]/i.test(title);
}

let bulkNamingSuggestions = [];

function updateBulkNamingCount() {
  const checked = [...document.querySelectorAll("#bulkNamingList input:checked")];
  document.querySelector("#bulkNamingCount").textContent = `${checked.length} selected`;
  document.querySelector("#runBulkNaming").disabled = checked.length === 0;
}

document.querySelector("#openBulkNaming").onclick = () => {
  const candidates = artworks.filter(hasGenericArtworkTitle);
  const list = document.querySelector("#bulkNamingList");
  if (!candidates.length) {
    list.innerHTML = '<p class="bulk-naming-empty">No numbered, filename-style, or untitled artwork was found.</p>';
  } else {
    list.innerHTML = candidates.map((artwork, index) => `
      <label class="bulk-naming-item">
        <input type="checkbox" value="${artwork.id}" ${index < 10 ? "checked" : ""}>
        <img src="${artwork.url}" alt="">
        <span><strong>${escapeHtml(artwork.title)}</strong><small>${escapeHtml(artwork.collection)}</small></span>
      </label>`).join("");
  }
  list.querySelectorAll("input").forEach((input) => {
    input.onchange = () => {
      const checked = [...list.querySelectorAll("input:checked")];
      if (checked.length > 10) {
        input.checked = false;
        notify("Choose up to 10 artworks at a time.");
      }
      updateBulkNamingCount();
    };
  });
  updateBulkNamingCount();
  document.querySelector("#bulkNamingDialog").showModal();
};
document.querySelector("#closeBulkNaming").onclick = () => document.querySelector("#bulkNamingDialog").close();
document.querySelector("#closeBulkNamingReview").onclick = () => document.querySelector("#bulkNamingReviewDialog").close();
document.querySelector("#closeInquiries").onclick = () => document.querySelector("#inquiriesDialog").close();
document.querySelector("#openInquiries").onclick = async () => {
  const list = document.querySelector("#inquiriesList");
  list.innerHTML = '<p class="inquiries-empty">Loading collector messages…</p>';
  document.querySelector("#inquiriesDialog").showModal();
  try {
    const response = await fetch("/api/inquiries");
    if (!response.ok) throw new Error();
    const inquiries = await response.json();
    list.innerHTML = inquiries.length ? inquiries.map((inquiry) => `<article class="inquiry-card"><div><span>${escapeHtml(inquiry.inquiry_type)}</span><strong>${escapeHtml(inquiry.name)}</strong><a href="mailto:${escapeHtml(inquiry.email)}">${escapeHtml(inquiry.email)}</a></div><small>${escapeHtml(inquiry.artwork_title || "General inquiry")}${inquiry.budget ? ` · Budget: ${escapeHtml(inquiry.budget)}` : ""}</small><p>${escapeHtml(inquiry.message)}</p></article>`).join("") : '<p class="inquiries-empty">No collector inquiries yet. When the gallery is online, messages from the inquiry page will appear here.</p>';
  } catch { list.innerHTML = '<p class="inquiries-empty">Could not load collector inquiries just now.</p>'; }
};
function updateBulkOrganizerCount() {
  const selected = document.querySelectorAll("#bulkOrganizerList input:checked").length;
  document.querySelector("#bulkOrganizerCount").textContent = `${selected} selected`;
  document.querySelector("#applyBulkOrganizer").disabled = selected === 0;
}
document.querySelector("#openBulkOrganizer").onclick = () => {
  const list = document.querySelector("#bulkOrganizerList");
  list.innerHTML = artworks.map((artwork) => `<label class="bulk-organizer-item"><input type="checkbox" value="${artwork.id}"><img src="${artwork.url}" alt=""><span><strong>${escapeHtml(artwork.title || "Untitled artwork")}</strong><small>${escapeHtml(artwork.collection)} · ${escapeHtml(artwork.sale_status || "In progress")}</small></span></label>`).join("");
  list.querySelectorAll("input").forEach((input) => { input.onchange = updateBulkOrganizerCount; });
  document.querySelector("#bulkCollection").value = "";
  document.querySelector("#bulkMedium").value = "";
  document.querySelector("#bulkSaleStatus").value = "";
  document.querySelector("#bulkGalleryVisible").value = "";
  document.querySelector("#bulkAddTags").value = "";
  updateBulkOrganizerCount();
  document.querySelector("#bulkOrganizeDialog").showModal();
};
document.querySelector("#closeBulkOrganizer").onclick = () => document.querySelector("#bulkOrganizeDialog").close();
document.querySelector("#selectShownArtworks").onclick = () => {
  document.querySelectorAll("#bulkOrganizerList input").forEach((input) => { input.checked = true; });
  updateBulkOrganizerCount();
};
document.querySelector("#applyBulkOrganizer").onclick = async () => {
  const artwork_ids = [...document.querySelectorAll("#bulkOrganizerList input:checked")].map((input) => Number(input.value));
  const collection = document.querySelector("#bulkCollection").value || null;
  const medium = document.querySelector("#bulkMedium").value.trim() || null;
  const sale_status = document.querySelector("#bulkSaleStatus").value || null;
  const galleryChoice = document.querySelector("#bulkGalleryVisible").value;
  const payload = { artwork_ids, collection, medium, sale_status, gallery_visible: galleryChoice === "" ? null : galleryChoice === "true", add_tags: document.querySelector("#bulkAddTags").value.trim() };
  if (!collection && !medium && !sale_status && payload.gallery_visible === null && !payload.add_tags) return notify("Choose at least one change first.");
  const button = document.querySelector("#applyBulkOrganizer");
  button.disabled = true; button.textContent = "Updating...";
  try {
    const response = await fetch("/api/artworks/bulk-update", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const result = await response.json();
    if (!response.ok) throw Error(result.detail || "Could not update the selected artwork.");
    document.querySelector("#bulkOrganizeDialog").close();
    await load();
    notify(`${result.updated} artwork${result.updated === 1 ? "" : "s"} updated.`);
  } catch (error) { notify(error.message); } finally { button.disabled = false; button.textContent = "Apply selected changes"; }
};
document.querySelector("#runBulkNaming").onclick = async () => {
  const ids = [...document.querySelectorAll("#bulkNamingList input:checked")].map((input) => Number(input.value));
  if (!ids.length) return;
  const button = document.querySelector("#runBulkNaming");
  button.disabled = true;
  const suggestions = [];
  let failed = 0;
  for (let index = 0; index < ids.length; index += 1) {
    const artwork = artworks.find((item) => item.id === ids[index]);
    if (!artwork) continue;
    button.textContent = `Naming ${index + 1} of ${ids.length}…`;
    try {
      const analysisResponse = await fetch(`/api/artworks/${artwork.id}/visual-analysis`, { method: "POST" });
      const analysis = await analysisResponse.json();
      if (!analysisResponse.ok || !analysis.title) throw new Error();
      suggestions.push({ id: artwork.id, originalTitle: artwork.title, title: analysis.title.trim() });
    } catch {
      failed += 1;
    }
  }
  button.disabled = false;
  button.textContent = "Suggest unique titles";
  if (!suggestions.length) return notify("No title suggestions were created. Please try again.");
  bulkNamingSuggestions = suggestions;
  const list = document.querySelector("#bulkNamingReviewList");
  list.innerHTML = suggestions.map((suggestion) => {
    const artwork = artworks.find((item) => item.id === suggestion.id);
    return `<label class="bulk-naming-item"><img src="${artwork?.url || ""}" alt=""><span><small>Was: ${escapeHtml(suggestion.originalTitle)}</small><input type="text" data-artwork-id="${suggestion.id}" value="${escapeHtml(suggestion.title)}" spellcheck="true" lang="en"></span></label>`;
  }).join("");
  document.querySelector("#bulkNamingReviewCount").textContent = `${suggestions.length} title${suggestions.length === 1 ? "" : "s"} ready`;
  document.querySelector("#bulkNamingDialog").close();
  document.querySelector("#bulkNamingReviewDialog").showModal();
  if (failed) notify(`${suggestions.length} suggestions ready; ${failed} could not be named.`);
};
document.querySelector("#saveBulkNaming").onclick = async () => {
  const entries = [...document.querySelectorAll("#bulkNamingReviewList input")]
    .map((input) => ({ id: Number(input.dataset.artworkId), title: input.value.trim() }))
    .filter((item) => item.title);
  if (!entries.length) return notify("Keep at least one title before saving.");
  const normalized = entries.map((item) => item.title.toLowerCase());
  if (new Set(normalized).size !== normalized.length) return notify("Two suggested titles are the same. Change one before saving.");
  const button = document.querySelector("#saveBulkNaming");
  button.disabled = true;
  button.textContent = "Saving…";
  let saved = 0;
  let failed = 0;
  for (const entry of entries) {
    const artwork = artworks.find((item) => item.id === entry.id);
    if (!artwork) continue;
    const payload = {
      title: entry.title, collection: artwork.collection, tags: artwork.tags || "", notes: artwork.notes || "",
      dimensions: artwork.dimensions || "", medium: artwork.medium || "", price: Number(artwork.price) || 0,
      sale_status: artwork.sale_status || "In progress", gallery_visible: Boolean(artwork.gallery_visible),
      listing_url: artwork.listing_url || "",
    };
    try {
      const response = await fetch(`/api/artworks/${entry.id}`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error();
      saved += 1;
    } catch { failed += 1; }
  }
  await load();
  document.querySelector("#bulkNamingReviewDialog").close();
  button.disabled = false;
  button.textContent = "Save these titles";
  notify(failed ? `${saved} titles saved; ${failed} could not be saved.` : `${saved} artwork titles saved.`);
};
document.querySelector("#askArtworkAgent").onclick = () => {
  if (!selectedId) return;
  window.location.href = `/chat?artwork=${selectedId}`;
};
document.querySelector("#createContentKit").onclick = async () => {
  if (!selectedId) return;
  const button = document.querySelector("#createContentKit");
  button.disabled = true;
  button.textContent = "Creating content kit...";
  try {
    const response = await fetch(`/api/artworks/${selectedId}/content-kit`);
    if (!response.ok) throw new Error();
    const kit = await response.json();
    currentContentKit = kit;
    document.querySelector("#contentKitTitle").textContent = `${kit.artwork_title} Content Kit`;
    document.querySelector("#kitPinterestTitle").value = kit.pinterest_title;
    document.querySelector("#kitPinterestDescription").value = kit.pinterest_description;
    document.querySelector("#kitPinterestTopics").value = kit.pinterest_topics.join(", ");
    document.querySelector("#kitPinterestBoard").value = kit.pinterest_board;
    document.querySelector("#kitPinterestDestination").value = kit.pinterest_destination || "";
    document.querySelector("#kitPinterestAltText").value = kit.pinterest_alt_text;
    document.querySelector("#kitInstagram").value = kit.instagram;
    document.querySelector("#kitTikTokHook").value = kit.tiktok_hook;
    document.querySelector("#kitTikTokCaption").value = kit.tiktok_caption;
    document.querySelector("#kitListingTitle").value = kit.listing_title;
    document.querySelector("#kitListingDescription").value = kit.listing_description;
    document.querySelector("#kitListingTags").value = kit.listing_tags.join(", ");
    document.querySelector("#detailDialog").close();
    document.querySelector("#contentKitDialog").showModal();
  } catch {
    notify("Could not create the content kit just now.");
  } finally {
    button.disabled = false;
    button.textContent = "◇ Create marketing content kit";
  }
};
document.querySelector("#closeContentKit").onclick = () => document.querySelector("#contentKitDialog").close();
document.querySelector("#openPinterest").onclick = () => {
  window.open("https://www.pinterest.com/pin-creation-tool/", "_blank", "noopener");
  notify("Pinterest Create Pin opened. Upload the artwork, paste the fields, then Publish.");
};
document.querySelector("#downloadPinterestImage").onclick = () => {
  const artwork = artworks.find((item) => item.id === selectedId);
  if (!artwork?.url) return notify("The artwork image could not be found.");
  const extension = artwork.url.match(/\.(png|jpe?g|webp)$/i)?.[1] || "png";
  const link = document.createElement("a");
  link.href = artwork.url;
  link.download = `${(artwork.title || "black-canvas-artwork").replace(/[^a-z0-9]+/gi, "-")}-Pinterest.${extension}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  notify("Artwork downloaded for Pinterest.");
};
document.querySelectorAll("[data-copy]").forEach((button) => {
  button.onclick = async () => {
    await navigator.clipboard.writeText(document.querySelector(`#${button.dataset.copy}`).value);
    notify("Content copied.");
  };
});
document.querySelectorAll("[data-save]").forEach((button) => {
  button.onclick = () => {
    const text = document.querySelector(`#${button.dataset.save}`).value.trim();
    const artwork = artworks.find((item) => item.id === selectedId);
    if (!text) return notify("There is no content to save yet.");
    const title = `${artwork?.title || "Artwork"} — ${button.dataset.label}`;
    window.location.href = `/prompts?new=1&title=${encodeURIComponent(title)}&category=Content&text=${encodeURIComponent(text)}`;
  };
});
const pricingInputs = ["priceMaterials", "priceHours", "priceHourly", "priceOverhead", "priceFees", "priceProfit"];
let pricingSummary = "";
let recommendedArtworkPrice = 0;
const money = (value) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
function calculatePrice() {
  const values = Object.fromEntries(pricingInputs.map((id) => [id, Math.max(0, Number(document.querySelector(`#${id}`).value) || 0)]));
  const feeRate = Math.min(values.priceFees, 90) / 100;
  const creativeCost = values.priceMaterials + (values.priceHours * values.priceHourly) + values.priceOverhead;
  const minimum = creativeCost / (1 - feeRate);
  const target = (creativeCost * (1 + values.priceProfit / 100)) / (1 - feeRate);
  const recommended = Math.ceil(target / 5) * 5;
  recommendedArtworkPrice = recommended;
  document.querySelector("#priceCreativeCost").textContent = money(creativeCost);
  document.querySelector("#priceMinimum").textContent = money(Math.ceil(minimum));
  document.querySelector("#priceRecommended").textContent = money(recommended);
  document.querySelector("#priceExplanation").textContent = `Includes ${money(values.priceHours * values.priceHourly)} for your time, a ${values.priceProfit}% profit goal, and ${values.priceFees}% estimated selling fees.`;
  const artwork = artworks.find((item) => item.id === selectedId);
  pricingSummary = `${artwork?.title || "Artwork"} pricing estimate\nCreative cost: ${money(creativeCost)}\nMinimum no-loss price: ${money(Math.ceil(minimum))}\nRecommended retail price: ${money(recommended)}\n${document.querySelector("#priceExplanation").textContent}`;
}
document.querySelector("#openPricing").onclick = async () => {
  const artwork = artworks.find((item) => item.id === selectedId);
  if (!artwork) return;
  try {
    const response = await fetch(`/api/artworks/${selectedId}/pricing`);
    if (response.ok) {
      const saved = (await response.json()).pricing || {};
      const values = {
        priceMaterials: saved.materials,
        priceHours: saved.hours,
        priceHourly: saved.hourly_rate,
        priceOverhead: saved.overhead,
        priceFees: saved.fees_percent,
        priceProfit: saved.profit_percent,
      };
      Object.entries(values).forEach(([id, value]) => {
        if (value !== undefined && value !== null) document.querySelector(`#${id}`).value = value;
      });
    }
  } catch {
    notify("Using the standard pricing starting points.");
  }
  document.querySelector("#pricingTitle").textContent = `${artwork?.title || "Artwork"} Pricing`;
  document.querySelector("#detailDialog").close();
  calculatePrice();
  document.querySelector("#pricingDialog").showModal();
};
pricingInputs.forEach((id) => { document.querySelector(`#${id}`).oninput = calculatePrice; });
document.querySelector("#closePricing").onclick = () => document.querySelector("#pricingDialog").close();
document.querySelector("#copyPricing").onclick = async () => {
  await navigator.clipboard.writeText(pricingSummary);
  notify("Pricing summary copied.");
};
document.querySelector("#applyArtworkPrice").onclick = async () => {
  if (!selectedId || recommendedArtworkPrice <= 0) return;
  const button = document.querySelector("#applyArtworkPrice");
  button.disabled = true;
  button.textContent = "Saving price...";
  try {
    const response = await fetch(`/api/artworks/${selectedId}/pricing`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        materials: Number(document.querySelector("#priceMaterials").value) || 0,
        hours: Number(document.querySelector("#priceHours").value) || 0,
        hourly_rate: Number(document.querySelector("#priceHourly").value) || 0,
        overhead: Number(document.querySelector("#priceOverhead").value) || 0,
        fees_percent: Number(document.querySelector("#priceFees").value) || 0,
        profit_percent: Number(document.querySelector("#priceProfit").value) || 0,
        recommended_price: recommendedArtworkPrice,
      }),
    });
    if (!response.ok) throw new Error();
    await load();
    notify(`Artwork price set to ${money(recommendedArtworkPrice)}.`);
  } catch {
    notify("Could not save the artwork price.");
  } finally {
    button.disabled = false;
    button.textContent = "Apply price to artwork";
  }
};
let printInfo = null;
let syncingPrintSize = false;
function checkPrintSize() {
  if (!printInfo) return;
  const width = Number(document.querySelector("#printWidth").value) || 0;
  const height = Number(document.querySelector("#printHeight").value) || 0;
  const requiredWidth = Math.round(width * 300);
  const requiredHeight = Math.round(height * 300);
  const fits = width > 0 && height > 0 && requiredWidth <= printInfo.pixel_width && requiredHeight <= printInfo.pixel_height;
  const check = document.querySelector("#printCheck");
  check.className = `print-check ${fits ? "ready" : "too-small"}`;
  check.querySelector("strong").textContent = fits ? "Ready for a true 300-DPI export" : "Not enough pixels for this print size";
  document.querySelector("#printRequired").textContent = `${width || 0} × ${height || 0} inches requires ${requiredWidth.toLocaleString()} × ${requiredHeight.toLocaleString()} pixels.`;
  document.querySelector("#exportPrint").disabled = !fits;
}
document.querySelector("#openPrintPrep").onclick = async () => {
  if (!selectedId) return;
  const button = document.querySelector("#openPrintPrep");
  button.disabled = true;
  button.textContent = "Checking image...";
  try {
    const response = await fetch(`/api/artworks/${selectedId}/print-info`);
    if (!response.ok) throw new Error();
    printInfo = await response.json();
    document.querySelector("#printPrepTitle").textContent = `${printInfo.artwork_title} Print Prep`;
    document.querySelector("#printPixels").textContent = `${printInfo.pixel_width.toLocaleString()} × ${printInfo.pixel_height.toLocaleString()} px`;
    document.querySelector("#printCurrentDpi").textContent = printInfo.current_dpi ? `${printInfo.current_dpi} DPI` : "Not labeled";
    document.querySelector("#printMaximum").textContent = `${printInfo.max_width_300} × ${printInfo.max_height_300} in`;
    const startingWidth = Math.max(0.1, Math.floor(printInfo.max_width_300 * 10) / 10);
    document.querySelector("#printWidth").value = startingWidth.toFixed(1);
    document.querySelector("#printHeight").value = (startingWidth / printInfo.aspect_ratio).toFixed(2);
    checkPrintSize();
    document.querySelector("#detailDialog").close();
    document.querySelector("#printPrepDialog").showModal();
  } catch {
    notify("Could not inspect this image just now.");
  } finally {
    button.disabled = false;
    button.textContent = "▣ Prepare a 300 DPI print";
  }
};
document.querySelector("#printWidth").oninput = (event) => {
  if (!printInfo || syncingPrintSize) return;
  syncingPrintSize = true;
  document.querySelector("#printHeight").value = ((Number(event.target.value) || 0) / printInfo.aspect_ratio).toFixed(2);
  syncingPrintSize = false;
  checkPrintSize();
};
document.querySelector("#printHeight").oninput = (event) => {
  if (!printInfo || syncingPrintSize) return;
  syncingPrintSize = true;
  document.querySelector("#printWidth").value = ((Number(event.target.value) || 0) * printInfo.aspect_ratio).toFixed(2);
  syncingPrintSize = false;
  checkPrintSize();
};
document.querySelector("#closePrintPrep").onclick = () => document.querySelector("#printPrepDialog").close();
document.querySelector("#exportPrint").onclick = async () => {
  if (!selectedId || !printInfo) return;
  const button = document.querySelector("#exportPrint");
  button.disabled = true;
  button.textContent = "Preparing print file...";
  try {
    const response = await fetch(`/api/artworks/${selectedId}/print-export`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ width_inches: Number(document.querySelector("#printWidth").value), height_inches: Number(document.querySelector("#printHeight").value) }),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Could not prepare the file");
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `${printInfo.artwork_title.replace(/[^a-z0-9]+/gi, "-")}-300dpi.png`;
    link.click();
    URL.revokeObjectURL(url);
    notify("Print-ready PNG downloaded.");
  } catch (error) {
    notify(error.message || "Could not prepare the print file.");
  } finally {
    button.textContent = "Download print-ready PNG";
    checkPrintSize();
  }
};
let readinessData = null;
function renderReadiness(result) {
  readinessData = result;
  document.querySelector("#readinessTitle").textContent = `${result.artwork_title} Listing Readiness`;
  document.querySelector("#readinessPercent").textContent = `${result.percent}%`;
  document.querySelector("#readinessCount").textContent = `${result.completed} of ${result.total} complete`;
  document.querySelector("#readinessBar").style.width = `${result.percent}%`;
  document.querySelector("#readinessList").innerHTML = result.checks.map((check) => `<div class="readiness-item ${check.ready ? "ready" : ""}"><b>${check.ready ? "✓" : "!"}</b><div><strong>${escapeHtml(check.label)}</strong><small>${escapeHtml(check.ready ? "Complete" : check.detail)}</small></div></div>`).join("");
  const markButton = document.querySelector("#markReady");
  markButton.disabled = !result.ready_to_list || result.sale_status === "Ready to list";
  markButton.textContent = result.sale_status === "Ready to list" ? "✓ Already Ready to List" : "Mark Ready to List";
  document.querySelector("#downloadSellerPackage").disabled = !result.ready_to_list;
}
document.querySelector("#openReadiness").onclick = async () => {
  if (!selectedId) return;
  const button = document.querySelector("#openReadiness");
  button.disabled = true;
  button.textContent = "Checking listing...";
  try {
    const response = await fetch(`/api/artworks/${selectedId}/listing-readiness`);
    if (!response.ok) throw new Error();
    renderReadiness(await response.json());
    document.querySelector("#detailDialog").close();
    document.querySelector("#readinessDialog").showModal();
  } catch {
    notify("Could not check listing readiness just now.");
  } finally {
    button.disabled = false;
    button.textContent = "✓ Check listing readiness";
  }
};
document.querySelector("#closeReadiness").onclick = () => document.querySelector("#readinessDialog").close();
document.querySelector("#editFromReadiness").onclick = () => {
  document.querySelector("#readinessDialog").close();
  openEditDialog();
};
document.querySelector("#markReady").onclick = async () => {
  if (!selectedId || !readinessData?.ready_to_list) return;
  const response = await fetch(`/api/artworks/${selectedId}/mark-ready`, { method: "POST" });
  if (!response.ok) return notify("Complete the missing listing details first.");
  renderReadiness(await response.json());
  await load();
  notify("Artwork marked Ready to List.");
};
document.querySelector("#downloadSellerPackage").onclick = async () => {
  if (!selectedId || !readinessData?.ready_to_list) return;
  const button = document.querySelector("#downloadSellerPackage");
  button.disabled = true;
  button.textContent = "Building package...";
  try {
    const response = await fetch(`/api/artworks/${selectedId}/seller-package`);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Could not create seller package");
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `${readinessData.artwork_title.replace(/[^a-z0-9]+/gi, "-")}-seller-package.zip`;
    link.click();
    URL.revokeObjectURL(url);
    notify("Seller Package downloaded.");
  } catch (error) {
    notify(error.message || "Could not create the seller package.");
  } finally {
    button.textContent = "Download Seller Package";
    button.disabled = !readinessData.ready_to_list;
  }
};
document.querySelector("#recordSale").onclick = () => {
  const artwork = artworks.find((item) => item.id === selectedId);
  if (!artwork) return;
  const today = new Date();
  const localDate = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  document.querySelector("#saleTitle").textContent = `${artwork.title} Sale`;
  document.querySelector("#salePrice").value = artwork.sale_price || artwork.price || "";
  document.querySelector("#soldDate").value = artwork.sold_date || localDate;
  document.querySelector("#salesChannel").value = artwork.sales_channel || "Direct sale";
  document.querySelector("#buyerName").value = artwork.buyer_name || "";
  document.querySelector("#saleNotes").value = artwork.sale_notes || "";
  document.querySelector("#detailDialog").close();
  document.querySelector("#saleDialog").showModal();
};
document.querySelector("#saveSale").onclick = async (event) => {
  event.preventDefault();
  if (!selectedId) return;
  const payload = {
    sale_price: Number(document.querySelector("#salePrice").value) || 0,
    sold_date: document.querySelector("#soldDate").value,
    sales_channel: document.querySelector("#salesChannel").value,
    buyer_name: document.querySelector("#buyerName").value.trim(),
    notes: document.querySelector("#saleNotes").value.trim(),
  };
  if (payload.sale_price <= 0) return document.querySelector("#salePrice").focus();
  if (!payload.sold_date) return document.querySelector("#soldDate").focus();
  const response = await fetch(`/api/artworks/${selectedId}/record-sale`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  if (!response.ok) return notify("Could not save the sale record.");
  document.querySelector("#saleDialog").close();
  await load();
  notify("Sale recorded. Congratulations!");
};
document.querySelector("#openSalesReport").onclick = async () => {
  const button = document.querySelector("#openSalesReport");
  button.disabled = true;
  button.textContent = "Loading report...";
  try {
    const response = await fetch("/api/sales");
    if (!response.ok) throw new Error();
    const report = await response.json();
    document.querySelector("#reportSalesCount").textContent = report.count;
    document.querySelector("#reportRevenue").textContent = money(report.total_revenue);
    document.querySelector("#reportAverage").textContent = money(report.average_sale);
    document.querySelector("#salesReportRows").innerHTML = report.sales.map((sale) => `<tr><td><strong>${escapeHtml(sale.title)}</strong><br><small>${escapeHtml(sale.collection)}</small></td><td>${escapeHtml(sale.sold_date)}</td><td>${escapeHtml(sale.sales_channel)}</td><td>${escapeHtml(sale.buyer_name || "—")}</td><td>${money(sale.sale_price)}</td></tr>`).join("");
    document.querySelector("#salesReportEmpty").hidden = report.count > 0;
    document.querySelector("#downloadSalesCsv").disabled = report.count === 0;
    document.querySelector("#salesReportDialog").showModal();
  } catch {
    notify("Could not load the sales report.");
  } finally {
    button.disabled = false;
    button.textContent = "Sales report";
  }
};
document.querySelector("#openOrdersDashboard").onclick = async () => {
  const button = document.querySelector("#openOrdersDashboard");
  button.disabled = true;
  button.textContent = "Loading orders...";
  try {
    const response = await fetch("/api/orders");
    if (!response.ok) throw new Error();
    const report = await response.json();
    document.querySelector("#ordersTotal").textContent = report.count;
    document.querySelector("#ordersActive").textContent = report.active;
    document.querySelector("#ordersCompleted").textContent = report.completed;
    document.querySelector("#ordersList").innerHTML = report.orders.map((order) => {
      const shipping = [order.shipping_carrier, order.tracking_number].filter(Boolean).map(escapeHtml).join(" · ");
      return `<button class="order-row" data-order-id="${order.id}"><div><strong>${escapeHtml(order.title)}</strong><span>${escapeHtml(order.buyer_name || "Private buyer")} · ${escapeHtml(order.sold_date)}</span></div><div><span class="order-stage stage-${String(order.fulfillment_status).toLowerCase().replaceAll(" ", "-")}">${escapeHtml(order.fulfillment_status)}</span>${shipping ? `<small>${shipping}</small>` : ""}</div></button>`;
    }).join("");
    document.querySelector("#ordersEmpty").hidden = report.count > 0;
    document.querySelectorAll("[data-order-id]").forEach((row) => {
      row.onclick = () => {
        const artwork = artworks.find((item) => item.id === Number(row.dataset.orderId));
        if (!artwork) return;
        document.querySelector("#ordersDialog").close();
        showDetail(artwork);
      };
    });
    document.querySelector("#ordersDialog").showModal();
  } catch {
    notify("Could not load the orders dashboard.");
  } finally {
    button.disabled = false;
    button.textContent = "Orders";
  }
};
document.querySelector("#closeOrders").onclick = () => document.querySelector("#ordersDialog").close();
let editingExpenseId = null;
function resetExpenseForm() {
  editingExpenseId = null;
  document.querySelector("#expenseDescription").value = "";
  document.querySelector("#expenseAmount").value = "";
  document.querySelector("#expenseNotes").value = "";
  document.querySelector("#saveExpense").textContent = "Add expense";
  document.querySelector("#cancelExpenseEdit").hidden = true;
}
async function loadExpenses() {
  const response = await fetch("/api/expenses");
  if (!response.ok) throw new Error();
  const report = await response.json();
  document.querySelector("#expenseTotal").textContent = money(report.total);
  document.querySelector("#expenseList").innerHTML = report.expenses.map((expense) => `<div><span><strong>${escapeHtml(expense.description)}</strong><small>${escapeHtml(expense.category)} · ${escapeHtml(expense.expense_date)}</small></span><b>${money(expense.amount)}</b><div class="expense-row-actions"><button data-edit-expense="${expense.id}">Edit</button><button data-delete-expense="${expense.id}" aria-label="Delete expense">×</button></div></div>`).join("");
  document.querySelector("#expensesEmpty").hidden = report.count > 0;
  document.querySelectorAll("[data-delete-expense]").forEach((button) => {
    button.onclick = async () => {
      if (!window.confirm("Remove this expense record?")) return;
      const result = await fetch(`/api/expenses/${button.dataset.deleteExpense}`, { method: "DELETE" });
      if (!result.ok) return notify("Could not remove the expense.");
      await loadExpenses();
      notify("Expense removed.");
    };
  });
  document.querySelectorAll("[data-edit-expense]").forEach((button) => {
    button.onclick = () => {
      const expense = report.expenses.find((item) => item.id === Number(button.dataset.editExpense));
      if (!expense) return;
      editingExpenseId = expense.id;
      document.querySelector("#expenseDescription").value = expense.description;
      document.querySelector("#expenseCategory").value = expense.category;
      document.querySelector("#expenseAmount").value = expense.amount;
      document.querySelector("#expenseDate").value = expense.expense_date;
      document.querySelector("#expenseNotes").value = expense.notes || "";
      document.querySelector("#saveExpense").textContent = "Update expense";
      document.querySelector("#cancelExpenseEdit").hidden = false;
      document.querySelector("#expenseDescription").focus();
    };
  });
}
document.querySelector("#openExpenses").onclick = async () => {
  const today = new Date();
  document.querySelector("#expenseDate").value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  try {
    await loadExpenses();
    document.querySelector("#expensesDialog").showModal();
  } catch {
    notify("Could not load expenses.");
  }
};
document.querySelector("#closeExpenses").onclick = () => document.querySelector("#expensesDialog").close();
document.querySelector("#cancelExpenseEdit").onclick = resetExpenseForm;
document.querySelector("#expenseForm").onsubmit = async (event) => {
  event.preventDefault();
  const payload = {
    description: document.querySelector("#expenseDescription").value.trim(),
    category: document.querySelector("#expenseCategory").value,
    amount: Number(document.querySelector("#expenseAmount").value) || 0,
    expense_date: document.querySelector("#expenseDate").value,
    notes: document.querySelector("#expenseNotes").value.trim(),
  };
  const response = await fetch(editingExpenseId ? `/api/expenses/${editingExpenseId}` : "/api/expenses", { method: editingExpenseId ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  if (!response.ok) {
    const error = await response.json();
    return notify(error.detail || "Could not save the expense.");
  }
  const wasEditing = Boolean(editingExpenseId);
  resetExpenseForm();
  await loadExpenses();
  notify(wasEditing ? "Expense updated." : "Expense recorded.");
};
async function loadFinanceReport() {
  const period = document.querySelector("#financePeriod").value;
  const response = await fetch(`/api/finance-report?period=${period}`);
  if (!response.ok) throw new Error();
  const report = await response.json();
  document.querySelector("#financeRevenue").textContent = money(report.revenue);
  document.querySelector("#financeExpenses").textContent = money(report.expenses);
  document.querySelector("#financeNet").textContent = money(report.net_profit);
  document.querySelector("#financeNet").classList.toggle("negative", report.net_profit < 0);
  document.querySelector("#financeGoalRevenue").textContent = money(report.monthly_goal.revenue);
  document.querySelector("#financeGoalTarget").textContent = money(report.monthly_goal.goal);
  document.querySelector("#financeGoalBar").style.width = `${report.monthly_goal.percent}%`;
  document.querySelector("#monthlyRevenueGoal").value = report.monthly_goal.goal;
  const categories = Object.entries(report.expense_categories).sort((a, b) => b[1] - a[1]);
  document.querySelector("#financeCategories").innerHTML = categories.length ? categories.map(([category, amount]) => `<div><span>${escapeHtml(category)}</span><strong>${money(amount)}</strong></div>`).join("") : '<p class="finance-empty">No expenses recorded.</p>';
  document.querySelector("#financeTransactions").innerHTML = report.transactions.length ? report.transactions.slice(0, 10).map((item) => `<div><span><strong>${escapeHtml(item.description)}</strong><small>${escapeHtml(item.type)} · ${escapeHtml(item.entry_date)}</small></span><b class="${item.signed_amount < 0 ? "negative" : ""}">${item.signed_amount < 0 ? "−" : "+"}${money(Math.abs(item.signed_amount))}</b></div>`).join("") : '<p class="finance-empty">No financial activity recorded.</p>';
}
document.querySelector("#openFinanceReport").onclick = async () => {
  const button = document.querySelector("#openFinanceReport");
  button.disabled = true;
  button.textContent = "Loading report...";
  try {
    await loadFinanceReport();
    document.querySelector("#financeDialog").showModal();
  } catch {
    notify("Could not load the profit and loss report.");
  } finally {
    button.disabled = false;
    button.textContent = "Profit & loss";
  }
};
document.querySelector("#financePeriod").onchange = async () => {
  try { await loadFinanceReport(); } catch { notify("Could not change the report period."); }
};
document.querySelector("#revenueGoalForm").onsubmit = async (event) => {
  event.preventDefault();
  const monthly_goal = Number(document.querySelector("#monthlyRevenueGoal").value) || 0;
  const response = await fetch("/api/revenue-goal", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ monthly_goal }) });
  if (!response.ok) {
    const error = await response.json();
    return notify(error.detail || "Could not update the revenue goal.");
  }
  const goal = await response.json();
  document.querySelector("#financeGoalTarget").textContent = money(goal.goal);
  document.querySelector("#financeGoalBar").style.width = `${goal.percent}%`;
  notify("Monthly revenue goal updated.");
};
document.querySelector("#closeFinanceReport").onclick = () => document.querySelector("#financeDialog").close();
document.querySelector("#downloadFinanceCsv").onclick = async () => {
  const button = document.querySelector("#downloadFinanceCsv");
  button.disabled = true;
  button.textContent = "Preparing CSV...";
  try {
    const period = document.querySelector("#financePeriod").value;
    const response = await fetch(`/api/finance-report/export?period=${period}`);
    if (!response.ok) throw new Error();
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `BlackCanvasAI-Profit-Loss-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    notify("Profit and loss CSV downloaded.");
  } catch {
    notify("Could not download the report.");
  } finally {
    button.disabled = false;
    button.textContent = "Download CSV";
  }
};
document.querySelector("#closeSalesReport").onclick = () => document.querySelector("#salesReportDialog").close();
document.querySelector("#downloadCatalogCsv").onclick = async () => {
  const button = document.querySelector("#downloadCatalogCsv");
  button.disabled = true;
  button.textContent = "Preparing catalog...";
  try {
    const response = await fetch("/api/artworks-export");
    if (!response.ok) throw new Error();
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `BlackCanvasAI-Artwork-Catalog-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    notify("Artwork catalog CSV downloaded.");
  } catch {
    notify("Could not download the artwork catalog.");
  } finally {
    button.disabled = false;
    button.textContent = "Catalog CSV";
  }
};
document.querySelector("#downloadSalesCsv").onclick = async () => {
  const button = document.querySelector("#downloadSalesCsv");
  button.disabled = true;
  button.textContent = "Preparing CSV...";
  try {
    const response = await fetch("/api/sales/export");
    if (!response.ok) throw new Error();
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `BlackCanvasAI-Sales-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    notify("Sales CSV downloaded.");
  } catch {
    notify("Could not download the sales report.");
  } finally {
    button.disabled = false;
    button.textContent = "Download CSV";
  }
};
document.querySelector("#downloadCertificate").onclick = async () => {
  if (!selectedId) return;
  const button = document.querySelector("#downloadCertificate");
  button.disabled = true;
  button.textContent = "Creating certificate...";
  try {
    const response = await fetch(`/api/artworks/${selectedId}/certificate`);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Could not create certificate");
    }
    const artwork = artworks.find((item) => item.id === selectedId);
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `${(artwork?.title || "artwork").replace(/[^a-z0-9]+/gi, "-")}-certificate-of-authenticity.pdf`;
    link.click();
    URL.revokeObjectURL(url);
    notify("Certificate of Authenticity downloaded.");
  } catch (error) {
    notify(error.message || "Could not create the certificate.");
  } finally {
    button.disabled = false;
    button.textContent = "▤ Certificate of Authenticity";
  }
};

document.querySelector("#downloadSaleReceipt").onclick = async () => {
  if (!selectedId) return;
  const artwork = artworks.find((item) => item.id === selectedId);
  const button = document.querySelector("#downloadSaleReceipt");
  button.disabled = true;
  button.textContent = "Creating receipt...";
  try {
    const response = await fetch(`/api/artworks/${selectedId}/sale-receipt`);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Could not create the sale receipt");
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `${(artwork?.title || "artwork").replace(/[^a-z0-9]+/gi, "-")}-sale-receipt.pdf`;
    link.click();
    URL.revokeObjectURL(url);
    notify("Sale receipt downloaded.");
  } catch (error) {
    notify(error.message || "Could not create the sale receipt.");
  } finally {
    button.disabled = false;
    button.textContent = "▤ Download Sale Receipt";
  }
};

document.querySelector("#downloadGalleryLabel").onclick = async () => {
  if (!selectedId) return;
  const artwork = artworks.find((item) => item.id === selectedId);
  const button = document.querySelector("#downloadGalleryLabel");
  button.disabled = true;
  button.textContent = "Creating label...";
  try {
    const response = await fetch(`/api/artworks/${selectedId}/gallery-label`);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Could not create the gallery label");
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `${(artwork?.title || "artwork").replace(/[^a-z0-9]+/gi, "-")}-gallery-label.pdf`;
    link.click();
    URL.revokeObjectURL(url);
    notify("Gallery label downloaded.");
  } catch (error) {
    notify(error.message || "Could not create the gallery label.");
  } finally {
    button.disabled = false;
    button.textContent = "▤ Printable Gallery Label";
  }
};

let packingChecklistText = "";
document.querySelector("#openBuyerKit").onclick = async () => {
  if (!selectedId) return;
  const button = document.querySelector("#openBuyerKit");
  button.disabled = true;
  button.textContent = "Creating buyer kit...";
  try {
    const response = await fetch(`/api/artworks/${selectedId}/buyer-kit`);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Could not create the buyer kit");
    }
    const kit = await response.json();
    document.querySelector("#buyerKitTitle").textContent = `${kit.artwork_title} Buyer Kit`;
    document.querySelector("#buyerThankYou").value = kit.thank_you;
    document.querySelector("#buyerCare").value = kit.care_instructions;
    document.querySelector("#packingChecklist").innerHTML = kit.packing_checklist.map((item) => `<label><input type="checkbox"><span>${escapeHtml(item)}</span></label>`).join("");
    packingChecklistText = kit.packing_checklist.map((item) => `☐ ${item}`).join("\n");
    document.querySelector("#detailDialog").close();
    document.querySelector("#buyerKitDialog").showModal();
  } catch (error) {
    notify(error.message || "Could not create the buyer kit.");
  } finally {
    button.disabled = false;
    button.textContent = "♡ Buyer Thank-You Kit";
  }
};
document.querySelector("#closeBuyerKit").onclick = () => document.querySelector("#buyerKitDialog").close();
document.querySelector("#copyPackingChecklist").onclick = async () => {
  await navigator.clipboard.writeText(packingChecklistText);
  notify("Packing checklist copied.");
};

document.querySelector("#openFulfillment").onclick = () => {
  const artwork = artworks.find((item) => item.id === selectedId);
  if (!artwork) return;
  document.querySelector("#fulfillmentTitle").textContent = `${artwork.title} Order`;
  document.querySelector("#fulfillmentStatus").value = artwork.fulfillment_status || "Not started";
  document.querySelector("#shippingCarrier").value = artwork.shipping_carrier || "";
  document.querySelector("#trackingNumber").value = artwork.tracking_number || "";
  document.querySelector("#detailDialog").close();
  document.querySelector("#fulfillmentDialog").showModal();
};
document.querySelector("#saveFulfillment").onclick = async (event) => {
  event.preventDefault();
  if (!selectedId) return;
  const payload = {
    status: document.querySelector("#fulfillmentStatus").value,
    carrier: document.querySelector("#shippingCarrier").value.trim(),
    tracking_number: document.querySelector("#trackingNumber").value.trim(),
  };
  const response = await fetch(`/api/artworks/${selectedId}/fulfillment`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json();
    return notify(error.detail || "Could not save the order status.");
  }
  document.querySelector("#fulfillmentDialog").close();
  await load();
  notify("Order status updated.");
};
document.querySelector("#saveArtworkDetails").onclick = async (event) => {
  event.preventDefault();
  if (!selectedId) return;
  const payload = {
    title: document.querySelector("#editTitle").value.trim(),
    collection: document.querySelector("#editCollection").value,
    tags: document.querySelector("#editTags").value.trim(),
    notes: document.querySelector("#editNotes").value.trim(),
    dimensions: document.querySelector("#editDimensions").value.trim(),
    medium: document.querySelector("#editMedium").value.trim(),
    price: Number(document.querySelector("#editPrice").value) || 0,
    sale_status: document.querySelector("#editSaleStatus").value,
    gallery_visible: document.querySelector("#editGalleryVisible").checked,
    listing_url: document.querySelector("#editListingUrl").value.trim(),
  };
  if (!payload.title) return document.querySelector("#editTitle").focus();
  const response = await fetch(`/api/artworks/${selectedId}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    return notify(error.detail || "The artwork details could not be saved.");
  }
  document.querySelector("#editDialog").close();
  await load();
  notify("Artwork details updated.");
};

document.querySelector("#artSearch").oninput = (event) => { query = event.target.value.toLowerCase().trim(); render(); };
document.querySelector("#saleStatusFilter").onchange = (event) => { saleStatusFilter = event.target.value; render(); };
document.querySelectorAll("#artFilters button").forEach((button) => {
  button.onclick = () => {
    document.querySelectorAll("#artFilters button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    filter = button.dataset.filter;
    render();
  };
});
document.querySelector("#detailClose").onclick = () => document.querySelector("#detailDialog").close();
document.querySelector("#removeArtwork").onclick = async () => {
  if (!selectedId) return;
  await fetch(`/api/artworks/${selectedId}`, { method: "DELETE" });
  document.querySelector("#detailDialog").close();
  await load();
  notify("Artwork removed from this catalog.");
};
document.querySelector("#menuButton").onclick = () => document.querySelector("#sidebar").classList.toggle("open");
document.querySelectorAll("#studioToolsMenu button").forEach((button) => {
  button.addEventListener("click", () => { document.querySelector("#studioToolsMenu").open = false; });
});
function clearStudioFocus() {
  focusMode = "";
  document.querySelector("#studioFocus").hidden = true;
  document.querySelector("#focusAction").hidden = true;
  window.history.replaceState({}, "", "/image-studio");
  render();
}
document.querySelector("#clearFocus").onclick = clearStudioFocus;
async function initializeStudio() {
  await load();
  const focusCopy = {
    unpriced: ["Artwork that needs a price", "Open a piece and use Calculate artwork price."],
    incomplete: ["Artwork with missing details", "Add size, medium, story, or tags to complete each record."],
    ready: ["Artwork ready to list", "These pieces are prepared for publishing or sale."],
  };
  if (focusCopy[focusMode]) {
    document.querySelector("#focusTitle").textContent = focusCopy[focusMode][0];
    document.querySelector("#focusDescription").textContent = focusCopy[focusMode][1];
    document.querySelector("#studioFocus").hidden = false;
    const actionable = artworks.filter((artwork) => {
      const available = artwork.sale_status !== "Sold" && artwork.sale_status !== "Not for sale";
      if (focusMode === "incomplete") return available && (!artwork.dimensions?.trim() || !artwork.medium?.trim() || !artwork.notes?.trim() || !artwork.tags?.trim());
      if (focusMode === "unpriced") return available && Number(artwork.price) <= 0;
      return artwork.sale_status === "Ready to list";
    });
    const nextArtwork = actionable[0];
    const focusAction = document.querySelector("#focusAction");
    if (nextArtwork) {
      const labels = { incomplete: "Complete next artwork", unpriced: "Price next artwork", ready: "Open next listing" };
      focusAction.textContent = labels[focusMode];
      focusAction.hidden = false;
      focusAction.onclick = () => {
        showDetail(nextArtwork);
        const tool = { incomplete: "#editArtwork", unpriced: "#openPricing", ready: "#openReadiness" }[focusMode];
        document.querySelector(tool).click();
      };
    }
  } else if (focusMode === "orders") {
    focusMode = "";
    document.querySelector("#openOrdersDashboard").click();
  }
  if (requestedArtworkId) {
    const artwork = artworks.find((item) => item.id === requestedArtworkId);
    if (!artwork) return notify("That artwork could not be found in your catalog.");
    showDetail(artwork);
    const toolButton = {
      content: "#createContentKit",
      pricing: "#openPricing",
      readiness: "#openReadiness",
      fulfillment: "#openFulfillment",
      edit: "#editArtwork",
    }[requestedTool];
    if (toolButton) document.querySelector(toolButton).click();
  }
}
initializeStudio().catch(() => notify("Could not load the artwork catalog."));
