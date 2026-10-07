from html import escape
try:
    from .images import get_images, resolve_niche
except ImportError:
    from images import get_images, resolve_niche


def e(v):
    return escape(str(v or ""), quote=True)


def _img(url: str, fallback: str = "") -> str:
    """Return url if truthy, else fallback Unsplash URL."""
    return url.strip() if url and url.strip() else fallback


# ──────────────────────────────────────────────────────────────────────────────
#  SECTION HEADING COPY — varies by site_type so each site feels unique
# ──────────────────────────────────────────────────────────────────────────────

_SECTION_COPY = {
    # services section heading: (eyebrow, title_html)
    "services": {
        "restaurant":   ("On the menu",        "Crafted with <em>love.</em>"),
        "barbershop":   ("Our craft",           "Every cut, <em>intentional.</em>"),
        "gym":          ("What we offer",       "Programs built for <em>results.</em>"),
        "portfolio":    ("Services",            "How I can <em>help.</em>"),
        "saas":         ("What's included",     "Everything you need to <em>ship.</em>"),
        "startup":      ("Our product",         "Built for the <em>next wave.</em>"),
        "agency":       ("What we do",          "Full-service, <em>zero fluff.</em>"),
        "photography":  ("Packages",            "Every session, <em>a story.</em>"),
        "ecommerce":    ("Collections",         "Wear what <em>defines you.</em>"),
        "personal":     ("What I do",           "Skills I bring to the <em>table.</em>"),
        "default":      ("What we offer",       "Designed around <em>your edge.</em>"),
    },
    # features section heading
    "features": {
        "restaurant":   ("Why us",              "The difference you can <em>taste.</em>"),
        "barbershop":   ("The experience",      "More than a cut — <em>a ritual.</em>"),
        "gym":          ("Why FORGE",           "Training that <em>transforms.</em>"),
        "portfolio":    ("Capabilities",        "What makes my work <em>different.</em>"),
        "saas":         ("Built for impact",    "Small details. <em>Huge</em> difference."),
        "startup":      ("Product pillars",     "Three things we obsess <em>over.</em>"),
        "agency":       ("Our approach",        "Strategy, design, <em>delivered.</em>"),
        "photography":  ("The process",         "From brief to <em>breathtaking.</em>"),
        "ecommerce":    ("Why we're different", "Quality that <em>speaks.</em>"),
        "personal":     ("Core strengths",      "What makes me <em>different.</em>"),
        "default":      ("Built for impact",    "Small details. <em>Huge</em> difference."),
    },
    # gallery/work heading
    "gallery": {
        "restaurant":   ("The atmosphere",      "A feast for the <em>eyes.</em>"),
        "barbershop":   ("Fresh cuts",          "See the <em>results.</em>"),
        "gym":          ("The facility",        "Built to <em>perform.</em>"),
        "portfolio":    ("Portfolio",           "Work that <em>speaks.</em>"),
        "saas":         ("Product",             "Designed to <em>delight.</em>"),
        "startup":      ("In the wild",         "See it in <em>action.</em>"),
        "agency":       ("Selected work",       "Made to be <em>remembered.</em>"),
        "photography":  ("Gallery",             "Every frame, a <em>feeling.</em>"),
        "ecommerce":    ("The collection",      "Pieces worth <em>wearing.</em>"),
        "personal":     ("My work",             "Projects I'm <em>proud of.</em>"),
        "default":      ("Selected work",       "Made to be <em>remembered.</em>"),
    },
    # testimonials heading
    "testimonials": {
        "restaurant":   ("Guest reviews",       "Words from our <em>guests.</em>"),
        "barbershop":   ("Client love",         "Straight from the <em>chair.</em>"),
        "gym":          ("Member stories",      "Transformations speak <em>louder.</em>"),
        "portfolio":    ("Kind words",          "What clients <em>say.</em>"),
        "saas":         ("Social proof",        "Trusted by <em>the best.</em>"),
        "startup":      ("Early adopters",      "People who bet on <em>us.</em>"),
        "agency":       ("What clients say",    "Trusted by <em>the bold.</em>"),
        "photography":  ("Client love",         "Stories behind the <em>photos.</em>"),
        "ecommerce":    ("Reviews",             "Why they keep coming <em>back.</em>"),
        "personal":     ("Testimonials",        "Colleagues who <em>vouch for me.</em>"),
        "default":      ("What clients say",    "Trusted by <em>the best.</em>"),
    },
}


def _sc(section: str, site_type: str) -> tuple[str, str]:
    """Return (eyebrow, title_html) for a section + site_type combo."""
    d = _SECTION_COPY.get(section, {})
    return d.get(site_type) or d.get("default", ("", ""))


# ──────────────────────────────────────────────────────────────────────────────
#  TESTIMONIALS POOL — per site_type so quotes feel authentic
# ──────────────────────────────────────────────────────────────────────────────

_TESTIMONIALS = {
    "restaurant": [
        ('"Every dish is a memory in the making. The best dining experience in the city."', "Isabella T.", "Food critic, Le Monde"),
        ('"Maison redefined what a dinner out can be. Flawless from first bite to last."', "Marco V.", "Regular guest"),
        ('"The atmosphere, the service, the food — all exceptional. We come every month."', "Claire D.", "Local resident"),
    ],
    "barbershop": [
        ('"Best cut I\'ve had in years. These guys treat it like an art form."', "James L.", "Loyal client, 3 years"),
        ('"The hot towel shave alone is worth the trip. Absolute precision."', "Omar S.", "Weekly visitor"),
        ('"Walked in nervous, walked out confident. Never going anywhere else."', "David K.", "New client"),
    ],
    "gym": [
        ('"Lost 18kg in 5 months. The trainers here genuinely care about your progress."', "Sarah M.", "Member since 2024"),
        ('"Best gym I\'ve ever been to. The community keeps me coming back every day."', "Tom B.", "6-month member"),
        ('"The coaches know their stuff. My performance improved beyond what I thought possible."', "Lisa R.", "Competitive athlete"),
    ],
    "portfolio": [
        ('"Far beyond what I expected. The final product elevated our entire brand."', "Alexandra M.", "Head of Brand, Luxe Co."),
        ('"Delivered exactly what we needed — with craft and intention I rarely see."', "Daniel R.", "Creative Director"),
        ('"Thoughtful, communicative, and the work speaks for itself."', "Sophia K.", "Founder, Studio K"),
    ],
    "saas": [
        ('"Cut our deployment time by 70%. The ROI was visible within the first week."', "Nathan P.", "CTO, Framestack"),
        ('"Finally a tool that does what it says. Our whole team switched within a day."', "Maya L.", "Product Manager"),
        ('"The best SaaS decision we made this year. Support is incredible too."', "Chris W.", "Engineering Lead"),
    ],
    "agency": [
        ('"They didn\'t just design a website — they defined our visual identity."', "Laura B.", "CEO, Meridian Brand"),
        ('"Strategic, creative, and fast. We saw results before launch even finished."', "Kevin T.", "CMO, Rise Group"),
        ('"The rebrand tripled our inbound leads. Worth every penny."', "Priya N.", "Founder, NorthStar"),
    ],
    "default": [
        ('"The difference is in the details. People noticed immediately."', "Alexandra M.", "Head of Brand, Luxe Co."),
        ('"Far from the usual — this feels genuinely crafted with care."', "Daniel R.", "Creative Director"),
        ('"It finally caught up with the brand. Clean, confident, and beautiful."', "Sophia K.", "Founder, Studio K"),
    ],
}


