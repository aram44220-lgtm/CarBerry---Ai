try:
    from .themes import THEME_DEFAULT_FONT
except ImportError:
    # pyrefly: ignore [missing-import]
    from themes import THEME_DEFAULT_FONT

ALLOWED_THEMES = {
    "noir_gold", "obsidian_mint", "ivory_editorial", "electric_cobalt", "sandstone"
}

ALLOWED_FONTS = {"editorial", "modern", "clean", "expressive"}

ALLOWED_COMPONENTS: dict[str, set[str]] = {
    "navbar":       {"glass", "minimal", "solid"},
    "hero":         {"split_editorial", "centered_glow", "image_full", "product_focus"},
    "about":        {"minimal", "image_split"},
    "stats":        {"minimal", "cards"},
    "features":     {"bento", "three_up", "icon_rows"},
    "services":     {"stacked", "cards"},
    "gallery":      {"masonry", "grid", "editorial"},
    "testimonials": {"editorial", "cards"},
    "pricing":      {"featured", "clean"},
    "faq":          {"accordion", "split"},
    "cta":          {"luxury", "contrast", "soft"},
    "contact":      {"split", "minimal"},
    "footer":       {"minimal", "rich"},
}

ALLOWED_SITE_TYPES = {
    "restaurant", "portfolio", "saas", "startup", "agency",
    "personal", "ecommerce", "barbershop", "gym", "photography", "landing",
    "salon", "spa", "hotel", "medical", "law", "real_estate",
}

# Recommended section compositions per site type
SITE_TYPE_LAYOUTS: dict[str, list[dict]] = {
    "restaurant": [
        {"type": "navbar",       "variant": "glass"},
        {"type": "hero",         "variant": "image_full"},
        {"type": "about",        "variant": "minimal"},
        {"type": "stats",        "variant": "minimal"},
        {"type": "services",     "variant": "cards"},
        {"type": "gallery",      "variant": "masonry"},
        {"type": "testimonials", "variant": "editorial"},
        {"type": "cta",          "variant": "luxury"},
        {"type": "contact",      "variant": "minimal"},
        {"type": "footer",       "variant": "rich"},
    ],
    "barbershop": [
        {"type": "navbar",       "variant": "solid"},
        {"type": "hero",         "variant": "image_full"},
        {"type": "stats",        "variant": "cards"},
        {"type": "services",     "variant": "stacked"},
        {"type": "gallery",      "variant": "grid"},
        {"type": "testimonials", "variant": "cards"},
        {"type": "cta",          "variant": "contrast"},
        {"type": "contact",      "variant": "split"},
        {"type": "footer",       "variant": "minimal"},
    ],
    "gym": [
        {"type": "navbar",       "variant": "solid"},
        {"type": "hero",         "variant": "split_editorial"},
        {"type": "stats",        "variant": "cards"},
        {"type": "features",     "variant": "three_up"},
        {"type": "services",     "variant": "cards"},
        {"type": "gallery",      "variant": "masonry"},
        {"type": "pricing",      "variant": "featured"},
        {"type": "testimonials", "variant": "cards"},
        {"type": "cta",          "variant": "contrast"},
        {"type": "footer",       "variant": "rich"},
    ],
    "portfolio": [
        {"type": "navbar",       "variant": "minimal"},
        {"type": "hero",         "variant": "centered_glow"},
        {"type": "about",        "variant": "image_split"},
        {"type": "stats",        "variant": "minimal"},
        {"type": "gallery",      "variant": "editorial"},
        {"type": "features",     "variant": "icon_rows"},
        {"type": "testimonials", "variant": "editorial"},
        {"type": "contact",      "variant": "minimal"},
        {"type": "footer",       "variant": "minimal"},
    ],
    "saas": [
        {"type": "navbar",       "variant": "glass"},
        {"type": "hero",         "variant": "centered_glow"},
        {"type": "stats",        "variant": "minimal"},
        {"type": "features",     "variant": "bento"},
        {"type": "testimonials", "variant": "cards"},
        {"type": "pricing",      "variant": "featured"},
        {"type": "faq",          "variant": "accordion"},
        {"type": "cta",          "variant": "contrast"},
        {"type": "footer",       "variant": "rich"},
    ],
    "startup": [
        {"type": "navbar",       "variant": "glass"},
        {"type": "hero",         "variant": "product_focus"},
        {"type": "stats",        "variant": "minimal"},
        {"type": "features",     "variant": "bento"},
        {"type": "gallery",      "variant": "grid"},
        {"type": "pricing",      "variant": "featured"},
        {"type": "cta",          "variant": "contrast"},
        {"type": "footer",       "variant": "rich"},
    ],
    "agency": [
        {"type": "navbar",       "variant": "glass"},
        {"type": "hero",         "variant": "split_editorial"},
        {"type": "stats",        "variant": "minimal"},
        {"type": "services",     "variant": "stacked"},
        {"type": "gallery",      "variant": "masonry"},
        {"type": "testimonials", "variant": "editorial"},
        {"type": "contact",      "variant": "split"},
        {"type": "footer",       "variant": "rich"},
    ],
    "photography": [
        {"type": "navbar",       "variant": "minimal"},
        {"type": "hero",         "variant": "image_full"},
        {"type": "gallery",      "variant": "editorial"},
        {"type": "about",        "variant": "minimal"},
        {"type": "testimonials", "variant": "editorial"},
        {"type": "contact",      "variant": "minimal"},
        {"type": "footer",       "variant": "minimal"},
    ],
    "ecommerce": [
        {"type": "navbar",       "variant": "solid"},
        {"type": "hero",         "variant": "split_editorial"},
        {"type": "stats",        "variant": "cards"},
        {"type": "features",     "variant": "three_up"},
        {"type": "gallery",      "variant": "grid"},
        {"type": "testimonials", "variant": "cards"},
        {"type": "cta",          "variant": "contrast"},
        {"type": "footer",       "variant": "rich"},
    ],
    # Extra types that map to nearest equivalent
    "salon":       None,  # fallback to barbershop
    "spa":         None,
    "hotel":       None,
    "medical":     None,
    "law":         None,
    "real_estate": None,
    "personal": [
        {"type": "navbar",       "variant": "minimal"},
        {"type": "hero",         "variant": "centered_glow"},
        {"type": "about",        "variant": "minimal"},
        {"type": "stats",        "variant": "minimal"},
        {"type": "features",     "variant": "icon_rows"},
        {"type": "contact",      "variant": "minimal"},
        {"type": "footer",       "variant": "minimal"},
    ],
}

