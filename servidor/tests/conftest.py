import fastmcp
import pytest


@pytest.fixture(autouse=True)
def _fastmcp_home_temporario(tmp_path, monkeypatch):
    """O OAuthProxy grava clientes e tokens em settings.home; nos testes, fica numa pasta temporária."""
    monkeypatch.setattr(fastmcp.settings, "home", tmp_path / "fastmcp")