def _quotes(site_type: str) -> list[tuple[str, str, str]]:
    return _TESTIMONIALS.get(site_type) or _TESTIMONIALS["default"]


# ──────────────────────────────────────────────────────────────────────────────
#  CONTENT EXTRACTOR
# ──────────────────────────────────────────────────────────────────────────────

def _is_ru(c: dict) -> bool:
    """Detect Russian language from any content field."""
    text = " ".join(filter(None, [
        c.get("brand", ""), c.get("title", ""),
        c.get("subtitle", ""), c.get("primary_cta", ""),
    ]))
    return bool(any('\u0400' <= ch <= '\u04ff' for ch in text))


def content(plan: dict) -> dict:
    c = plan.get("content", {}) or {}
    site_type = plan.get("site_type", "landing")

    # ── Defaults per site type ──────────────────────────────────────────────
    defaults = {
        "restaurant": {
            "brand": "Maison", "eyebrow": "Est. 2019",
            "title": "Where every plate tells a story",
            "subtitle": "Handcrafted cuisine rooted in tradition, shaped by modern imagination. A dining experience worth returning to.",
            "primary_cta": "Reserve a table", "secondary_cta": "View menu",
            "hero_tag": "Award-winning cuisine",
            "stat1_num": "250+", "stat1_label": "Dishes crafted",
            "stat2_num": "98%",  "stat2_label": "Guest satisfaction",
            "stat3_num": "12",   "stat3_label": "Years of excellence",
            "stat4_num": "8",    "stat4_label": "Chef awards",
            "about_title": "A kitchen driven by obsession",
            "about_body":  "We source every ingredient with the same attention we give every plate. Local farms, seasonal rhythms, and the belief that great food starts before the stove.",
            "cta_title":   "A table awaits you.",
            "cta_body":    "Reserve your evening now — and let the kitchen do the rest.",
        },
        "barbershop": {
            "brand": "EDGE", "eyebrow": "Premium Grooming",
            "title": "Precision cuts. Confident style.",
            "subtitle": "The craft of barbering elevated to an art form. Walk in looking good, walk out feeling exceptional.",
            "primary_cta": "Book appointment", "secondary_cta": "Our services",
            "hero_tag": "Est. 2018",
            "stat1_num": "5000+", "stat1_label": "Satisfied clients",
            "stat2_num": "4.9",   "stat2_label": "Average rating",
            "stat3_num": "15",    "stat3_label": "Expert barbers",
            "stat4_num": "3",     "stat4_label": "City locations",
            "about_title": "Where grooming becomes ritual",
            "about_body":  "Founded by master barbers who believed a haircut should be an experience, not a chore. Every visit is a ceremony — hot towel, sharp blade, and the perfect finish.",
            "cta_title":   "Your next great cut is one click away.",
            "cta_body":    "Book your appointment online in under 60 seconds.",
        },
        "gym": {
            "brand": "FORGE", "eyebrow": "Elite Fitness",
            "title": "Build the body. Shape the mind.",
            "subtitle": "State-of-the-art equipment, expert coaching, and a community that pushes you beyond your limits every single day.",
            "primary_cta": "Start free trial", "secondary_cta": "View plans",
            "hero_tag": "7-day free trial",
            "stat1_num": "2000+", "stat1_label": "Active members",
            "stat2_num": "50+",   "stat2_label": "Weekly classes",
            "stat3_num": "20",    "stat3_label": "Expert trainers",
            "stat4_num": "98%",   "stat4_label": "Member retention",
            "about_title": "Forged from the ground up",
            "about_body":  "FORGE was built by athletes who were tired of gyms that look premium but train average. We invested in the equipment, the coaches, and the culture — because all three matter.",
            "cta_title":   "Start strong. Start free.",
            "cta_body":    "7 days. No card required. Come see what training actually feels like.",
        },
        "portfolio": {
            "brand": "FOLIO", "eyebrow": "Creative work",
            "title": "Design that speaks before you do",
            "subtitle": "Selected projects spanning brand identity, digital products, and visual storytelling — built with care and intent.",
            "primary_cta": "See my work", "secondary_cta": "Get in touch",
            "hero_tag": "Available for projects",
            "stat1_num": "48",  "stat1_label": "Projects shipped",
            "stat2_num": "30+", "stat2_label": "Happy clients",
            "stat3_num": "6",   "stat3_label": "Years experience",
            "stat4_num": "12",  "stat4_label": "Awards received",
            "about_title": "Rooted in craft, driven by results",
            "about_body":  "I believe great design solves real problems — and looks stunning doing it. Before touching a pixel, I listen. To your goals, your users, and the nuances of your market.",
            "cta_title":   "Let's make something remarkable.",
            "cta_body":    "Open for new projects. Drop me a message and we'll talk.",
        },
        "saas": {
            "brand": "Launchpad", "eyebrow": "New in 2026",
            "title": "Ship faster. Scale smarter.",
            "subtitle": "The all-in-one platform that gets your product to market in days, not months. Built for modern teams who move fast.",
            "primary_cta": "Start free", "secondary_cta": "See how it works",
            "hero_tag": "No credit card required",
            "stat1_num": "10k+",  "stat1_label": "Teams onboarded",
            "stat2_num": "99.9%", "stat2_label": "Uptime SLA",
            "stat3_num": "3×",    "stat3_label": "Faster delivery",
            "stat4_num": "$0",    "stat4_label": "To get started",
            "about_title": "Built for teams that ship",
            "about_body":  "We spent three years inside fast-moving startups watching great ideas die in slow tools. Launchpad exists to close that gap — fast deploys, clean APIs, and zero overhead.",
            "cta_title":   "Start shipping in minutes.",
            "cta_body":    "Free forever on the starter plan. No card, no friction, no catch.",
        },
        "startup": {
            "brand": "Nexus", "eyebrow": "Backed by top VCs",
            "title": "The future of work starts here",
            "subtitle": "We're reimagining how teams collaborate, create, and ship — powered by AI and built for the next decade.",
            "primary_cta": "Join the waitlist", "secondary_cta": "Learn more",
            "hero_tag": "Series A funded",
            "stat1_num": "50k+", "stat1_label": "Early adopters",
            "stat2_num": "$12M", "stat2_label": "Raised",
            "stat3_num": "40+",  "stat3_label": "Team members",
            "stat4_num": "2×",   "stat4_label": "MoM growth",
            "about_title": "A team obsessed with what's next",
            "about_body":  "We came from Google, Stripe, and Figma — and we built Nexus because we couldn't find the tool we wanted. Now 50,000 early adopters agree it was worth the wait.",
            "cta_title":   "Be first in line.",
            "cta_body":    "Join the waitlist today and get early access when we launch publicly in Q1.",
        },
        "agency": {
            "brand": "STUDIO", "eyebrow": "Creative agency",
            "title": "We craft brands people remember",
            "subtitle": "From strategy to execution, we build visual identities that make a lasting mark in competitive markets.",
            "primary_cta": "Start a project", "secondary_cta": "Our work",
            "hero_tag": "10+ years crafting",
            "stat1_num": "120+", "stat1_label": "Brands launched",
            "stat2_num": "4.9",  "stat2_label": "Client rating",
            "stat3_num": "18",   "stat3_label": "Countries served",
            "stat4_num": "7",    "stat4_label": "Awards won",
            "about_title": "Craft-first, results-driven",
            "about_body":  "We're a boutique agency that refuses to be a production line. Every project gets our full attention — from the first brief to the final pixel.",
            "cta_title":   "Ready to stand out?",
            "cta_body":    "Tell us about your project. We respond within 24 hours.",
        },
        "photography": {
            "brand": "LENS", "eyebrow": "Visual storytelling",
            "title": "Every frame, a feeling",
            "subtitle": "Capturing moments that live forever. Editorial, commercial, and portrait photography with a distinct point of view.",
            "primary_cta": "View portfolio", "secondary_cta": "Book a session",
            "hero_tag": "Booking open",
            "stat1_num": "800+", "stat1_label": "Sessions completed",
            "stat2_num": "15",   "stat2_label": "Publications featured",
            "stat3_num": "100%", "stat3_label": "Client satisfaction",
            "stat4_num": "8",    "stat4_label": "Years shooting",
            "about_title": "A photographer who listens first",
            "about_body":  "I don't just show up and shoot. I spend time understanding what a photo needs to communicate — and then I make sure it says exactly that.",
            "cta_title":   "Let's create something timeless.",
            "cta_body":    "Book your session now. Slots fill up 4–6 weeks in advance.",
        },
        "ecommerce": {
            "brand": "VAULT", "eyebrow": "New collection",
            "title": "Wear what defines you",
            "subtitle": "Curated essentials and statement pieces for those who understand that style is a language, not a trend.",
            "primary_cta": "Shop now", "secondary_cta": "Explore collection",
            "hero_tag": "Free shipping over $50",
            "stat1_num": "500+",  "stat1_label": "Premium items",
            "stat2_num": "40k+",  "stat2_label": "Happy customers",
            "stat3_num": "4.8",   "stat3_label": "Average rating",
            "stat4_num": "Free",  "stat4_label": "Returns & exchanges",
            "about_title": "Curation over quantity",
            "about_body":  "We don't carry everything. We carry the right things — selected by our team for quality, longevity, and that feeling when you put it on for the first time.",
            "cta_title":   "Style is a decision.",
            "cta_body":    "Free shipping on every order over $50. Free returns, always.",
        },
        "personal": {
            "brand": "SELF", "eyebrow": "Hello, I'm",
            "title": "Building the web with purpose",
            "subtitle": "Developer, creator, and problem-solver. I build clean, fast, and accessible digital experiences that users love.",
            "primary_cta": "Download CV", "secondary_cta": "My projects",
            "hero_tag": "Open to opportunities",
            "stat1_num": "5",    "stat1_label": "Years experience",
            "stat2_num": "30+",  "stat2_label": "Projects delivered",
            "stat3_num": "10k+", "stat3_label": "GitHub stars",
            "stat4_num": "15+",  "stat4_label": "Technologies",
            "about_title": "Code with intention",
            "about_body":  "I care about the craft behind every line of code — not just shipping features, but building systems that are fast, accessible, and a joy to maintain.",
            "cta_title":   "Let's build something great.",
            "cta_body":    "Currently available for freelance and full-time opportunities.",
        },
    }

    d = defaults.get(site_type, defaults["agency"])

    # ── Smart images via images.py ──────────────────────────────────────────
    image_topic = c.get("image_topic", "")
    brand_hint  = c.get("brand", d.get("brand", ""))
    title_hint  = c.get("title", d.get("title", ""))
    smart_imgs  = get_images(
        image_topic=image_topic,
        site_type=site_type,
        brand=brand_hint,
        title=title_hint,
        count=6,
    )

    # ── Legacy img_pool kept only as dead-code reference ─ not used ─────────
    _img_pool_unused = {
        "restaurant": [
            "https://images.unsplash.com/photo-1414235077428-338989a2e8c0?auto=format&fit=crop&w=1600&q=85",
            "https://images.unsplash.com/photo-1504674900247-0877df9cc836?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1466978913421-dad2ebd01d17?auto=format&fit=crop&w=1200&q=85",
        ],
        "barbershop": [
            "https://images.unsplash.com/photo-1585747860715-2ba37e788b70?auto=format&fit=crop&w=1600&q=85",
            "https://images.unsplash.com/photo-1503951914875-452162b0f3f1?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1621605815971-fbc98d665033?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1534297635766-a262cdcb8ee4?auto=format&fit=crop&w=1200&q=85",
        ],
        "gym": [
            "https://images.unsplash.com/photo-1534438327276-14e5300c3a48?auto=format&fit=crop&w=1600&q=85",
            "https://images.unsplash.com/photo-1571902943202-507ec2618e8f?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1583454110551-21f2fa2afe61?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1549060279-7e168fcee0c2?auto=format&fit=crop&w=1200&q=85",
        ],
        "portfolio": [
            "https://images.unsplash.com/photo-1524758631624-e2822e304c36?auto=format&fit=crop&w=1600&q=85",
            "https://images.unsplash.com/photo-1497366754035-f200968a6e72?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1467232004584-a241de8bcf5d?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?auto=format&fit=crop&w=1200&q=85",
        ],
        "saas": [
            "https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=1600&q=85",
            "https://images.unsplash.com/photo-1460925895917-afdab827c52f?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1504868584819-f8e8b4b6d7e3?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1498050108023-c5249f4df085?auto=format&fit=crop&w=1200&q=85",
        ],
        "startup": [
            "https://images.unsplash.com/photo-1553877522-43269d4ea984?auto=format&fit=crop&w=1600&q=85",
            "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1497366216548-37526070297c?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1528747045269-390fe33c19f2?auto=format&fit=crop&w=1200&q=85",
        ],
        "agency": [
            "https://images.unsplash.com/photo-1497366811353-6870744d04b2?auto=format&fit=crop&w=1600&q=85",
            "https://images.unsplash.com/photo-1541746972996-4e0b0f43e02a?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1564069114553-7215e1ff1890?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1556742049-0cfed4f6a45d?auto=format&fit=crop&w=1200&q=85",
        ],
        "photography": [
            "https://images.unsplash.com/photo-1452587925148-ce544e77e70d?auto=format&fit=crop&w=1600&q=85",
            "https://images.unsplash.com/photo-1516035069371-29a1b244cc32?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1542038784456-1ea8e935640e?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1500051638674-ff996a0ec29e?auto=format&fit=crop&w=1200&q=85",
        ],
        "ecommerce": [
            "https://images.unsplash.com/photo-1441986300917-64674bd600d8?auto=format&fit=crop&w=1600&q=85",
            "https://images.unsplash.com/photo-1490481651871-ab68de25d43d?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=1200&q=85",
            "https://images.unsplash.com/photo-1542291026-7eec264c27ff?auto=format&fit=crop&w=1200&q=85",
        ],
    }
    # Use smart images (override with AI-provided URLs if given)
    ai_img  = c.get("image", "")
    ai_img2 = c.get("image2", "")
    img1 = _img(ai_img,  smart_imgs[0])
    img2 = _img(ai_img2, smart_imgs[1])

    return {
        "brand":         c.get("brand")         or d["brand"],
        "eyebrow":       c.get("eyebrow")       or d["eyebrow"],
        "title":         c.get("title")         or d["title"],
        "subtitle":      c.get("subtitle")      or d["subtitle"],
        "primary_cta":   c.get("primary_cta")   or d["primary_cta"],
        "secondary_cta": c.get("secondary_cta") or d["secondary_cta"],
        "hero_tag":      c.get("hero_tag")      or d.get("hero_tag", ""),
        "stat1_num":     c.get("stat1_num")     or d.get("stat1_num", ""),
        "stat1_label":   c.get("stat1_label")   or d.get("stat1_label", ""),
        "stat2_num":     c.get("stat2_num")     or d.get("stat2_num", ""),
        "stat2_label":   c.get("stat2_label")   or d.get("stat2_label", ""),
        "stat3_num":     c.get("stat3_num")     or d.get("stat3_num", ""),
        "stat3_label":   c.get("stat3_label")   or d.get("stat3_label", ""),
        "stat4_num":     c.get("stat4_num")     or d.get("stat4_num", ""),
        "stat4_label":   c.get("stat4_label")   or d.get("stat4_label", ""),
        "email":         c.get("email")         or "hello@example.com",
        "phone":         c.get("phone")         or "+1 (555) 000-0000",
        "location":      c.get("location")      or "New York · United States",
        "image":  img1,
        "image2": img2,
        "image3": smart_imgs[2] if len(smart_imgs) > 2 else img1,
        "image4": smart_imgs[3] if len(smart_imgs) > 3 else img2,
        # Feature content
        "feat1_title": c.get("feat1_title") or "Precision craft",
        "feat1_body":  c.get("feat1_body")  or "Every detail is considered — from spacing to interactions.",
        "feat2_title": c.get("feat2_title") or "Built to scale",
        "feat2_body":  c.get("feat2_body")  or "Foundations that grow with your ambition, never against it.",
        "feat3_title": c.get("feat3_title") or "Fast by default",
        "feat3_body":  c.get("feat3_body")  or "Optimised from the ground up. No bloat, no compromise.",
        "feat4_title": c.get("feat4_title") or "Fully responsive",
        "feat4_body":  c.get("feat4_body")  or "Looks and works perfectly across every screen size.",
        # Service content
        "svc1_title": c.get("svc1_title") or "Strategy",
        "svc1_body":  c.get("svc1_body")  or "Research-backed direction that cuts through noise.",
        "svc2_title": c.get("svc2_title") or "Design",
        "svc2_body":  c.get("svc2_body")  or "Interfaces that balance utility with distinct personality.",
        "svc3_title": c.get("svc3_title") or "Development",
        "svc3_body":  c.get("svc3_body")  or "Clean, maintainable code shipped with care.",
        "svc4_title": c.get("svc4_title") or "Launch",
        "svc4_body":  c.get("svc4_body")  or "From zero to live, without the usual chaos.",
        # FAQ
        "q1": c.get("q1") or "How does this work?",
        "a1": c.get("a1") or "We start with a discovery call to understand your goals, then move through design and build phases with regular checkpoints.",
        "q2": c.get("q2") or "How long does a project take?",
        "a2": c.get("a2") or "Most projects are completed in 4–8 weeks depending on scope and complexity.",
        "q3": c.get("q3") or "Do you offer revisions?",
        "a3": c.get("a3") or "Yes — we include two rounds of revisions in every engagement, with additional rounds available.",
        # About & CTA
        "about_title": c.get("about_title") or d.get("about_title") or "Rooted in craft, driven by results",
        "about_body":  c.get("about_body")  or d.get("about_body")  or "We believe great work comes from deep understanding.",
        "cta_title":   c.get("cta_title")   or d.get("cta_title")   or "Make the first impression count.",
        "cta_body":    c.get("cta_body")    or d.get("cta_body")    or "Turn your idea into something people can actually feel.",
        "year": "2026",
        # Language + site meta
        "__lang":      "ru" if _is_ru(c) else "en",
        "__site_type": plan.get("site_type", "landing"),
        "__theme":     plan.get("theme", ""),
        # AI-generated testimonials (used if present)
        "t1_quote": c.get("t1_quote", ""),
        "t1_name":  c.get("t1_name",  ""),
        "t1_role":  c.get("t1_role",  ""),
        "t2_quote": c.get("t2_quote", ""),
        "t2_name":  c.get("t2_name",  ""),
        "t2_role":  c.get("t2_role",  ""),
        "t3_quote": c.get("t3_quote", ""),
        "t3_name":  c.get("t3_name",  ""),
        "t3_role":  c.get("t3_role",  ""),
        # AI-generated pricing
        "p1_name": c.get("p1_name", ""), "p1_price": c.get("p1_price", ""),
        "p1_desc": c.get("p1_desc", ""), "p1_feats": c.get("p1_feats", ""),
        "p2_name": c.get("p2_name", ""), "p2_price": c.get("p2_price", ""),
        "p2_desc": c.get("p2_desc", ""), "p2_feats": c.get("p2_feats", ""),
        "p3_name": c.get("p3_name", ""), "p3_price": c.get("p3_price", ""),
        "p3_desc": c.get("p3_desc", ""), "p3_feats": c.get("p3_feats", ""),
    }


