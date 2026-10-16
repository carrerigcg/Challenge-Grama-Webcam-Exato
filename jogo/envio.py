"""POST da medição da feira para a API de produção.

Em background e silencioso: o jogo revela o valor na hora e nunca espera a
rede. Falha de envio não é problema do visitante.

A região é fixa em "Feira de Ciências" e não vem da calibração: um dia de
feira são dezenas de medições, e entrar como "Rod. Anchieta" contaminaria a
série temporal da rodovia com dado que não é dela.
"""
from __future__ import annotations

import os
import sys
import threading

import requests

REGIAO_DA_FEIRA = "Feira de Ciências"
TIMEOUT_S = 15


def montar_payload(resultado: dict) -> dict:
    altura = resultado.get("altura_cm")
    payload = {
        "regiao": REGIAO_DA_FEIRA,
        "altura_cm": altura if altura is not None else 0.0,
        # A API aceita MEDIA sem acento; o pipeline produz "MÉDIA".
        "nivel_risco": str(resultado.get("categoria", "")).replace("MÉDIA", "MEDIA"),
    }
    if resultado.get("temperatura_c") is not None:
        payload["temperatura_c"] = resultado["temperatura_c"]
    if resultado.get("clima"):
        payload["clima"] = resultado["clima"]
    return payload


def enviar(resultado: dict) -> None:
    chave = os.environ.get("API_KEY_WRITE")
    if not chave:
        print("AVISO: API_KEY_WRITE ausente, medição da feira não enviada",
              file=sys.stderr)
        return
    base = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
    try:
        resposta = requests.post(
            f"{base}/leituras",
            json=montar_payload(resultado),
            headers={"X-API-Key": chave},
            timeout=TIMEOUT_S,
        )
        if resposta.status_code >= 400:
            print(f"AVISO: API respondeu {resposta.status_code}", file=sys.stderr)
    except requests.RequestException as e:
        print(f"AVISO: envio para a API falhou ({e})", file=sys.stderr)


def enviar_em_background(resultado: dict) -> None:
    """Dispara e esquece. `requests` é síncrono e travaria o event loop."""
    threading.Thread(target=enviar, args=(resultado,), daemon=True).start()
