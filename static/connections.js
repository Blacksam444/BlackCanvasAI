const statusLabel = document.querySelector("#driveStatus");
const action = document.querySelector("#driveAction");
const panel = document.querySelector("#setupPanel");
const toast = document.querySelector("#toast");
const importPrompts = document.querySelector("#importPrompts");
const importArtwork = document.querySelector("#importArtwork");
const restoreLibrary = document.querySelector("#restoreLibrary");
const backupBrowser = document.querySelector("#backupBrowser");
const backupList = document.querySelector("#backupList");
const backupSummary = document.querySelector("#backupSummary");
const driveBrowser = document.querySelector("#driveBrowser");
const driveFiles = document.querySelector("#driveFiles");
const artworkBrowser = document.querySelector("#artworkBrowser");
const driveArtworkFiles = document.querySelector("#driveArtworkFiles");
let selectedDriveArtwork = null;

const collectionSuggestions = {
  "AfroNova": {
    tags: "afrofuturism, cosmic, regal, Black art, violet, gold, future heritage",
    description: "An AfroNova piece exploring Black identity, imagined futures, ancestral power, and cosmic elegance. Cataloged as part of the collection's bold, regal visual world.",
  },
  "Quiet Nova": {
    tags: "contemplative, minimal, soft light, neutral tones, calm, intimate, reflective",
    description: "A Quiet Nova piece centered on stillness, reflection, and understated strength. The direction favors gentle atmosphere, emotional intimacy, and spacious composition.",
  },
  "GraffitiX": {
    tags: "street art, graffiti, urban, neon, typography, layered texture, expressive",
    description: "A GraffitiX piece driven by urban energy, expressive marks, layered texture, and street-art attitude. Cataloged for its bold visual rhythm and contemporary edge.",
  },
  "Unsorted": {
    tags: "artwork, visual archive, uncategorized",
    description: "An artwork imported from Google Drive and saved for creative review. Add visual details, meaning, materials, or intended use as the direction develops.",
  },
};

function autofillDriveArtwork() {
  const collection = document.querySelector("#driveArtCollection").value;
  const suggestion = collectionSuggestions[collection] || collectionSuggestions.Unsorted;
  document.querySelector("#driveArtTags").value = suggestion.tags;
  document.querySelector("#driveArtNotes").value = suggestion.description;
}
let status = {};

const notify = message => {
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2600);
};

async function loadStatus() {
  const response = await fetch("/api/google/status");
  status = await response.json();
  action.disabled = false;
  if (status.connected) {
    statusLabel.textContent = `Connected${status.email ? " · " + status.email : ""}`;
    statusLabel.classList.add("connected");
    action.textContent = "Back up now";
    importPrompts.hidden = false;
    importArtwork.hidden = false;
    restoreLibrary.hidden = false;
    panel.hidden = true;
  } else if (status.configured) {
    statusLabel.textContent = "One permission update needed";
    action.textContent = "Update Google access";
    importPrompts.hidden = true;
    importArtwork.hidden = true;
    restoreLibrary.hidden = true;
    panel.hidden = true;
  } else {
    statusLabel.textContent = "Not connected";
    action.textContent = "Set up";
    importPrompts.hidden = true;
    importArtwork.hidden = true;
    restoreLibrary.hidden = true;
  }
}