# ──────────────────────────────────────────────────────────────────────────────
#  NAVBAR
# ──────────────────────────────────────────────────────────────────────────────

def navbar(variant: str, c: dict) -> str:
    ru = c.get("__lang") == "ru"
    nav_about    = "О нас" if ru else "About"
    nav_services = "Услуги" if ru else "Services"
    nav_work     = "Портфолио" if ru else "Work"
    nav_contact  = "Контакты" if ru else "Contact"
    links = (
        f'<a href="#about">{nav_about}</a>'
        f'<a href="#services">{nav_services}</a>'
        f'<a href="#work">{nav_work}</a>'
        f'<a href="#contact">{nav_contact}</a>'
    )
    burger = '<button class="menu-toggle" aria-label="Open menu" aria-expanded="false"><span></span><span></span><span></span></button>'

    if variant == "solid":
        return f'''<header class="site-section navbar navbar--solid">
  <div class="container nav-wrap">
    <a class="brand" href="#">{e(c['brand'])}</a>
    <nav class="nav-links">{links}</nav>
    <a class="button button--small button--primary nav-cta" href="#contact">{e(c['primary_cta'])}</a>
    {burger}
  </div>
</header>'''

    if variant == "minimal":
        return f'''<header class="site-section navbar navbar--minimal">
  <div class="container nav-wrap">
    <a class="brand" href="#">{e(c['brand'])}</a>
    <nav class="nav-links">{links}</nav>
    <a class="button button--small button--ghost nav-cta" href="#contact">{e(c['primary_cta'])}</a>
    {burger}
  </div>
</header>'''

    # glass (default)
    return f'''<header class="site-section navbar navbar--glass">
  <div class="container nav-wrap">
    <a class="brand" href="#">{e(c['brand'])}</a>
    <nav class="nav-links">{links}</nav>
    <a class="button button--small button--outline nav-cta" href="#contact">{e(c['primary_cta'])}</a>
    {burger}
  </div>
</header>'''


