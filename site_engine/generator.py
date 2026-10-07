import json
import re
import logging
from pathlib import Path
from .schema import validate_plan
from .themes import THEMES, FONT_PAIRS, THEME_DEFAULT_FONT
from .components import COMPONENTS, content

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
PROMPT_PATH = ROOT / "ai_system_prompt.txt"


def get_system_prompt() -> str:
    """Load the AI system prompt from file."""
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are a website design planner. Return ONLY valid JSON with "
            "site_type, theme, font_pair, sections array, and content object. "
            "No HTML, no markdown, no code fences."
        )


def css_vars(theme_name: str, font_pair_name: str) -> str:
    """Generate :root CSS custom properties for the given theme + font pair."""
    theme = THEMES[theme_name]
    # Fallback font pair: use theme default if font_pair_name missing from FONT_PAIRS
    fp_name = font_pair_name if font_pair_name in FONT_PAIRS else THEME_DEFAULT_FONT.get(theme_name, "modern")
    fonts = FONT_PAIRS[fp_name]

    key_map = {
        "bg":        "--bg",
        "surface":   "--surface",
        "surface_2": "--surface-2",
        "text":      "--text",
        "muted":     "--muted",
        "accent":    "--accent",
        "accent_2":  "--accent-2",
        "border":    "--border",
        "shadow":    "--shadow",
        # Geometry tokens
        "radius_btn":  "--radius-btn",
        "radius_card": "--radius-card",
        "radius_img":  "--radius-img",
    }
    lines = [":root {"]
    for k, v in theme["vars"].items():
        css_key = key_map.get(k, f"--{k.replace('_', '-')}")
        lines.append(f"  {css_key}: {v};")
    lines.append(f"  --font-display: '{fonts['display']}', Georgia, serif;")
    lines.append(f"  --font-body: '{fonts['body']}', system-ui, sans-serif;")
    lines.append("}")
    return "\n".join(lines)


def extract_json(raw: str) -> dict:
    """
    Extract and parse JSON from an AI response.
    Handles: clean JSON, JSON inside ```code blocks```, extra leading/trailing text.
    """
    text = raw.strip()

    # Remove markdown code fences
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find first { ... } block
    start = text.find('{')
    if start != -1:
        depth = 0
        end = -1
        for i, ch in enumerate(text[start:], start):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

    raise ValueError(f"Cannot extract valid JSON from AI response: {text[:200]}")


def build_html(plan: dict) -> str:
    plan = validate_plan(plan)
    c = content(plan)

    # Pass theme_name + font_pair into content dict so components can use it
    c["__theme"] = plan["theme"]
    c["__site_type"] = plan["site_type"]

    sections_html: list[str] = []
    for section in plan["sections"]:
        fn = COMPONENTS.get(section["type"])
        if fn:
            try:
                sections_html.append(fn(section["variant"], c))
            except Exception as ex:
                logger.warning("Component %s/%s failed: %s", section["type"], section["variant"], ex)

    theme = THEMES[plan["theme"]]
    root_css = css_vars(plan["theme"], plan["font_pair"])
    base_css = (STATIC / "site.css").read_text(encoding="utf-8")
    js = (STATIC / "site.js").read_text(encoding="utf-8")

    fonts_url = theme["fonts"]
    title_safe = c['brand'].replace('"', '')
    desc_safe  = c['subtitle'][:160].replace('"', '')

    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_safe} — {c['title'][:60]}</title>
<meta name="description" content="{desc_safe}">
<meta property="og:title" content="{title_safe}">
<meta property="og:description" content="{desc_safe}">
<meta name="theme-color" content="{theme['vars']['bg']}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{fonts_url}" rel="stylesheet">
<style>{root_css}
{base_css}</style>
</head>
<body class="{theme['class_name']}">
<div class="page-noise"></div>
<main>
{''.join(sections_html)}
</main>
<script>{js}</script>
</body>
</html>'''


def generate(plan: dict, output_path: str) -> Path:
    """Generate a full HTML file from a plan dict. Returns path to the written file."""
    html = build_html(plan)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
