import sys, os
sys.path.insert(0, '.')

from site_engine.generator import build_html, extract_json, get_system_prompt
from site_engine.schema import validate_plan

tests = [
    {
        'name': 'Barbershop',
        'plan': {
            'site_type': 'barbershop',
            'theme': 'noir_gold',
            'font_pair': 'editorial',
            'sections': [
                {'type':'navbar','variant':'solid'},
                {'type':'hero','variant':'image_full'},
                {'type':'stats','variant':'cards'},
                {'type':'services','variant':'stacked'},
                {'type':'gallery','variant':'grid'},
                {'type':'testimonials','variant':'cards'},
                {'type':'cta','variant':'contrast'},
                {'type':'footer','variant':'rich'},
            ],
            'content': {
                'brand': 'EDGE',
                'eyebrow': 'Premium Grooming',
                'title': 'Precision cuts. Confident style',
                'subtitle': 'The craft of barbering elevated to an art form. Walk in looking good, walk out feeling exceptional.',
                'primary_cta': 'Book appointment',
                'secondary_cta': 'Our services',
                'hero_tag': 'Est. 2018',
                'stat1_num': '5000+', 'stat1_label': 'Happy clients',
                'stat2_num': '4.9', 'stat2_label': 'Average rating',
                'stat3_num': '12', 'stat3_label': 'Expert barbers',
                'stat4_num': '3', 'stat4_label': 'Locations',
                'svc1_title': 'Classic Cut', 'svc1_body': 'Precision haircut, wash and style.',
                'svc2_title': 'Beard Trim', 'svc2_body': 'Full beard sculpting with hot towel finish.',
                'svc3_title': 'Hot Towel Shave', 'svc3_body': 'Traditional shave. Relaxing and flawless.',
                'svc4_title': 'VIP Package', 'svc4_body': 'Cut + beard + scalp massage + styling.',
                'email': 'book@edgebarber.com',
                'location': 'Downtown, New York City',
            }
        }
    },
    {
        'name': 'Restaurant',
        'plan': {
            'site_type': 'restaurant',
            'theme': 'ivory_editorial',
            'font_pair': 'editorial',
            'sections': [
                {'type':'navbar','variant':'glass'},
                {'type':'hero','variant':'image_full'},
                {'type':'about','variant':'minimal'},
                {'type':'stats','variant':'minimal'},
                {'type':'services','variant':'cards'},
                {'type':'gallery','variant':'masonry'},
                {'type':'testimonials','variant':'editorial'},
                {'type':'cta','variant':'luxury'},
                {'type':'footer','variant':'rich'},
            ],
            'content': {
                'brand': 'Maison',
                'eyebrow': 'Est. 2019',
                'title': 'Where every plate tells a story',
                'subtitle': 'Handcrafted cuisine rooted in tradition, shaped by modern imagination.',
                'primary_cta': 'Reserve a table',
                'secondary_cta': 'View menu',
                'stat1_num': '250+', 'stat1_label': 'Dishes crafted',
                'stat2_num': '98%', 'stat2_label': 'Guest satisfaction',
                'stat3_num': '12', 'stat3_label': 'Years of excellence',
                'stat4_num': '8', 'stat4_label': 'Chef awards',
                'email': 'reserve@maisondining.com',
                'location': 'Paris, France',
            }
        }
    },
    {
        'name': 'Portfolio',
        'plan': {
            'site_type': 'portfolio',
            'theme': 'sandstone',
            'font_pair': 'expressive',
            'sections': [
                {'type':'navbar','variant':'minimal'},
                {'type':'hero','variant':'centered_glow'},
                {'type':'about','variant':'image_split'},
                {'type':'stats','variant':'minimal'},
                {'type':'gallery','variant':'editorial'},
                {'type':'features','variant':'icon_rows'},
                {'type':'testimonials','variant':'editorial'},
                {'type':'contact','variant':'minimal'},
                {'type':'footer','variant':'minimal'},
            ],
            'content': {
                'brand': 'FOLIO',
                'eyebrow': 'Creative work',
                'title': 'Design that speaks before you do',
                'subtitle': 'Selected projects spanning brand identity, digital products, and visual storytelling.',
                'primary_cta': 'See my work',
                'secondary_cta': 'Get in touch',
                'stat1_num': '48', 'stat1_label': 'Projects shipped',
                'stat2_num': '30+', 'stat2_label': 'Happy clients',
                'stat3_num': '6', 'stat3_label': 'Years experience',
                'stat4_num': '12', 'stat4_label': 'Awards',
                'email': 'hello@folio.design',
                'location': 'Berlin, Germany',
            }
        }
    },
    {
        'name': 'AI Startup',
        'plan': {
            'site_type': 'saas',
            'theme': 'electric_cobalt',
            'font_pair': 'modern',
            'sections': [
                {'type':'navbar','variant':'glass'},
                {'type':'hero','variant':'centered_glow'},
                {'type':'stats','variant':'minimal'},
                {'type':'features','variant':'bento'},
                {'type':'testimonials','variant':'cards'},
                {'type':'pricing','variant':'featured'},
                {'type':'faq','variant':'accordion'},
                {'type':'cta','variant':'contrast'},
                {'type':'footer','variant':'rich'},
            ],
            'content': {
                'brand': 'Nexus AI',
                'eyebrow': 'Powered by AI',
                'title': 'Ship faster. Scale smarter',
                'subtitle': 'The all-in-one AI platform that gets your product to market in days, not months.',
                'primary_cta': 'Start free trial',
                'secondary_cta': 'Watch demo',
                'stat1_num': '10k+', 'stat1_label': 'Teams onboarded',
                'stat2_num': '99.9%', 'stat2_label': 'Uptime SLA',
                'stat3_num': '3x', 'stat3_label': 'Faster delivery',
                'stat4_num': '$0', 'stat4_label': 'To get started',
                'email': 'hello@nexus.ai',
                'location': 'San Francisco, CA',
            }
        }
    },
    {
        'name': 'Gym',
        'plan': {
            'site_type': 'gym',
            'theme': 'obsidian_mint',
            'font_pair': 'modern',
            'sections': [
                {'type':'navbar','variant':'solid'},
                {'type':'hero','variant':'split_editorial'},
                {'type':'stats','variant':'cards'},
                {'type':'features','variant':'three_up'},
                {'type':'services','variant':'cards'},
                {'type':'gallery','variant':'masonry'},
                {'type':'pricing','variant':'featured'},
                {'type':'testimonials','variant':'cards'},
                {'type':'cta','variant':'contrast'},
                {'type':'footer','variant':'rich'},
            ],
            'content': {
                'brand': 'FORGE',
                'eyebrow': 'Elite Fitness',
                'title': 'Build the body. Shape the mind',
                'subtitle': 'State-of-the-art equipment, expert coaching, and a community that pushes you beyond limits.',
                'primary_cta': 'Start free trial',
                'secondary_cta': 'View plans',
                'stat1_num': '2000+', 'stat1_label': 'Active members',
                'stat2_num': '50+', 'stat2_label': 'Weekly classes',
                'stat3_num': '20', 'stat3_label': 'Expert trainers',
                'stat4_num': '98%', 'stat4_label': 'Member retention',
                'email': 'join@forgegym.com',
                'location': 'New York City',
            }
        }
    },
]