# ──────────────────────────────────────────────────────────────────────────────
#  HERO
# ──────────────────────────────────────────────────────────────────────────────

def hero(variant: str, c: dict) -> str:
    if variant == "centered_glow":
        tag_html = f'<div class="hero-tag">{e(c["hero_tag"])}</div>' if c.get("hero_tag") else ""
        return f'''<section class="site-section hero hero--centered section-pad">
  <div class="ambient ambient--one"></div><div class="ambient ambient--two"></div>
  <div class="container hero-center">
    {tag_html}
    <div class="eyebrow">{e(c['eyebrow'])}</div>
    <h1>{e(c['title'])}</h1>
    <p>{e(c['subtitle'])}</p>
    <div class="button-row">
      <a class="button button--primary" href="#contact">{e(c['primary_cta'])}</a>
      <a class="button button--ghost" href="#about">{e(c['secondary_cta'])}</a>
    </div>
    <div class="hero-orbit">
      <div class="orbit-card orbit-card--a">&#9679; {e(c['stat1_num'])} {e(c['stat1_label'])}</div>
      <div class="orbit-card orbit-card--b">&#10022; {e(c['stat2_num'])} {e(c['stat2_label'])}</div>
      <div class="orbit-card orbit-card--c">{e(c['hero_tag'] or 'Premium quality')}</div>
    </div>
  </div>
</section>'''

    if variant == "image_full":
        return f'''<section class="site-section hero hero--full" style="--hero-image:url('{e(c['image'])}')">
  <div class="hero-full-overlay"></div>
  <div class="container hero-full-inner">
    <div class="eyebrow">{e(c['eyebrow'])}</div>
    <h1>{e(c['title'])}</h1>
    <p>{e(c['subtitle'])}</p>
    <div class="button-row">
      <a class="button button--primary" href="#contact">{e(c['primary_cta'])}</a>
      <a class="button button--outline" href="#about" style="color:#fff;border-color:rgba(255,255,255,.4)">{e(c['secondary_cta'])}</a>
    </div>
  </div>
</section>'''

    if variant == "product_focus":
        return f'''<section class="site-section hero hero--product section-pad">
  <div class="container product-hero-grid">
    <div class="hero-copy">
      <div class="eyebrow">{e(c['eyebrow'])}</div>
      <h1>{e(c['title'])}</h1>
      <p>{e(c['subtitle'])}</p>
      <div class="button-row">
        <a class="button button--primary" href="#contact">{e(c['primary_cta'])}</a>
        <a class="button button--ghost" href="#about">{e(c['secondary_cta'])}</a>
      </div>
      <div class="hero-meta">
        <span>&#9679; {e(c['stat1_num'])} {e(c['stat1_label'])}</span>
        <span>&#10022; {e(c['stat2_num'])} {e(c['stat2_label'])}</span>
      </div>
    </div>
    <div class="product-stage">
      <div class="stage-glow"></div>
      <img src="{e(c['image'])}" alt="{e(c['brand'])} showcase" loading="eager" onerror="this.style.opacity='0.4'"/>
    </div>
  </div>
</section>'''

    # default: split_editorial
    return f'''<section class="site-section hero hero--split section-pad">
  <div class="container split-grid">
    <div class="hero-copy">
      <div class="eyebrow">{e(c['eyebrow'])}</div>
      <h1>{e(c['title'])}</h1>
      <p>{e(c['subtitle'])}</p>
      <div class="button-row">
        <a class="button button--primary" href="#contact">{e(c['primary_cta'])}</a>
        <a class="button button--ghost" href="#about">{e(c['secondary_cta'])}</a>
      </div>
      <div class="hero-meta">
        <span>&#9679; {e(c['stat1_num'])} {e(c['stat1_label'])}</span>
        <span>&#10022; {e(c['hero_tag'] or c['stat2_num'] + ' ' + c['stat2_label'])}</span>
      </div>
    </div>
    <div class="hero-media">
      <div class="media-card">
        <img src="{e(c['image'])}" alt="{e(c['brand'])}" loading="eager" onerror="this.style.opacity='0.4'"/>
      </div>
      <div class="float-chip">&#10003; {e(c['hero_tag'] or 'Trusted worldwide')}</div>
    </div>
  </div>
</section>'''


