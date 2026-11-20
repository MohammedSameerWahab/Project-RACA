import pytest

from src.retrieval.keyword import KeywordRetriever


def test_natural_language_query_terms_are_or_combined():
    assert KeywordRetriever._search_query(
        "Where is the transcription entry point?"
    ) == "Where OR is OR the OR transcription OR entry OR point"


def test_keyword_query_without_terms_is_rejected():
    with pytest.raises(ValueError, match="searchable terms"):
        KeywordRetriever._search_query("?!")
