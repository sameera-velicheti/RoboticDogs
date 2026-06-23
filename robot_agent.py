import requests
import json

from command_schema.schema_validator import validate_intent
from behaviors.behavior_loader import load_behavior
from ros2_bridge.ros_executor import execute_command

NIM_URL = "http://localhost:8000/v1/chat/completions"


def send_prompt(prompt):
    payload = {
        "model": "meta/llama-3.1-8b-instruct",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }

    print("Sending request to NIM...")

    r = requests.post(NIM_URL, json=payload)

    print("Status code:", r.status_code)

    try:
        data = r.json()

        print("\nFULL RESPONSE:")
        print(json.dumps(data, indent=2))

        return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("Failed to parse response:", e)
        print("Raw text:", r.text)
        return None


def get_prompt():
    return """
Return ONLY valid JSON.

Allowed actions:
- cautious_walk
- sit
- stop
- turn_left

Format:
{"action": "<action>"}

User instruction: make the robot move carefully
"""


if __name__ == "__main__":

    prompt = get_prompt()
    response = send_prompt(prompt)

    print("\nRAW MODEL OUTPUT:")
    print(response)

    if not response:
        print("No response from model")
        exit(1)

    try:
        # Parse JSON from model output
        intent = json.loads(response)

        print("\nINTENT RECEIVED:")
        print(intent)

        # Validate intent
        validate_intent(intent)
        print("Intent validated")

        # Load behavior from intent
        command = load_behavior(intent["action"])

        print("\nLOADED BEHAVIOR:")
        print(command)

        # Execute on robot layer
        execute_command(command)

        print("\nROBOT EXECUTED COMMAND")

    except json.JSONDecodeError as e:
        print("JSON PARSE FAILED")
        print(str(e))
        print("Raw response:", response)

    except Exception as e:
        print("PIPELINE ERROR:", str(e))
        