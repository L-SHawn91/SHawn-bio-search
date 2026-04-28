"""Shared pytest fixtures for SHawn-bio-search tests."""
import pytest


@pytest.fixture(autouse=True)
def clear_fetch_cache():
    """Clear the in-memory fetch cache before each test to prevent cross-test pollution."""
    import shawn_bio_search.search as _s
    _s._FETCH_CACHE.clear()
    yield
    _s._FETCH_CACHE.clear()


@pytest.fixture(autouse=True)
def clear_warn_state():
    """Reset the _warn_once dedup set before each test."""
    import shawn_bio_search.text_utils as _tu
    _tu._WARNED.clear()
    yield
    _tu._WARNED.clear()
