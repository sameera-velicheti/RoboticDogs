import requests
import json

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
        print("FULL RESPONSE:")
        print(json.dumps(data, indent=2))
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        print("Failed to parse response:", e)
        print("Raw text:", r.text)
        return None


if __name__ == "__main__":
    prompt = "Return ONLY JSON: {action: cautious_walk, speed: 0.2}"
    response = send_prompt(prompt)

    print("\nRAW MODEL OUTPUT:")
    print(response)