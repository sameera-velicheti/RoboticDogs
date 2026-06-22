import requests

NIM_URL = "http://localhost:8000/v1/chat/completions"

payload = {
    "model": "meta/llama-3.1-8b-instruct",
    "messages": [
        {"role": "system", "content": "You are a robotics control assistant."},
        {"role": "user", "content": "Say 'ready' if you are connected."}
    ],
    "temperature": 0.2
}

print("Sending request to NIM...")

response = requests.post(NIM_URL, json=payload)

print("Status:", response.status_code)
print("Response:")
print(response.json())