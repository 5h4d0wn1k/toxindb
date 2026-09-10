"""Tests for TX-004 Canary Resurgence detector."""
from toxindb.trace import Trace, IngestEvent, QueryEvent, CanaryClaim
from toxindb.heuristics import CanaryResurgenceDetector


def test_tx004_fires_on_canary_in_output():
    trace = Trace()
    canary = CanaryClaim(
        claim_id="test-canary",
        text="SECRET-CANARY-CLAIM-12345",
        planted_in_doc_id="canary-doc",
        planted_at=100.0,
    )
    trace.canaries.append(canary)
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=200.0,
        retrieved_doc_ids=["canary-doc"],
        output_text="Here is the answer: SECRET-CANARY-CLAIM-12345 is true.",
    ))
    det = CanaryResurgenceDetector()
    alerts = det.detect(trace)
    assert len(alerts) == 1
    assert alerts[0].heuristic_id == "TX-004"
    assert alerts[0].severity == "critical"


def test_tx004_quiet_when_canary_not_in_output():
    trace = Trace()
    canary = CanaryClaim(
        claim_id="test-canary",
        text="SECRET-CANARY-CLAIM-12345",
        planted_in_doc_id="canary-doc",
        planted_at=100.0,
    )
    trace.canaries.append(canary)
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=200.0,
        retrieved_doc_ids=["canary-doc"],
        output_text="Normal response without any canary content.",
    ))
    det = CanaryResurgenceDetector()
    alerts = det.detect(trace)
    assert len(alerts) == 0


def test_tx004_quiet_empty_output():
    trace = Trace()
    canary = CanaryClaim(
        claim_id="c1", text="CANARY-X",
        planted_in_doc_id="d1", planted_at=100.0,
    )
    trace.canaries.append(canary)
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=200.0,
        output_text="",
    ))
    det = CanaryResurgenceDetector()
    alerts = det.detect(trace)
    assert len(alerts) == 0


def test_tx004_case_insensitive():
    trace = Trace()
    canary = CanaryClaim(
        claim_id="c2", text="MySecretCanary",
        planted_in_doc_id="d2", planted_at=100.0,
    )
    trace.canaries.append(canary)
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=200.0,
        output_text="Result: mysecretcanary found in data.",
    ))
    det = CanaryResurgenceDetector()
    alerts = det.detect(trace)
    assert len(alerts) == 1
