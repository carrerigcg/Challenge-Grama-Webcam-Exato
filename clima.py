"""Cliente do Open-Meteo — busca temperatura e condição do tempo.

Vive na raiz (não em api/) porque é a estação que chama, não a API:
o IP compartilhado do Render sofre rate-limit 429 por vizinho barulhento,
enquanto o IP residencial da estação tem cota própria de 10k/dia.
"""
from __future__ import annotations

import sys

import requests

# São Paulo/SP — usado pra buscar clima no Open-Meteo
SP_LAT = -23.55
SP_LON = -46.63

# Mapeia weather_code (padrão WMO) do Open-Meteo pra descrição simples
WEATHER_CODE_MAP = {
    0: "Ensolarado",
    1: "Parcialmente nublado",
    2: "Parcialmente nublado",
    3: "Nublado",
    45: "Neblina",
    48: "Neblina",
    51: "Chuvisco",
    53: "Chuvisco",
    55: "Chuvisco",
    61: "Chuvoso",
    63: "Chuvoso",
    65: "Chuva forte",
    71: "Neve",
    73: "Neve",
    75: "Neve forte",
    80: "Pancadas de chuva",
    81: "Pancadas de chuva",
    82: "Pancadas de chuva fortes",
    95: "Tempestade",
    96: "Tempestade com granizo",
    99: "Tempestade com granizo",
}


def buscar_clima(lat: float, lon: float) -> tuple[float | None, str | None]:
    """Consulta Open-Meteo. Retorna (temperatura_c, clima) ou (None, None) se falhar."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,weather_code",
        "timezone": "America/Sao_Paulo",
    }
    try:
        r = requests.get(url, params=params, timeout=5)
        r.raise_for_status()
        dados = r.json()["current"]
        temperatura = dados["temperature_2m"]
        clima = WEATHER_CODE_MAP.get(dados["weather_code"], "Desconhecido")
        return temperatura, clima
    except (requests.RequestException, KeyError, ValueError) as e:
        print(
            f"AVISO: buscar_clima falhou: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return None, None
