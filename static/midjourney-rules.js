const midjourneyDialog = $("#midjourneyDialog");

function renderMidjourneyMetadata() {
  const verified = midjourneyRules.verified_at || "Not recorded";
  const source = midjourneyRules.verification_source;
  $("#verificationStatus").innerHTML = source
    ? `Verified ${verified} · <a href="${source}" target="_blank" rel="noopener">Open source ↗</a>`
    : `Verified ${verified}`;
  const previous = midjourneyRules.previous_rules;
  $("#previousRules").hidden = !previous;
  if (previous) {
    $("#previousRulesSummary").textContent = `Previous: MidJourney v${previous.version} · ${previous.raw_parameter}`;
  }
}

$("#editMidjourney").onclick = () => {
  $("#midjourneyVersion").value = midjourneyRules.version;
  $("#midjourneyRaw").value = midjourneyRules.raw_parameter;
  $("#midjourneyRatios").value = midjourneyRules.supported_aspect_ratios.join(", ");
  $("#midjourneyDefaultRatio").value = midjourneyRules.default_aspect_ratio;
  $("#midjourneyVerifiedAt").value = midjourneyRules.verified_at || "";
  $("#midjourneySource").value = midjourneyRules.verification_source || "";
  $("#midjourneyNote").value = midjourneyRules.update_note || "";
  renderMidjourneyMetadata();
  midjourneyDialog.showModal();
};

$("#saveMidjourney").onclick = async event => {
  event.preventDefault();
  const payload = {
    version: $("#midjourneyVersion").value.trim(),
    raw_parameter: $("#midjourneyRaw").value.trim(),
    supported_aspect_ratios: values("#midjourneyRatios"),
    default_aspect_ratio: $("#midjourneyDefaultRatio").value.trim(),
    verified_at: $("#midjourneyVerifiedAt").value,
    verification_source: $("#midjourneySource").value.trim(),
    update_note: $("#midjourneyNote").value.trim(),
  };
  const response = await fetch("/api/midjourney-rules", {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) {
    notify(result.detail || "Those MidJourney rules could not be saved.");
    return;
  }
  midjourneyRules = result;
  midjourneyDialog.close();
  render();
  notify(`MidJourney v${result.version} rules saved.`);
};

$("#restorePrevious").onclick = async () => {
  const response = await fetch("/api/midjourney-rules/restore-previous", {method: "POST"});
  const result = await response.json();
  if (!response.ok) {
    notify(result.detail || "The previous rules could not be restored.");
    return;
  }
  midjourneyRules = result;
  midjourneyDialog.close();
  render();
  notify(`Restored MidJourney v${result.version}.`);
};
