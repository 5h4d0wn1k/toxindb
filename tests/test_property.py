"""Property-based tests."""
try:
    from hypothesis import given, strategies as st
    HYP = True
except Exception:
    HYP = False


def test_property_placeholder():
    # Keep as simple test if hypothesis not installed
    assert True


if HYP:
    @given(st.integers(min_value=1, max_value=100))
    def test_metrics_property(tp):
        from toxindb import metrics
        tpr, fpr, prec, rec, f1 = metrics.compute_metrics(tp, 1, 10, 1)
        assert 0 <= tpr <= 1
        assert 0 <= fpr <= 1
