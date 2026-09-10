"""Tests for provenance attestation audit."""
from toxindb.trace import Trace, IngestEvent
from toxindb.provenance import audit_provenance


def test_provenance_clean_trace():
    trace = Trace()
    for i in range(10):
        trace.ingests.append(IngestEvent(
            doc_id=f"d-{i}", source="wiki", owner="wiki",
            namespace="ns", timestamp=float(i),
            content=f"Doc {i}", signature=f"sig-{i}", user_agent="ua",
        ))
    report = audit_provenance(trace)
    assert report.total_docs == 10
    assert report.signed_docs == 10
    assert report.unsigned_docs == 0
    assert len(report.issues) == 0


def test_provenance_multi_owner():
    trace = Trace()
    trace.ingests.append(IngestEvent(
        doc_id="d1", source="repo", owner="owner-a",
        namespace="ns", timestamp=1.0, content="c",
        signature="s1", user_agent="ua",
    ))
    trace.ingests.append(IngestEvent(
        doc_id="d2", source="repo", owner="owner-b",
        namespace="ns", timestamp=2.0, content="c",
        signature="s2", user_agent="ua",
    ))
    report = audit_provenance(trace)
    issues = [i for i in report.issues if i["type"] == "multi_owner_source"]
    assert len(issues) >= 1


def test_provenance_unsigned_among_signed():
    trace = Trace()
    trace.ingests.append(IngestEvent(
        doc_id="signed", source="repo", owner="owner",
        namespace="ns", timestamp=1.0, content="c",
        signature="sig", user_agent="ua",
    ))
    trace.ingests.append(IngestEvent(
        doc_id="unsigned", source="repo", owner="owner",
        namespace="ns", timestamp=2.0, content="c",
        signature=None, user_agent="ua",
    ))
    report = audit_provenance(trace)
    issues = [i for i in report.issues if i["type"] == "unsigned_among_signed"]
    assert len(issues) >= 1


def test_provenance_report_to_dict():
    trace = Trace()
    trace.ingests.append(IngestEvent(
        doc_id="d1", source="s", owner="o", namespace="ns",
        timestamp=1.0, content="c", signature="sig", user_agent="ua",
    ))
    report = audit_provenance(trace)
    d = report.to_dict()
    assert "total_docs" in d
    assert "issues" in d
    assert d["total_docs"] == 1
    assert d["signed_docs"] == 1


def test_provenance_empty_trace():
    trace = Trace()
    report = audit_provenance(trace)
    assert report.total_docs == 0
    assert report.unique_sources == 0


def test_provenance_source_summary():
    trace = Trace()
    trace.ingests.append(IngestEvent(
        doc_id="d1", source="repo", owner="owner",
        namespace="ns", timestamp=1.0, content="c",
        signature="s", user_agent="ua",
    ))
    report = audit_provenance(trace)
    assert report.source_owner_map["repo"] == "owner"


def test_provenance_multi_owner_summary():
    trace = Trace()
    trace.ingests.append(IngestEvent(
        doc_id="d1", source="repo", owner="a",
        namespace="ns", timestamp=1.0, content="c",
        signature="s", user_agent="ua",
    ))
    trace.ingests.append(IngestEvent(
        doc_id="d2", source="repo", owner="b",
        namespace="ns", timestamp=2.0, content="c",
        signature="s2", user_agent="ua",
    ))
    report = audit_provenance(trace)
    assert report.source_owner_map["repo"] == "MULTIPLE"


def test_provenance_signature_mismatch():
    trace = Trace()
    for i in range(8):
        trace.ingests.append(IngestEvent(
            doc_id=f"d-{i}", source="repo", owner="owner",
            namespace="ns", timestamp=float(i),
            content=f"Doc {i}", signature="dominant-sig", user_agent="ua",
        ))
    for i in range(3):
        trace.ingests.append(IngestEvent(
            doc_id=f"fake-{i}", source="repo", owner="owner",
            namespace="ns", timestamp=100.0 + i,
            content=f"Fake doc {i}", signature="fake-sig", user_agent="ua",
        ))
    report = audit_provenance(trace)
    issues = [i for i in report.issues if i["type"] == "signature_mismatch"]
    assert len(issues) >= 1
    assert issues[0]["count"] == 3
