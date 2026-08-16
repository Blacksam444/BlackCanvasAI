const midjourneyDialog = $("#midjourneyDialog");

$("#editMidjourney").onclick = () => {
  $("#midjourneyVersion").value = midjourneyRules.version;
  $("#midjourneyRaw").value = midjourneyRules.raw_parameter;
  $("#midjourneyRatios").value = midjourneyRules.supported_aspect_ratios.join(", ");
  $("#midjourneyDefaultRatio").value = midjourneyRules.default_aspect_ratio;
  midjourneyDialog.showModal();
};

$("#saveMidjourney").onclick = async event => {
  event.preventDefault();
  const payload = {
    version: $("#midjourneyVersion").value.trim(),
    raw_parameter: $("#midjourneyRaw").value.trim(),
    supported_aspect_ratios: values("#midjourneyRatios"),
    default_aspect_ratio: $("#midjourneyDefaultRatio").value.trim(),
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
