"""App do jogo da feira: rotas, WebSockets e broadcast.

Cola, sem regra de negócio. A regra está em `jogo/sala.py`.

Os tokens são lidos a cada requisição, e não no import do módulo como em
`api/main.py`: aqui os testes exercitam token certo, errado e ausente, e
recarregar o módulo a cada caso seria frágil.
"""
from __future__ import annotations

import io
import logging
import os
import secrets
from pathlib import Path

import qrcode
import qrcode.image.svg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from jogo.medicao import Medidor
from jogo.sala import Sala

PASTA = Path(__file__).parent

app = FastAPI(
    title="Grama Webcam — jogo da feira",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
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
    """403 sem token válido. Esconder o botão no CSS não é controle de acesso.

    O `not esperado` e o `token is None` são checados antes da comparação: sem
    eles, variável ausente e token ausente dariam `None != None`, que é falso,
    e o palco abriria para qualquer um numa URL pública.

    `compare_digest` em bytes, não em `str`: com `str` não-ASCII ele levanta
    `TypeError`, que viraria 500 em vez de 403 — um `?token=é` derrubaria a
    rota. O timing não é a ameaça real num jogo de altura de grama, mas a
    comparação certa custa uma linha.

    `.strip()` na variável porque token colado no painel da Render com espaço
    ou `\\n` no fim trancaria o apresentador para fora, na feira, sem pista do
    motivo. O token que chega na URL não é estripado: ali um espaço é mesmo
    divergência.
    """
    esperado = (os.environ.get("HOST_TOKEN") or "").strip()
    if not esperado or token is None:
        raise HTTPException(status_code=403, detail="Token de host inválido.")
    if not secrets.compare_digest(token.encode("utf-8"), esperado.encode("utf-8")):
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
    resposta = _html("palco.html")
    # O token viaja na query string, e requisição same-origin (o CSS, o JS da
    # própria página) manda a URL completa no `Referer` — o segredo cairia no
    # log de acesso do Render. `no-referrer` corta isso.
    resposta.headers["Referrer-Policy"] = "no-referrer"
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


@app.get("/qr.svg")
def qr(request: Request):
    """QR da URL pública do jogo, gerado no servidor.

    Em Python e não com um `qrcode.js` de CDN: script de terceiro é
    exatamente o que falha quando a rede da feira oscila.
    """
    url = (os.environ.get("JOGO_URL_PUBLICA") or "").strip()
    if not url:
        url = str(request.base_url)
        # Em LAN isso é exatamente o que se quer. Atrás do proxy da Render, o
        # esquema pode sair `http` e o `Host` vem de header controlável pelo
        # cliente — o QR apontaria para o lugar errado em silêncio.
        logging.getLogger(__name__).warning(
            "JOGO_URL_PUBLICA não definida; QR gerado a partir de %s", url
        )
    imagem = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO()
    imagem.save(buffer)
    return Response(content=buffer.getvalue(), media_type="image/svg+xml")