action.onclick = async () => {
  if (status.connected) {
    action.disabled = true;
    action.textContent = "Backing up...";
    try {
      const response = await fetch("/api/google/backup", { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw Error(result.detail || "Backup failed");
      notify(`Complete backup saved: ${result.prompts} prompts and ${result.artwork_files} artwork file${result.artwork_files === 1 ? "" : "s"}.`);
      backupSummary.textContent = `Latest backup: just now · ${result.artwork_files} artwork file${result.artwork_files === 1 ? "" : "s"}`;
      action.textContent = "Backed up ✓";
      setTimeout(() => {
        action.textContent = "Back up now";
        action.disabled = false;
      }, 2200);
    } catch (error) {
      notify(error.message);
      action.textContent = "Try backup again";
      action.disabled = false;
    }
    return;
  }
  if (status.configured) window.location.href = "/google/connect";
  else {
    panel.hidden = !panel.hidden;
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }
};

async function loadBackups() {
  backupList.innerHTML = '<p class="loading-files">Loading your backups...</p>';
  try {
    const response = await fetch("/api/google/backups");
    const result = await response.json();
    if (!response.ok) throw Error(result.detail || "Could not load backups");
    if (!result.backups.length) {
      backupList.innerHTML = '<p class="backup-empty">No complete folder backups yet. Click Back up now to create the first one.</p>';
      backupSummary.textContent = "No complete folder backup yet";
      return;
    }
    const latest = result.backups[0];
    backupSummary.textContent = `Latest backup: ${new Date(latest.createdTime).toLocaleString()} · ${(latest.appProperties || {}).artwork_count || 0} artwork files`;
    backupList.replaceChildren(...result.backups.map(backup => {
      const row = document.createElement("div");
      row.className = "backup-item";
      const copy = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = backup.name;
      const details = document.createElement("small");
      details.textContent = `${new Date(backup.createdTime).toLocaleString()} · ${(backup.appProperties || {}).artwork_count || 0} artwork files`;
      copy.append(name, details);
      const button = document.createElement("button");
      button.textContent = "Restore safely";
      button.onclick = async () => {
        if (!window.confirm("Restore this backup into the current library? Existing work will be kept, and a local safety snapshot will be created first.")) return;
        button.disabled = true;
        button.textContent = "Restoring...";
        try {
          const restoreResponse = await fetch(`/api/google/restore/${encodeURIComponent(backup.id)}`, {method:"POST"});
          const restored = await restoreResponse.json();
          if (!restoreResponse.ok) throw Error(restored.detail || "Restore failed");
          button.textContent = "Restored ✓";
          notify(`Restore complete: ${restored.prompts} prompts, ${restored.artworks} catalog entries, and ${restored.images} image files added.`);
        } catch (error) {
          button.disabled = false;
          button.textContent = "Try restore again";
          notify(error.message);
        }
      };
      row.append(copy, button);
      return row;
    }));
  } catch (error) {
    const message = document.createElement("p");
    message.className = "backup-empty";
    message.textContent = error.message;
    backupList.replaceChildren(message);
  }
}

restoreLibrary.onclick = async () => {
  backupBrowser.hidden = false;
  backupBrowser.scrollIntoView({behavior:"smooth", block:"start"});
  await loadBackups();
};
document.querySelector("#closeBackupBrowser").onclick = () => { backupBrowser.hidden = true; };

importPrompts.onclick = async () => {
  driveBrowser.hidden = false;
  driveFiles.innerHTML = '<p class="loading-files">Loading your documents...</p>';
  driveBrowser.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const response = await fetch("/api/google/prompt-files");
    const result = await response.json();
    if (!response.ok) throw Error(result.detail || "Could not read Google Drive");
    if (!result.files.length) {
      driveFiles.innerHTML = '<p class="empty-files">No Google Docs, text files, or Markdown files were found.</p>';
      return;
    }
    driveFiles.replaceChildren(...result.files.map(file => {
      const row = document.createElement("div");
      row.className = "drive-file";
      const copy = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = file.name;
      const modified = document.createElement("small");
      modified.textContent = `Updated ${new Date(file.modifiedTime).toLocaleDateString()}`;
      copy.append(name, modified);
      const button = document.createElement("button");
      button.textContent = "Import";
      button.onclick = async () => {
        button.disabled = true;
        button.textContent = "Importing...";
        const importedResponse = await fetch(`/api/google/import-prompt/${encodeURIComponent(file.id)}`, { method: "POST" });
        const imported = await importedResponse.json();
        if (!importedResponse.ok) {
          notify(imported.detail || "That prompt could not be imported.");
          button.disabled = false;
          button.textContent = "Try again";
          return;
        }
        button.textContent = imported.imported ? "Imported ✓" : "Already added";
        notify(imported.imported ? `${imported.title} added to Prompt Library.` : "That prompt is already in your library.");
      };
      row.append(copy, button);
      return row;
    }));
  } catch (error) {
    const message = document.createElement("p");
    message.className = "empty-files";
    message.textContent = error.message;
    driveFiles.replaceChildren(message);
  }
};

document.querySelector("#closeDriveBrowser").onclick = () => { driveBrowser.hidden = true; };

importArtwork.onclick = async () => {
  artworkBrowser.hidden = false;
  driveArtworkFiles.innerHTML = '<p class="loading-files">Loading your images...</p>';
  artworkBrowser.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const response = await fetch("/api/google/artwork-files");
    const result = await response.json();
    if (!response.ok) throw Error(result.detail || "Could not read artwork from Drive");
    if (!result.files.length) {
      driveArtworkFiles.innerHTML = '<p class="empty-files">No supported JPG, PNG, WebP, or GIF images were found.</p>';
      return;
    }
    driveArtworkFiles.replaceChildren(...result.files.map(file => {
      const card = document.createElement("article");
      card.className = "drive-artwork-card";
      const preview = document.createElement("img");
      preview.src = `/api/google/artwork-preview/${encodeURIComponent(file.id)}`;
      preview.alt = file.name;
      preview.loading = "lazy";
      const footer = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = file.name;
      const button = document.createElement("button");
      button.textContent = "Catalog";
      button.onclick = () => {
        selectedDriveArtwork = file;
        document.querySelector("#driveArtForm").reset();
        document.querySelector("#driveArtTitle").value = file.name.replace(/\.[^.]+$/, "");
        document.querySelector("#driveArtPreview").src = preview.src;
        autofillDriveArtwork();
        document.querySelector("#driveArtDialog").showModal();
      };
      footer.append(name, button);
      card.append(preview, footer);
      return card;
    }));
  } catch (error) {
    const message = document.createElement("p");
    message.className = "empty-files";
    message.textContent = error.message;
    driveArtworkFiles.replaceChildren(message);
  }
};

