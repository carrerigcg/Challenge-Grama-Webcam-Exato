"""Testes do cliente Open-Meteo."""
import requests

import clima


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_traduz_weather_code_para_descricao(monkeypatch):
    monkeypatch.setattr(
        requests, "get",
        lambda *a, **k: _FakeResponse(
            {"current": {"temperature_2m": 21.5, "weather_code": 3}}
        ),
    )
    assert clima.buscar_clima(-23.55, -46.63) == (21.5, "Nublado")


def test_weather_code_desconhecido_vira_desconhecido(monkeypatch):
    monkeypatch.setattr(
        requests, "get",
        lambda *a, **k: _FakeResponse(
            {"current": {"temperature_2m": 19.0, "weather_code": 999}}
        ),
    )
    assert clima.buscar_clima(-23.55, -46.63) == (19.0, "Desconhecido")


def test_falha_de_rede_retorna_none_none(monkeypatch):
    def _boom(*a, **k):
        raise requests.RequestException("sem rede")

    monkeypatch.setattr(requests, "get", _boom)
    assert clima.buscar_clima(-23.55, -46.63) == (None, None)


def test_buscar_clima_repassa_coordenadas_recebidas(monkeypatch):
    chamadas = {}

    def _captura(url, params, timeout):
        chamadas["params"] = params
        return _FakeResponse(
            {"current": {"temperature_2m": 18.0, "weather_code": 0}}
        )

    monkeypatch.setattr(requests, "get", _captura)

    assert clima.buscar_clima(clima.SP_LAT, clima.SP_LON) == (18.0, "Ensolarado")
    assert chamadas["params"]["latitude"] == clima.SP_LAT
    assert chamadas["params"]["longitude"] == clima.SP_LON