# ──────────────────────────────────────────────────────────────────────────────
#  ABOUT
# ──────────────────────────────────────────────────────────────────────────────

def about(variant: str, c: dict) -> str:
    site_type = c.get("__site_type", "landing")

    if variant == "image_split":
        return f'''<section id="about" class="site-section section-pad">
  <div class="container about-split">
    <div class="about-img">
      <img src="{e(c['image2'])}" alt="About {e(c['brand'])}" onerror="this.style.opacity='0.3'"/>
    </div>
    <div class="about-copy">
      <div class="eyebrow">Our story</div>
      <h2>{e(c['about_title'])}</h2>
      <p>{e(c['about_body'])}</p>
      <div class="about-stats">
        <div class="about-stat"><strong>{e(c['stat1_num'])}</strong><span>{e(c['stat1_label'])}</span></div>
        <div class="about-stat"><strong>{e(c['stat2_num'])}</strong><span>{e(c['stat2_label'])}</span></div>
        <div class="about-stat"><strong>{e(c['stat3_num'])}</strong><span>{e(c['stat3_label'])}</span></div>
      </div>
      <a class="button button--primary" href="#contact">{e(c['primary_cta'])}</a>
    </div>
  </div>
</section>'''

    # minimal (default)
    return f'''<section id="about" class="site-section section-pad">
  <div class="container">
    <div class="section-head">
      <div>
        <div class="eyebrow">Who we are</div>
        <h2>{e(c['about_title'])}</h2>
      </div>
      <p>{e(c['about_body'])}</p>
    </div>
  </div>
</section>'''