DEFAULT_LAYOUT = [
    {"type": "navbar",       "variant": "glass"},
    {"type": "hero",         "variant": "split_editorial"},
    {"type": "features",     "variant": "bento"},
    {"type": "gallery",      "variant": "masonry"},
    {"type": "testimonials", "variant": "editorial"},
    {"type": "cta",          "variant": "luxury"},
    {"type": "footer",       "variant": "minimal"},
]


def validate_plan(plan: dict) -> dict:
    if not isinstance(plan, dict):
        raise ValueError("Plan must be an object")

    site_type = plan.get("site_type", "landing")
    if site_type not in ALLOWED_SITE_TYPES:
        site_type = "landing"

    theme = plan.get("theme", "ivory_editorial")
    if theme not in ALLOWED_THEMES:
        theme = "ivory_editorial"

    font_pair = plan.get("font_pair", "")
    if font_pair not in ALLOWED_FONTS:
        # Use theme's recommended font pair
        font_pair = THEME_DEFAULT_FONT.get(theme, "modern")

    sections = plan.get("sections", [])
    cleaned: list[dict] = []

    if isinstance(sections, list):
        for item in sections:
            if not isinstance(item, dict):
                continue
            typ = item.get("type", "")
            variant = item.get("variant", "")
            if typ not in ALLOWED_COMPONENTS:
                continue
            allowed_variants = ALLOWED_COMPONENTS[typ]
            if variant not in allowed_variants:
                variant = next(iter(allowed_variants))
            cleaned.append({"type": typ, "variant": variant})

    if not cleaned:
        # Map extended site types to nearest equivalent
        _type_alias = {
            "salon": "barbershop", "spa": "restaurant", "hotel": "restaurant",
            "medical": "saas", "law": "agency", "real_estate": "agency",
        }
        layout_key = _type_alias.get(site_type, site_type)
        cleaned = SITE_TYPE_LAYOUTS.get(layout_key, DEFAULT_LAYOUT)

    return {
        "site_type": site_type,
        "theme":     theme,
        "font_pair": font_pair,
        "sections":  cleaned,
        "content":   plan.get("content", {}) or {},
    }
