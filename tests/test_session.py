"""Test session tracking."""
from toxindb import session_tracker


def test_session_tracker():
    st = session_tracker.SessionTracker()
    s = st.get_or_create('s1', agent_id='a1')
    assert s.session_id == 's1'
    st.record_turn('s1', 'q', ['d1', 'd2'])
    assert len(st.sessions['s1'].turns) == 1
