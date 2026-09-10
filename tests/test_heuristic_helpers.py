"""Tests for heuristic helper functions."""
from toxindb.heuristics import _tokens, _token_set, _jaccard, _cosine_bow, _lexical_distance


def test_tokens_basic():
    result = _tokens("Hello World foo")
    assert result == ["hello", "world", "foo"]


def test_tokens_filters_short():
    result = _tokens("a bb ccc dddd")
    assert "a" not in result
    assert "bb" in result


def test_tokens_empty():
    assert _tokens("") == []


def test_token_set():
    result = _token_set("hello world hello")
    assert result == {"hello", "world"}


def test_jaccard_identical():
    assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0


def test_jaccard_disjoint():
    assert _jaccard({"a"}, {"b"}) == 0.0


def test_jaccard_partial():
    result = _jaccard({"a", "b"}, {"b", "c"})
    assert abs(result - 1 / 3) < 1e-9


def test_jaccard_empty():
    assert _jaccard(set(), set()) == 0.0


def test_cosine_bow_identical():
    val = _cosine_bow("hello world", "hello world")
    assert abs(val - 1.0) < 1e-9


def test_cosine_bow_disjoint():
    assert _cosine_bow("alpha", "bravo") == 0.0


def test_cosine_bow_partial():
    result = _cosine_bow("alpha bravo charlie", "alpha bravo delta")
    assert 0.0 < result < 1.0


def test_cosine_bow_empty():
    assert _cosine_bow("", "hello world") == 0.0
    assert _cosine_bow("hello world", "") == 0.0
    assert _cosine_bow("", "") == 0.0


def test_lexical_distance_identical():
    assert _lexical_distance("hello world", "hello world") == 0.0


def test_lexical_distance_disjoint():
    assert _lexical_distance("alpha", "bravo") == 1.0


def test_lexical_distance_partial():
    result = _lexical_distance("alpha bravo charlie", "alpha bravo delta")
    assert 0.0 < result < 1.0


def test_lexical_distance_empty():
    assert _lexical_distance("", "hello") == 1.0


def test_lexical_distance_stopwords():
    result = _lexical_distance("the quick brown fox", "quick brown fox jumps")
    assert result < 0.5
