import pytest


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    """Enforce the offline contract: any outbound connect during tests fails loudly."""

    def guard(*args, **kwargs):
        raise RuntimeError("network access is blocked in scoria tests (offline contract)")

    monkeypatch.setattr("socket.socket.connect", guard)
    monkeypatch.setattr("socket.socket.connect_ex", lambda self, address: 1)
    monkeypatch.setattr("socket.create_connection", guard)
