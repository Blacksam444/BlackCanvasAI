"""Physical-art directions for the app's existing local prompt engine."""

USER_DIRECTION = "My own direction"

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
    ("Focal form", "Build one large focal form with open space around it; use a low horizon only if it suits the subject."),
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
                palette_override="", mood_override="", studio_notes="", composition_index=None,
                style_direction="", user_avoid="", other_materials=""):
    """Return three plans, or refine one while retaining its composition."""
    if collection == USER_DIRECTION:
        saved_style = {}
    palette, mood = DEFAULT_STYLES.get(collection, ("", ""))
    palette = palette_override or style_list(saved_style, "colors") or palette
    mood = mood_override or style_list(saved_style, "mood") or mood
    ingredients = style_list(saved_style, "ingredients")
    always = style_list(saved_style, "dos")
    avoid = user_avoid or style_list(saved_style, "donts")
    labels = [MATERIALS[name]["label"] for name in materials]
    if other_materials:
        labels.append(other_materials)
    ideas = []
    indices = [composition_index] if composition_index is not None else [
        (variation + index * 2) % len(COMPOSITIONS) for index in range(3)
    ]
    for index, selected_composition in enumerate(indices):
        name, composition = COMPOSITIONS[selected_composition]
        # Rotate the focal treatment as well as the composition for each remix.
        treatment = ("a bold silhouette", "broken tonal planes", "a continuous contour")[(variation + index) % 3]
        if style_direction or collection == USER_DIRECTION:
            treatment = style_direction or "your preferred visual approach"
        steps = [
            f"On {SURFACES[surface].lower()}, make a small thumbnail of {direction}, using {treatment}.",
            composition,
            *[MATERIALS[material]["step"] for material in materials],
            "Step back, check the focal point, and simplify any marks that compete with it.",
        ]
        if other_materials:
            steps.insert(-1, f"Make a small material test with {other_materials} on the chosen surface before committing to the full piece.")
        if "charcoal" in materials and "acrylic" in materials:
            steps.append("Finish the acrylic layers before adding charcoal so wet paint does not lift the drawing.")
        if "pastel" in materials and len(materials) > 1:
            steps.append("Keep oil pastel for the final marks; water-based layers may resist its waxy surface.")
        title = f"{name}: {direction}"[:100]
        reference_parts = [direction, f"Materials: {', '.join(labels)} on {SURFACES[surface].lower()}.", composition]
        if collection != USER_DIRECTION:
            reference_parts.append(f"Optional collection: {collection}.")
        if style_direction:
            reference_parts.append(f"User's style direction: {style_direction}.")
        if palette:
            reference_parts.append(f"Palette: {palette}.")
        if mood:
            reference_parts.append(f"Mood: {mood}.")
        if ingredients:
            reference_parts.append(f"Collection ingredients, only where consistent with the user's direction: {ingredients}.")
        if always:
            reference_parts.append(f"Collection guidance, only where consistent with the user's direction: {always}.")
        if avoid:
            reference_parts.append(f"Avoid: {avoid}.")
        if studio_notes:
            reference_parts.append(f"Studio notes: {studio_notes}.")
        _, reference_prompt = prompt_factory(" ".join(reference_parts), collection_override=USER_DIRECTION)
        notes = [
            "ART THINK TANK · PHYSICAL ART", f"Direction: {direction}", f"Collection: {collection}",
            f"Materials: {', '.join(labels)}", f"Surface: {SURFACES[surface]}",
            f"Composition: {composition}", f"Palette: {palette or 'Not specified'}", f"Mood: {mood or 'Not specified'}",
        ]
        if style_direction:
            notes.append(f"Your style direction: {style_direction}")
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
            "style_direction": style_direction,
            "brief": {"materials": list(materials), "surface": surface, "direction": direction,
                      "collection": collection, "palette": palette_override, "mood": mood_override,
                      "studio_notes": studio_notes, "style_direction": style_direction,
                      "avoid": user_avoid, "other_materials": other_materials},
        })
    return ideas
