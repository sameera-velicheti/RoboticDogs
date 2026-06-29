import requests
import json
import logging

from command_schema.schema_validator import validate_intent
from behaviors.behavior_loader import load_behavior
from ros2_bridge.ros_executor import execute_command
from ros2_bridge.ros_nodes import RosPugBridge

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

Allowed actions: cautious_walk, sit, stop, turn_left, turn_right

Rules:
- Always include speed and duration for movement actions
- If given multiple actions, complete one full movement before starting the next
- Default speed is 0.10, default duration is 3.0
- Use the exact duration the user specifies if they mention seconds
- Maximum duration is 60.0, maximum speed is 0.20

Return a list of actions in order:
{{"actions": [
    {{"action": "<action>", "speed": <float>, "duration": <float>}},
    {{"action": "<action>", "speed": <float>, "duration": <float>}}
]}}

User instruction: {user_instruction}
"""


def run_agent(user_instruction, bridge):
    logger.info(f"User instruction: {user_instruction}")

    # Always allow emergency stop without hitting the model
    if user_instruction.strip().lower() in ("stop", "halt", "emergency stop"):
        logger.warning("Emergency stop triggered by user")
        execute_command({"action": "stop"}, bridge)
        return

    prompt = get_prompt(user_instruction)
    response = send_prompt(prompt)

    if not response:
        logger.error("No response from model — issuing stop")
        execute_command({"action": "stop"}, bridge)
        return

    logger.info(f"Raw model output: {response}")

    try:
        # Strip any markdown the model adds despite instructions
        clean = response.strip().strip("```json").strip("```").strip()
        intent = json.loads(clean)

        logger.info(f"Intent received: {intent}")

        # Support both single action and list of actions
        actions = intent.get("actions", [intent])

        print(f"Executing {len(actions)} action(s)...")

        for action in actions:
            # Validate and clamp
            validate_intent(action)

            # Load behavior defaults from JSON file
            command = load_behavior(action["action"])

            # NIM values override the defaults
            if "speed" in action:
                command["speed"] = action["speed"]
            if "duration" in action:
                command["duration"] = action["duration"]
            if "safety_level" in action:
                command["safety_level"] = action["safety_level"]

            print(f"  → {command['action']} for {command.get('duration', '?')}s at speed {command.get('speed', '?')}")
            logger.info(f"Executing command: {command}")

            execute_command(command, bridge)

        print("Done.\n")
        logger.info("All commands executed successfully")

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse failed: {e} — raw: {response}")
        execute_command({"action": "stop"}, bridge)

    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        execute_command({"action": "stop"}, bridge)


if __name__ == "__main__":
    print("ROSPug NemoClaw Control")
    print("Type a command for the robot. Type 'quit' to exit.\n")
    
    bridge = RosPugBridge()
    
    while True:
        try:
            user_input = input(">> ").strip()
            
            if not user_input:
                continue
                
            if user_input.lower() in ("quit", "exit", "q"):
                print("Shutting down...")
                bridge.stop()
                bridge.close()
                break
            
            if user_input.lower() in ("stop", "halt", "emergency stop"):
                print("Emergency stop!")
                bridge.stop()
                continue
            
            # Send to NIM
            prompt = get_prompt(user_input)
            response = send_prompt(prompt)
            
            if not response:
                print("No response from model, stopping robot")
                bridge.stop()
                continue
            
            try:
                clean = response.strip().strip("```json").strip("```").strip()
                intent = json.loads(clean)
                actions = intent.get("actions", [intent])
                
                print(f"Executing {len(actions)} action(s)...")
                
                for action in actions:
                    validate_intent(action)
                    command = load_behavior(action["action"])

                    if "speed" in action:
                     command["speed"] = action["speed"]
                    if "duration" in action:
                        command["duration"] = action["duration"]
                    if "safety_level" in action:
                        command["safety_level"] = action["safety_level"]

                    print(f"  → {command['action']} for {command.get('duration', '?')}s")
                    execute_command(command, bridge)
                    
                    print("Done.\n")
                
            except json.JSONDecodeError as e:
                print(f"Model returned invalid JSON: {e}")
                bridge.stop()
                
            except Exception as e:
                print(f"Error: {e}")
                bridge.stop()
                
        except KeyboardInterrupt:
            print("\nEmergency stop!")
            bridge.stop()
            bridge.close()
            break