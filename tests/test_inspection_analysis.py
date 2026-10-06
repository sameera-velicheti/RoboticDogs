import json
from pathlib import Path

import app as flask_app
from vision import compliance_checker, report_generator


def test_analyze_combines_images_and_keeps_waypoint_sources(tmp_path, monkeypatch):
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    image_paths = [capture_dir / "corner1.jpg", capture_dir / "corner2.jpg"]
    for image_path in image_paths:
        image_path.write_bytes(b"image")

    monkeypatch.setattr(report_generator, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(flask_app, "CAPTURE_DIR", str(capture_dir))

    def fake_check(filepath, timestamp=None):
        is_issue = filepath.endswith("corner2.jpg")
        return [{
            "rule_id": "CABLE_001",
            "rule_name": "Loose cable",
            "severity": "HIGH" if is_issue else "NONE",
            "matched_keywords": ["cable"] if is_issue else [],
            "remediation": "Secure the cable" if is_issue else "None required",
            "image_path": filepath,
            "timestamp": timestamp,
            "status": "FAIL" if is_issue else "PASS",
        }]

    monkeypatch.setattr(compliance_checker, "check_compliance_with_nim", fake_check)
    response = flask_app.app.test_client().post("/analyze", json={
        "dog_id": "dog1",
        "route_name": "Data Center Patrol",
        "images": [
            {"filepath": str(image_paths[0]), "waypoint_name": "Corner 1"},
            {"filepath": str(image_paths[1]), "waypoint_name": "Corner 2"},
        ],
    }, buffered=True)

    assert response.status_code == 200
    events = [
        json.loads(line[6:])
        for line in response.get_data(as_text=True).splitlines()
        if line.startswith("data: ")
    ]
    image_events = [event for event in events if event["type"] == "image_findings"]
    summaries = [event for event in events if event["type"] == "report_summary"]
    assert [event["waypoint_name"] for event in image_events] == ["Corner 1", "Corner 2"]
    assert len(summaries) == 1
    assert summaries[0]["overall"] == "FAIL"
    assert summaries[0]["total_images"] == 2
    assert summaries[0]["total_fails"] == 1

    report_files = list(Path(report_generator.REPORTS_DIR).glob("*.json"))
    assert len(report_files) == 1
    report = json.loads(report_files[0].read_text())
    assert report["summary"]["total_images"] == 2
    assert report["route_name"] == "Data Center Patrol"
    assert report["findings"][1]["waypoint_name"] == "Corner 2"
    assert report["findings"][1]["image_path"] == str(image_paths[1])
    text_report = report_files[0].with_suffix(".txt").read_text()
    assert text_report.startswith("# Data Center Patrol Report\n\n")
    assert f"- {report['inspection_date']}" in text_report
    assert "- Data Center Patrol" in text_report
    assert "- 2" in text_report
    assert "- Corner 2: Loose cable detected" in text_report
    assert "- 1 issue found requiring review" in text_report


def test_analyze_rejects_image_paths_outside_capture_directory(tmp_path, monkeypatch):
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    outside_image = tmp_path / "outside.jpg"
    outside_image.write_bytes(b"image")
    monkeypatch.setattr(flask_app, "CAPTURE_DIR", str(capture_dir))

    response = flask_app.app.test_client().post("/analyze", json={
        "images": [{"filepath": str(outside_image)}],
    })

    assert response.status_code == 400
    assert response.get_json()["error"] == "Invalid filepath"


def test_analyze_keeps_legacy_single_filepath_requests(tmp_path, monkeypatch):
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    image_path = capture_dir / "single.jpg"
    image_path.write_bytes(b"image")
    monkeypatch.setattr(flask_app, "CAPTURE_DIR", str(capture_dir))
    monkeypatch.setattr(report_generator, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(compliance_checker, "check_compliance_with_nim", lambda **kwargs: [])

    response = flask_app.app.test_client().post("/analyze", json={
        "filepath": str(image_path),
    }, buffered=True)

    events = [
        json.loads(line[6:])
        for line in response.get_data(as_text=True).splitlines()
        if line.startswith("data: ")
    ]
    summary = next(event for event in events if event["type"] == "report_summary")
    assert response.status_code == 200
    assert summary["overall"] == "PASS"
    assert summary["total_images"] == 1
    report_path = next(Path(report_generator.REPORTS_DIR).glob("*.json"))
    report = json.loads(report_path.read_text())
    assert report["route_name"] == "Data Center Patrol"
    assert report_path.with_suffix(".txt").read_text().startswith("# Data Center Patrol Report")
