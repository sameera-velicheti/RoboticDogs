import sys

sys.path.insert(0, '/home/demo_user/RoboticDogs')

from vision.compliance_checker import check_compliance


def test_keys_on_floor_or_table_are_flagged():
    description = "There are keys on the floor near the desk and a second set of keys on the table."

    findings = check_compliance(description)

    keys_finding = next((f for f in findings if f['rule_id'] == 'KEYS_001'), None)

    assert keys_finding is not None
    assert keys_finding['status'] == 'FAIL'
    assert keys_finding['rule_name'] == 'Keys Left on Floor or Table'
