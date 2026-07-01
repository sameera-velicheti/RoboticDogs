
import sys
import os
sys.path.insert(0, '/home/demo_user/RoboticDogs')

from datetime import datetime
from ros2_bridge.ros_nodes import RosPugBridge
from vision.image_capture import capture_image
from vision.compliance_checker import check_compliance_with_nim, print_findings
from vision.report_generator import generate_report, print_report_summary


def run_inspection(label=None):
    print("\n=== NEMOCLAW SAFETY INSPECTION ===\n")

    # Step 1 — Capture
    print("Step 1: Connecting to robot and capturing image...")
    bridge = RosPugBridge()
    filepath, metadata = capture_image(bridge, label=label)
    bridge.close()
    print(f"Image saved: {filepath}\n")

    # Step 2 — Check compliance directly with NIM per rule
    print("Step 2: Checking compliance rules with NIM...")
    findings = check_compliance_with_nim(
        filepath=filepath,
        timestamp=metadata["timestamp"]
    )
    print_findings(findings)

    # Step 3 — Generate report
    print("Step 3: Generating report...")
    report, json_path, txt_path = generate_report(
        all_findings=[findings],
        location="SHI Lab",
        inspector="NemoClaw"
    )
    print_report_summary(report)

    print(f"Reports saved to:")
    print(f"  {json_path}")
    print(f"  {txt_path}")

    return report


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "inspection"
    run_inspection(label=label)