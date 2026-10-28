"""Physical-art directions for the app's existing local prompt engine."""

MATERIALS = {
    "acrylic": {"label": "Acrylic paint", "step": "Block in thin acrylic layers, let them dry, then build opaque focal marks."},
    "charcoal": {"label": "Charcoal", "step": "Map the darkest shapes with charcoal, lift lights with a kneaded eraser, and leave some paper visible."},
    "pastel": {"label": "Oil pastel", "step": "Layer oil pastel over the dry surface; alternate broad strokes with scratched-back details."},
    "collage": {"label": "Paper collage", "step": "Arrange torn paper first, adhere it with acrylic medium, and let the adhesive dry before drawing over it."},
    "ink": {"label": "Water-based ink", "step": "Test the ink on a scrap, establish broad washes, then add a few deliberate line accents."},
}
SURFACES = {
    "canvas": "Primed canvas",
    "paper": "Heavy mixed-media paper",
    "panel": "Primed wood panel",
}
COMPOSITIONS = (
    ("Monument", "Build one large focal silhouette above a low horizon, with open space around the head or main form."),
    ("Quiet interval", "Place the focal form to one side and let a broad, lightly worked field carry the opposite half."),
    ("Rhythm wall", "Repeat three related shapes at different scales, keeping the largest shape as the clear focal point."),
    ("Threshold", "Frame the main form with two offset vertical bands and leave a narrow opening of light between them."),
    ("Orbit", "Arrange smaller marks in an incomplete arc around the focal form, leaving one generous gap."),
    ("Crosscurrent", "Run a broad diagonal behind the focal form and answer it with a smaller counter-diagonal."),
)
DEFAULT_STYLES = {
    "AfroNova": ("deep violet, midnight blue, luminous gold, and rich earth tones", "powerful, visionary, dignified"),
    "Quiet Nova": ("warm earth tones, soft cream, muted blue, and restrained gold", "intimate, grounded, contemplative"),
    "GraffitiX": ("electric magenta, cyan, black, and flashes of gold", "bold, rebellious, kinetic"),
}


def style_list(style: dict, key: str) -> str:
    values = style.get(key)
    if not isinstance(values, list):
        return ""
    return ", ".join(value.strip()[:200] for value in values[:12] if isinstance(value, str) and value.strip())


def build_ideas(materials, surface, direction, collection, variation, saved_style, prompt_factory,
                palette_override="", mood_override="", studio_notes="", composition_index=None):
    """Return three plans, or refine one while retaining its composition."""
    palette, mood = DEFAULT_STYLES[collection]
    palette = palette_override or style_list(saved_style, "colors") or palette
    mood = mood_override or style_list(saved_style, "mood") or mood
    ingredients = style_list(saved_style, "ingredients")
    always = style_list(saved_style, "dos")
    avoid = style_list(saved_style, "donts")
    labels = [MATERIALS[name]["label"] for name in materials]
    ideas = []
    indices = [composition_index] if composition_index is not None else [
        (variation + index * 2) % len(COMPOSITIONS) for index in range(3)
    ]
    for index, selected_composition in enumerate(indices):
        name, composition = COMPOSITIONS[selected_composition]
        # Rotate the focal treatment as well as the composition for each remix.
        treatment = ("a bold silhouette", "broken tonal planes", "a continuous contour")[(variation + index) % 3]
        steps = [
            f"On {SURFACES[surface].lower()}, make a small thumbnail of {direction}, using {treatment}.",
            composition,
            *[MATERIALS[material]["step"] for material in materials],
            "Step back, check the focal point, and simplify any marks that compete with it.",
        ]
        if "charcoal" in materials and "acrylic" in materials:
            steps.append("Finish the acrylic layers before adding charcoal so wet paint does not lift the drawing.")
        if "pastel" in materials and len(materials) > 1:
            steps.append("Keep oil pastel for the final marks; water-based layers may resist its waxy surface.")
        title = f"{name}: {direction}"[:100]
        brief = f"{direction} in the {collection} style with a {mood} mood using {palette}, as acrylic canvas painting. {composition}"
        _, reference_prompt = prompt_factory(brief)
        notes = [
            "ART THINK TANK · PHYSICAL ART", f"Direction: {direction}", f"Collection: {collection}",
            f"Materials: {', '.join(labels)}", f"Surface: {SURFACES[surface]}",
            f"Composition: {composition}", f"Palette: {palette}", f"Mood: {mood}",
        ]
        if ingredients:
            notes.append(f"Style Bible ingredients: {ingredients}")
        if always:
            notes.append(f"Always include: {always}")
        if avoid:
            notes.append(f"Avoid: {avoid}")
        notes.extend(["", "STUDIO PLAN", *[f"{n}. {step}" for n, step in enumerate(steps, 1)]])
        if studio_notes:
            notes.extend(["", "STUDIO NOTES", studio_notes])
        notes.extend(["", "OPTIONAL IMAGE REFERENCE PROMPT", reference_prompt])
        ideas.append({
            "title": title, "category": collection, "composition": composition, "palette": palette,
            "mood": mood, "materials": labels, "surface": SURFACES[surface], "steps": steps,
            "style_ingredients": ingredients, "always": always, "avoid": avoid,
            "reference_prompt": reference_prompt, "text": "\n".join(notes),
            "composition_index": selected_composition,
            "brief": {"materials": list(materials), "surface": surface, "direction": direction,
                      "collection": collection, "palette": palette_override, "mood": mood_override,
                      "studio_notes": studio_notes},
        })
    return ideas