# ──────────────────────────────────────────────────────────────────────────────
#  STATS
# ──────────────────────────────────────────────────────────────────────────────

def stats(variant: str, c: dict) -> str:
    nums = [
        (c['stat1_num'], c['stat1_label']),
        (c['stat2_num'], c['stat2_label']),
        (c['stat3_num'], c['stat3_label']),
        (c['stat4_num'], c['stat4_label']),
    ]
    if variant == "cards":
        inner = ''.join(
            f'<div class="stat stat--card"><strong>{e(n)}</strong><span>{e(l)}</span></div>'
            for n, l in nums if n
        )
        return f'<section class="site-section stats section-pad-small"><div class="container stats-grid stats--cards">{inner}</div></section>'

    inner = ''.join(
        f'<div class="stat"><strong>{e(n)}</strong><span>{e(l)}</span></div>'
        for n, l in nums if n
    )
    return f'<section class="site-section stats section-pad-small"><div class="container stats-grid">{inner}</div></section>'


# ──────────────────────────────────────────────────────────────────────────────
#  FEATURES
# ──────────────────────────────────────────────────────────────────────────────

def features(variant: str, c: dict) -> str:
    site_type = c.get("__site_type", "landing")
    eyebrow_txt, title_html = _sc("features", site_type)

    cards = [
        ("01", c['feat1_title'], c['feat1_body']),
        ("02", c['feat2_title'], c['feat2_body']),
        ("03", c['feat3_title'], c['feat3_body']),
        ("04", c['feat4_title'], c['feat4_body']),
    ]

    if variant == "three_up":
        cards3 = cards[:3]
        html = ''.join(
            f'<article class="feature-card"><div class="feature-num">{a}</div><h3>{e(b)}</h3><p>{e(d)}</p><span class="feature-arrow">&#8599;</span></article>'
            for a, b, d in cards3
        )
        return f'''<section class="site-section section-pad">
  <div class="container">
    <div class="section-head"><div><div class="eyebrow">{e(eyebrow_txt)}</div><h2>{title_html}</h2></div><p>Every element is crafted to convert — not just to look good.</p></div>
    <div class="feature-grid feature-grid--three_up">{html}</div>
  </div>
</section>'''

    if variant == "icon_rows":
        rows = ''.join(
            f'<div class="icon-row"><div class="icon-num">{a}</div><div class="icon-row-body"><h3>{e(b)}</h3><p>{e(d)}</p></div><span class="icon-row-arrow">&#8599;</span></div>'
            for a, b, d in cards
        )
        return f'''<section class="site-section section-pad">
  <div class="container">
    <div class="section-head"><div><div class="eyebrow">{e(eyebrow_txt)}</div><h2>{title_html}</h2></div></div>
    <div class="icon-rows">{rows}</div>
  </div>
</section>'''

    # bento (default)
    html = ''.join(
        f'<article class="feature-card"><div class="feature-num">{a}</div><h3>{e(b)}</h3><p>{e(d)}</p><span class="feature-arrow">&#8599;</span></article>'
        for a, b, d in cards
    )
    return f'''<section class="site-section section-pad">
  <div class="container">
    <div class="section-head"><div><div class="eyebrow">{e(eyebrow_txt)}</div><h2>{title_html}</h2></div><p>Every element is designed to convert — not just to look good.</p></div>
    <div class="feature-grid feature-grid--bento">{html}</div>
  </div>
</section>'''


# ──────────────────────────────────────────────────────────────────────────────
#  SERVICES
# ──────────────────────────────────────────────────────────────────────────────

def services(variant: str, c: dict) -> str:
    site_type = c.get("__site_type", "landing")
    eyebrow_txt, title_html = _sc("services", site_type)

    items = [
        (c['svc1_title'], c['svc1_body']),
        (c['svc2_title'], c['svc2_body']),
        (c['svc3_title'], c['svc3_body']),
        (c['svc4_title'], c['svc4_body']),
    ]

    if variant == "cards":
        body = ''.join(
            f'<article class="service-card"><span>&#8599;</span><h3>{e(a)}</h3><p>{e(b)}</p></article>'
            for a, b in items
        )
        return f'''<section id="services" class="site-section section-pad">
  <div class="container">
    <div class="section-head"><div><div class="eyebrow">{e(eyebrow_txt)}</div><h2>{title_html}</h2></div></div>
    <div class="services services--cards">{body}</div>
  </div>
</section>'''

    # stacked (default)
    body = ''.join(
        f'<div class="service-row"><span>0{i}</span><div><h3>{e(a)}</h3><p>{e(b)}</p></div><b>&#8599;</b></div>'
        for i, (a, b) in enumerate(items, 1)
    )
    return f'''<section id="services" class="site-section section-pad">
  <div class="container">
    <div class="section-head"><div><div class="eyebrow">{e(eyebrow_txt)}</div><h2>{title_html}</h2></div></div>
    <div class="services services--stacked">{body}</div>
  </div>
</section>'''


# ──────────────────────────────────────────────────────────────────────────────
#  GALLERY
# ──────────────────────────────────────────────────────────────────────────────

