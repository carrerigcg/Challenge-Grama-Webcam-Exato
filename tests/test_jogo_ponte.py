"""A ponte que roda no notebook da feira.

Importar `jogo.ponte` puxa `medir_grama`, que importa `cv2` no topo. Em máquina
sem OpenCV a suíte pula estes testes em vez de falhar — é o mesmo motivo pelo
qual o serviço hospedado não instala `requirements-station.txt`.
"""
import asyncio
import json
import threading
from http import HTTPStatus

import pytest

pytest.importorskip("cv2")

import numpy as np  # noqa: E402
import websockets  # noqa: E402

from jogo import ponte  # noqa: E402

CALIBRACAO = {"px_por_cm": 17.5, "y_chao": 433}


def test_calibracao_ausente_impede_o_boot(tmp_path, monkeypatch):
    monkeypatch.setattr(ponte, "CALIBRATION_PATH", str(tmp_path / "nao-existe.json"))
    # Falhar às 8h é melhor que falhar no primeiro clique com cinco pessoas
    # esperando.
    with pytest.raises(SystemExit):
        ponte.carregar_calibracao_ou_sair()


def test_medir_usa_o_pipeline_e_devolve_o_payload(monkeypatch, tmp_path):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    mascara = np.zeros((480, 640), dtype=np.uint8)
    mascara[300:433, :] = 255  # faixa verde começando 133px acima do chão

    chamadas = []

    monkeypatch.setattr(ponte.medir_grama, "capture_frames",
                        lambda n, i, b: chamadas.append("capture") or [frame] * n)
    monkeypatch.setattr(ponte.medir_grama, "apply_mask",
                        lambda f: chamadas.append("mask") or mascara)
    monkeypatch.setattr(ponte.medir_grama, "save_debug",
                        lambda *a, **k: chamadas.append("debug"))
    monkeypatch.setattr(ponte, "DEBUG_PATH", str(tmp_path / "debug.png"))
    monkeypatch.setattr(ponte, "ler_imagem_b64", lambda path: "iVBOR")

    payload = ponte.medir(CALIBRACAO)

    assert payload["tipo"] == "resultado"
    assert payload["altura_cm"] == pytest.approx(7.6, abs=0.1)
    assert payload["categoria"] == "ALTA"
    assert payload["imagem_b64"] == "iVBOR"
    assert chamadas.count("capture") == 1
    assert chamadas.count("debug") == 1


def test_medir_sem_verde_devolve_erro_em_vez_de_zero(monkeypatch, tmp_path):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    vazia = np.zeros((480, 640), dtype=np.uint8)

    monkeypatch.setattr(ponte.medir_grama, "capture_frames", lambda n, i, b: [frame] * n)
    monkeypatch.setattr(ponte.medir_grama, "apply_mask", lambda f: vazia)
    monkeypatch.setattr(ponte.medir_grama, "save_debug", lambda *a, **k: None)
    monkeypatch.setattr(ponte, "DEBUG_PATH", str(tmp_path / "debug.png"))

    payload = ponte.medir(CALIBRACAO)

    # Ranquear gente num 0,0 que foi erro de enquadramento deslegitima o sistema.
    assert payload["tipo"] == "erro"
    assert "grama" in payload["mensagem"].lower()


def test_medir_transforma_falha_de_camera_em_payload_de_erro(monkeypatch):
    def explodir(n, i, b):
        raise RuntimeError("camera nao abriu")

    monkeypatch.setattr(ponte.medir_grama, "capture_frames", explodir)
    payload = ponte.medir(CALIBRACAO)
    assert payload["tipo"] == "erro"
    assert "camera nao abriu" in payload["mensagem"]


def test_espera_do_backoff_cresce_e_tem_teto():
    assert ponte.espera_do_backoff(0) == 1
    assert ponte.espera_do_backoff(1) == 2
    assert ponte.espera_do_backoff(2) == 4
    assert ponte.espera_do_backoff(99) == ponte.BACKOFF_MAX_S


def test_url_do_websocket_usa_wss_em_https(monkeypatch):
    monkeypatch.setenv("JOGO_URL_PUBLICA", "https://jogo.test")
    monkeypatch.setenv("PONTE_TOKEN", "tok")
    assert ponte.url_do_websocket() == "wss://jogo.test/ws/ponte?token=tok"


def test_url_do_websocket_usa_ws_em_http(monkeypatch):
    monkeypatch.setenv("JOGO_URL_PUBLICA", "http://localhost:8000/")
    monkeypatch.setenv("PONTE_TOKEN", "tok")
    assert ponte.url_do_websocket() == "ws://localhost:8000/ws/ponte?token=tok"


