"""Tests for the OpenLibrary book search autocomplete endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

from .conftest import make_client


async def test_book_search_returns_results(engine, db, test_user):
    """Search with a valid query returns book suggestions."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "docs": [
            {
                "title": "The Name of the Wind",
                "author_name": ["Patrick Rothfuss"],
                "number_of_pages_median": 662,
            },
            {
                "title": "The Wise Man's Fear",
                "author_name": ["Patrick Rothfuss"],
                "number_of_pages_median": 994,
            },
        ]
    }

    with patch("app.main.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.get.return_value = mock_response
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_instance

        async with make_client(engine, test_user) as client:
            resp = await client.get("/api/book-search?q=name+of+the+wind")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["title"] == "The Name of the Wind"
    assert data[0]["author"] == "Patrick Rothfuss"
    assert data[0]["page_count"] == 662


async def test_book_search_short_query_returns_empty(engine, db, test_user):
    """Queries shorter than 3 characters return empty list."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/api/book-search?q=ab")

    assert resp.status_code == 200
    assert resp.json() == []


async def test_book_search_empty_query_returns_empty(engine, db, test_user):
    """Empty query returns empty list."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/api/book-search?q=")

    assert resp.status_code == 200
    assert resp.json() == []


async def test_book_search_handles_missing_fields(engine, db, test_user):
    """Results with missing author or page count are handled gracefully."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "docs": [
            {
                "title": "Unknown Book",
            },
        ]
    }

    with patch("app.main.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.get.return_value = mock_response
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_instance

        async with make_client(engine, test_user) as client:
            resp = await client.get("/api/book-search?q=unknown+book")

    data = resp.json()
    assert len(data) == 1
    assert data[0]["author"] == ""
    assert data[0]["page_count"] is None


async def test_book_search_api_failure_returns_empty(engine, db, test_user):
    """If OpenLibrary is down, return empty list instead of error."""
    with patch("app.main.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.get.side_effect = Exception("Connection failed")
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_instance

        async with make_client(engine, test_user) as client:
            resp = await client.get("/api/book-search?q=some+book")

    assert resp.status_code == 200
    assert resp.json() == []
