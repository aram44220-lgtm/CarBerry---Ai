# ══════════════════════════════════════════════════════════════════
#  SITE ENGINE — themes.py
#  5 radically different visual archetypes.
#  Each theme controls: palette, typography pair, geometry tokens
#  (border-radius, button shape, card style), and spacing rhythm.
# ══════════════════════════════════════════════════════════════════

THEMES = {

    # ── 1. NOIR GOLD ─────────────────────────────────────────────
    # Dark luxury. Gold accents. Serif editorial display font.
    # Sharp-ish corners, heavy shadows, thick gold borders on feature elements.
    # Target: barbershop, restaurant, luxury brand, photography.
    "noir_gold": {
        "name": "Noir Gold",
        "fonts": "https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,600;0,700;1,400;1,600&family=DM+Sans:wght@300;400;500;600&display=swap",
        "class_name": "theme-noir-gold",
        "vars": {
            "bg":        "#080806",
            "surface":   "#0f0f0b",
            "surface_2": "#161610",
            "text":      "#f0ead8",
            "muted":     "#8c8472",
            "accent":    "#c9a84c",
            "accent_2":  "#eed98a",
            "border":    "rgba(201,168,76,.15)",
            "shadow":    "0 40px 100px rgba(0,0,0,.55)",
            # Geometry tokens — read by theme CSS overrides in site.css
            "radius_btn": "4px",
            "radius_card": "6px",
            "radius_img":  "4px",
        },
    },

    # ── 2. OBSIDIAN MINT ─────────────────────────────────────────
    # Dark tech / SaaS. Vivid mint/emerald neon accent.
    # Rounded pill buttons, glassy cards, subtle grid background.
    # Target: SaaS, startup, AI product, fintech.
    "obsidian_mint": {
        "name": "Obsidian Mint",
        "fonts": "https://fonts.googleapis.com/css2?family=Manrope:wght@300;400;500;600;700;800&family=Space+Grotesk:wght@400;500;600;700&display=swap",
        "class_name": "theme-obsidian-mint",
        "vars": {
            "bg":        "#060d0b",
            "surface":   "#0c1612",
            "surface_2": "#0f1f19",
            "text":      "#e8faf3",
            "muted":     "#7aaa96",
            "accent":    "#00e89e",
            "accent_2":  "#7fffcf",
            "border":    "rgba(0,232,158,.12)",
            "shadow":    "0 24px 80px rgba(0,232,158,.08)",
            "radius_btn": "999px",
            "radius_card": "20px",
            "radius_img":  "20px",
        },
    },

    # ── 3. IVORY EDITORIAL ───────────────────────────────────────
    # Light luxury. Warm ivory paper. Terracotta/rust accent.
    # Serif display, generous whitespace, zero-radius ("flat") cards.
    # Target: restaurant, agency, architecture, editorial magazine.
    "ivory_editorial": {
        "name": "Ivory Editorial",
        "fonts": "https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400;1,700&family=DM+Sans:wght@300;400;500;600&display=swap",
        "class_name": "theme-ivory-editorial",
        "vars": {
            "bg":        "#f4f0e6",
            "surface":   "#fdfaf2",
            "surface_2": "#e8e2d4",
            "text":      "#141210",
            "muted":     "#6b6560",
            "accent":    "#b84f2a",
            "accent_2":  "#e09278",
            "border":    "rgba(20,18,16,.11)",
            "shadow":    "0 20px 60px rgba(40,30,18,.10)",
            "radius_btn": "0px",
            "radius_card": "0px",
            "radius_img":  "0px",
        },
    },

    # ── 4. ELECTRIC COBALT ───────────────────────────────────────
    # Dark futuristic / cyber. Electric blue-violet accent.
    # Sharp rectangular cards, monospace/geometric font, glowing borders.
    # Target: tech startup, gaming, crypto, software tool.
    "electric_cobalt": {
        "name": "Electric Cobalt",
        "fonts": "https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@300;400;500;600;700&display=swap",
        "class_name": "theme-electric-cobalt",
        "vars": {
            "bg":        "#06080f",
            "surface":   "#0b0e1a",
            "surface_2": "#0f1326",
            "text":      "#eef0ff",
            "muted":     "#8890b0",
            "accent":    "#5b7dff",
            "accent_2":  "#9cb0ff",
            "border":    "rgba(91,125,255,.16)",
            "shadow":    "0 0 60px rgba(91,125,255,.12), 0 30px 80px rgba(0,0,0,.4)",
            "radius_btn": "8px",
            "radius_card": "12px",
            "radius_img":  "10px",
        },
    },

    # ── 5. SANDSTONE ─────────────────────────────────────────────
    # Warm minimalist. Sandy tones, forest green accent.
    # Generous rounded corners, organic feel, humanist sans-serif.
    # Target: portfolio, personal brand, wellness, lifestyle.
    "sandstone": {
        "name": "Sandstone",
        "fonts": "https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700;800&family=DM+Sans:wght@300;400;500;600&display=swap",
        "class_name": "theme-sandstone",
        "vars": {
            "bg":        "#f0ebe0",
            "surface":   "#faf7f0",
            "surface_2": "#e3dac9",
            "text":      "#1e1e18",
            "muted":     "#6d6860",
            "accent":    "#2e5a4a",
            "accent_2":  "#7fad9a",
            "border":    "rgba(30,30,24,.10)",
            "shadow":    "0 20px 56px rgba(40,36,22,.09)",
            "radius_btn": "999px",
            "radius_card": "28px",
            "radius_img":  "28px",
        },
    },
}

FONT_PAIRS = {
    "editorial":   {"display": "Cormorant Garamond", "body": "DM Sans"},
    "modern":      {"display": "Space Grotesk",      "body": "Manrope"},
    "clean":       {"display": "Space Grotesk",      "body": "Inter"},
    "expressive":  {"display": "Syne",               "body": "DM Sans"},
}

# Map theme → recommended font_pair (used by schema validator as default)
THEME_DEFAULT_FONT = {
    "noir_gold":        "editorial",
    "obsidian_mint":    "modern",
    "ivory_editorial":  "editorial",
    "electric_cobalt":  "clean",
    "sandstone":        "expressive",
}
