import assert from "node:assert/strict";
import test from "node:test";
import { restoreWorkspace, selectSingleRemix, arrangeRemixGroups } from "./static/think-tank-state.js";

const options = { materials: { acrylic: "Acrylic paint", collage: "Paper collage" }, surfaces: { canvas: "Primed canvas", paper: "Heavy paper" } };
const brief = { materials: ["acrylic"], surface: "canvas", direction: "A quiet portrait", collection: "Quiet Nova" };
const idea = (composition, variation = 0) => ({
  title: composition, composition, category: "Quiet Nova", palette: "Gold", mood: "Quiet",
  surface: "Primed canvas", style_ingredients: "", always: "", avoid: "",
  reference_prompt: "A reference", text: `Plan: ${composition}`,
  materials: ["Acrylic paint"], steps: ["Make a thumbnail"], variation, saved: false, savedId: null,
});
const workspace = () => ({ version: 1, form: { ...brief, direction: "An unfinished new direction" },
  brief, variation: 0, ideas: [idea("A"), { ...idea("C"), saved: true, savedId: 7 }, idea("E")] });

test("restoration keeps the unfinished form separate from the generated brief and saves", () => {
  const original = workspace();
  const restored = restoreWorkspace(JSON.stringify(original), options);
  assert.deepEqual(restored, original);
  assert.notEqual(restored.form.direction, restored.brief.direction);
  assert.equal(restored.ideas[1].savedId, 7);
});

test("an unfinished direction is recoverable before generating or selecting materials", () => {
  const original = { version: 1, form: { ...brief, materials: [], direction: "A" }, brief: null, variation: 0, ideas: [] };
  assert.deepEqual(restoreWorkspace(JSON.stringify(original), options), original);
});

test("missing, corrupt, oversized, or incompatible browser drafts are ignored", () => {
  for (const raw of [null, "undefined", "{", "[]", "null", "x".repeat(250001), JSON.stringify({ ...workspace(), version: 2 })]) {
    assert.equal(restoreWorkspace(raw, options), null);
  }
});

test("invalid cached cards and unsupported materials cannot break the restored page", () => {
  const mutations = [
    (value) => { value.form.materials = ["unknown"]; },
    (value) => { value.form.materials = ["acrylic", "acrylic"]; },
    (value) => { value.brief = null; },
    (value) => { value.ideas = []; },
    (value) => { value.ideas[0].steps = "not an array"; },
    (value) => { value.ideas[0].variation = -1; },
    (value) => { value.ideas[0].savedId = "7"; },
    (value) => { value.ideas[0].category = "AfroNova"; },
    (value) => { value.ideas[0].composition = value.ideas[1].composition; },
  ];
  for (const mutate of mutations) {
    const value = workspace();
    mutate(value);
    assert.equal(restoreWorkspace(JSON.stringify(value), options), null);
  }
});

test("a single remix avoids the current idea and both neighboring compositions", () => {
  const current = [idea("A"), idea("C"), idea("E")];
  assert.equal(selectSingleRemix([idea("C"), idea("E"), idea("B")], current, 0).composition, "B");
  assert.equal(selectSingleRemix(current, current, 1), null);
});

const candidates = (variation) => [0, 1, 2].map((index) => idea(String((variation + index * 2) % 6), variation));

test("repeated individual remixes preserve the other two cards and their saved status", () => {
  const current = candidates(0);
  current[1].saved = true;
  current[1].savedId = 7;
  for (let turn = 0; turn < 30; turn += 1) {
    const index = turn % 2 === 0 ? 0 : 2;
    const before = [...current];
    const nextVariation = (current[index].variation + 1) % 6;
    const remixed = selectSingleRemix(candidates(nextVariation), current, index);
    assert.ok(remixed);
    assert.notEqual(remixed.composition, current[index].composition);
    current[index] = remixed;
    assert.equal(new Set(current.map((item) => item.composition)).size, 3);
    before.forEach((item, other) => { if (other !== index) assert.equal(current[other], item); });
    assert.equal(current[1].savedId, 7);
  }
});

test("batch remix changes every card even after arbitrary individual remixes", () => {
  for (let a = 0; a < 6; a += 1) for (let b = 0; b < 6; b += 1) for (let c = 0; c < 6; c += 1) {
    if (new Set([a, b, c]).size !== 3) continue;
    const current = [a, b, c].map((value) => idea(String(value)));
    for (let variation = 0; variation < 6; variation += 1) {
      const group = candidates(variation);
      const remixed = arrangeRemixGroups([group, group, group], current);
      remixed.forEach((item, index) => assert.notEqual(item.composition, current[index].composition));
      assert.equal(new Set(remixed.map((item) => item.composition)).size, 3);
    }
  }
});

test("batch remixes retain each card's own direction and refinement", () => {
  const current = [idea("0"), idea("1"), idea("4")];
  const groups = current.map((item, index) => candidates((Number(item.composition) + 1) % 6)
    .map((candidate) => ({ ...candidate, brief: { ...brief, direction: `Individual direction ${index}`, studio_notes: `Notes ${index}` } })));
  const result = arrangeRemixGroups(groups, current);
  assert.ok(result);
  result.forEach((item, index) => {
    assert.equal(item.brief.direction, `Individual direction ${index}`);
    assert.equal(item.brief.studio_notes, `Notes ${index}`);
    assert.notEqual(item.composition, current[index].composition);
  });
  assert.equal(new Set(result.map((item) => item.composition)).size, 3);
});

test("impossible remixes leave the caller able to keep its current cards", () => {
  const current = [idea("A"), idea("B"), idea("C")];
  assert.equal(arrangeRemixGroups([[idea("A")], [idea("B")], [idea("C")]], current), null);
});

test("refined briefs and unfinished refinement edits survive workspace restoration", () => {
  const value = workspace();
  value.ideas[0].brief = { ...brief, direction: "A hopeful portrait", palette: "Copper and indigo", mood: "Hopeful", studio_notes: "Leave the lower edge raw." };
  value.ideas[0].composition_index = 0;
  value.ideas[0].refineDraft = { direction: "An unfinished revision", palette: "Copper", mood: "", studio_notes: "A work in progress" };
  assert.deepEqual(restoreWorkspace(JSON.stringify(value), options), value);
  value.ideas[0].refineDraft.studio_notes = "x".repeat(1201);
  assert.equal(restoreWorkspace(JSON.stringify(value), options), null);
});

test("user direction, custom-only materials, and preferences restore without collection defaults", () => {
  const own = { materials: [], other_materials: "Watercolor", surface: "paper", collection: "My own direction",
    direction: "An abstract seascape", palette: "teal and rust", mood: "playful", style_direction: "Loose washes", avoid: "faces" };
  const value = { version: 1, form: own, brief: own, variation: 0, ideas: ["A", "C", "E"].map((composition) => ({
    ...idea(composition), category: "My own direction", materials: ["Watercolor"], brief: own,
  })) };
  assert.deepEqual(restoreWorkspace(JSON.stringify(value), options), value);
  value.form = { ...own, avoid: "x".repeat(1201) };
  assert.equal(restoreWorkspace(JSON.stringify(value), options), null);
});
