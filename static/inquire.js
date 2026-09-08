const params = new URLSearchParams(window.location.search);
const artworkId = Number(params.get("artwork") || 0) || null;
const selectedWork = document.querySelector("#selectedWork");
let publicContact = "";
const settingsReady = fetch('/api/gallery-settings').then(r => {
  if (!r.ok) throw new Error('Contact details could not be loaded. Please reload.');
  return r.json();
}).then(settings => {
  if (!settings.public_mode) return;
  publicContact = settings.contact_email;
  document.querySelector('#sendInquiry').textContent = 'Open email draft →';
  document.querySelector('.form-note').textContent = 'This opens your email app. Review your message and press Send there to contact the studio.';
  const contact = document.createElement('a');
  contact.href = `mailto:${publicContact}`;
  contact.textContent = publicContact;
  document.querySelector('.intro').append(contact);
});

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
    await settingsReady;
    if (publicContact) {
      const title = document.querySelector('#selectedWorkTitle').textContent;
      const subject = `${payload.inquiry_type}${title ? ': ' + title : ''}`;
      const body = `${payload.message}\n\nName: ${payload.name}\nReply email: ${payload.email}\nBudget: ${payload.budget || 'Not specified'}${artworkId ? '\nArtwork: ' + artworkId : ''}`;
      window.location.href = `mailto:${publicContact}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
      button.disabled = false;
      button.textContent = 'Open email draft →';
      return;
    }
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
