import requests

ROBOT_IP = "http://10.21.129.17:5000"

payload = {
    "action": "cautious_walk",
    "speed": 0.1,
    "duration": 2.0
}

response = requests.post(ROBOT_IP, json=payload)

print("Status:", response.status_code)
print("Response:", response.text)