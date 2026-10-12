"""Auditor control unit tests: no fake application events to make 4.1 pass."""

from types import SimpleNamespace

import pytest
from audit_contract import BodyActivity, validate_exemption

pytestmark = pytest.mark.no_app_operation(
    reason="Audit meta-fixture validation with synthetic counters; no HTTP or services executed."
)


@pytest.mark.parametrize("reason", [None, "", "   ", 123])
def test_no_app_marker_requires_reason(reason):
    marker = SimpleNamespace(args=(), kwargs={"reason": reason})
    with pytest.raises(pytest.fail.Exception, match="non-empty keyword reason"):
        validate_exemption(marker, BodyActivity())


@pytest.mark.parametrize("activity", [BodyActivity(requests=1), BodyActivity(services=1)])
def test_no_app_marker_never_hides_operations(activity):
    marker = SimpleNamespace(args=(), kwargs={"reason": "static inspection"})
    with pytest.raises(pytest.fail.Exception, match="hid an HTTP request or services-layer call"):
        validate_exemption(marker, activity)


def test_unmarked_audit_operations_are_not_exempt():
    validate_exemption(None, BodyActivity(requests=1, services=1))
