import json
from nim_client import query_nim

PROMPT_PATH = "prompt_template.txt"

def load_prompt():
    with open(PROMPT_PATH, "r") as f:
        return f.read()

def parse_user_input(user_input: str):
    prompt_template = load_prompt()

    full_prompt = f"""
{prompt_template}

User input:
{user_input}
"""

    result = query_nim(full_prompt)

    try:
        return json.loads(result)
    except Exception:
        raise ValueError(f"Model did not return valid JSON:\n{result}")