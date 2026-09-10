"""Tests for canary lifecycle."""
from toxindb.trace import Trace, IngestEvent, QueryEvent
from toxindb.canary import (
    generate_canary,
    plant_canary_in_trace,
    monitor_canaries,
    check_canary_resurgence,
)


def test_generate_canary():
    c = generate_canary("seed", 0)
    assert c.claim_id
    assert "CANARY-" in c.text
    assert c.planted_in_doc_id.startswith("canary-doc-")


def test_generate_canary_deterministic():
    c1 = generate_canary("seed", 0)
    c2 = generate_canary("seed", 0)
    assert c1.claim_id == c2.claim_id
    assert c1.text == c2.text


def test_generate_canary_different_seeds():
    c1 = generate_canary("seed-a", 0)
    c2 = generate_canary("seed-b", 0)
    assert c1.claim_id != c2.claim_id


def test_plant_canary_in_trace():
    trace = Trace()
    canary = generate_canary("test", 0)
    doc = plant_canary_in_trace(trace, canary, timestamp=100.0)
    assert doc.doc_id == canary.planted_in_doc_id
    assert doc.source == "canary-source"
    assert len(trace.ingests) == 1
    assert len(trace.canaries) == 1
    assert canary.planted_at == 100.0


def test_check_canary_resurgence_detected():
    trace = Trace()
    canary = generate_canary("test", 0)
    plant_canary_in_trace(trace, canary, 100.0)
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=200.0,
        output_text=f"Answer: {canary.text} done.",
    ))
    results = check_canary_resurgence(trace)
    assert len(results) == 1
    assert results[0]["resurfaced"] is True
    assert results[0]["query_id"] == "q1"


def test_check_canary_resurgence_not_detected():
    trace = Trace()
    canary = generate_canary("test", 0)
    plant_canary_in_trace(trace, canary, 100.0)
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=200.0,
        output_text="Normal output without canary.",
    ))
    results = check_canary_resurgence(trace)
    assert len(results) == 1
    assert results[0]["resurfaced"] is False


def test_monitor_canaries():
    trace = Trace()
    canary = generate_canary("test", 0)
    plant_canary_in_trace(trace, canary, 100.0)
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=200.0,
        output_text=f"Contains: {canary.text}",
    ))
    results = monitor_canaries(trace)
    assert len(results) == 1
    assert results[0].detected is True
    assert results[0].detected_at == 200.0


def test_canary_multiple_canaries():
    trace = Trace()
    for i in range(3):
        c = generate_canary("test", i)
        plant_canary_in_trace(trace, c, 100.0 + i)
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=200.0,
        output_text=f"Answer: {generate_canary('test', 1).text}",
    ))
    results = check_canary_resurgence(trace)
    assert sum(1 for r in results if r["resurfaced"]) == 1
