"""Tests for TX-008 LangChain Double-Retrieval detector."""
from toxindb.trace import Trace, QueryEvent
from toxindb.heuristics import DoubleRetrievalDetector


def test_tx008_fires_on_double_retrieval():
    trace = Trace()
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="same query text",
        timestamp=100.0, retrieved_doc_ids=["d1", "d2", "d3"],
    ))
    trace.queries.append(QueryEvent(
        query_id="q2", query_text="same query text",
        timestamp=105.0, retrieved_doc_ids=["d1", "d2", "d4"],
    ))
    det = DoubleRetrievalDetector(window_seconds=60.0)
    alerts = det.detect(trace)
    assert any(a.heuristic_id == "TX-008" for a in alerts)


def test_tx008_quiet_different_queries():
    trace = Trace()
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="query A",
        timestamp=100.0, retrieved_doc_ids=["d1", "d2"],
    ))
    trace.queries.append(QueryEvent(
        query_id="q2", query_text="query B",
        timestamp=105.0, retrieved_doc_ids=["d1", "d2"],
    ))
    det = DoubleRetrievalDetector(window_seconds=60.0)
    alerts = det.detect(trace)
    assert not any(a.heuristic_id == "TX-008" for a in alerts)


def test_tx008_quiet_outside_window():
    trace = Trace()
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="same query text",
        timestamp=100.0, retrieved_doc_ids=["d1", "d2", "d3"],
    ))
    trace.queries.append(QueryEvent(
        query_id="q2", query_text="same query text",
        timestamp=200.0, retrieved_doc_ids=["d1", "d2", "d3"],
    ))
    det = DoubleRetrievalDetector(window_seconds=60.0)
    alerts = det.detect(trace)
    assert not any(a.heuristic_id == "TX-008" for a in alerts)


def test_tx008_quiet_insufficient_overlap():
    trace = Trace()
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="same query text",
        timestamp=100.0, retrieved_doc_ids=["d1", "d2"],
    ))
    trace.queries.append(QueryEvent(
        query_id="q2", query_text="same query text",
        timestamp=105.0, retrieved_doc_ids=["d1", "d3"],
    ))
    det = DoubleRetrievalDetector(window_seconds=60.0)
    alerts = det.detect(trace)
    assert not any(a.heuristic_id == "TX-008" for a in alerts)
