import json
from generator import generate


def generate_from_ai(ai_text: str, output_path: str = "generated/index.html"):
    """Pass the raw model response here. The model must return JSON only."""
    plan = json.loads(ai_text)
    return generate(plan, output_path)


# Example:
# ai_response = your_llm_call(SYSTEM_PROMPT, user_request)
# html_path = generate_from_ai(ai_response)
# send html_path back through Telegram / Mini App storage.