def gallery(variant: str, c: dict) -> str:
    site_type = c.get("__site_type", "landing")
    eyebrow_txt, title_html = _sc("gallery", site_type)

    imgs = [c['image'], c['image2'], c['image3'], c['image4']]

    def item(url: str, idx: int) -> str:
        return (
            f'<figure class="gallery-item">'
            f'<img src="{e(url)}" alt="{e(c["brand"])} — work {idx}" loading="lazy" onerror="this.style.opacity=\'0.3\'"/>'
            f'<figcaption><span>{e(c["brand"])} {idx:02d}</span><b>View &#8599;</b></figcaption>'
            f'</figure>'
        )

    if variant == "grid":
        items = ''.join(item(u, i + 1) for i, u in enumerate(imgs))
        return f'''<section id="work" class="site-section section-pad">
  <div class="container">
    <div class="section-head"><div><div class="eyebrow">{e(eyebrow_txt)}</div><h2>{title_html}</h2></div></div>
    <div class="gallery-grid gallery-grid--grid">{items}</div>
  </div>
</section>'''

    if variant == "editorial":
        return f'''<section id="work" class="site-section section-pad">
  <div class="container">
    <div class="section-head"><div><div class="eyebrow">{e(eyebrow_txt)}</div><h2>{title_html}</h2></div></div>
    <div class="gallery-editorial">
      <div class="gallery-editorial-main">
        <figure class="gallery-item">
          <img src="{e(imgs[0])}" alt="Featured work" loading="lazy" onerror="this.style.opacity='0.3'"/>
          <figcaption><span>Featured</span><b>View &#8599;</b></figcaption>
        </figure>
      </div>
      <div class="gallery-editorial-side">
        {''.join(item(u, i + 2) for i, u in enumerate(imgs[1:3]))}
      </div>
    </div>
  </div>
</section>'''

    # masonry (default)
    items = ''.join(item(u, i + 1) for i, u in enumerate(imgs))
    return f'''<section id="work" class="site-section section-pad">
  <div class="container">
    <div class="section-head"><div><div class="eyebrow">{e(eyebrow_txt)}</div><h2>{title_html}</h2></div></div>
    <div class="gallery-grid gallery-grid--masonry">{items}</div>
  </div>
</section>'''


# ──────────────────────────────────────────────────────────────────────────────
#  TESTIMONIALS
# ──────────────────────────────────────────────────────────────────────────────

def testimonials(variant: str, c: dict) -> str:
    site_type = c.get("__site_type", "landing")
    eyebrow_txt, title_html = _sc("testimonials", site_type)

    # Prefer AI-generated quotes, fall back to curated pool
    ai_quotes = []
    for i in range(1, 4):
        q = c.get(f"t{i}_quote", "")
        n = c.get(f"t{i}_name",  "")
        r = c.get(f"t{i}_role",  "")
        if q and n:
            ai_quotes.append((f'"{q}"', n, r))
    quotes = ai_quotes if len(ai_quotes) >= 2 else _quotes(site_type)

    if variant == "cards":
        body = ''.join(
            f'<article class="quote-card"><div class="stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>'
            f'<blockquote>{q}</blockquote>'
            f'<div class="quote-person"><strong>{e(n)}</strong><span>{e(r)}</span></div></article>'
            for q, n, r in quotes
        )
        return f'''<section class="site-section section-pad">
  <div class="container">
    <div class="section-head"><div><div class="eyebrow">{e(eyebrow_txt)}</div><h2>{title_html}</h2></div></div>
    <div class="quotes-grid">{body}</div>
  </div>
</section>'''

    # editorial (default) — large single quote
    q, n, r = quotes[0]
    return f'''<section class="site-section section-pad">
  <div class="container">
    <div class="editorial-quote">
      <div class="quote-mark">&#8220;</div>
      <blockquote>{q}</blockquote>
      <div class="quote-person"><strong>{e(n)}</strong><span>{e(r)}</span></div>
    </div>
  </div>
</section>'''


# ──────────────────────────────────────────────────────────────────────────────
#  PRICING
# ──────────────────────────────────────────────────────────────────────────────

def pricing(variant: str, c: dict) -> str:
    ru = c.get("__lang") == "ru"
    lbl_popular = "Популярный" if ru else "Most popular"
    lbl_start   = "Записаться" if ru else "Get started"
    lbl_price_h = "Прайс" if ru else "Pricing"
    lbl_price_t = f'Выберите <em>нужный пакет.</em>' if ru else f'Pick the level of <em>momentum.</em>'
    lbl_price_s = "Без скрытых платежей." if ru else "No hidden fees. Cancel any time."

    # Build plans: prefer AI-generated content, fallback to generic
    ai_plans = []
    for i in range(1, 4):
        nm = c.get(f"p{i}_name", "")
        pr = c.get(f"p{i}_price", "")
        ds = c.get(f"p{i}_desc", "")
        ft = c.get(f"p{i}_feats", "")
        if nm and pr:
            feats = [f.strip() for f in ft.split(",") if f.strip()] if isinstance(ft, str) else []
            if not feats:
                feats = [ds] if ds else []
            ai_plans.append((nm, pr, ds, feats))

    if not ai_plans:
        if ru:
            ai_plans = [
                ("Базовый",    "по запросу", "Для старта",          ["Консультация", "Базовый пакет", "Поддержка"]),
                ("Стандарт",   "по запросу", "Для роста",           ["Всё из Базового", "Приоритет", "Расширенный пакет"]),
                ("Премиум",    "по запросу", "Для большого бизнеса",["Всё из Стандарта", "Персональный менеджер", "VIP-доступ"]),
            ]
        else:
            ai_plans = [
                ("Starter", "$29/mo",  "For quick launches",   ["1 project", "Core sections", "Responsive design"]),
                ("Studio",  "$79/mo",  "For serious launches", ["Unlimited projects", "Premium themes", "Priority support"]),
                ("Scale",   "$149/mo", "For growing teams",    ["Multiple sites", "Advanced analytics", "Dedicated manager"]),
            ]

    def card(idx: int, name: str, price: str, desc: str, feats: list) -> str:
        featured  = idx == 1
        cls       = "price-card price-card--featured" if featured else "price-card"
        btn_cls   = "button--primary" if featured else "button--outline"
        badge     = f'<span class="price-badge">{lbl_popular}</span>' if featured else ""
        feat_html = ''.join(f'<li>&#10003; {e(f)}</li>' for f in feats)
        return (
            f'<article class="{cls}">'
            f'{badge}'
            f'<div class="price-top"><span>{e(name)}</span><p>{e(desc)}</p></div>'
            f'<strong class="price">{e(price)}</strong>'
            f'<ul>{feat_html}</ul>'
            f'<a class="button {btn_cls}" href="#contact">{lbl_start}</a>'
            f'</article>'
        )

    body = ''.join(card(i, *p) for i, p in enumerate(ai_plans))
    return f'''<section class="site-section section-pad">
  <div class="container">
    <div class="section-head"><div><div class="eyebrow">{lbl_price_h}</div><h2>{lbl_price_t}</h2></div><p>{lbl_price_s}</p></div>
    <div class="pricing-grid">{body}</div>
  </div>
</section>'''




# ──────────────────────────────────────────────────────────────────────────────
#  FAQ
# ──────────────────────────────────────────────────────────────────────────────

