let artworks = [];
let filter = "All";
let saleStatusFilter = "All statuses";
let query = "";
let pendingFile = null;
let selectedId = null;
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
  const shown = artworks.filter((artwork) => (
    filter === "All" || (filter === "Favorites" ? artwork.favorite : artwork.collection === filter)
  ) && (saleStatusFilter === "All statuses" || artwork.sale_status === saleStatusFilter)
    && `${artwork.title} ${artwork.collection} ${artwork.tags} ${artwork.notes} ${artwork.medium} ${artwork.dimensions}`.toLowerCase().includes(query)
    && (focusMode !== "unpriced" || (Number(artwork.price) <= 0 && artwork.sale_status !== "Sold"))
    && (focusMode !== "incomplete" || !artwork.dimensions?.trim() || !artwork.medium?.trim() || !artwork.notes?.trim())
    && (focusMode !== "ready" || artwork.sale_status === "Ready to list"));
  shown.forEach((artwork) => {
    const card = document.createElement("article");
    card.className = "art-card";
    const displayPrice = artwork.sale_status === "Sold" && artwork.sale_price ? artwork.sale_price : artwork.price;
    const missingDetails = [["dimensions", "size"], ["medium", "medium"], ["notes", "story"], ["tags", "tags"]]
      .filter(([field]) => !String(artwork[field] || "").trim())
      .map(([, label]) => label);
    if (Number(artwork.price) <= 0 && artwork.sale_status !== "Sold" && artwork.sale_status !== "Not for sale") missingDetails.push("price");
    const attention = artwork.sale_status !== "Sold" && missingDetails.length
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
    dimensions: document.querySelector("#artDimensions").value.trim(),
    medium: document.querySelector("#artMedium").value.trim(),
    price: Number(document.querySelector("#artPrice").value) || 0,
    sale_status: document.querySelector("#artSaleStatus").value,
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
    document.querySelector("#contentKitTitle").textContent = `${kit.artwork_title} Content Kit`;
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
document.querySelectorAll("[data-copy]").forEach((button) => {
  button.onclick = async () => {
    await navigator.clipboard.writeText(document.querySelector(`#${button.dataset.copy}`).value);
    notify("Content copied.");
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
  };
  if (!payload.title) return document.querySelector("#editTitle").focus();
  const response = await fetch(`/api/artworks/${selectedId}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  if (!response.ok) return notify("The artwork details could not be saved.");
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
  window.history.replaceState({}, "", "/image-studio");
  render();
}
document.querySelector("#clearFocus").onclick = clearStudioFocus;
async function initializeStudio() {
  await load();
  const focusCopy = {
    unpriced: ["Artwork that needs a price", "Open a piece and use Calculate artwork price."],
    incomplete: ["Artwork with missing details", "Add size, medium, or a description to complete each record."],
    ready: ["Artwork ready to list", "These pieces are prepared for publishing or sale."],
  };
  if (focusCopy[focusMode]) {
    document.querySelector("#focusTitle").textContent = focusCopy[focusMode][0];
    document.querySelector("#focusDescription").textContent = focusCopy[focusMode][1];
    document.querySelector("#studioFocus").hidden = false;
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
    }[requestedTool];
    if (toolButton) document.querySelector(toolButton).click();
  }
}
initializeStudio().catch(() => notify("Could not load the artwork catalog."));
