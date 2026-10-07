import os, sys, json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

def _clean_env(s: str | None) -> str:
    if not s:
        return ""
    s = s.strip().strip('"').strip("'")
    while s and s[-1] in ",;":
        s = s[:-1].rstrip()
    return s.strip()

key = _clean_env(os.getenv("GROQ_API_KEY"))
print(f"KEY loaded: {key[:10]}...{key[-4:]} (len={len(key)})", file=sys.stderr)
if not key:
    print("NO KEY", file=sys.stderr)
    sys.exit(1)

import urllib.request, urllib.error
req = urllib.request.Request(
    "https://api.groq.com/openai/v1/models",
    headers={"Authorization": f"Bearer {key}"},
)
try:
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode("utf-8"))
except Exception as e:
    print("ERROR FETCHING:", type(e).__name__, str(e)[:400], file=sys.stderr)
    sys.exit(2)

models = sorted([m["id"] for m in data.get("data", [])])
print(f"TOTAL MODELS: {len(models)}", file=sys.stderr)

def likely_chat(mid: str) -> bool:
    s = mid.lower()
    for bad in ("whisper", "embed", "speech", "tts", "audio", "vision"):
        if bad in s:
            return False
    return True

chat_models = [m for m in models if likely_chat(m)]

# Фильтруем по «качеству» — крупные сначала:
order = []
for key in ("70b", "72b", "8x7b", "v3", "671b", "405b", "32b", "27b", "8b", "instant"):
    for m in chat_models:
        if m in order:
            continue
        if key in m.lower():
            order.append(m)
for m in chat_models:
    if m not in order:
        order.append(m)

out = {
    "total": len(models),
    "chat_models": chat_models,
    "sorted_chat_priority": order,
}
print(json.dumps(out, ensure_ascii=False, indent=2))
