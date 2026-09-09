const params = new URLSearchParams(window.location.search);
const artworkId = Number(params.get("artwork") || 0) || null;
const selectedWork = document.querySelector("#selectedWork");

if (artworkId) {
  fetch(`/api/inquiry-artwork/${artworkId}`).then((response) => response.ok ? response.json() : null).then((artwork) => {
    if (!artwork) return;
    selectedWork.hidden = false;
    document.querySelector("#selectedWorkTitle").textContent = artwork.title;
    document.querySelector("#selectedWorkCollection").textContent = artwork.collection;
  });
}

document.querySelector("#inquiryForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.querySelector("#sendInquiry");
  button.disabled = true;
  button.textContent = "Submitting…";
  const payload = {
    artwork_id: artworkId,
    inquiry_type: document.querySelector("#inquiryType").value,
    name: document.querySelector("#inquiryName").value.trim(),
    email: document.querySelector("#inquiryEmail").value.trim(),
    budget: document.querySelector("#inquiryBudget").value.trim(),
    message: document.querySelector("#inquiryMessage").value.trim(),
  };
  try {
    const response = await fetch("/api/inquiries", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not send your inquiry.");
    document.querySelector("#inquiryForm").hidden = true;
    document.querySelector("#inquirySuccess").hidden = false;
  } catch (error) {
    button.disabled = false;
    button.textContent = "Send inquiry →";
    window.alert(error.message || "Could not send your inquiry.");
  }
});
