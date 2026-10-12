"""Sends image and text prompts to the NIM model for safety-related image description.
"""

import base64
from email import message
import json
import requests
import os
import sys
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo folder
sys.path.insert(0, _ROOT)

from nim_config import NIM_URL, NIM_MODEL, headers as nim_headers, extract_answer, extra_params


def image_to_base64(filepath):
    """Encode a local image file as a base64 data URI payload."""
    with open(filepath, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def describe_image(filepath, context=None):
    """Send the image to NIM and receive a safety-focused text description."""
    """
    Send an image to Nemotron and get a description back.
    context: optional string to focus the model (e.g. 'safety inspection')
    """
    print(f"Encoding image: {filepath}")
    b64 = image_to_base64(filepath)

    prompt = "Describe everything you see in this image that could be relevant to safety, hazards, or equipment."
    if context:
        prompt = f"You are performing a {context}. Describe everything you see in this image that could be relevant to safety, hazards, or equipment."

    payload = {
        "model": NIM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}"
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ],
        "temperature": 0.2,
        "max_tokens": 2000,
        **extra_params(),
    }

    print("Sending image to NIM...")
    r = requests.post(NIM_URL, json=payload, headers=nim_headers(), timeout=120)
    print(f"Status: {r.status_code}")

    if r.status_code != 200:
        print(f"Error: {r.text}")
        return None

    data = r.json()
    message = data["choices"][0]["message"]

    description = extract_answer(message)
    return description


if __name__ == "__main__":
    import os
    # Find the most recent capture to test with
    capture_dir = os.path.join(_ROOT, 'captures')
    jpgs = [f for f in os.listdir(capture_dir) if f.endswith('.jpg')]
    
    if not jpgs:
        print("No captures found. Run vision/image_capture.py first.")
        sys.exit(1)

    latest = sorted(jpgs)[-1]
    filepath = os.path.join(capture_dir, latest)
    print(f"Testing with: {filepath}")

    description = describe_image(filepath, context="safety inspection")
    
    print("\n--- NIM DESCRIPTION ---")
    print(description)
    print("-----------------------")