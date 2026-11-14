"""Opt-in cultural context for Black Canvas AI creative prompts.

This module supplies editorial guidance, not assertions about the identity or
intent of an artist or the meaning of a particular symbol.
"""
from dataclasses import dataclass

CULTURAL_THEMES = {
    "ancestry": "Explore intergenerational memory and personal connections without assuming a single shared Black experience.",
    "identity": "Explore self-definition, masks, belonging, and the tension between public and private selves.",
    "survival": "Consider resilience and complexity without reducing Black life to trauma.",
    "future": "Explore Afrofuturism, speculative futures, invention, and imaginative freedom.",
    "legacy": "Explore what is passed forward through art, relationships, and memory.",
}
SYMBOL_GUIDANCE = {
    "crown": "Earned authority, survival, and self-defined sovereignty in this artist's visual vocabulary.",
    "skull": "Mortality, wisdom, legacy, or transformation; meaning depends on the specific work.",
    "doorway": "Transition and becoming.",
    "mirror": "Reflection, alternate selves, and identity.",
    "wings": "Freedom, transcendence, and movement.",
    "444": "A recurring personal visual motif; ask the artist for its intended meaning rather than assigning a universal cultural interpretation.",
}

@dataclass(frozen=True)
class CulturalContext:
    enabled: bool = False
    theme: str = "identity"

def guidance(context: CulturalContext) -> str:
    """Return optional context for an artwork prompt or artist statement."""
    if not context.enabled:
        return ""
    if context.theme not in CULTURAL_THEMES:
        raise ValueError("Unknown cultural theme")
    return (
        "OPTIONAL CULTURAL CONTEXT — " + CULTURAL_THEMES[context.theme] + " "
        "Draw from Black artistic traditions only when relevant to the artist's stated intent. "
        "Distinguish documented historical references from imaginative interpretation. "
        "Do not invent provenance, historical facts, spiritual meanings, or the artist's lived experience. "
        "Avoid stereotypes, forced symbolism, and treating Black cultures as interchangeable. "
        "Honor the existing Style Bible, handmade textures, and one dominant hero symbol. "
        "When describing a work, prioritize what is visible and what the artist has confirmed."
    )
