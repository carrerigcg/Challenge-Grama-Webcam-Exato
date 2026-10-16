"""App do jogo da feira: rotas, WebSockets e broadcast.

Cola, sem regra de negócio. A regra está em `jogo/sala.py`.

Os tokens são lidos a cada requisição, e não no import do módulo como em
`api/main.py`: aqui os testes exercitam token certo, errado e ausente, e
recarregar o módulo a cada caso seria frágil.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import qrcode
import qrcode.image.svg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from jogo.medicao import Medidor
from jogo.sala import Sala

PASTA = Path(__file__).parent

app = FastAPI(title="Grama Webcam — jogo da feira", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=PASTA / "static"), name="static")

# Estado do processo. Uma sala só, um medidor só: é um jogo por feira.
# NUNCA reatribua `sala = Sala()` para zerar — use `sala.nova_rodada()`. Uma
# instância nova recomeça o ticket de medição em 0, e ele volta a colidir com
# o de uma task que ainda esteja em voo, reabrindo a corrida que o ticket
# existe para fechar.
sala = Sala()
medidor = Medidor()


def _html(nome: str) -> HTMLResponse:
    return HTMLResponse((PASTA / "templates" / nome).read_text(encoding="utf-8"))


def _conferir_token_de_host(token: str | None) -> None:
    """403 sem token válido. Esconder o botão no CSS não é controle de acesso."""
    esperado = os.environ.get("HOST_TOKEN")
    if not esperado or token != esperado:
        raise HTTPException(status_code=403, detail="Token de host inválido.")


@app.get("/saude")
def saude():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def controle():
    return _html("controle.html")


@app.get("/host", response_class=HTMLResponse)
def palco(token: str | None = None):
    _conferir_token_de_host(token)
    return _html("palco.html")


@app.get("/qr.svg")
def qr(request: Request):
    """QR da URL pública do jogo, gerado no servidor.

    Em Python e não com um `qrcode.js` de CDN: script de terceiro é
    exatamente o que falha quando a rede da feira oscila.
    """
    url = os.environ.get("JOGO_URL_PUBLICA") or str(request.base_url)
    imagem = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO()
    imagem.save(buffer)
    return Response(content=buffer.getvalue(), media_type="image/svg+xml")