def test_url_do_websocket_exige_token(monkeypatch):
    monkeypatch.setenv("JOGO_URL_PUBLICA", "http://localhost:8000")
    monkeypatch.delenv("PONTE_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        ponte.url_do_websocket()


def test_keep_alive_bate_na_saude(monkeypatch):
    monkeypatch.setenv("JOGO_URL_PUBLICA", "https://jogo.test")
    urls = []
    monkeypatch.setattr(ponte.requests, "get",
                        lambda url, timeout: urls.append(url))
    ponte.bater_no_keep_alive()
    assert urls == ["https://jogo.test/saude"]


def test_keep_alive_engole_erro_de_rede(monkeypatch):
    monkeypatch.setenv("JOGO_URL_PUBLICA", "https://jogo.test")

    def explodir(url, timeout):
        raise ponte.requests.RequestException("sem rede")

    monkeypatch.setattr(ponte.requests, "get", explodir)
    ponte.bater_no_keep_alive()  # não levanta


def test_processar_ignora_ordem_desconhecida():
    assert ponte.processar(json.dumps({"cmd": "sei-la"}), CALIBRACAO) is None


def test_processar_devolve_o_id_da_ordem(monkeypatch):
    """Sem o eco do `id`, o servidor descarta toda resposta desta ponte."""
    monkeypatch.setattr(ponte, "medir", lambda c: {"tipo": "resultado", "altura_cm": 9.0})
    resposta = ponte.processar(json.dumps({"cmd": "medir", "id": 42}), CALIBRACAO)
    assert resposta["id"] == 42


def test_processar_ignora_json_quebrado():
    assert ponte.processar("nao e json", CALIBRACAO) is None


# --- o laço de reconexão -----------------------------------------------------
#
# Reconectar depois de uma piscada de Wi-Fi é a razão de a ponte existir, então
# daqui pra baixo os testes sobem um servidor WebSocket de verdade em
# 127.0.0.1 e exercitam `servir()` contra ele. Sem webcam (`medir` é mockado) e
# sem rede externa.


class AsyncioEncurtado:
    """Proxy do módulo `asyncio` que registra as esperas da ponte e as zera.

    A ponte dorme 1s, 2s, 4s... entre tentativas. Esperar isso de verdade
    deixaria o teste em dezenas de segundos — e registrar quanto ela PEDIU para
    dormir é justamente o que permite afirmar que o backoff cresce, zera ao
    conectar e respeita o teto. O resto do módulo (`to_thread`, `Event`) passa
    direto.
    """

    def __init__(self):
        self.esperas: list[float] = []

    def __getattr__(self, nome):
        return getattr(asyncio, nome)

    async def sleep(self, segundos):
        self.esperas.append(segundos)
        await asyncio.sleep(0)


class ServidorDeTeste:
    """Servidor de roteiro: a enésima tentativa recebe o enésimo tratamento.

    - `"rejeitar"`: nega o handshake com 503. É a única forma de fazer o
      `websockets.connect` em si falhar, que é o que faz o contador de
      tentativas CRESCER — handshake aceito zera o contador antes de qualquer
      queda.
    - `"cair"`: aceita e derruba com código 1011 (anormal), que cai no
      `except` da ponte. Fechar com 1000 seria fim de iteração limpo.
    - `("medir", id)`: manda a ordem de medir, guarda a resposta e derruba.

    Esgotado o roteiro, a tentativa seguinte é negada e sinaliza o fim do
    teste. Ser a tentativa N+1 garante que as N esperas já foram registradas.
    """

    def __init__(self, roteiro):
        self.roteiro = roteiro
        self.tentativas = 0
        self.conexoes = 0
        self.respostas = []
        self.threads_do_medir = []
        self.esgotado = asyncio.Event()

    def filtrar(self, conexao, requisicao):
        self.tentativas += 1
        conexao.passo = self.tentativas - 1
        if conexao.passo >= len(self.roteiro):
            self.esgotado.set()
            return conexao.respond(HTTPStatus.SERVICE_UNAVAILABLE, "fim do roteiro\n")
        if self.roteiro[conexao.passo] == "rejeitar":
            return conexao.respond(HTTPStatus.SERVICE_UNAVAILABLE, "nao hoje\n")
        return None

    async def __call__(self, ws):
        self.conexoes += 1
        passo = self.roteiro[ws.passo]
        if isinstance(passo, tuple):
            _, ordem_id = passo
            await ws.send(json.dumps({"cmd": "medir", "id": ordem_id}))
            self.respostas.append(json.loads(await ws.recv()))
        await ws.close(code=1011, reason="queda de teste")


async def rodar_a_ponte(monkeypatch, roteiro, timeout=10):
    """Roda `servir()` contra o servidor de roteiro até ele se esgotar."""
    servidor = ServidorDeTeste(roteiro)

    def medir_falso(calibracao):
        servidor.threads_do_medir.append(threading.get_ident())
        return {"tipo": "resultado", "altura_cm": 9.0}

    monkeypatch.setattr(ponte, "medir", medir_falso)
    encurtado = AsyncioEncurtado()
    monkeypatch.setattr(ponte, "asyncio", encurtado)

    async with websockets.serve(servidor, "127.0.0.1", 0,
                                process_request=servidor.filtrar) as srv:
        porta = srv.sockets[0].getsockname()[1]
        monkeypatch.setenv("JOGO_URL_PUBLICA", f"http://127.0.0.1:{porta}")
        monkeypatch.setenv("PONTE_TOKEN", "tok")
        tarefa = asyncio.create_task(ponte.servir(CALIBRACAO))
        try:
            await asyncio.wait_for(servidor.esgotado.wait(), timeout=timeout)
        finally:
            tarefa.cancel()
            await asyncio.gather(tarefa, return_exceptions=True)
    return servidor, encurtado


@pytest.mark.asyncio
async def test_a_ponte_responde_a_ordem_no_mesmo_socket_ecoando_o_id(monkeypatch):
    """A resposta tem que voltar pelo socket, com o `id` daquela ordem.

    Sem o eco do `id` o servidor descarta a resposta e o telão nunca revela
    nada — e `processar` devolver o payload certo não prova que ele foi
    enviado.
    """
    servidor, _ = await rodar_a_ponte(monkeypatch, [("medir", 7)])

    assert len(servidor.respostas) == 1
    assert servidor.respostas[0]["id"] == 7
    assert servidor.respostas[0]["altura_cm"] == 9.0


@pytest.mark.asyncio
async def test_a_ponte_reconecta_sozinha_e_volta_a_medir(monkeypatch):
    """Piscada de Wi-Fi no meio da feira: a ponte volta sem ninguém mexer."""
    servidor, _ = await rodar_a_ponte(monkeypatch, ["cair", ("medir", 3)])

    assert servidor.conexoes >= 2
    assert [r["id"] for r in servidor.respostas] == [3]


@pytest.mark.asyncio
async def test_o_medir_roda_fora_do_event_loop(monkeypatch):
    """O pipeline é síncrono e leva ~3s.

    No event loop ele travaria os pings do WebSocket e a conexão cairia
    sozinha no meio da medição — o `to_thread` é o que impede isso.
    """
    servidor, _ = await rodar_a_ponte(monkeypatch, [("medir", 1)])

    assert servidor.threads_do_medir == [servidor.threads_do_medir[0]]
    assert servidor.threads_do_medir[0] != threading.get_ident()


@pytest.mark.asyncio
async def test_o_backoff_cresce_e_zera_ao_conectar(monkeypatch):
    """Uma queda depois de uma conexão boa não herda a espera longa anterior.

    Três handshakes negados fazem a espera crescer (1, 2, 4s). O quarto é
    aceito: a queda logo depois tem que esperar 1s de novo, não 8s. Com 30s de
    teto, herdar a espera significaria a webcam sumir por meia hora.
    """
    _, encurtado = await rodar_a_ponte(
        monkeypatch, ["rejeitar", "rejeitar", "rejeitar", "cair", "rejeitar"])

    assert encurtado.esperas[:5] == [1, 2, 4, 1, 2]


@pytest.mark.asyncio
async def test_a_espera_entre_tentativas_respeita_o_teto(monkeypatch):
    """O dobro a cada tentativa para no teto em vez de virar horas."""
    _, encurtado = await rodar_a_ponte(monkeypatch, ["rejeitar"] * 7)

    assert encurtado.esperas[:7] == [1, 2, 4, 8, 16, 30, 30]
    assert ponte.BACKOFF_MAX_S == 30


@pytest.mark.asyncio
async def test_o_keep_alive_bate_no_saude_a_cada_intervalo(monkeypatch):
    """Sem o GET periódico o serviço hiberna e a primeira medição demora ~50s."""
    batidas = []
    monkeypatch.setattr(ponte, "bater_no_keep_alive", lambda: batidas.append(1))
    encurtado = AsyncioEncurtado()
    monkeypatch.setattr(ponte, "asyncio", encurtado)

    tarefa = asyncio.create_task(ponte.laco_de_keep_alive())
    while len(batidas) < 3:
        await asyncio.sleep(0)
    tarefa.cancel()
    await asyncio.gather(tarefa, return_exceptions=True)

    assert encurtado.esperas[:3] == [ponte.KEEP_ALIVE_INTERVALO_S] * 3
