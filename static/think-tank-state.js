// The workspace is a recoverable browser draft; library saves still use the API.
export const WORKSPACE_KEY = "blackCanvasThinkTankWorkspace";
const collections = new Set(["AfroNova", "Quiet Nova", "GraffitiX"]);
const text = (value, limit = 20000) => typeof value === "string" && value.length <= limit;
const variation = (value) => Number.isInteger(value) && value >= 0 && value < 6;

function validBrief(brief, options, allowEmpty = false) {
  return brief && Array.isArray(brief.materials) && brief.materials.length <= 5
    && (allowEmpty || brief.materials.length > 0)
    && brief.materials.every((name) => Object.hasOwn(options.materials, name))
    && new Set(brief.materials).size === brief.materials.length
    && Object.hasOwn(options.surfaces, brief.surface) && collections.has(brief.collection)
    && text(brief.direction, 600) && (allowEmpty || brief.direction.trim().length >= 3);
}

function validIdea(idea) {
  return idea && ["title", "composition", "palette", "mood", "surface", "style_ingredients",
    "always", "avoid", "reference_prompt", "text"].every((key) => text(idea[key]))
    && collections.has(idea.category)
    && Array.isArray(idea.materials) && idea.materials.length > 0 && idea.materials.length <= 5
    && idea.materials.every((item) => text(item, 100))
    && Array.isArray(idea.steps) && idea.steps.length > 0 && idea.steps.length <= 15
    && idea.steps.every((item) => text(item, 2000))
    && variation(idea.variation) && typeof idea.saved === "boolean"
    && (idea.savedId === null || (Number.isInteger(idea.savedId) && idea.savedId > 0));
}

export function restoreWorkspace(raw, options) {
  try {
    if (!text(raw, 250000)) return null;
    const value = JSON.parse(raw);
    if (!value || value.version !== 1 || !validBrief(value.form, options, true)
        || !variation(value.variation) || !Array.isArray(value.ideas)) return null;
    if (value.ideas.length === 0) return value.brief === null ? value : null;
    if (value.ideas.length !== 3 || !value.ideas.every(validIdea)
        || !validBrief(value.brief, options)
        || new Set(value.ideas.map((idea) => idea.composition)).size !== 3
        || value.ideas.some((idea) => idea.category !== value.brief.collection)) return null;
    return value;
  } catch {
    return null;
  }
}

export function selectSingleRemix(candidates, current, index) {
  const occupied = new Set(current.map((idea) => idea.composition));
  return [candidates[index], ...candidates].find((idea) => idea && !occupied.has(idea.composition)) || null;
}

export function arrangeBatchRemix(candidates, current) {
  if (current.length !== 3) return candidates;
  const orders = [[0, 1, 2], [0, 2, 1], [1, 0, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0]];
  const order = orders.find((indices) => indices.every((candidate, index) =>
    candidates[candidate].composition !== current[index].composition));
  return (order || orders[0]).map((index) => candidates[index]);
}
