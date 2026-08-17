import base64
import json
import re
import shutil
import sqlite3
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel

from storage import UPLOAD_DIR, backup_data, connect, execute, initialize, rows

BASE_DIR = Path(__file__).resolve().parent
MIDJOURNEY_RULES_PATH = BASE_DIR / "midjourney_rules.json"
MIDJOURNEY_RULES = json.loads(MIDJOURNEY_RULES_PATH.read_text(encoding="utf-8"))
DEFAULT_ASPECT_RATIO = MIDJOURNEY_RULES["default_aspect_ratio"]
SUPPORTED_ASPECT_RATIOS = set(MIDJOURNEY_RULES["supported_aspect_ratios"])
DEFAULT_NEGATIVE_INSTRUCTIONS = "no text, no watermark, no signature, no logo, no frame"
GRAFFITIX_NEGATIVE_INSTRUCTIONS = (
    "no digital smoothness, no glossy CGI finish, no polished 3D render, "
    "no clean vector edges, no random decorative symbols, no cluttered focal hierarchy, "
    f"{DEFAULT_NEGATIVE_INSTRUCTIONS}"
)


def midjourney_v82_suffix(idea: str) -> str:
    requested_ratio = re.search(r"(?:^|[.;])\s*aspect ratio\s*:\s*([0-9]+:[0-9]+)", idea, flags=re.IGNORECASE)
    aspect_ratio = requested_ratio.group(1) if requested_ratio else DEFAULT_ASPECT_RATIO
    if aspect_ratio not in SUPPORTED_ASPECT_RATIOS:
        aspect_ratio = DEFAULT_ASPECT_RATIO
    return f"--ar {aspect_ratio} {MIDJOURNEY_RULES['raw_parameter']} --v {MIDJOURNEY_RULES['version']}"


def strip_midjourney_parameters(text: str) -> str:
    cleaned = re.sub(
        r"\s*--(?:style\s+raw\b|ar\s+[0-9]+:[0-9]+\b|raw\b|v\s+[0-9]+(?:\.[0-9]+)?\b)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def midjourney_parameter_summary(prompt: str) -> dict[str, str]:
    aspect = re.search(r"--ar\s+([0-9]+:[0-9]+)\b", prompt, flags=re.IGNORECASE)
    version = re.search(r"--v\s+([0-9]+(?:\.[0-9]+)?)\b", prompt, flags=re.IGNORECASE)
    if re.search(r"--style\s+raw\b", prompt, flags=re.IGNORECASE):
        raw_mode = "--style raw"
    elif re.search(r"--raw\b", prompt, flags=re.IGNORECASE):
        raw_mode = "--raw"
    else:
        raw_mode = "not set"
    return {
        "Aspect ratio": aspect.group(1) if aspect else "not set",
        "Raw mode": raw_mode,
        "Version": version.group(1) if version else "not set",
    }


def format_version_test_pair(original: dict, migrated: dict, original_version: str, migrated_version: str) -> str:
    return (
        f"ORIGINAL — MIDJOURNEY V{original_version}\n"
        f"{original['title']}\n\n{original['text'].strip()}\n\n"
        f"ACTIVE COPY — MIDJOURNEY V{migrated_version}\n"
        f"{migrated['title']}\n\n{migrated['text'].strip()}\n"
    )


def format_version_test_report(comparison: dict) -> str:
    verdicts = {"original": "Original preferred", "active": "Active copy preferred", "tie": "No clear winner"}
    verdict = verdicts.get(comparison["migrated"].get("version_test_result"), "Not tested")
    notes = comparison["migrated"].get("version_test_notes") or "No notes recorded."
    tested_at = comparison["migrated"].get("version_tested_at") or "Not recorded"
    rules_verified_at = comparison.get("rules_verified_at") or MIDJOURNEY_RULES.get("verified_at", "Not recorded")
    retest_recommended = "Yes" if comparison["migrated"].get("retest_recommended") else "No"
    changes = comparison["parameter_changes"]
    change_lines = "\n".join(
        f"- {change['parameter']}: {change['original']} -> {change['migrated']}" for change in changes
    ) or "- No technical parameter changes detected."
    preserved = "Yes" if comparison["creative_body_preserved"] else "No — review creative text carefully"
    return (
        "BLACK CANVAS AI — MIDJOURNEY VERSION TEST REPORT\n"
        f"Created {datetime.now().astimezone().strftime('%B %d, %Y')}\n\n"
        f"Creative direction preserved: {preserved}\n"
        f"Test verdict: {verdict}\n\n"
        f"Verdict recorded: {tested_at}\n\n"
        f"MidJourney rules verified: {rules_verified_at}\n"
        f"Retest recommended: {retest_recommended}\n\n"
        f"PARAMETER CHANGES\n{change_lines}\n\n"
        f"TEST NOTES\n{notes}\n\n"
        f"ORIGINAL — MIDJOURNEY V{comparison['original']['version']}\n"
        f"{comparison['original']['title']}\n\n{comparison['original']['text'].strip()}\n\n"
        f"ACTIVE COPY — MIDJOURNEY V{comparison['migrated']['version']}\n"
        f"{comparison['migrated']['title']}\n\n{comparison['migrated']['text'].strip()}\n"
    )


def format_version_test_report_collection(reports: list[str]) -> str:
    heading = (
        "BLACK CANVAS AI — MIDJOURNEY VERSION TEST REPORT BUNDLE\n"
        f"Created {datetime.now().astimezone().strftime('%B %d, %Y')}\n"
        f"{len(reports)} version test {'report' if len(reports) == 1 else 'reports'}\n"
    )
    separator = "\n" + "=" * 72 + "\n\n"
    return heading + separator + separator.join(report.strip() for report in reports) + "\n"


def midjourney_syntax_issues(prompt: str) -> list[str]:
    issues: list[str] = []
    has_legacy_raw = bool(re.search(r"--style\s+raw\b", prompt, flags=re.IGNORECASE))
    if has_legacy_raw:
        issues.append("Legacy --style raw syntax")
    prompt_versions = re.findall(r"--v\s+([0-9]+(?:\.[0-9]+)?)\b", prompt, flags=re.IGNORECASE)
    mismatched_versions = list(dict.fromkeys(version for version in prompt_versions if version != MIDJOURNEY_RULES["version"]))
    if mismatched_versions:
        issues.append(
            f"Uses MidJourney v{', '.join(mismatched_versions)}; active verified rules are v{MIDJOURNEY_RULES['version']}"
        )
    version_pattern = re.escape(MIDJOURNEY_RULES["version"])
    raw_pattern = rf"{re.escape(MIDJOURNEY_RULES['raw_parameter'])}\b"
    if not has_legacy_raw and re.search(rf"--v\s+{version_pattern}\b", prompt, flags=re.IGNORECASE) and not re.search(
        raw_pattern, prompt, flags=re.IGNORECASE
    ):
        issues.append(f"MidJourney v{MIDJOURNEY_RULES['version']} prompt is missing {MIDJOURNEY_RULES['raw_parameter']}")
    return issues


def repair_midjourney_syntax(prompt: str) -> str:
    repaired = prompt
    for deprecated, replacement in MIDJOURNEY_RULES["deprecated_parameters"].items():
        deprecated_pattern = re.escape(deprecated).replace(r"\ ", r"\s+")
        repaired = re.sub(deprecated_pattern, replacement, repaired, flags=re.IGNORECASE)
    version_pattern = re.escape(MIDJOURNEY_RULES["version"])
    raw_parameter = MIDJOURNEY_RULES["raw_parameter"]
    if re.search(rf"--v\s+{version_pattern}\b", repaired, flags=re.IGNORECASE) and not re.search(
        rf"{re.escape(raw_parameter)}\b", repaired, flags=re.IGNORECASE
    ):
        repaired = re.sub(
            rf"(?=--v\s+{version_pattern}\b)", f"{raw_parameter} ", repaired, count=1, flags=re.IGNORECASE
        )
    return repaired


def format_prompt_pack(prompts: list[dict]) -> str:
    created = datetime.now().astimezone().strftime("%B %d, %Y")
    sections = [
        "BLACK CANVAS AI — PROMPT PACK",
        f"Created {created}",
        f"{len(prompts)} prompt{'s' if len(prompts) != 1 else ''}",
    ]
    for index, prompt in enumerate(prompts, start=1):
        issues = midjourney_syntax_issues(prompt["text"])
        heading = f"{index}. {prompt['title']} [{prompt['category']}]"
        if issues:
            heading += f"\nSYNTAX CHECK: {'; '.join(issues)}"
        sections.extend((heading, prompt["text"].strip()))
    return "\n\n".join(sections) + "\n"
initialize()
app = FastAPI(title="Black Canvas AI")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


def dashboard_file() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "dashboard.html")


class ChatMessage(BaseModel):
    message: str


class PromptPayload(BaseModel):
    title: str
    category: str
    text: str
    favorite: bool = False


