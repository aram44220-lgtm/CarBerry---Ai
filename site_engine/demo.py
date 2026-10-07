import json
from generator import generate

with open('example_plan.json', 'r', encoding='utf-8') as f:
    plan = json.load(f)

out = generate(plan, 'demo/index.html')
print(f'Generated: {out.resolve()}')