document.querySelector("#closeArtworkBrowser").onclick = () => { artworkBrowser.hidden = true; };
document.querySelector("#driveArtCollection").onchange = autofillDriveArtwork;
document.querySelector("#saveDriveArtwork").onclick = async event => {
  event.preventDefault();
  if (!selectedDriveArtwork) return;
  const title = document.querySelector("#driveArtTitle").value.trim();
  if (!title) return notify("Add an artwork title first.");
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "Saving...";
  const response = await fetch(`/api/google/import-artwork/${encodeURIComponent(selectedDriveArtwork.id)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title,
      collection: document.querySelector("#driveArtCollection").value,
      tags: document.querySelector("#driveArtTags").value.trim(),
      notes: document.querySelector("#driveArtNotes").value.trim(),
    }),
  });
  const result = await response.json();
  if (!response.ok) {
    notify(result.detail || "That artwork could not be imported.");
    button.disabled = false;
    button.textContent = "Save to Image Studio";
    return;
  }
  document.querySelector("#driveArtDialog").close();
  button.disabled = false;
  button.textContent = "Save to Image Studio";
  notify("Artwork added to Image Studio.");
};

document.querySelector("#credentialFile").onchange = async event => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const credentials = JSON.parse(await file.text());
    const response = await fetch("/api/google/credentials", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ credentials }),
    });
    if (!response.ok) throw Error();
    document.querySelector("#fileResult").textContent = "✓ Added safely";
    notify("Google setup file saved privately.");
    await loadStatus();
  } catch {
    notify("That does not look like a Google OAuth JSON file.");
  }
};

document.querySelector("#menuButton").onclick = () => document.querySelector("#sidebar").classList.toggle("open");
loadStatus();