class PromptBulkPayload(BaseModel):
    prompt_ids: list[int]
    category: str | None = None
    reviewed: bool | None = None
    favorite: bool | None = None


class PromptIdsPayload(BaseModel):
    prompt_ids: list[int]


class VersionTestResultPayload(BaseModel):
    result: str


class VersionTestNotesPayload(BaseModel):
    notes: str = ""


class StylePayload(BaseModel):
    content: dict


class MidJourneyRulesPayload(BaseModel):
    version: str
    default_aspect_ratio: str
    supported_aspect_ratios: list[str]
    raw_parameter: str
    verified_at: str = ""
    verification_source: str = ""
    update_note: str = ""


class ArtworkPayload(BaseModel):
    title: str
    collection: str
    tags: str = ""
    notes: str = ""
    favorite: bool = False
    data_url: str


class ArtworkDetailsPayload(BaseModel):
    title: str
    collection: str
    tags: str = ""
    notes: str = ""


class GoogleCredentialsPayload(BaseModel):
    credentials: dict


class GoogleClientPayload(BaseModel):
    client_id: str
    client_secret: str


class ChatGPTImportPayload(BaseModel):
    candidate_ids: list[str]


class DriveArtworkPayload(BaseModel):
    title: str
    collection: str = "Unsorted"
    tags: str = ""
    notes: str = ""


def clean_image_idea(message: str) -> str:
    idea = message.strip().rstrip(".?!")
    patterns = [
        r"^(?:can|could|will|would)\s+(?:we|you)\s+(?:write|create|make|generate)\s+(?:me\s+)?(?:an?\s+)?(?:image\s+)?prompt\s+(?:for|of|about)\s+",
        r"^(?:please\s+)?(?:write|create|make|generate)\s+(?:me\s+)?(?:an?\s+)?(?:image\s+)?prompt\s+(?:for|of|about)?\s*",
        r"^(?:i\s+(?:want|need)\s+)(?:an?\s+)?(?:image\s+)?prompt\s+(?:for|of|about)?\s*",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, "", idea, flags=re.IGNORECASE).strip()
        if cleaned != idea:
            idea = cleaned
            break
    idea = re.sub(r"\b(a)\s+(african)\b", r"an \2", idea, flags=re.IGNORECASE)
    simple_style = re.sub(r"[^a-z]", "", idea.lower())
    if simple_style in ("afronova", "afronovastyle"):
        idea = "a regal Black visionary in the AfroNova style"
    elif simple_style in ("quietnova", "quietnovastyle"):
        idea = "a contemplative Black figure in the Quiet Nova style"
    elif simple_style in ("graffitix", "graffitixstyle"):
        idea = "an expressive Black urban creator in the GraffitiX style"
    return idea or message.strip()


def prompt_collection(idea: str) -> tuple[str, str, str, str]:
    lowered = idea.lower()
    if "afro nova" in lowered or "afronova" in lowered:
        return ("AfroNova", "deep violet, midnight blue, luminous gold, and rich earth tones",
                "Afrofuturist elegance, celestial symbolism, intricate textile detail, and regal visual language",
                "powerful, visionary, dignified")
    if "quiet nova" in lowered:
        return ("Quiet Nova", "warm earth tones, soft cream, muted blue, and restrained gold",
                "subtle tactile texture, generous negative space, and softly rendered details",
                "intimate, grounded, contemplative")
    if "graffitix" in lowered or "graffiti x" in lowered:
        return ("GraffitiX", "electric magenta, cyan, black, and flashes of gold",
                "layered spray-paint marks, torn-paper textures, expressive urban energy, and a restrained symbolic vocabulary of hand-drawn 444 numerals, crowns, skulls, X-eyes, crude diamonds, primitive pyramids, cryptic writing, crossed-out phrases, ledger marks, and loose scribbles; organize the composition around one main subject, one hero symbol, one or two supporting symbols, then secondary background writing",
                "bold, rebellious, kinetic")
    if any(word in lowered for word in ("graffiti", "street", "urban", "neon", "city", "hip-hop")):
        return ("GraffitiX", "electric magenta, cyan, black, and flashes of gold",
                "layered spray-paint marks, torn-paper textures, expressive urban energy, and a restrained symbolic vocabulary of hand-drawn 444 numerals, crowns, skulls, X-eyes, crude diamonds, primitive pyramids, cryptic writing, crossed-out phrases, ledger marks, and loose scribbles; organize the composition around one main subject, one hero symbol, one or two supporting symbols, then secondary background writing",
                "bold, rebellious, kinetic")
    if any(word in lowered for word in ("quiet", "calm", "peaceful", "soft", "gentle", "reflective", "morning")):
        return ("Quiet Nova", "warm earth tones, soft cream, muted blue, and restrained gold",
                "subtle tactile texture, generous negative space, and softly rendered details",
                "intimate, grounded, contemplative")
    return ("AfroNova", "deep violet, midnight blue, luminous gold, and rich earth tones",
            "Afrofuturist elegance, celestial symbolism, intricate textile detail, and regal visual language",
            "powerful, visionary, dignified")


def create_image_prompt(message: str) -> tuple[str, str]:
    idea = clean_image_idea(message)
    collection, palette, style, mood = prompt_collection(idea)
    lowered = idea.lower()
    subject = re.split(r"\s+in\s+the\s+(?:AfroNova|Quiet Nova|GraffitiX)\s+style", idea, maxsplit=1, flags=re.IGNORECASE)[0]
    requested_mood = re.search(r"with\s+(?:an?\s+)?(.+?)\s+mood", idea, flags=re.IGNORECASE)
    requested_colors = re.search(r"using\s+(.+?),\s+as\s+", idea, flags=re.IGNORECASE)
    if requested_mood:
        mood = requested_mood.group(1).strip()
    if requested_colors and "collection color palette" not in requested_colors.group(1).lower():
        palette = requested_colors.group(1).strip()
    requested_pose = re.search(r"(?:^|[.;])\s*pose\s*:\s*([^.;]+)", idea, flags=re.IGNORECASE)
    requested_camera = re.search(r"(?:^|[.;])\s*camera\s*:\s*([^.;]+)", idea, flags=re.IGNORECASE)
    requested_wardrobe = re.search(r"(?:^|[.;])\s*wardrobe\s*:\s*([^.;]+)", idea, flags=re.IGNORECASE)
    requested_hero = re.search(r"(?:^|[.;])\s*hero symbol\s*:\s*([^.;]+)", idea, flags=re.IGNORECASE)
    requested_supporting = re.search(r"(?:^|[.;])\s*supporting symbols\s*:\s*([^.;]+)", idea, flags=re.IGNORECASE)
    requested_media = re.search(r"(?:^|[.;])\s*physical media\s*:\s*([^.;]+)", idea, flags=re.IGNORECASE)
    requested_background = re.search(r"(?:^|[.;])\s*background marks\s*:\s*([^.;]+)", idea, flags=re.IGNORECASE)
    requested_lighting = re.search(r"(?:^|[.;])\s*lighting\s*:\s*([^.;]+)", idea, flags=re.IGNORECASE)
    midjourney_suffix = midjourney_v82_suffix(idea)
    if "photorealistic" in lowered or "photograph" in lowered:
        medium = "cinematic photorealistic portrait photography"
    elif "acrylic" in lowered:
        medium = "museum-quality acrylic painting on textured canvas"
    elif "editorial fashion" in lowered:
        medium = "high-fashion editorial portrait photography"
    elif "graphic poster" in lowered:
        medium = "bold contemporary graphic poster art"
    else:
        medium = "museum-quality fine-art digital painting with painterly realism"
    safety = " age-appropriate styling and a dignified, authentic expression," if any(
        word in subject.lower() for word in ("child", "boy", "girl", "kid", "baby")
    ) else ""
    if collection == "GraffitiX":
        pose_direction = requested_pose.group(1).strip() if requested_pose else (
            "a grounded, readable pose with clearly described planted foot, weight distribution, bent joints, "
            "hip angle, shoulder counter-rotation, torso twist, and an intentional S-curve, Z-curve, or spiral "
            "line of action suited to the movement"
        )
        camera_direction = requested_camera.group(1).strip() if requested_camera else (
            "a deliberate cinematic angle—low-angle three-quarter, pavement-level tracking shot, high-angle "
            "Dutch angle, or another specific viewpoint that strengthens the pose"
        )
        hero_symbol = requested_hero.group(1).strip() if requested_hero else (
            "a rough-painted 444, distorted crown, skull, or X-eye treatment"
        )
        wardrobe_direction = requested_wardrobe.group(1).strip() if requested_wardrobe else (
            "oversized deeply pleated chinos stacked at the ankles, a loose pocket tee or cropped tank, "
            "an open flannel or vintage windbreaker, a bandana or snapback when appropriate, and retro statement sneakers"
        )
        lighting_direction = requested_lighting.group(1).strip() if requested_lighting else (
            "stark graphic directional lighting with brutal contrast and hard-edged shadows"
        )
        supporting_symbols = requested_supporting.group(1).strip() if requested_supporting else (
            "one or two small symbols chosen from a crude diamond, primitive pyramid, tiny xxx marks, or nova glyph"
        )
        background_marks = requested_background.group(1).strip() if requested_background else (
            "restrained ledger numbers, anatomical labels, cryptic notes, crossed-out phrases, and loose scribbles"
        )
        physical_media = requested_media.group(1).strip() if requested_media else (
            "heavy oil stick, thick oil pastel, viscous dripping acrylic, palette-knife impasto ridges, "
            "aerosol haze and overspray, charcoal drag marks, scratches, torn collage, and exposed unprimed canvas"
        )
        prompt = (
            f"/imagine prompt: full-body {subject},{safety} presented as the unmistakable focal subject. "
            f"Engineer {pose_direction}. Use {camera_direction}, and keep the silhouette immediately readable. "
            f"Build authentic 1990s streetwear with construction detail: {wardrobe_direction}. "
            f"Establish the 444 GraffitiX symbol hierarchy: one dominant hero symbol—{hero_symbol}; "
            f"supporting layer with one or two small supporting symbols—{supporting_symbols}; "
            f"secondary background layer—{background_marks}. "
            "Never let either secondary layer compete with the subject or hero symbol. "
            "Render as raw Black Canvas AI / 444 GraffitiX mixed-media fine art. "
            f"Physical media treatment: {physical_media}. Embed handwritten ledger numbers, anatomical-style labels, cryptic "
            "notes, crossed-out phrases, loose scribbles, directional paint streaks, diamonds, pyramids, and "
            "X/444 treatments into the environment with controlled negative space. "
            f"Use {palette}. Light the scene with {lighting_direction}, irregular hand-drawn edges, "
            f"tactile matte surfaces, and a {mood} emotional charge. Keep the figure sharp and emotionally "
            "present while environmental marks reinforce movement. Museum-quality contemporary urban artwork, "
            f"{GRAFFITIX_NEGATIVE_INSTRUCTIONS} {midjourney_suffix}"
        )
        return collection, f"{strip_midjourney_parameters(prompt)} {midjourney_suffix}"
    prompt = (
        f"Create {medium} of {subject},{safety} presented as the unmistakable focal subject. "
        f"Use a balanced three-quarter composition at eye level, with confident posture, expressive eyes, "
        f"and carefully observed facial features. Build the visual direction around {style}. "
        f"Illuminate the subject with soft directional key light and a subtle luminous rim light, creating "
        f"dimensional skin tones, controlled highlights, and rich shadow detail. Use a refined palette of "
        f"{palette}. Place the subject against an atmospheric, story-rich background that supports the idea "
        f"without competing with the face. The mood is {mood}. Include believable materials, finely rendered "
        f"fabric and accessories, natural depth of field, sophisticated color grading, crisp focal detail, "
        f"gallery-ready composition, ultra-detailed, cohesive, emotionally resonant, "
        f"{DEFAULT_NEGATIVE_INSTRUCTIONS} {midjourney_suffix}"
    )
    return collection, f"{strip_midjourney_parameters(prompt)} {midjourney_suffix}"


