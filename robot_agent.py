import requests
import json
import logging

from command_schema.schema_validator import validate_intent
from behaviors.behavior_loader import load_behavior
from ros2_bridge.ros_executor import execute_command

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

NIM_URL = "http://localhost:8000/v1/chat/completions"


def send_prompt(prompt):
    payload = {
        "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }

    logger.info("Sending request to NIM...")
    r = requests.post(NIM_URL, json=payload)
    logger.info(f"Status code: {r.status_code}")

    try:
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Failed to parse response: {e}")
        logger.error(f"Raw text: {r.text}")
        return None


def get_prompt(user_instruction):
    return f"""
Return ONLY valid JSON. No explanation, no markdown, no extra text.

Allowed actions:
- cautious_walk
- sit
- stop
- turn_left

Format:
{{"action": "<action>"}}

User instruction: {user_instruction}
"""


def run_agent(user_instruction):
    logger.info(f"User instruction: {user_instruction}")

    # Always allow emergency stop without hitting the model
    if user_instruction.strip().lower() in ("stop", "halt", "emergency stop"):
        logger.warning("Emergency stop triggered by user")
        execute_command({"action": "stop"})
        return

    prompt = get_prompt(user_instruction)
    response = send_prompt(prompt)

    if not response:
        logger.error("No response from model — issuing stop")
        execute_command({"action": "stop"})
        return

    logger.info(f"Raw model output: {response}")

    try:
        # Strip any markdown the model adds despite instructions
        clean = response.strip().strip("```json").strip("```").strip()
        intent = json.loads(clean)

        logger.info(f"Intent received: {intent}")

        # Validate and clamp
        validate_intent(intent)
        logger.info("Intent validated")

        # Load behavior file
        command = load_behavior(intent["action"])
        logger.info(f"Loaded behavior: {command}")

        # Execute
        execute_command(command)
        logger.info("Command executed successfully")

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse failed: {e} — raw: {response}")
        execute_command({"action": "stop"})

    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        execute_command({"action": "stop"})


if __name__ == "__main__":
    run_agent("make the robot move carefully")