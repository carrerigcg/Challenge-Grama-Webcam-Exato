"""App do jogo da feira: rotas, WebSockets e broadcast.

Cola, sem regra de negócio. A regra está em `jogo/sala.py`.

Os tokens são lidos a cada requisição, e não no import do módulo como em
`api/main.py`: aqui os testes exercitam token certo, errado e ausente, e
recarregar o módulo a cada caso seria frágil.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import secrets
from pathlib import Path

import qrcode
import qrcode.image.svg
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from jogo.difusor import Difusor
from jogo.envio import enviar_em_background
from jogo.medicao import ErroDeMedicao, Medidor
from jogo.sala import ErroDeJogo, Estado, Sala

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


# --- broadcast ---------------------------------------------------------------

# Todos os clientes recebem o MESMO payload. Nenhum tem versão especial: é o que
# mantém o broadcast trivial e impede vazamento acidental de chute.


def estado_atual() -> dict:
    return {
        "tipo": "estado",
        "estado": sala.estado.value,
        "aberta": sala.aberta,
        "ponte_conectada": medidor.conectado,
        # Sem o `id`: ele é a credencial que o `chutar` e o `voltar` exigem, e
        # no broadcast qualquer visitante com a aba Rede aberta chutaria em
        # nome de outro. O celular acha a própria linha pelo `nome`, que a
        # sala garante único por rodada.
        "jogadores": [
            {"nome": j.nome, "chutou": j.chute_cm is not None}
            for j in sala.jogadores
        ],
        "quantos_chutaram": sala.quantos_chutaram(),
        "altura_cm": sala.altura_cm,
        "margem_cm": sala.margem_cm,
        "categoria": sala.categoria,
        "imagem_b64": sala.imagem_b64,
        "erro": sala.erro,
        # Só em RESULTADO: a sala devolve o ranking já em REVELANDO (o palco
        # poderia querer), mas o payload é um só para todos, e mandá-lo antes
        # entrega o vencedor ao celular antes de a animação revelar na tela
        # grande. O palco não precisa dele em REVELANDO — ali ele só anima o
        # contador.
        "ranking": sala.ranking() if sala.estado is Estado.RESULTADO else [],
    }


# Declarado depois de `estado_atual`, porque recebe a referência dela.
difusor = Difusor(estado_atual)


# --- WebSocket dos jogadores -------------------------------------------------


@app.websocket("/ws/jogador")
async def ws_jogador(ws: WebSocket):
    await ws.accept()
    difusor.adicionar(ws)
    try:
        while True:
            try:
                msg = await ws.receive_json()
            except ValueError:
                # Texto que não é JSON. Não derruba o socket: a URL é pública
                # e qualquer cliente pode mandar qualquer coisa.
                await ws.send_json({"tipo": "erro", "mensagem": "Mensagem inválida."})
                continue
            if not isinstance(msg, dict):
                await ws.send_json({"tipo": "erro", "mensagem": "Mensagem inválida."})
                continue
            cmd = msg.get("cmd")
            try:
                if cmd == "entrar":
                    nome = msg.get("nome")
                    if not isinstance(nome, str):
                        # `str(["Ana"])` criaria um jogador chamado `['Ana']`.
                        raise ErroDeJogo("Digite um nome.")
                    jogador = sala.entrar(nome)
                    await ws.send_json(
                        {"tipo": "voce", "id": jogador.id, "nome": jogador.nome}
                    )
                elif cmd == "voltar":
                    jogador = sala.jogador(str(msg.get("id", "")))
                    await ws.send_json(
                        {"tipo": "voce", "id": jogador.id, "nome": jogador.nome}
                    )
                elif cmd == "chutar":
                    try:
                        valor = float(msg.get("valor_cm"))
                    except (TypeError, ValueError, OverflowError):
                        # `OverflowError` é um inteiro de 400 dígitos; sem ele
                        # no except, o handler morre e o socket cai.
                        raise ErroDeJogo("Digite um número.") from None
                    sala.chutar_por_id(str(msg.get("id", "")), valor)
                else:
                    # Comandos de host não existem neste socket: mandar na mão
                    # não faz nada.
                    raise ErroDeJogo("Comando desconhecido.")
            except ErroDeJogo as e:
                await ws.send_json({"tipo": "erro", "mensagem": str(e)})
                continue
            await difusor.transmitir()
    except WebSocketDisconnect:
        pass
    finally:
        difusor.remover(ws)


# --- WebSocket do palco ------------------------------------------------------


@app.websocket("/ws/palco")
async def ws_palco(ws: WebSocket):
    """Palco sem token: só observa. Os comandos vivem em `/ws/host`."""
    await ws.accept()
    difusor.adicionar(ws)
    try:
        # Dentro do `try`: se o cliente cair aqui, o `finally` ainda o remove.
        # Transmite para todos, não só para o recém-chegado: é o mesmo payload.
        await difusor.transmitir()
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        difusor.remover(ws)


# --- revelação ---------------------------------------------------------------

# Cronometrada pelo servidor, não disparada pelo palco: um palco fechado ou
# travado deixaria todos os celulares presos em REVELANDO para sempre.
# 2,2s é a animação do contador; a sobra deixa o número parado um instante.
DURACAO_REVELACAO_S_PADRAO = 2.6


def _duracao_revelacao() -> float:
    return float(os.environ.get("DURACAO_REVELACAO_S", DURACAO_REVELACAO_S_PADRAO))


# O asyncio só guarda referência fraca para tasks soltas, e uma task coletada
# no meio da medição morre em silêncio, deixando a sala presa em MEDINDO.
_tarefas_em_voo: set[asyncio.Task] = set()


async def _medir_e_revelar(ticket: int) -> None:
    """Pede a medição, revela e fecha. Cada passo é descartável por `ticket`.

    O ticket vem do `iniciar_medicao` e identifica a rodada. Se o apresentador
    resetar a sala no meio, a sala recusa tudo que chegar com ticket velho e
    esta task some sem efeito — é o que impede a resposta de uma rodada que já
    acabou de coroar um vencedor contra uma medida que não é dele.
    """
    try:
        resultado = await medidor.medir()
        # Dentro do try de propósito: um payload sem `altura_cm` levantaria
        # KeyError aqui, e fora do try isso deixaria a sala presa em MEDINDO
        # para sempre, com só o "nova rodada" como escape.
        altura = resultado["altura_cm"]
    except ErroDeMedicao as e:
        sala.falhar_medicao(ticket, str(e))
        await difusor.transmitir()
        return
    except Exception as e:
        sala.falhar_medicao(ticket, f"Falha inesperada na medição: {e}")
        await difusor.transmitir()
        return

    try:
        aceito = sala.concluir_medicao(
            ticket,
            altura_cm=altura,
            margem_cm=resultado.get("margem_cm"),
            categoria=resultado.get("categoria", ""),
            imagem_b64=resultado.get("imagem_b64"),
        )
    except ValueError as e:
        # A sala recusa NaN, infinito e negativo: seriam serializados como
        # tokens inválidos de JSON e derrubariam todos os clientes de uma vez.
        sala.falhar_medicao(ticket, f"Medição inválida: {e}")
        await difusor.transmitir()
        return

    # A grama foi medida de verdade, então o dado vai pra API mesmo quando a
    # rodada já acabou — a API guarda leitura bruta, não resultado de jogo.
    enviar_em_background(resultado)
    if not aceito:
        return  # rodada obsoleta: sem transmitir e sem dormir a animação

    await difusor.transmitir()
    await asyncio.sleep(_duracao_revelacao())
    sala.revelacao_terminou(ticket)
    await difusor.transmitir()


# --- WebSocket do host -------------------------------------------------------


@app.websocket("/ws/host")
async def ws_host(ws: WebSocket, token: str | None = None):
    esperado = os.environ.get("HOST_TOKEN")
    if not esperado or token != esperado:
        await ws.close(code=1008)
        return
    await ws.accept()
    difusor.adicionar(ws)
    await ws.send_json(estado_atual())
    try:
        while True:
            # Mesma blindagem do socket de jogador: a revisão da Task 7
            # reproduziu que texto não-JSON e mensagem que não é objeto matam
            # o handler. Aqui o estrago seria pior — o apresentador perde o
            # controle do jogo no meio da apresentação.
            try:
                msg = await ws.receive_json()
            except ValueError:
                await ws.send_json(
                    {"tipo": "erro", "mensagem": "Mensagem inválida."}
                )
                continue
            if not isinstance(msg, dict):
                await ws.send_json(
                    {"tipo": "erro", "mensagem": "Mensagem inválida."}
                )
                continue
            cmd = msg.get("cmd")
            try:
                if cmd == "medir":
                    if not medidor.conectado:
                        raise ErroDeJogo("A ponte da câmera não está conectada.")
                    ticket = sala.iniciar_medicao()
                    await difusor.transmitir()
                    # Task separada: o handler precisa voltar a ler o socket
                    # enquanto a medição corre. A referência fica no set porque
                    # o asyncio não segura task solta.
                    tarefa = asyncio.create_task(_medir_e_revelar(ticket))
                    _tarefas_em_voo.add(tarefa)
                    tarefa.add_done_callback(_tarefas_em_voo.discard)
                    continue
                if cmd == "nova_rodada":
                    sala.nova_rodada()
                elif cmd == "travar":
                    sala.definir_trava(bool(msg.get("travada")))
                else:
                    raise ErroDeJogo("Comando desconhecido.")
            except ErroDeJogo as e:
                await ws.send_json({"tipo": "erro", "mensagem": str(e)})
                continue
            await difusor.transmitir()
    except WebSocketDisconnect:
        pass
    finally:
        difusor.remover(ws)


# --- WebSocket da ponte ------------------------------------------------------


@app.websocket("/ws/ponte")
async def ws_ponte(ws: WebSocket, token: str | None = None):
    esperado = os.environ.get("PONTE_TOKEN")
    if not esperado or token != esperado:
        await ws.close(code=1008)
        return
    await ws.accept()
    # `conectar` não recusa a segunda ponte: devolve a anterior para fecharmos.
    # Na feira a segunda conexão é quase sempre o mesmo notebook reconectando
    # depois de o Wi-Fi piscar, e recusá-la travava a retomada até o servidor
    # detectar o socket morto — dezenas de segundos com o palco mostrando
    # "câmera offline".
    anterior = medidor.conectar(ws)
    if anterior is not None:
        try:
            await anterior.close(code=1000)
        except Exception:
            # Fechar socket já morto levanta. Não é motivo para derrubar a
            # ponte nova, que é a que vale agora.
            pass
    await difusor.transmitir()  # acende o semáforo no palco
    try:
        while True:
            try:
                msg = await ws.receive_json()
            except ValueError:
                # A ponte é nosso código e não lê resposta do servidor, então
                # mandar erro de volta não serve. Ignora e segue vivo: derrubar
                # o socket apagaria o semáforo do palco por causa de um frame.
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("tipo") == "resultado":
                medidor.entregar_resultado(msg)
            elif msg.get("tipo") == "erro":
                ordem = msg.get("id")
                if not isinstance(ordem, int):
                    # Sem o `id` não há como saber de qual medição é o erro, e
                    # aceitá-lo derrubaria a que está em curso. O `None` do
                    # `entregar_erro` significa falha local (desconexão), e a
                    # ponte não pode herdar esse passe livre por omissão.
                    continue
                medidor.entregar_erro(
                    str(msg.get("mensagem", "Falha na câmera.")), ordem
                )
    except WebSocketDisconnect:
        pass
    finally:
        medidor.desconectar(ws)
        await difusor.transmitir()  # apaga o semáforo
