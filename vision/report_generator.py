# vision/report_generator.py

import json
import os
import sys
from datetime import datetime
sys.path.insert(0, '/home/demo_user/RoboticDogs')

REPORTS_DIR = '/home/demo_user/RoboticDogs/reports'


def generate_report(all_findings, location="SHI Lab", inspector="NemoClaw"):
    """
    Takes a list of findings from multiple images and generates a full report.
    all_findings: list of finding lists (one per image captured)
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Flatten all findings
    flat_findings = [f for findings in all_findings for f in findings]

    # Separate passes and fails
    fails = [f for f in flat_findings if f["status"] == "FAIL"]
    passes = [f for f in flat_findings if f["status"] == "PASS"]

    # Count by severity
    high = [f for f in fails if f["severity"] == "HIGH"]
    alert = [f for f in fails if f["severity"] == "ALERT"]
    medium = [f for f in fails if f["severity"] == "MEDIUM"]

    # Overall status
    # Overall status — only FAIL if there are HIGH severity issues
    high_fails = [f for f in flat_findings if f["status"] == "FAIL" and f["severity"] in ("HIGH", "ALERT")]
    medium_fails = [f for f in flat_findings if f["status"] == "FAIL" and f["severity"] == "MEDIUM"]
    low_fails = [f for f in flat_findings if f["status"] == "FAIL" and f["severity"] == "LOW"]

    if high_fails:
        overall = "FAIL"
    elif medium_fails or low_fails:
        overall = "WARNING"
    else:
        overall = "PASS"
        
    report = {
        "report_id": f"INSPECTION_{timestamp}",
        "timestamp": timestamp,
        "location": location,
        "inspector": inspector,
        "overall_status": overall,
        "summary": {
            "total_images": len(all_findings),
            "total_findings": len(flat_findings),
            "total_fails": len(fails),
            "high_severity": len(high),
            "alert_severity": len(alert),
            "medium_severity": len(medium),
            "passes": len(passes)
        },
        "findings": flat_findings
    }

    # Save JSON report
    json_path = os.path.join(REPORTS_DIR, f"report_{timestamp}.json")
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)

    # Save human-readable text report
    txt_path = os.path.join(REPORTS_DIR, f"report_{timestamp}.txt")
    with open(txt_path, "w") as f:
        f.write(f"NEMOCLAW SAFETY INSPECTION REPORT\n")
        f.write(f"{'='*40}\n")
        f.write(f"Report ID:    {report['report_id']}\n")
        f.write(f"Timestamp:    {timestamp}\n")
        f.write(f"Location:     {location}\n")
        f.write(f"Inspector:    {inspector}\n")
        f.write(f"Overall:      {overall}\n")
        f.write(f"{'='*40}\n\n")

        f.write(f"SUMMARY\n")
        f.write(f"-------\n")
        f.write(f"Images captured:  {report['summary']['total_images']}\n")
        f.write(f"Issues found:     {len(fails)}\n")
        f.write(f"  HIGH severity:  {len(high)}\n")
        f.write(f"  ALERT severity: {len(alert)}\n")
        f.write(f"  MEDIUM severity:{len(medium)}\n")
        f.write(f"\n")

        if fails:
            f.write(f"ISSUES REQUIRING ACTION\n")
            f.write(f"-----------------------\n")
            for finding in fails:
                f.write(f"[{finding['severity']}] {finding['rule_name']}\n")
                f.write(f"  Rule ID:    {finding['rule_id']}\n")
                f.write(f"  Image:      {finding.get('image_path', 'N/A')}\n")
                f.write(f"  Timestamp:  {finding.get('timestamp', 'N/A')}\n")
                f.write(f"  Keywords:   {', '.join(finding['matched_keywords'])}\n")
                f.write(f"  Action:     {finding['remediation']}\n\n")
        else:
            f.write(f"No issues found. Area is compliant.\n")

    print(f"Report saved:")
    print(f"  JSON: {json_path}")
    print(f"  Text: {txt_path}")

    return report, json_path, txt_path


def print_report_summary(report):
    status_icon = "✓" if report["overall_status"] == "PASS" else "✗"
    print(f"\n{status_icon} INSPECTION {report['overall_status']}")
    print(f"  Images:   {report['summary']['total_images']}")
    print(f"  Issues:   {report['summary']['total_fails']}")
    print(f"  HIGH:     {report['summary']['high_severity']}")
    print(f"  MEDIUM:   {report['summary']['medium_severity']}\n")


if __name__ == "__main__":
    # Test with sample findings
    from vision.compliance_checker import check_compliance
    from datetime import datetime

    test_description = """
    The image shows a low-angle view of a workspace. A white cord lies loosely 
    on the carpet, creating a trip hazard near the person. A black cable near 
    the chair leg is another potential snag point.
    """

    findings = check_compliance(
        description=test_description,
        image_path="captures/test.jpg",
        timestamp=datetime.now().strftime("%Y%m%d_%H%M%S")
    )

    report, json_path, txt_path = generate_report(
        all_findings=[findings],
        location="SHI Lab",
        inspector="NemoClaw"
    )

    print_report_summary(report)

    # Print the text report
    with open(txt_path) as f:
        print(f.read())