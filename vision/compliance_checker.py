# vision/compliance_checker.py

import json
import os
import sys
import requests
import base64
sys.path.insert(0, '/home/demo_user/RoboticDogs')

RULES_PATH = '/home/demo_user/RoboticDogs/vision/compliance_rules.json'


def load_rules():
    with open(RULES_PATH, 'r') as f:
        return json.load(f)


def check_compliance(description, image_path=None, timestamp=None):
    """Keyword-based compliance check against NIM description text."""
    rules_data = load_rules()
    rules = rules_data["rules"]
    description_lower = description.lower()
    findings = []

    for rule in rules:
        matched_keywords = [
            kw for kw in rule["keywords"]
            if kw.lower() in description_lower
        ]
        if matched_keywords:
            findings.append({
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                "severity": rule["severity"],
                "matched_keywords": matched_keywords,
                "remediation": rule["remediation"],
                "image_path": image_path,
                "timestamp": timestamp,
                "status": "FAIL"
            })
        else:
            findings.append({
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                "severity": "NONE",
                "matched_keywords": [],
                "remediation": "None required",
                "image_path": image_path,
                "timestamp": timestamp,
                "status": "PASS"
            })

    return findings


def check_compliance_with_nim(filepath, timestamp=None):
    """Ask the NIM directly about each compliance rule with keyword hints."""
    with open(filepath, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    rules_data = load_rules()
    rules = rules_data["rules"]
    findings = []

    for rule in rules:
        keywords_str = ", ".join(rule["keywords"])

        prompt = f"""You are a safety compliance inspector examining a workplace image.

Check for this specific safety issue: {rule['name']}
Visual indicators to look for: {keywords_str}

Look carefully at the image. Can you clearly see this safety issue?
Your answer MUST start with YES or NO.
YES if the issue is clearly visible.
NO if the issue is not visible or you are not sure."""

        payload = {
            "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": prompt}
            ]}],
            "temperature": 0.1,
            "max_tokens": 500
        }

        r = requests.post("http://localhost:8000/v1/chat/completions", json=payload, timeout=60)
        data = r.json()
        message = data["choices"][0]["message"]
        answer = (message.get("reasoning") or message.get("content") or "").strip()

        print(f"  Checking [{rule['id']}] {rule['name']}... ", end="", flush=True)

        is_flagged = (
            answer.upper().startswith("YES") or
            "\nYES" in answer.upper() or
            "YES." in answer.upper() or
            "YES," in answer.upper()
        )

        print("FLAGGED" if is_flagged else "clear")

        if is_flagged:
            findings.append({
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                "severity": rule["severity"],
                "matched_keywords": [rule["name"]],
                "remediation": rule["remediation"],
                "image_path": filepath,
                "timestamp": timestamp,
                "status": "FAIL"
            })
        else:
            findings.append({
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                "severity": "NONE",
                "matched_keywords": [],
                "remediation": "None required",
                "image_path": filepath,
                "timestamp": timestamp,
                "status": "PASS"
            })

    return findings


def print_findings(findings):
    print("\n--- COMPLIANCE FINDINGS ---")
    for f in findings:
        status_icon = "✓" if f["status"] == "PASS" else "✗"
        print(f"{status_icon} [{f['severity']}] {f['rule_name']}")
        if f["status"] == "FAIL":
            print(f"  Issue:  {', '.join(f['matched_keywords'])}")
            print(f"  Action: {f['remediation']}")
    print("---------------------------\n")


if __name__ == "__main__":
    from datetime import datetime

    # Find the most recent capture
    capture_dir = '/home/demo_user/RoboticDogs/captures'
    jpgs = sorted([f for f in os.listdir(capture_dir) if f.endswith('.jpg')])

    if not jpgs:
        print("No captures found. Run vision/image_capture.py first.")
        sys.exit(1)

    latest = os.path.join(capture_dir, jpgs[-1])
    print(f"Testing with: {latest}\n")

    findings = check_compliance_with_nim(
        filepath=latest,
        timestamp=datetime.now().strftime("%Y%m%d_%H%M%S")
    )

    print_findings(findings)