def faq(variant: str, c: dict) -> str:
    qs = [
        (c['q1'], c['a1']),
        (c['q2'], c['a2']),
        (c['q3'], c['a3']),
        ("Is there a free trial?", "Yes — we offer a 14-day trial on all plans with no credit card required."),
    ]
    body = ''.join(
        f'<details class="faq-item"><summary>{e(q)}<span>+</span></summary><p>{e(a)}</p></details>'
        for q, a in qs
    )

    if variant == "split":
        return f'''<section class="site-section section-pad">
  <div class="container faq-wrap">
    <div class="faq-title"><div class="eyebrow">FAQ</div><h2>Everything clear.<br><em>No guesswork.</em></h2></div>
    <div class="faq-list">{body}</div>
  </div>
</section>'''

    return f'''<section class="site-section section-pad">
  <div class="container">
    <div class="section-head"><div><div class="eyebrow">FAQ</div><h2>Questions? <em>Answered.</em></h2></div></div>
    <div class="faq-list">{body}</div>
  </div>
</section>'''


# ──────────────────────────────────────────────────────────────────────────────
#  CTA
# ──────────────────────────────────────────────────────────────────────────────

def cta(variant: str, c: dict) -> str:
    title     = e(c.get("cta_title") or "Make the first impression count.")
    body_text = e(c.get("cta_body")  or "Turn your idea into something people can actually feel.")

    if variant == "contrast":
        return f'''<section class="site-section section-pad">
  <div class="container">
    <div class="cta cta--contrast">
      <div>
        <div class="eyebrow">Ready when you are</div>
        <h2>{title}</h2>
        <p>{body_text}</p>
      </div>
      <a class="button button--primary" href="#contact">{e(c['primary_cta'])}</a>
    </div>
  </div>
</section>'''

    if variant == "soft":
        return f'''<section class="site-section section-pad">
  <div class="container">
    <div class="cta cta--soft">
      <div>
        <div class="eyebrow">Next step</div>
        <h2>{title}</h2>
        <p>{body_text}</p>
      </div>
      <a class="button button--outline" href="#contact">{e(c['primary_cta'])}</a>
    </div>
  </div>
</section>'''

    # luxury (default)
    return f'''<section class="site-section section-pad">
  <div class="container">
    <div class="cta cta--luxury">
      <div>
        <div class="eyebrow">Ready when you are</div>
        <h2>{title}</h2>
        <p>{body_text}</p>
      </div>
      <a class="button button--primary" href="#contact">{e(c['primary_cta'])}</a>
    </div>
  </div>
</section>'''


# ──────────────────────────────────────────────────────────────────────────────
#  CONTACT
# ──────────────────────────────────────────────────────────────────────────────

def contact(variant: str, c: dict) -> str:
    ru = c.get("__lang") == "ru"
    lbl_name   = "Ваше имя" if ru else "Your name"
    lbl_email  = "Телефон или Email" if ru else "Email address"
    lbl_msg    = "Опишите ваш вопрос" if ru else "Tell us about your project"
    lbl_send   = "Отправить заявку" if ru else "Send inquiry"
    lbl_start  = "Напишите нам" if ru else "Start a conversation"
    lbl_cont   = "Контакты" if ru else "Contact"
    lbl_imag   = "Расскажите, что вы хотите" if ru else "Tell us what you imagine"
    if variant == "minimal":
        return f'''<section id="contact" class="site-section section-pad">
  <div class="container contact-min">
    <div>
      <div class="eyebrow">{lbl_start}</div>
      <h2>{e(c['email'])}</h2>
      <p>{e(c['location'])}</p>
    </div>
    <a class="button button--primary" href="mailto:{e(c['email'])}">Email &#8599;</a>
  </div>
</section>'''

    # split (default)
    return f'''<section id="contact" class="site-section section-pad">
  <div class="container contact-split">
    <div>
      <div class="eyebrow">{lbl_cont}</div>
      <h2>{lbl_imag}</h2>
      <p>{e(c['location'])}</p>
      <p><a href="mailto:{e(c['email'])}">{e(c['email'])}</a></p>
      <p>{e(c['phone'])}</p>
    </div>
    <form class="contact-form" onsubmit="return false;">
      <input placeholder="{lbl_name}" autocomplete="name"/>
      <input type="email" placeholder="{lbl_email}" autocomplete="email"/>
      <textarea placeholder="{lbl_msg}"></textarea>
      <button class="button button--primary" type="button">{lbl_send}</button>
    </form>
  </div>
</section>'''


# ──────────────────────────────────────────────────────────────────────────────
#  FOOTER
# ──────────────────────────────────────────────────────────────────────────────

def footer(variant: str, c: dict) -> str:
    year = c.get("year", "2026")
    ru = c.get("__lang") == "ru"
    lbl_explore  = "Навигация" if ru else "Explore"
    lbl_contacts = "Контакты" if ru else "Contact"
    lbl_tagline  = "Создано с душой и вниманием к деталям." if ru else "Built with taste, structure and intent."
    lbl_bottom   = "Все права защищены" if ru else "Made for the web."

    if variant == "rich":
        return f'''<footer class="site-section footer">
  <div class="container footer-grid">
    <div>
      <a class="brand" href="#">{e(c['brand'])}</a>
      <p>{lbl_tagline}</p>
    </div>
    <div>
      <span>{lbl_explore}</span>
      <a href="#about">{"О нас" if ru else "About"}</a><a href="#services">{"Услуги" if ru else "Services"}</a><a href="#work">{"Работы" if ru else "Work"}</a><a href="#contact">{"Контакты" if ru else "Contact"}</a>
    </div>
    <div>
      <span>{lbl_contacts}</span>
      <a href="mailto:{e(c['email'])}">{e(c['email'])}</a>
      <a href="#">Instagram</a><a href="#">{'ВКонтакте' if ru else 'LinkedIn'}</a>
    </div>
  </div>
  <div class="container footer-bottom">
    <span>&copy; {year} {e(c['brand'])}</span>
    <span>{lbl_bottom}</span>
  </div>
</footer>'''

    # minimal (default)
    return f'''<footer class="site-section footer">
  <div class="container footer-bottom">
    <a class="brand" href="#">{e(c['brand'])}</a>
    <span>&copy; {year} &middot; {lbl_bottom}</span>
  </div>
</footer>'''


# ──────────────────────────────────────────────────────────────────────────────
#  REGISTRY
# ──────────────────────────────────────────────────────────────────────────────

COMPONENTS: dict = {
    "navbar":       navbar,
    "hero":         hero,
    "about":        about,
    "stats":        stats,
    "features":     features,
    "services":     services,
    "gallery":      gallery,
    "testimonials": testimonials,
    "pricing":      pricing,
    "faq":          faq,
    "cta":          cta,
    "contact":      contact,
    "footer":       footer,
}