output_dir = 'site_engine/demo'
os.makedirs(output_dir, exist_ok=True)

ok = 0
errors = []
for t in tests:
    try:
        plan = validate_plan(t['plan'])
        html = build_html(plan)

        # Basic checks
        assert len(html) > 2000, f'HTML too short: {len(html)}'
        assert '<!doctype html>' in html.lower(), 'Missing doctype'
        assert 'Lorem ipsum' not in html, 'Lorem ipsum found!'
        assert 'Company Name' not in html, 'Placeholder found!'
        brand = t['plan']['content']['brand']
        assert brand in html, f'Brand "{brand}" not in HTML'

        fname = f"{output_dir}/{t['name'].lower().replace(' ','_')}.html"
        with open(fname, 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"  OK   {t['name']:20s} — {len(html):7,} chars | theme={plan['theme']:20s} | sections={len(plan['sections'])}")
        ok += 1
    except Exception as e:
        import traceback
        err = str(e)
        errors.append((t['name'], err))
        print(f"  ERR  {t['name']:20s} — {err}")
        traceback.print_exc()

print(f"\n{'='*60}")
print(f"Result: {ok}/{len(tests)} sites generated OK")
if errors:
    print("Errors:")
    for name, err in errors:
        print(f"  - {name}: {err}")

# Also test JSON extraction
print("\n--- Testing extract_json ---")
test_cases = [
    ('clean json', '{"site_type":"test","theme":"noir_gold","font_pair":"modern","sections":[],"content":{}}'),
    ('json in backticks', '```json\n{"site_type":"test","theme":"noir_gold","font_pair":"modern","sections":[],"content":{}}\n```'),
    ('json with prefix', 'Here is the plan:\n{"site_type":"test","theme":"noir_gold","font_pair":"modern","sections":[],"content":{}}'),
]
for name, raw in test_cases:
    try:
        result = extract_json(raw)
        assert isinstance(result, dict)
        print(f"  OK   extract_json [{name}]")
    except Exception as e:
        print(f"  ERR  extract_json [{name}]: {e}")

print("\nAll tests complete.")