@app.get("/")
def home() -> FileResponse:
    return dashboard_file()


@app.get("/dashboard")
def dashboard() -> FileResponse:
    return dashboard_file()


@app.get("/chat")
def chat() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "chat.html")


@app.get("/prompts")
def prompts() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "prompts.html")


@app.get("/image-studio")
def image_studio() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "image-studio.html")


@app.get("/style-bible")
def style_bible() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "style-bible.html")


@app.get("/connections")
def connections() -> FileResponse:
    return FileResponse(
        BASE_DIR / "templates" / "connections.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.post("/api/chat")
def chat_reply(payload: ChatMessage) -> dict[str, str]:
    topic = payload.message.strip()
    creative_triggers = ("prompt", "image", "portrait", "painting", "photo", "artwork", "style",
                         "afronova", "afro nova", "quiet nova", "graffitix", "graffiti x")
    if any(word in topic.lower() for word in creative_triggers):
        collection, prompt = create_image_prompt(topic)
        idea = clean_image_idea(topic)
        title = re.sub(r"\s+", " ", idea).strip().title()[:70] or "Generated Image Prompt"
        return {
            "reply": (
                f"**Your {collection} image prompt**\n\n{prompt}\n\n"
                "You can copy this prompt into your image generator. This version was created locally, "
                "so it did not use a paid AI key."
            ),
            "generated_prompt": prompt,
            "prompt_title": title,
            "prompt_category": collection,
        }
    return {
        "reply": (
            f"I’m ready to help you develop **{topic}**.\n\n"
            "Here’s a strong way to begin:\n"
            "- Define the goal and who it is for.\n"
            "- Choose the Black Canvas style or collection it belongs to.\n"
            "- Turn the idea into one clear, testable creative direction.\n\n"
            "The chat workspace is working. The next connection will replace this preview "
            "response with live AI reasoning."
        )
    }


@app.get("/api/prompts")
def list_prompts() -> list[dict]:
    items = rows("SELECT id, title, category, text, favorite, source, reviewed, trashed, parent_prompt_id, migrated_from_version, version_test_result, version_tested_at FROM prompts ORDER BY id DESC")
    for item in items:
        item["syntax_issues"] = midjourney_syntax_issues(item["text"])
        item["version_mismatch"] = any(issue.startswith("Uses MidJourney v") for issue in item["syntax_issues"])
        item["syntax_repairable"] = repair_midjourney_syntax(item["text"]) != item["text"]
        item["retest_recommended"] = version_test_needs_retest(item)
    return items


def version_test_needs_retest(item: dict, verified_at: str | None = None) -> bool:
    if not item.get("version_test_result"):
        return False
    tested_at = item.get("version_tested_at")
    verified_at = verified_at or MIDJOURNEY_RULES.get("verified_at")
    if not tested_at or not verified_at:
        return True
    try:
        return datetime.fromisoformat(str(tested_at).replace("Z", "+00:00")).date() < date.fromisoformat(verified_at)
    except ValueError:
        return True


def summarize_version_tests(items: list[dict]) -> dict[str, int]:
    migrated = [item for item in items if item.get("parent_prompt_id")]
    counts = {"total": len(migrated), "untested": 0, "active": 0, "original": 0, "tie": 0,
              "retest_recommended": sum(version_test_needs_retest(item) for item in migrated)}
    for item in migrated:
        result = item.get("version_test_result")
        if result in ("active", "original", "tie"):
            counts[result] += 1
        else:
            counts["untested"] += 1
    counts["tested"] = counts["total"] - counts["untested"]
    counts["completion_percent"] = round(counts["tested"] / counts["total"] * 100) if counts["total"] else 0
    return counts


@app.get("/api/dashboard")
def dashboard_summary() -> dict:
    with connect() as db:
        prompt_count = db.execute("SELECT COUNT(*) FROM prompts WHERE trashed = 0").fetchone()[0]
        artwork_count = db.execute("SELECT COUNT(*) FROM artworks").fetchone()[0]
        favorite_count = db.execute(
            "SELECT (SELECT COUNT(*) FROM prompts WHERE favorite = 1 AND trashed = 0) + "
            "(SELECT COUNT(*) FROM artworks WHERE favorite = 1)"
        ).fetchone()[0]
        review_count = db.execute("SELECT COUNT(*) FROM prompts WHERE reviewed = 0 AND trashed = 0").fetchone()[0]
        prompt_rows = [dict(item) for item in db.execute(
            "SELECT id, title, category, text FROM prompts WHERE trashed = 0 ORDER BY id DESC LIMIT 3"
        ).fetchall()]
        artwork_rows = [dict(item) for item in db.execute(
            "SELECT id, title, collection, notes FROM artworks ORDER BY id DESC LIMIT 3"
        ).fetchall()]
        version_testing = summarize_version_tests([dict(item) for item in db.execute(
            "SELECT parent_prompt_id, version_test_result, version_tested_at FROM prompts WHERE trashed = 0 AND parent_prompt_id IS NOT NULL"
        ).fetchall()])
        prompt_of_day = db.execute(
            "SELECT id, title, category, text FROM prompts WHERE trashed = 0 "
            "ORDER BY favorite DESC, id DESC LIMIT 1 OFFSET ?",
            ((datetime.now().timetuple().tm_yday - 1) % max(prompt_count, 1),),
        ).fetchone() if prompt_count else None

    activity = [
        {"kind": "prompt", "id": item["id"], "title": item["title"],
         "detail": item["category"], "description": item["text"]}
        for item in prompt_rows
    ] + [
        {"kind": "artwork", "id": item["id"], "title": item["title"],
         "detail": item["collection"], "description": item["notes"] or "Saved artwork"}
        for item in artwork_rows
    ]
    activity.sort(key=lambda item: item["id"], reverse=True)
    return {
        "counts": {"prompts": prompt_count, "artworks": artwork_count,
                   "favorites": favorite_count, "to_review": review_count},
        "version_testing": version_testing,
        "prompt_of_day": dict(prompt_of_day) if prompt_of_day else None,
        "recent": activity[:3],
    }


@app.post("/api/prompts")
def create_prompt(payload: PromptPayload) -> dict:
    normalized_text = repair_midjourney_syntax(payload.text.strip())
    try:
        prompt_id = execute(
            "INSERT INTO prompts(title, category, text, favorite, source, reviewed) VALUES (?, ?, ?, ?, 'manual', 1)",
            (payload.title.strip(), payload.category, normalized_text, int(payload.favorite)),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Prompt already exists")
    return {"id": prompt_id, **payload.model_dump(), "text": normalized_text}


@app.put("/api/prompts/{prompt_id}")
def update_prompt(prompt_id: int, payload: PromptPayload) -> dict:
    normalized_text = repair_midjourney_syntax(payload.text.strip())
    try:
        with connect() as db:
            cursor = db.execute(
                "UPDATE prompts SET title = ?, category = ?, text = ?, favorite = ?, reviewed = 1 WHERE id = ?",
                (payload.title.strip(), payload.category, normalized_text, int(payload.favorite), prompt_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Prompt not found")
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="That prompt is already saved")
    return {"id": prompt_id, **payload.model_dump(), "text": normalized_text, "reviewed": True}


@app.post("/api/prompts/bulk-update")
def bulk_update_prompts(payload: PromptBulkPayload) -> dict[str, int]:
    prompt_ids = list(dict.fromkeys(payload.prompt_ids))[:500]
    if not prompt_ids:
        raise HTTPException(status_code=400, detail="Select at least one prompt")
    updates: list[str] = []
    values: list[str | int] = []
    if payload.category is not None:
        updates.append("category = ?")
        values.append(payload.category)
    if payload.reviewed is not None:
        updates.append("reviewed = ?")
        values.append(int(payload.reviewed))
    if payload.favorite is not None:
        updates.append("favorite = ?")
        values.append(int(payload.favorite))
    if not updates:
        raise HTTPException(status_code=400, detail="No changes were requested")
    placeholders = ",".join("?" for _ in prompt_ids)
    with connect() as db:
        cursor = db.execute(
            f"UPDATE prompts SET {', '.join(updates)} WHERE trashed = 0 AND id IN ({placeholders})",
            (*values, *prompt_ids),
        )
    return {"updated": cursor.rowcount}


@app.post("/api/prompts/bulk-delete")
def bulk_delete_prompts(payload: PromptIdsPayload) -> dict[str, int]:
    prompt_ids = list(dict.fromkeys(payload.prompt_ids))[:500]
    if not prompt_ids:
        raise HTTPException(status_code=400, detail="Select at least one prompt")
    placeholders = ",".join("?" for _ in prompt_ids)
    with connect() as db:
        cursor = db.execute(f"UPDATE prompts SET trashed = 1 WHERE trashed = 0 AND id IN ({placeholders})", prompt_ids)
    return {"trashed": cursor.rowcount}


@app.post("/api/prompts/bulk-restore")
def bulk_restore_prompts(payload: PromptIdsPayload) -> dict[str, int]:
    prompt_ids = list(dict.fromkeys(payload.prompt_ids))[:500]
    if not prompt_ids:
        raise HTTPException(status_code=400, detail="Select at least one prompt")
    placeholders = ",".join("?" for _ in prompt_ids)
    with connect() as db:
        cursor = db.execute(f"UPDATE prompts SET trashed = 0 WHERE trashed = 1 AND id IN ({placeholders})", prompt_ids)
    return {"restored": cursor.rowcount}


@app.post("/api/prompts/bulk-repair-midjourney-syntax")
def bulk_repair_prompt_syntax(payload: PromptIdsPayload) -> dict[str, int]:
    prompt_ids = list(dict.fromkeys(payload.prompt_ids))[:500]
    if not prompt_ids:
        raise HTTPException(status_code=400, detail="Select at least one prompt")
    placeholders = ",".join("?" for _ in prompt_ids)
    repaired_count = 0
    skipped_count = 0
    with connect() as db:
        selected = db.execute(
            f"SELECT id, text FROM prompts WHERE trashed = 0 AND id IN ({placeholders})",
            prompt_ids,
        ).fetchall()
        for prompt_id, text in selected:
            repaired = repair_midjourney_syntax(text)
            if repaired == text:
                skipped_count += 1
                continue
            try:
                db.execute(
                    "UPDATE prompts SET text = ?, reviewed = 1 WHERE id = ?",
                    (repaired, prompt_id),
                )
                repaired_count += 1
            except sqlite3.IntegrityError:
                skipped_count += 1
    return {"repaired": repaired_count, "skipped": skipped_count}


@app.post("/api/prompts/export")
def export_prompts(payload: PromptIdsPayload) -> Response:
    prompt_ids = list(dict.fromkeys(payload.prompt_ids))[:500]
    if not prompt_ids:
        raise HTTPException(status_code=400, detail="Select at least one prompt")
    placeholders = ",".join("?" for _ in prompt_ids)
    selected = rows(
        f"SELECT id, title, category, text FROM prompts WHERE trashed = 0 AND id IN ({placeholders})",
        tuple(prompt_ids),
    )
    by_id = {prompt["id"]: prompt for prompt in selected}
    ordered = [by_id[prompt_id] for prompt_id in prompt_ids if prompt_id in by_id]
    if not ordered:
        raise HTTPException(status_code=404, detail="No selected prompts were found")
    filename = f"black-canvas-prompt-pack-{datetime.now().strftime('%Y-%m-%d')}.txt"
    return Response(
        format_prompt_pack(ordered),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.delete("/api/prompts/{prompt_id}")
def delete_prompt(prompt_id: int) -> dict[str, str]:
    with connect() as db:
        cursor = db.execute("UPDATE prompts SET trashed = 1 WHERE trashed = 0 AND id = ?", (prompt_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Prompt not found")
    return {"status": "trashed"}


@app.patch("/api/prompts/{prompt_id}/favorite")
def favorite_prompt(prompt_id: int, favorite: bool) -> dict[str, bool]:
    execute("UPDATE prompts SET favorite = ? WHERE id = ?", (int(favorite), prompt_id))
    return {"favorite": favorite}


@app.patch("/api/prompts/{prompt_id}/repair-midjourney-syntax")
def repair_prompt_syntax(prompt_id: int) -> dict:
    matching = rows(
        "SELECT id, title, category, text, favorite, source, reviewed FROM prompts WHERE id = ?",
        (prompt_id,),
    )
    if not matching:
        raise HTTPException(status_code=404, detail="Prompt not found")
    prompt = matching[0]
    repaired = repair_midjourney_syntax(prompt["text"])
    if repaired == prompt["text"]:
        raise HTTPException(status_code=400, detail="No supported MidJourney syntax issue was found")
    try:
        execute("UPDATE prompts SET text = ?, reviewed = 1 WHERE id = ?", (repaired, prompt_id))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="The repaired prompt would duplicate an existing prompt")
    prompt["text"] = repaired
    prompt["reviewed"] = 1
    prompt["syntax_issues"] = []
    return prompt


@app.post("/api/prompts/{prompt_id}/copy-to-active-midjourney-version")
def copy_prompt_to_active_midjourney_version(prompt_id: int) -> dict:
    matching = rows(
        "SELECT id, title, category, text FROM prompts WHERE trashed = 0 AND id = ?",
        (prompt_id,),
    )
    if not matching:
        raise HTTPException(status_code=404, detail="Prompt not found")
    original = matching[0]
    if not any(issue.startswith("Uses MidJourney v") for issue in midjourney_syntax_issues(original["text"])):
        raise HTTPException(status_code=400, detail="This prompt already uses the active MidJourney version")
    migrated_text = re.sub(
        r"--v\s+[0-9]+(?:\.[0-9]+)?\b",
        f"--v {MIDJOURNEY_RULES['version']}",
        original["text"],
        flags=re.IGNORECASE,
    )
    migrated_text = repair_midjourney_syntax(migrated_text)
    title = f"{original['title']} (MJ v{MIDJOURNEY_RULES['version']})"[:120]
    source_version = re.search(r"--v\s+([0-9]+(?:\.[0-9]+)?)\b", original["text"], flags=re.IGNORECASE).group(1)
    try:
        prompt_id = execute(
            "INSERT INTO prompts(title, category, text, favorite, source, reviewed, parent_prompt_id, migrated_from_version) "
            "VALUES (?, ?, ?, 0, 'manual', 0, ?, ?)",
            (title, original["category"], migrated_text, original["id"], source_version),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="That active-version copy already exists")
    return {"id": prompt_id, "title": title, "category": original["category"], "text": migrated_text,
            "favorite": 0, "source": "manual", "reviewed": 0, "parent_prompt_id": original["id"],
            "migrated_from_version": source_version, "syntax_issues": midjourney_syntax_issues(migrated_text)}


@app.post("/api/prompts/bulk-copy-to-active-midjourney-version")
def bulk_copy_prompts_to_active_midjourney_version(payload: PromptIdsPayload) -> dict[str, int]:
    prompt_ids = list(dict.fromkeys(payload.prompt_ids))
    if not prompt_ids:
        raise HTTPException(status_code=400, detail="Select at least one prompt")
    placeholders = ",".join("?" for _ in prompt_ids)
    copied = 0
    skipped = 0
    with connect() as db:
        selected = db.execute(
            f"SELECT id, title, category, text FROM prompts WHERE trashed = 0 AND id IN ({placeholders})",
            prompt_ids,
        ).fetchall()
        selected_by_id = {prompt["id"]: prompt for prompt in selected}
        for selected_id in prompt_ids:
            original = selected_by_id.get(selected_id)
            if not original or not any(
                issue.startswith("Uses MidJourney v") for issue in midjourney_syntax_issues(original["text"])
            ):
                skipped += 1
                continue
            migrated_text = re.sub(
                r"--v\s+[0-9]+(?:\.[0-9]+)?\b",
                f"--v {MIDJOURNEY_RULES['version']}",
                original["text"],
                flags=re.IGNORECASE,
            )
            migrated_text = repair_midjourney_syntax(migrated_text)
            title = f"{original['title']} (MJ v{MIDJOURNEY_RULES['version']})"[:120]
            source_version = re.search(r"--v\s+([0-9]+(?:\.[0-9]+)?)\b", original["text"], flags=re.IGNORECASE).group(1)
            try:
                db.execute(
                    "INSERT INTO prompts(title, category, text, favorite, source, reviewed, parent_prompt_id, migrated_from_version) "
                    "VALUES (?, ?, ?, 0, 'manual', 0, ?, ?)",
                    (title, original["category"], migrated_text, original["id"], source_version),
                )
                copied += 1
            except sqlite3.IntegrityError:
                skipped += 1
    return {"selected": len(prompt_ids), "copied": copied, "skipped": skipped}


@app.post("/api/prompts/version-reports/export")
def export_prompt_version_reports(payload: PromptIdsPayload) -> Response:
    prompt_ids = list(dict.fromkeys(payload.prompt_ids))
    if not prompt_ids:
        raise HTTPException(status_code=400, detail="Select at least one prompt")
    reports = []
    for prompt_id in prompt_ids:
        try:
            reports.append(format_version_test_report(prompt_version_comparison(prompt_id)))
        except HTTPException as error:
            if error.status_code != 404:
                raise
    if not reports:
        raise HTTPException(status_code=400, detail="Select at least one migrated version copy")
    created = datetime.now().astimezone().strftime("%Y-%m-%d")
    return Response(
        format_version_test_report_collection(reports),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="midjourney-version-tests-{created}.txt"'},
    )


@app.get("/api/prompts/{prompt_id}/version-comparison")
def prompt_version_comparison(prompt_id: int) -> dict:
    copies = rows(
        "SELECT id, title, category, text, parent_prompt_id, migrated_from_version, version_test_result, version_test_notes, version_tested_at FROM prompts "
        "WHERE id = ? AND parent_prompt_id IS NOT NULL",
        (prompt_id,),
    )
    if not copies:
        raise HTTPException(status_code=404, detail="That prompt is not a migrated version copy")
    migrated = copies[0]
    migrated["retest_recommended"] = version_test_needs_retest(migrated)
    originals = rows(
        "SELECT id, title, category, text FROM prompts WHERE id = ?",
        (migrated["parent_prompt_id"],),
    )
    if not originals:
        raise HTTPException(status_code=404, detail="The original prompt is no longer available")
    original = originals[0]
    original_parameters = midjourney_parameter_summary(original["text"])
    migrated_parameters = midjourney_parameter_summary(migrated["text"])
    parameter_changes = [
        {"parameter": name, "original": original_parameters[name], "migrated": migrated_parameters[name]}
        for name in original_parameters
        if original_parameters[name] != migrated_parameters[name]
    ]
    return {
        "original": {**original, "version": migrated["migrated_from_version"]},
        "migrated": {**migrated, "version": MIDJOURNEY_RULES["version"]},
        "creative_body_preserved": strip_midjourney_parameters(original["text"]) == strip_midjourney_parameters(migrated["text"]),
        "parameter_changes": parameter_changes,
        "test_pair": format_version_test_pair(
            original, migrated, str(migrated["migrated_from_version"]), MIDJOURNEY_RULES["version"]
        ),
        "rules_verified_at": MIDJOURNEY_RULES.get("verified_at"),
    }


@app.get("/api/prompts/{prompt_id}/version-report")
def download_prompt_version_report(prompt_id: int) -> Response:
    report = format_version_test_report(prompt_version_comparison(prompt_id))
    return Response(
        report,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="midjourney-version-test-{prompt_id}.txt"'},
    )


@app.patch("/api/prompts/{prompt_id}/version-test-result")
def save_prompt_version_test_result(prompt_id: int, payload: VersionTestResultPayload) -> dict[str, str | None]:
    allowed = {"original", "active", "tie"}
    requested = payload.result.strip().lower()
    if requested not in allowed | {"clear"}:
        raise HTTPException(status_code=400, detail="Choose original, active, tie, or clear")
    result = None if requested == "clear" else requested
    tested_at = datetime.now(timezone.utc).isoformat(timespec="seconds") if result else None
    matching = rows("SELECT id FROM prompts WHERE id = ? AND parent_prompt_id IS NOT NULL", (prompt_id,))
    if not matching:
        raise HTTPException(status_code=404, detail="That prompt is not a migrated version copy")
    execute("UPDATE prompts SET version_test_result = ?, version_tested_at = ? WHERE id = ?", (result, tested_at, prompt_id))
    return {"result": result, "tested_at": tested_at}


@app.patch("/api/prompts/{prompt_id}/version-test-notes")
def save_prompt_version_test_notes(prompt_id: int, payload: VersionTestNotesPayload) -> dict[str, str]:
    notes = payload.notes.strip()
    if len(notes) > 2000:
        raise HTTPException(status_code=400, detail="Keep version-test notes under 2,000 characters")
    matching = rows("SELECT id FROM prompts WHERE id = ? AND parent_prompt_id IS NOT NULL", (prompt_id,))
    if not matching:
        raise HTTPException(status_code=404, detail="That prompt is not a migrated version copy")
    execute("UPDATE prompts SET version_test_notes = ? WHERE id = ?", (notes, prompt_id))
    return {"notes": notes}


@app.get("/api/styles")
def list_styles() -> dict:
    return {item["name"]: json.loads(item["content"]) for item in rows("SELECT name, content FROM styles")}


@app.get("/api/midjourney-rules")
def get_midjourney_rules() -> dict:
    return MIDJOURNEY_RULES


def midjourney_verification_status(today: date | None = None) -> dict:
    today = today or date.today()
    verified_text = str(MIDJOURNEY_RULES.get("verified_at", ""))
    try:
        verified_at = date.fromisoformat(verified_text)
    except ValueError:
        return {"status": "unverified", "label": "Not verified", "today": today.isoformat(), "days_since": None,
                "next_review": None, "version": MIDJOURNEY_RULES["version"]}
    days_since = max((today - verified_at).days, 0)
    if days_since <= 60:
        status, label = "current", "Verified"
    elif days_since <= 90:
        status, label = "due", "Review due"
    else:
        status, label = "overdue", "Review overdue"
    return {
        "status": status,
        "label": label,
        "today": today.isoformat(),
        "days_since": days_since,
        "next_review": (verified_at + timedelta(days=60)).isoformat(),
        "version": MIDJOURNEY_RULES["version"],
    }


@app.get("/api/midjourney-rules/status")
def get_midjourney_verification_status() -> dict:
    return midjourney_verification_status()


@app.put("/api/midjourney-rules")
def save_midjourney_rules(payload: MidJourneyRulesPayload) -> dict:
    version = payload.version.strip()
    raw_parameter = payload.raw_parameter.strip().lower()
    aspect_ratios = list(dict.fromkeys(ratio.strip() for ratio in payload.supported_aspect_ratios if ratio.strip()))
    default_ratio = payload.default_aspect_ratio.strip()
    verified_at = payload.verified_at.strip()
    verification_source = payload.verification_source.strip()
    if not re.fullmatch(r"[1-9][0-9]*(?:\.[0-9]+)?", version):
        raise HTTPException(status_code=400, detail="Use a numeric MidJourney version such as 8.2")
    if not re.fullmatch(r"--[a-z][a-z0-9-]*", raw_parameter):
        raise HTTPException(status_code=400, detail="The raw parameter must look like --raw")
    if not aspect_ratios or any(not re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", ratio) for ratio in aspect_ratios):
        raise HTTPException(status_code=400, detail="Aspect ratios must look like 4:5 or 16:9")
    if default_ratio not in aspect_ratios:
        raise HTTPException(status_code=400, detail="The default aspect ratio must be in the supported list")
    if verified_at and not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", verified_at):
        raise HTTPException(status_code=400, detail="The verification date must use YYYY-MM-DD")
    if verification_source and not re.fullmatch(r"https://[^\s]+", verification_source):
        raise HTTPException(status_code=400, detail="Use an https:// link for the verification source")
    previous = {key: value for key, value in MIDJOURNEY_RULES.items() if key != "previous_rules"}
    updated = {
        "ruleset": f"midjourney-v{version}-custom",
        "version": version,
        "default_aspect_ratio": default_ratio,
        "supported_aspect_ratios": aspect_ratios,
        "raw_parameter": raw_parameter,
        "verified_at": verified_at,
        "verification_source": verification_source,
        "update_note": payload.update_note.strip(),
        "deprecated_parameters": MIDJOURNEY_RULES["deprecated_parameters"],
        "previous_rules": previous,
    }
    apply_midjourney_rules(updated)
    return updated


def apply_midjourney_rules(updated: dict) -> None:
    MIDJOURNEY_RULES_PATH.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    MIDJOURNEY_RULES.clear()
    MIDJOURNEY_RULES.update(updated)
    global DEFAULT_ASPECT_RATIO, SUPPORTED_ASPECT_RATIOS
    DEFAULT_ASPECT_RATIO = updated["default_aspect_ratio"]
    SUPPORTED_ASPECT_RATIOS = set(updated["supported_aspect_ratios"])


@app.post("/api/midjourney-rules/restore-previous")
def restore_previous_midjourney_rules() -> dict:
    previous = MIDJOURNEY_RULES.get("previous_rules")
    if not isinstance(previous, dict):
        raise HTTPException(status_code=400, detail="There is no previous MidJourney ruleset to restore")
    current = {key: value for key, value in MIDJOURNEY_RULES.items() if key != "previous_rules"}
    restored = {**previous, "previous_rules": current}
    apply_midjourney_rules(restored)
    return restored


def restore_midjourney_rules_from_manifest(manifest: dict) -> bool:
    saved_rules = manifest.get("midjourney_rules")
    if not isinstance(saved_rules, dict):
        return False
    save_midjourney_rules(MidJourneyRulesPayload(
        version=str(saved_rules.get("version", "")),
        default_aspect_ratio=str(saved_rules.get("default_aspect_ratio", "")),
        supported_aspect_ratios=saved_rules.get("supported_aspect_ratios") or [],
        raw_parameter=str(saved_rules.get("raw_parameter", "")),
        verified_at=str(saved_rules.get("verified_at", "")),
        verification_source=str(saved_rules.get("verification_source", "")),
        update_note=str(saved_rules.get("update_note", "Restored from backup")),
    ))
    return True


@app.put("/api/styles/{name}")
def save_style(name: str, payload: StylePayload) -> dict[str, str]:
    execute("INSERT OR REPLACE INTO styles(name, content) VALUES (?, ?)", (name, json.dumps(payload.content)))
    return {"status": "saved"}


@app.get("/api/artworks")
def list_artworks() -> list[dict]:
    items = rows("SELECT id, title, collection, tags, notes, favorite, filename, created_at FROM artworks ORDER BY id DESC")
    for item in items:
        item["url"] = f"/uploads/{item['filename']}"
    return items


@app.post("/api/artworks")
def create_artwork(payload: ArtworkPayload) -> dict:
    match = re.fullmatch(r"data:(image/(?:jpeg|png|webp|gif));base64,(.+)", payload.data_url, re.DOTALL)
    if not match:
        raise HTTPException(status_code=400, detail="Unsupported image format")
    image_bytes = base64.b64decode(match.group(2), validate=True)
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image must be smaller than 10 MB")
    extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}[match.group(1)]
    filename = f"{uuid.uuid4().hex}{extension}"
    (UPLOAD_DIR / filename).write_bytes(image_bytes)
    artwork_id = execute(
        "INSERT INTO artworks(title, collection, tags, notes, favorite, filename) VALUES (?, ?, ?, ?, ?, ?)",
        (payload.title.strip(), payload.collection, payload.tags.strip(), payload.notes.strip(), int(payload.favorite), filename),
    )
    return {"id": artwork_id, "url": f"/uploads/{filename}"}


@app.patch("/api/artworks/{artwork_id}/favorite")
def favorite_artwork(artwork_id: int, favorite: bool) -> dict[str, bool]:
    execute("UPDATE artworks SET favorite = ? WHERE id = ?", (int(favorite), artwork_id))
    return {"favorite": favorite}


@app.put("/api/artworks/{artwork_id}")
def update_artwork(artwork_id: int, payload: ArtworkDetailsPayload) -> dict:
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Artwork title is required")
    with connect() as db:
        cursor = db.execute(
            "UPDATE artworks SET title = ?, collection = ?, tags = ?, notes = ? WHERE id = ?",
            (title, payload.collection, payload.tags.strip(), payload.notes.strip(), artwork_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Artwork not found")
    return {"id": artwork_id, "title": title, "collection": payload.collection,
            "tags": payload.tags.strip(), "notes": payload.notes.strip()}


@app.delete("/api/artworks/{artwork_id}")
def delete_artwork(artwork_id: int) -> dict[str, str]:
    with connect() as db:
        item = db.execute("SELECT filename FROM artworks WHERE id = ?", (artwork_id,)).fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="Artwork not found")
        db.execute("DELETE FROM artworks WHERE id = ?", (artwork_id,))
    image_path = UPLOAD_DIR / item["filename"]
    if image_path.exists():
        image_path.unlink()
    return {"status": "removed"}


@app.get("/api/backup")
def download_backup() -> JSONResponse:
    return JSONResponse(
        backup_data(),
        headers={"Content-Disposition": "attachment; filename=blackcanvas-backup.json"},
    )


CHATGPT_IMPORT_CACHE = UPLOAD_DIR.parent / "chatgpt_import_candidates.json"


def chatgpt_candidates(conversations: list[dict]) -> list[dict[str, str | float]]:
    candidates: list[dict[str, str | float]] = []
    seen: set[str] = set()
    for conversation in conversations:
        conversation_title = str(conversation.get("title") or "Untitled conversation")
        for node_id, node in (conversation.get("mapping") or {}).items():
            message = (node or {}).get("message") or {}
            if (message.get("author") or {}).get("role") != "user":
                continue
            parts = (message.get("content") or {}).get("parts") or []
            text = "\n".join(part for part in parts if isinstance(part, str)).strip()
            if len(text) < 20 or text in seen:
                continue
            seen.add(text)
            candidate_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{conversation.get('id', '')}:{node_id}"))
            candidates.append({
                "id": candidate_id,
                "conversation": conversation_title,
                "text": text,
                "created_at": float(message.get("create_time") or 0),
            })
    candidates.sort(key=lambda item: float(item["created_at"]), reverse=True)
    return candidates[:1000]


@app.post("/api/chatgpt/import-preview")
async def preview_chatgpt_export(export_file: UploadFile = File(...)) -> dict:
    try:
        if (export_file.filename or "").lower().endswith(".zip"):
            await export_file.seek(0)
            with zipfile.ZipFile(export_file.file) as archive:
                conversation_names = sorted(
                    name for name in archive.namelist()
                    if re.fullmatch(r"conversations(?:-\d+)?\.json", Path(name).name, flags=re.IGNORECASE)
                )
                if not conversation_names:
                    raise ValueError("Conversation history files were not found in that ZIP")
                history_size = sum(archive.getinfo(name).file_size for name in conversation_names)
                if history_size > 500 * 1024 * 1024:
                    raise ValueError("The conversation history is too large to scan safely")
                conversations = []
                for conversation_name in conversation_names:
                    history_part = json.loads(archive.read(conversation_name))
                    if not isinstance(history_part, list):
                        raise ValueError(f"{conversation_name} does not contain a conversation list")
                    conversations.extend(history_part)
        else:
            raw = await export_file.read(200 * 1024 * 1024 + 1)
            if len(raw) > 200 * 1024 * 1024:
                raise ValueError("That JSON export is too large to scan safely")
            conversations = json.loads(raw)
        if not isinstance(conversations, list):
            raise ValueError("The conversation export is not a list")
    except (ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail=f"Could not read that ChatGPT export: {error}") from error
    candidates = chatgpt_candidates(conversations)
    CHATGPT_IMPORT_CACHE.write_text(json.dumps(candidates), encoding="utf-8")
    return {"count": len(candidates), "candidates": candidates}


@app.get("/api/chatgpt/import-candidates")
def saved_chatgpt_candidates() -> dict:
    if not CHATGPT_IMPORT_CACHE.exists():
        return {"count": 0, "candidates": []}
    candidates = json.loads(CHATGPT_IMPORT_CACHE.read_text(encoding="utf-8"))
    return {"count": len(candidates), "candidates": candidates}


@app.post("/api/chatgpt/import-selected")
def import_chatgpt_prompts(payload: ChatGPTImportPayload) -> dict[str, int]:
    if not CHATGPT_IMPORT_CACHE.exists():
        raise HTTPException(status_code=400, detail="Upload the ChatGPT export first")
    candidates = json.loads(CHATGPT_IMPORT_CACHE.read_text(encoding="utf-8"))
    selected = set(payload.candidate_ids)
    imported = 0
    with connect() as db:
        for candidate in candidates:
            if candidate["id"] not in selected:
                continue
            title = str(candidate["conversation"])[:120]
            cursor = db.execute(
                "INSERT OR IGNORE INTO prompts(title, category, text, favorite, source, reviewed) VALUES (?, ?, ?, 0, 'chatgpt', 0)",
                (title, "ChatGPT Import", repair_midjourney_syntax(str(candidate["text"]).strip())),
            )
            imported += max(cursor.rowcount, 0)
    return {"imported": imported, "selected": len(selected)}


GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
]
GOOGLE_CREDENTIALS = UPLOAD_DIR.parent / "google_credentials.json"
GOOGLE_TOKEN = UPLOAD_DIR.parent / "google_token.json"
GOOGLE_STATE = UPLOAD_DIR.parent / "google_oauth_state.txt"


def google_credentials():
    if not GOOGLE_TOKEN.exists():
        raise HTTPException(status_code=401, detail="Google Drive is not connected")
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    credentials = Credentials.from_authorized_user_file(GOOGLE_TOKEN)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        GOOGLE_TOKEN.write_text(credentials.to_json(), encoding="utf-8")
    if not credentials.valid:
        raise HTTPException(status_code=401, detail="Google Drive connection needs authorization")
    return credentials


@app.get("/api/google/status")
def google_status() -> dict:
    connected = False
    email = None
    if GOOGLE_TOKEN.exists():
        try:
            from googleapiclient.discovery import build

            credentials = google_credentials()
            if credentials.has_scopes(GOOGLE_SCOPES):
                about = build("drive", "v3", credentials=credentials).about().get(fields="user(displayName,emailAddress)").execute()
                email = about.get("user", {}).get("emailAddress")
                connected = True
        except Exception:
            connected = False
    configured = False
    if GOOGLE_CREDENTIALS.exists():
        try:
            saved = json.loads(GOOGLE_CREDENTIALS.read_text(encoding="utf-8"))
            client = saved.get("web") or saved.get("installed") or {}
            configured = bool(client.get("client_id") and client.get("client_secret"))
        except (OSError, ValueError):
            configured = False
    return {"configured": configured, "connected": connected, "email": email}


@app.post("/api/google/backup")
def backup_to_google_drive() -> dict:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaInMemoryUpload

    service = build("drive", "v3", credentials=google_credentials())
    root_id = ensure_google_backup_root(service)
    created_at = datetime.now(timezone.utc)
    timestamp = created_at.strftime("%Y-%m-%d_%H-%M-%S_UTC")
    folder = service.files().create(
        body={
            "name": f"Backup {timestamp}",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [root_id],
            "appProperties": {"blackcanvas_backup_set": "true", "backup_state": "creating"},
        },
        fields="id,name,webViewLink",
    ).execute()
    manifest = backup_data()
    manifest.update({"backup_format": 6, "created_at": created_at.isoformat(), "artwork_file_count": 0})
    uploaded_images = 0
    mime_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
    for artwork in manifest.get("artworks", []):
        image_path = UPLOAD_DIR / artwork["filename"]
        if not image_path.is_file():
            continue
        media = MediaFileUpload(
            str(image_path),
            mimetype=mime_types.get(image_path.suffix.lower(), "application/octet-stream"),
            resumable=True,
        )
        service.files().create(
            body={"name": artwork["filename"], "parents": [folder["id"]], "appProperties": {"blackcanvas_artwork": "true"}},
            media_body=media,
            fields="id",
        ).execute()
        uploaded_images += 1
    manifest["artwork_file_count"] = uploaded_images
    contents = json.dumps(manifest, indent=2).encode("utf-8")
    service.files().create(
        body={"name": "blackcanvas-backup.json", "parents": [folder["id"]], "appProperties": {"blackcanvas_manifest": "true"}},
        media_body=MediaInMemoryUpload(contents, mimetype="application/json", resumable=False),
        fields="id",
    ).execute()
    service.files().update(
        fileId=folder["id"],
        body={"appProperties": {"blackcanvas_backup_set": "true", "backup_state": "complete", "artwork_count": str(uploaded_images)}},
        fields="id",
    ).execute()
    return {
        "status": "backed_up",
        "name": folder["name"],
        "url": folder.get("webViewLink", ""),
        "artwork_files": uploaded_images,
        "prompts": len(manifest.get("prompts", [])),
    }


def ensure_google_backup_root(service) -> str:
    result = service.files().list(
        q="trashed=false and mimeType='application/vnd.google-apps.folder' and appProperties has { key='blackcanvas_backup_root' and value='true' }",
        pageSize=1,
        fields="files(id,name)",
    ).execute()
    if result.get("files"):
        return result["files"][0]["id"]
    folder = service.files().create(
        body={
            "name": "BlackCanvasAI Backups",
            "mimeType": "application/vnd.google-apps.folder",
            "appProperties": {"blackcanvas_backup_root": "true"},
        },
        fields="id",
    ).execute()
    return folder["id"]


@app.get("/api/google/backups")
def list_google_backups() -> dict[str, list[dict]]:
    from googleapiclient.discovery import build

    service = build("drive", "v3", credentials=google_credentials())
    root_id = ensure_google_backup_root(service)
    result = service.files().list(
        q=f"'{root_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder' and appProperties has {{ key='blackcanvas_backup_set' and value='true' }}",
        orderBy="createdTime desc",
        pageSize=25,
        fields="files(id,name,createdTime,webViewLink,appProperties)",
    ).execute()
    backups = [item for item in result.get("files", []) if (item.get("appProperties") or {}).get("backup_state") == "complete"]
    return {"backups": backups}


@app.post("/api/google/restore/{backup_id}")
def restore_google_backup(backup_id: str) -> dict[str, int | str]:
    from googleapiclient.discovery import build

    service = build("drive", "v3", credentials=google_credentials())
    folder = service.files().get(fileId=backup_id, fields="id,name,mimeType,appProperties").execute()
    properties = folder.get("appProperties") or {}
    if folder.get("mimeType") != "application/vnd.google-apps.folder" or properties.get("blackcanvas_backup_set") != "true" or properties.get("backup_state") != "complete":
        raise HTTPException(status_code=400, detail="That is not a complete BlackCanvasAI backup")
    children = service.files().list(
        q=f"'{backup_id}' in parents and trashed=false",
        pageSize=1000,
        fields="files(id,name,mimeType,appProperties)",
    ).execute().get("files", [])
    manifest_file = next((item for item in children if item["name"] == "blackcanvas-backup.json"), None)
    if not manifest_file:
        raise HTTPException(status_code=400, detail="The backup manifest is missing")
    try:
        manifest = json.loads(service.files().get_media(fileId=manifest_file["id"]).execute())
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail="The backup manifest is invalid") from error

    snapshot_root = UPLOAD_DIR.parent / "restore-snapshots"
    snapshot_dir = snapshot_root / datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S-%f_UTC")
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    with connect() as source_db, sqlite3.connect(snapshot_dir / "blackcanvas.db") as snapshot_db:
        source_db.backup(snapshot_db)
    shutil.copy2(MIDJOURNEY_RULES_PATH, snapshot_dir / "midjourney_rules.json")
    if UPLOAD_DIR.exists():
        shutil.copytree(UPLOAD_DIR, snapshot_dir / "uploads")

    restored_prompts = 0
    restored_artworks = 0
    restored_images = 0
    remote_by_name = {item["name"]: item for item in children}
    with connect() as db:
        for prompt in manifest.get("prompts", []):
            cursor = db.execute(
                "INSERT OR IGNORE INTO prompts(title, category, text, favorite, source, reviewed, trashed, parent_prompt_id, migrated_from_version, version_test_result, version_test_notes, version_tested_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    prompt.get("title", "Restored prompt"), prompt.get("category", "Unsorted"),
                    repair_midjourney_syntax(str(prompt.get("text", "")).strip()),
                    int(bool(prompt.get("favorite"))), prompt.get("source", "backup"), int(bool(prompt.get("reviewed", True))),
                    int(bool(prompt.get("trashed", False))),
                    prompt.get("parent_prompt_id"), prompt.get("migrated_from_version"),
                    prompt.get("version_test_result"),
                    str(prompt.get("version_test_notes", ""))[:2000],
                    prompt.get("version_tested_at"),
                ),
            )
            restored_prompts += max(cursor.rowcount, 0)
        for name, content in (manifest.get("styles") or {}).items():
            db.execute("INSERT OR REPLACE INTO styles(name, content) VALUES (?, ?)", (name, json.dumps(content)))
        for artwork in manifest.get("artworks", []):
            filename = Path(str(artwork.get("filename", ""))).name
            if not filename:
                continue
            image_path = UPLOAD_DIR / filename
            remote_image = remote_by_name.get(filename)
            if not image_path.exists() and remote_image:
                image_path.write_bytes(service.files().get_media(fileId=remote_image["id"]).execute())
                restored_images += 1
            existing = db.execute("SELECT id FROM artworks WHERE filename = ?", (filename,)).fetchone()
            if existing or not image_path.exists():
                continue
            db.execute(
                "INSERT INTO artworks(title, collection, tags, notes, favorite, filename, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    artwork.get("title", "Restored artwork"), artwork.get("collection", "Unsorted"), artwork.get("tags", ""),
                    artwork.get("notes", ""), int(bool(artwork.get("favorite"))), filename,
                    artwork.get("created_at") or datetime.now(timezone.utc).isoformat(),
                ),
            )
            restored_artworks += 1
    restored_rules = restore_midjourney_rules_from_manifest(manifest)
    return {
        "status": "restored",
        "prompts": restored_prompts,
        "artworks": restored_artworks,
        "images": restored_images,
        "midjourney_rules": int(restored_rules),
        "safety_snapshot": snapshot_dir.name,
    }


@app.get("/api/google/prompt-files")
def google_prompt_files() -> dict[str, list[dict[str, str]]]:
    from googleapiclient.discovery import build

    service = build("drive", "v3", credentials=google_credentials())
    compatible_types = ["application/vnd.google-apps.document", "text/plain", "text/markdown"]
    type_query = " or ".join(f"mimeType='{mime_type}'" for mime_type in compatible_types)
    result = service.files().list(
        q=f"trashed=false and ({type_query})",
        orderBy="modifiedTime desc",
        pageSize=50,
        fields="files(id,name,mimeType,modifiedTime,webViewLink)",
    ).execute()
    return {"files": result.get("files", [])}


@app.post("/api/google/import-prompt/{file_id}")
def import_google_prompt(file_id: str) -> dict[str, str | bool]:
    from googleapiclient.discovery import build

    service = build("drive", "v3", credentials=google_credentials())
    metadata = service.files().get(fileId=file_id, fields="id,name,mimeType").execute()
    mime_type = metadata.get("mimeType", "")
    if mime_type == "application/vnd.google-apps.document":
        content = service.files().export(fileId=file_id, mimeType="text/plain").execute()
    elif mime_type in {"text/plain", "text/markdown"}:
        content = service.files().get_media(fileId=file_id).execute()
    else:
        raise HTTPException(status_code=400, detail="This file type cannot be imported as a prompt yet")
    prompt_text = repair_midjourney_syntax(content.decode("utf-8", errors="replace").strip())
    if not prompt_text:
        raise HTTPException(status_code=400, detail="That document is empty")
    if len(prompt_text) > 100_000:
        raise HTTPException(status_code=400, detail="That document is too large to import as one prompt")
    title = re.sub(r"\.(txt|md)$", "", metadata["name"], flags=re.IGNORECASE).strip()
    with connect() as db:
        cursor = db.execute(
            "INSERT OR IGNORE INTO prompts(title, category, text, favorite, source, reviewed) VALUES (?, ?, ?, 0, 'drive', 0)",
            (title or "Imported prompt", "Imported", prompt_text),
        )
        imported = cursor.rowcount > 0
    return {"status": "imported" if imported else "already_exists", "title": title, "imported": imported}


@app.get("/api/google/artwork-files")
def google_artwork_files() -> dict[str, list[dict]]:
    from googleapiclient.discovery import build

    result = build("drive", "v3", credentials=google_credentials()).files().list(
        q="trashed=false and mimeType contains 'image/'",
        orderBy="modifiedTime desc",
        pageSize=60,
        fields="files(id,name,mimeType,modifiedTime,size)",
    ).execute()
    supported = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    return {"files": [item for item in result.get("files", []) if item.get("mimeType") in supported]}


@app.get("/api/google/artwork-preview/{file_id}")
def google_artwork_preview(file_id: str) -> Response:
    from googleapiclient.discovery import build

    service = build("drive", "v3", credentials=google_credentials())
    metadata = service.files().get(fileId=file_id, fields="mimeType,size").execute()
    if metadata.get("mimeType") not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        raise HTTPException(status_code=400, detail="Unsupported image format")
    if int(metadata.get("size") or 0) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image must be smaller than 10 MB")
    content = service.files().get_media(fileId=file_id).execute()
    return Response(content=content, media_type=metadata["mimeType"], headers={"Cache-Control": "private, max-age=300"})


@app.post("/api/google/import-artwork/{file_id}")
def import_google_artwork(file_id: str, payload: DriveArtworkPayload) -> dict[str, str | int]:
    from googleapiclient.discovery import build

    service = build("drive", "v3", credentials=google_credentials())
    metadata = service.files().get(fileId=file_id, fields="name,mimeType,size").execute()
    mime_type = metadata.get("mimeType")
    extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
    if mime_type not in extensions:
        raise HTTPException(status_code=400, detail="Unsupported image format")
    if int(metadata.get("size") or 0) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image must be smaller than 10 MB")
    image_bytes = service.files().get_media(fileId=file_id).execute()
    filename = f"{uuid.uuid4().hex}{extensions[mime_type]}"
    (UPLOAD_DIR / filename).write_bytes(image_bytes)
    artwork_id = execute(
        "INSERT INTO artworks(title, collection, tags, notes, favorite, filename) VALUES (?, ?, ?, ?, 0, ?)",
        (payload.title.strip() or metadata["name"], payload.collection, payload.tags.strip(), payload.notes.strip(), filename),
    )
    return {"status": "imported", "id": artwork_id, "url": f"/uploads/{filename}"}


@app.post("/api/google/credentials")
def save_google_credentials(payload: GoogleCredentialsPayload) -> dict[str, str]:
    credentials = payload.credentials
    if "installed" not in credentials and "web" not in credentials:
        raise HTTPException(status_code=400, detail="This is not a Google OAuth client file")
    GOOGLE_CREDENTIALS.write_text(json.dumps(credentials), encoding="utf-8")
    return {"status": "configured"}


@app.post("/api/google/client-id")
def save_google_client_id(payload: GoogleClientPayload) -> dict[str, str]:
    client_id = payload.client_id.strip()
    client_secret = payload.client_secret.strip()
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise HTTPException(status_code=400, detail="Invalid Google OAuth Client ID")
    if not client_secret:
        raise HTTPException(status_code=400, detail="Google OAuth Client Secret is required")
    credentials = {
        "web": {
            "client_id": client_id,
            "project_id": "blackcanvas-local",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": client_secret,
            "redirect_uris": ["http://localhost:8010/google/callback"],
        }
    }
    GOOGLE_CREDENTIALS.write_text(json.dumps(credentials), encoding="utf-8")
    return {"status": "configured"}


@app.get("/google/connect")
def google_connect() -> RedirectResponse:
    if not GOOGLE_CREDENTIALS.exists():
        return RedirectResponse("/connections?setup=needed")
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDENTIALS,
        scopes=GOOGLE_SCOPES,
        autogenerate_code_verifier=True,
    )
    flow.redirect_uri = "http://localhost:8010/google/callback"
    authorization_url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    GOOGLE_STATE.write_text(
        json.dumps({"state": state, "code_verifier": flow.code_verifier}),
        encoding="utf-8",
    )
    return RedirectResponse(authorization_url)


@app.get("/google/callback")
def google_callback(state: str, code: str | None = None, error: str | None = None) -> RedirectResponse:
    if error or not code:
        return RedirectResponse(f"/connections?error={error or 'authorization_cancelled'}")
    if not GOOGLE_STATE.exists():
        raise HTTPException(status_code=400, detail="Google authorization session expired")
    authorization = json.loads(GOOGLE_STATE.read_text(encoding="utf-8"))
    if state != authorization["state"]:
        raise HTTPException(status_code=400, detail="Invalid Google authorization state")
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDENTIALS,
        scopes=GOOGLE_SCOPES,
        state=state,
        code_verifier=authorization["code_verifier"],
    )
    flow.redirect_uri = "http://localhost:8010/google/callback"
    try:
        flow.oauth2session.fetch_token(
            flow.client_config["token_uri"],
            code=code,
            code_verifier=flow.code_verifier,
            client_secret=flow.client_config.get("client_secret"),
            include_client_id=True,
        )
    except Exception as exchange_error:
        (UPLOAD_DIR.parent / "google_oauth_error.txt").write_text(
            f"{type(exchange_error).__name__}: {exchange_error}",
            encoding="utf-8",
        )
        return RedirectResponse("/connections?error=token_exchange_failed")
    GOOGLE_TOKEN.write_text(flow.credentials.to_json(), encoding="utf-8")
    GOOGLE_STATE.unlink(missing_ok=True)
    return RedirectResponse("/connections?connected=true")
