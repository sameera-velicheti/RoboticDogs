"""The door rule tells Qwen what does NOT count as an open door."""

from vision import compliance_checker
from vision.compliance_checker import _rule_guidance, load_rules


def _rule(rule_id):
    return next(r for r in load_rules()["rules"] if r["id"] == rule_id)


def test_door_prompt_excludes_glass_and_far_doors():
    text = _rule_guidance(_rule("DOOR_001")).lower()
    assert "answer yes only if all" in text
    assert "glass" in text
    assert "far away" in text
    assert "close to the camera" in text


def test_rules_without_guidance_are_unchanged():
    assert _rule_guidance({"name": "x", "keywords": []}) == ""


def test_guidance_is_sent_to_the_model(tmp_path, monkeypatch):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"\xff\xd8fake")
    sent = []

    class Resp:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": "NO"}}]}

    def post(url, json=None, **kw):
        sent.append(json["messages"][0]["content"][1]["text"])
        return Resp()

    monkeypatch.setattr(compliance_checker.requests, "post", post)
    compliance_checker.check_compliance_with_nim(str(image))

    door_prompt = next(p for p in sent if "Open Door" in p)
    assert "seeing through glass does NOT mean the door is open" in door_prompt