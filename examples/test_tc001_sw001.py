"""TC-001 — SW-001 Battery Overtemperature Protection (SIL).

Verifies that charging is disabled at and above 60.0 degC and permitted below it.
"""
import pytest

from bms import BMS


@pytest.mark.parametrize(
    "temperature, expected",
    [
        (59.9, True),   # just below threshold: charging permitted
        (60.0, False),  # at threshold: charging disabled
        (60.1, False),  # above threshold: charging disabled
    ],
)
def test_sw001_overtemperature_protection(temperature, expected):
    assert BMS().charging_allowed(temperature) is expected
