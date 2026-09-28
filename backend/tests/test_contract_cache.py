"""
Phase 2.5 verification: BitgetClient.get_contracts() class-level cache.

These exact assertions were run standalone against the real
app.data.bitget_client module (mocking requests.get, no network needed)
before being committed here — confirmed passing, including the case that
matters most for a safety cache: a failed refresh must not destroy a
previously-valid cached value.
"""
import time
from unittest.mock import patch, MagicMock
import pytest
import requests
from app.data.bitget_client import BitgetClient


def _response(payload):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=payload)
    return resp


@pytest.fixture()
def client():
    c = BitgetClient()
    c._contracts_cache.clear()  # isolate from other tests / prior runs (class-level cache)
    c._CONTRACTS_CACHE_TTL_SECONDS = 300
    yield c
    c._contracts_cache.clear()


def test_first_call_hits_api(client):
    with patch("app.data.bitget_client.requests.get", return_value=_response({"data": ["v1"]})) as mock_get:
        result = client.get_contracts()
        assert mock_get.call_count == 1
        assert result == {"data": ["v1"]}


def test_second_call_within_ttl_uses_cache(client):
    with patch("app.data.bitget_client.requests.get", return_value=_response({"data": ["v1"]})):
        client.get_contracts()
    with patch("app.data.bitget_client.requests.get", return_value=_response({"data": ["should-not-be-seen"]})) as mock_get:
        result = client.get_contracts()
        assert mock_get.call_count == 0
        assert result == {"data": ["v1"]}


def test_cache_expires_after_ttl(client):
    client._CONTRACTS_CACHE_TTL_SECONDS = 0.05
    # Force a fresh fetched_at under the short TTL, rather than relying on
    # whatever timestamp an earlier test in this run left behind.
    with patch("app.data.bitget_client.requests.get", return_value=_response({"data": ["v1"]})):
        client.get_contracts(force_refresh=True)
    time.sleep(0.15)
    with patch("app.data.bitget_client.requests.get", return_value=_response({"data": ["v3"]})) as mock_get:
        result = client.get_contracts()
        assert mock_get.call_count == 1
        assert result == {"data": ["v3"]}


def test_failed_refresh_preserves_previous_cache(client):
    with patch("app.data.bitget_client.requests.get", return_value=_response({"data": ["good"]})):
        client.get_contracts(force_refresh=True)

    with patch("app.data.bitget_client.requests.get", side_effect=requests.RequestException("network down")):
        with pytest.raises(requests.RequestException):
            client.get_contracts(force_refresh=True)

    # The failed force_refresh must not have overwritten or cleared the
    # previously-good cached value.
    with patch("app.data.bitget_client.requests.get", return_value=_response({"data": ["should-not-be-called"]})) as mock_get:
        result = client.get_contracts()
        assert mock_get.call_count == 0
        assert result == {"data": ["good"]}
