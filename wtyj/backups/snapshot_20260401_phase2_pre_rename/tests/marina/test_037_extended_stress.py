#!/usr/bin/env python3
# bluemarlin/test_037_extended_stress.py
# Brief 037 — Structural checks only (not model output)
# Run: cd bluemarlin && python3 test_037_extended_stress.py

import os

stress_path = os.path.join(os.path.dirname(__file__), "test_marina_stress.py")
with open(stress_path) as f:
    content = f.read()

# T1: All 8 new scenario labels present in the file
for label in ["S15", "S16", "S17", "S18", "S19", "S20", "S21", "S22"]:
    assert label in content, f"T1 fail: {label} missing from test_marina_stress.py"
print("T1 pass — all 8 new scenario labels present in test_marina_stress.py")

# T2: Footer updated to 22 scenarios
assert "22 scenarios run" in content, \
    "T2 fail: footer still says 14 scenarios"
print("T2 pass — footer updated to 22 scenarios")

# T3: S22 present in key checks footer (two-space indent distinguishes footer line from scenario body)
assert "  S22 \u2014" in content, "T3 fail: S22 footer line missing (check key checks footer was updated)"
print("T3 pass — S22 present in key checks footer")

# T4: marina_output_037.md exists
output_path = os.path.join(os.path.dirname(__file__), "..", "..", "briefs", "marina_output_037.md")
assert os.path.exists(output_path), "T4 fail: marina_output_037.md not written"
print("T4 pass — marina_output_037.md exists")

# T5: marina_output_037.md contains per-scenario verdicts
with open(output_path) as f:
    output = f.read()
for label in ["S15", "S16", "S17", "S18", "S19", "S20", "S21", "S22"]:
    assert label in output, f"T5 fail: {label} missing from marina_output_037.md"
print("T5 pass — all 8 scenario labels present in marina_output_037.md")

# T6: marina_output_037.md has substantial content with actual Marina field output
# (not just labels — "guests" only appears if Marina's field dict was recorded)
assert len(output) > 500 and "guests" in output, \
    f"T6 fail: marina_output_037.md appears to lack actual Marina output (len={len(output)}, 'guests' present={'guests' in output})"
print("T6 pass — marina_output_037.md contains substantial content with Marina field output")

print("\nAll 6 tests passed.")
