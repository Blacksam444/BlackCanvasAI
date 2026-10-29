// The workspace is a recoverable browser draft; library saves still use the API.
export const WORKSPACE_KEY = "blackCanvasThinkTankWorkspace";
const collections = new Set(["My own direction", "AfroNova", "Quiet Nova", "GraffitiX"]);
const text = (value, limit = 40000) => typeof value === "string" && value.length <= limit;
const variation = (value) => Number.isInteger(value) && value >= 0 && value < 6;

function validBrief(brief, options, allowEmpty = false) {
  return brief && Array.isArray(brief.materials) && brief.materials.length <= 5
    && (allowEmpty || brief.materials.length > 0 || (typeof brief.other_materials === "string" && brief.other_materials.trim().length > 0))
    && brief.materials.every((name) => Object.hasOwn(options.materials, name))
    && new Set(brief.materials).size === brief.materials.length
    && Object.hasOwn(options.surfaces, brief.surface) && collections.has(brief.collection)
    && text(brief.direction, 600) && (allowEmpty || brief.direction.trim().length >= 3)
    && (brief.palette === undefined || text(brief.palette, 2600))
    && (brief.mood === undefined || text(brief.mood, 2600))
    && (brief.studio_notes === undefined || text(brief.studio_notes, 1200))
    && (brief.other_materials === undefined || text(brief.other_materials, 240))
    && (brief.style_direction === undefined || text(brief.style_direction, 600))
    && (brief.avoid === undefined || text(brief.avoid, 1200));
}

function validIdea(idea, options) {
  return idea && ["title", "composition", "palette", "mood", "surface", "style_ingredients",
    "always", "avoid", "reference_prompt", "text"].every((key) => text(idea[key]))
    && collections.has(idea.category)
    && Array.isArray(idea.materials) && idea.materials.length > 0 && idea.materials.length <= 6
    && idea.materials.every((item) => text(item, 240))
    && Array.isArray(idea.steps) && idea.steps.length > 0 && idea.steps.length <= 15
    && idea.steps.every((item) => text(item, 2000))
    && variation(idea.variation) && typeof idea.saved === "boolean"
    && (idea.savedId === null || (Number.isInteger(idea.savedId) && idea.savedId > 0))
    && (idea.brief === undefined || (validBrief(idea.brief, options) && idea.brief.collection === idea.category))
    && (idea.composition_index === undefined || variation(idea.composition_index))
    && (idea.projectId === undefined || (typeof idea.projectId === "string" && /^[A-Za-z0-9_-]{1,80}$/.test(idea.projectId)))
    && (idea.refineDraft === undefined || (idea.refineDraft
      && text(idea.refineDraft.direction, 600) && text(idea.refineDraft.palette, 2600)
      && text(idea.refineDraft.mood, 2600) && text(idea.refineDraft.studio_notes, 1200)
      && (idea.refineDraft.style_direction === undefined || text(idea.refineDraft.style_direction, 600))
      && (idea.refineDraft.avoid === undefined || text(idea.refineDraft.avoid, 1200))));
}

export function restoreWorkspace(raw, options) {
  try {
    if (!text(raw, 250000)) return null;
    const value = JSON.parse(raw);
    if (!value || value.version !== 1 || !validBrief(value.form, options, true)
        || !variation(value.variation) || !Array.isArray(value.ideas)) return null;
    if (value.ideas.length === 0) return value.brief === null ? value : null;
    if (value.ideas.length !== 3 || !value.ideas.every((idea) => validIdea(idea, options))
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

export function arrangeRemixGroups(groups, current) {
  function choose(index, selected) {
    if (index === groups.length) return selected;
    for (const candidate of groups[index]) {
      if (candidate.composition === current[index].composition
          || selected.some((idea) => idea.composition === candidate.composition)) continue;
      const result = choose(index + 1, [...selected, candidate]);
      if (result) return result;
    }
    return null;
  }
  return choose(0, []);
}
