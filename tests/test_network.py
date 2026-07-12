import httpx
import pytest

from atlas import network


@pytest.mark.asyncio
async def test_check_connectivity_success(monkeypatch) -> None:
    async def fake_request(self, method: str, url: str):
        return httpx.Response(204)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    result = await network.check_connectivity(
        network.ConnectivityTarget(
            label="Domestic",
            url="https://example.test/generate_204",
        )
    )

    assert result.status == "up"
    assert result.status_code == 204
    assert result.error is None
    assert result.latency_ms is not None
    assert result.last_checked is not None


@pytest.mark.asyncio
async def test_check_connectivity_unexpected_status(monkeypatch) -> None:
    async def fake_request(self, method: str, url: str):
        return httpx.Response(503)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    result = await network.check_connectivity(
        network.ConnectivityTarget(
            label="International",
            url="https://example.test/generate_204",
        )
    )

    assert result.status == "down"
    assert result.status_code == 503
    assert result.error == "Unexpected status code 503"


@pytest.mark.asyncio
async def test_check_connectivity_http_error(monkeypatch) -> None:
    async def fake_request(self, method: str, url: str):
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    result = await network.check_connectivity(
        network.ConnectivityTarget(
            label="International",
            url="https://example.test/generate_204",
        )
    )

    assert result.status == "down"
    assert result.status_code is None
    assert result.error == "connection failed"


@pytest.mark.asyncio
async def test_get_network_connectivity_returns_domestic_and_international(monkeypatch) -> None:
    async def fake_check_connectivity(target: network.ConnectivityTarget):
        return network.ConnectivityResult(
            label=target.label,
            target=target.url,
            status="up",
        )

    monkeypatch.setattr(network, "check_connectivity", fake_check_connectivity)

    result = await network.get_network_connectivity()

    assert result.domestic.label == "Domestic"
    assert result.international.label == "International"
    assert result.domestic.status == "up"
    assert result.international.status == "up"
