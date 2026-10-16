"""Rotas e WebSockets do jogo da feira.

Nenhuma fixture de `conftest.py` é usada: o jogo não tem banco. Os tokens são
injetados por `monkeypatch.setenv` e lidos a cada requisição, então não é
preciso recarregar o módulo entre casos.
"""
import pytest
from fastapi.testclient import TestClient

HOST_TOKEN = "token-de-host-de-teste"
PONTE_TOKEN = "token-de-ponte-de-teste"


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("HOST_TOKEN", HOST_TOKEN)
    monkeypatch.setenv("PONTE_TOKEN", PONTE_TOKEN)
    from jogo.main import app, medidor, sala

    # Estado global do processo: zera entre testes para não vazar jogador de um
    # caso para o outro.
    sala.nova_rodada()
    medidor.canal = None
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_raiz_serve_a_tela_do_controle(client):
    resposta = client.get("/")
    assert resposta.status_code == 200
    assert "text/html" in resposta.headers["content-type"]


def test_host_sem_token_responde_403(client):
    assert client.get("/host").status_code == 403


def test_host_com_token_errado_responde_403(client):
    assert client.get("/host?token=errado").status_code == 403


def test_host_com_token_certo_serve_a_tela_do_palco(client):
    resposta = client.get(f"/host?token={HOST_TOKEN}")
    assert resposta.status_code == 200
    assert "text/html" in resposta.headers["content-type"]


def test_host_responde_403_se_o_token_nao_esta_configurado(client, monkeypatch):
    monkeypatch.delenv("HOST_TOKEN")
    assert client.get(f"/host?token={HOST_TOKEN}").status_code == 403


def test_qr_devolve_svg(client):
    resposta = client.get("/qr.svg")
    assert resposta.status_code == 200
    assert "svg" in resposta.headers["content-type"]
    assert b"<svg" in resposta.content


def test_qr_usa_a_url_publica_configurada(client, monkeypatch):
    """Prova que a variável entra no QR, não só que a rota responde.

    Status 200 passaria com a variável sendo ignorada — e aí o QR impresso
    apontaria para o endereço errado, o que só se descobre com um celular na
    mão, na feira. Sem decodificar o QR (seria dependência nova): URLs
    diferentes têm de gerar SVGs diferentes, e a mesma URL, o mesmo SVG.
    """
    monkeypatch.setenv("JOGO_URL_PUBLICA", "https://um.test/")
    um = client.get("/qr.svg").content
    monkeypatch.setenv("JOGO_URL_PUBLICA", "https://outro.test/")
    outro = client.get("/qr.svg").content
    monkeypatch.setenv("JOGO_URL_PUBLICA", "https://um.test/")
    um_de_novo = client.get("/qr.svg").content

    assert b"<svg" in um and b"<svg" in outro
    assert um != outro, "o QR não mudou com a URL: a variável está sendo ignorada"
    assert um == um_de_novo, "o QR não é determinístico para a mesma URL"


def test_saude_responde_sem_token(client):
    resposta = client.get("/saude")
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "ok"
