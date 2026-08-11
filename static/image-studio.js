let artworks = [];
let filter = "All";
let query = "";
let pendingFile = null;
let selectedId = null;

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
  const shown = artworks.filter((artwork) => (
    filter === "All" || (filter === "Favorites" ? artwork.favorite : artwork.collection === filter)
  ) && `${artwork.title} ${artwork.collection} ${artwork.tags} ${artwork.notes}`.toLowerCase().includes(query));
  shown.forEach((artwork) => {
    const card = document.createElement("article");
    card.className = "art-card";
    card.innerHTML = `<img src="${artwork.url}" alt="${escapeHtml(artwork.title)}"><button class="art-favorite ${artwork.favorite ? "on" : ""}">★</button><div class="art-meta"><h2>${escapeHtml(artwork.title)}</h2><p>${escapeHtml(artwork.collection)}${artwork.tags ? " · " + escapeHtml(artwork.tags) : ""}</p></div>`;
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
}

function choose() { document.querySelector("#fileInput").click(); }
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
  document.querySelector("#detailDialog").close();
  document.querySelector("#editDialog").showModal();
}

const toDataUrl = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(reader.result);
  reader.onerror = reject;
  reader.readAsDataURL(file);
});

document.querySelectorAll("#uploadButton,#dropButton").forEach((button) => { button.onclick = choose; });
document.querySelector("#fileInput").onchange = (event) => prepare(event.target.files[0]);
drop.ondragover = (event) => { event.preventDefault(); drop.classList.add("dragging"); };
drop.ondragleave = () => drop.classList.remove("dragging");
drop.ondrop = (event) => { event.preventDefault(); drop.classList.remove("dragging"); prepare(event.dataTransfer.files[0]); };
document.querySelector("#artCollection").onchange = (event) => applySuggestedDetails(event.target.value, document.querySelector("#artTags"), document.querySelector("#artNotes"));
document.querySelector("#editCollection").onchange = (event) => applySuggestedDetails(event.target.value, document.querySelector("#editTags"), document.querySelector("#editNotes"));

document.querySelector("#saveArtwork").onclick = async (event) => {
  event.preventDefault();
  const title = document.querySelector("#artTitle").value.trim();
  if (!title || !pendingFile) return;
  const payload = {
    title,
    collection: document.querySelector("#artCollection").value,
    tags: document.querySelector("#artTags").value.trim(),
    notes: document.querySelector("#artNotes").value.trim(),
    data_url: await toDataUrl(pendingFile),
  };
  const response = await fetch("/api/artworks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  if (!response.ok) return notify("The artwork could not be saved.");
  pendingFile = null;
  document.querySelector("#fileInput").value = "";
  document.querySelector("#artDialog").close();
  await load();
  notify("Artwork saved permanently.");
};

document.querySelector("#editArtwork").onclick = openEditDialog;
document.querySelector("#createArtworkPrompt").onclick = () => {
  const artwork = artworks.find((item) => item.id === selectedId);
  if (!artwork) return;
  const details = [artwork.notes, artwork.tags ? `Visual details: ${artwork.tags}` : ""].filter(Boolean).join(". ");
  const request = `Create an image prompt for ${artwork.title} in the ${artwork.collection} style${details ? `. Use this creative direction: ${details}` : ""}.`;
  window.location.href = `/chat?q=${encodeURIComponent(request)}`;
};
document.querySelector("#saveArtworkDetails").onclick = async (event) => {
  event.preventDefault();
  if (!selectedId) return;
  const payload = {
    title: document.querySelector("#editTitle").value.trim(),
    collection: document.querySelector("#editCollection").value,
    tags: document.querySelector("#editTags").value.trim(),
    notes: document.querySelector("#editNotes").value.trim(),
  };
  if (!payload.title) return document.querySelector("#editTitle").focus();
  const response = await fetch(`/api/artworks/${selectedId}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  if (!response.ok) return notify("The artwork details could not be saved.");
  document.querySelector("#editDialog").close();
  await load();
  notify("Artwork details updated.");
};

document.querySelector("#artSearch").oninput = (event) => { query = event.target.value.toLowerCase().trim(); render(); };
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
load().catch(() => notify("Could not load the artwork catalog."));
