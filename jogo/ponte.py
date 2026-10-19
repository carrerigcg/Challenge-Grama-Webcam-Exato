"""Ponte da câmera: roda no notebook da feira, ao lado da webcam.

Conecta PARA FORA, no serviço hospedado, e fica pendurada esperando a ordem de
medir. Conexão de saída dispensa IP público, redirecionamento de porta e
configuração de firewall — e dispensa que os celulares estejam nesta rede.

Não altera `medir_grama.py`: importa as funções do pipeline e as orquestra
headless, sem a janela de preview do OpenCV.

Uso:  python -m jogo.ponte
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys

import requests
import websockets
from dotenv import load_dotenv

import medir_grama

load_dotenv()

CALIBRATION_PATH = "calibration.json"
DEBUG_PATH = "debug/ultima_medicao.png"
BACKOFF_MAX_S = 30
KEEP_ALIVE_INTERVALO_S = 600


# --- configuração ------------------------------------------------------------


def carregar_calibracao_ou_sair() -> dict:
    """Sai com mensagem clara se não houver calibração nesta máquina.

    `px_por_cm` e `y_chao` são da câmera E da posição dela. Trazer o JSON de
    outra máquina produz altura torta, que é pior que erro: é número errado
    com cara de certo.
    """
    try:
        return medir_grama.load_calibration(CALIBRATION_PATH)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"ERRO: {e}", file=sys.stderr)
        print("Rode `python calibrar.py` NESTA máquina, com a câmera já fixada.",
              file=sys.stderr)
        raise SystemExit(1) from None


def url_do_websocket() -> str:
    base = os.environ.get("JOGO_URL_PUBLICA", "http://localhost:8000").rstrip("/")
    token = os.environ.get("PONTE_TOKEN")
    if not token:
        print("ERRO: PONTE_TOKEN não configurado. Veja .env.example.",
              file=sys.stderr)
        raise SystemExit(1)
    esquema = "wss" if base.startswith("https://") else "ws"
    host = base.split("://", 1)[1]
    return f"{esquema}://{host}/ws/ponte?token={token}"


def espera_do_backoff(tentativa: int) -> int:
    return min(2 ** tentativa, BACKOFF_MAX_S)


# --- medição -----------------------------------------------------------------


def ler_imagem_b64(path: str) -> str | None:
    """A imagem anotada viaja no payload. ~100-300 KB em base64 é aceitável."""
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return None


def medir(calibracao: dict) -> dict:
    """Roda o pipeline headless e devolve o payload que o jogo espera."""
    y_chao = calibracao["y_chao"]
    px_por_cm = float(calibracao["px_por_cm"])
    try:
        frames = medir_grama.capture_frames(
            medir_grama.FRAME_COUNT,
            medir_grama.CAMERA_INDEX,
            medir_grama.CAMERA_BACKEND,
        )
        mascaras = [medir_grama.apply_mask(f) for f in frames]
        mascara = medir_grama.median_stack(mascaras)
        top_ys = medir_grama.measure_top_y(mascara, medir_grama.SAMPLE_COLS)
        alturas = [
            medir_grama.y_para_altura_cm(y, y_chao, px_por_cm) for y in top_ys
        ]
        nivel, categoria, mediana = medir_grama.classify_frame_cm(
            alturas, medir_grama.FAIXA_BAIXA_CM, medir_grama.FAIXA_MEDIA_CM,
        )
        margem = medir_grama.margem_erro_cm(alturas)
        medir_grama.save_debug(
            frames[-1], mascara, top_ys, alturas, mediana, margem,
            medir_grama.SAMPLE_COLS, y_chao, px_por_cm, categoria, DEBUG_PATH,
        )
    except Exception as e:  # câmera solta, driver, permissão
        return {"tipo": "erro", "mensagem": f"A câmera não respondeu: {e}"}

    if nivel == 0 or mediana is None:
        return {
            "tipo": "erro",
            "mensagem": "Não achei grama no quadro. Confira o enquadramento.",
        }

    return {
        "tipo": "resultado",
        "altura_cm": round(mediana, 1),
        "margem_cm": round(margem, 1) if margem is not None else None,
        "categoria": categoria,
        "imagem_b64": ler_imagem_b64(DEBUG_PATH),
    }


def processar(bruto: str, calibracao: dict) -> dict | None:
    """Traduz a mensagem recebida em payload de resposta, ou None se ignorada."""
    try:
        msg = json.loads(bruto)
    except json.JSONDecodeError:
        return None
    if msg.get("cmd") != "medir":
        return None
    resposta = medir(calibracao)
    # Devolve o `id` da ordem. Sem ele o servidor descarta a resposta — é o que
    # impede a resposta atrasada de uma ordem que já estourou o timeout ser
    # revelada como se fosse da medição atual.
    resposta["id"] = msg.get("id")
    return resposta


# --- keep-alive --------------------------------------------------------------


def bater_no_keep_alive() -> None:
    """GET no /saude a cada 10min.

    O free tier da Render hiberna após ~15min de inatividade e demora ~50s para
    acordar. Não há garantia documentada de que um WebSocket pendurado conte
    como atividade, então o GET elimina a dúvida por um custo desprezível.
    """
    base = os.environ.get("JOGO_URL_PUBLICA", "http://localhost:8000").rstrip("/")
    try:
        requests.get(f"{base}/saude", timeout=10)
    except requests.RequestException:
        pass


async def laco_de_keep_alive() -> None:
    while True:
        await asyncio.sleep(KEEP_ALIVE_INTERVALO_S)
        await asyncio.to_thread(bater_no_keep_alive)


# --- loop principal ----------------------------------------------------------


async def servir(calibracao: dict) -> None:
    url = url_do_websocket()
    tentativa = 0
    while True:
        try:
            async with websockets.connect(url) as ws:
                print("Ponte conectada. Esperando ordem de medir.")
                tentativa = 0
                async for bruto in ws:
                    # `to_thread` porque o pipeline é síncrono e leva ~3s: no
                    # event loop ele travaria os pings do WebSocket e a conexão
                    # cairia sozinha.
                    resposta = await asyncio.to_thread(processar, bruto, calibracao)
                    if resposta is not None:
                        await ws.send(json.dumps(resposta))
        except Exception as e:
            espera = espera_do_backoff(tentativa)
            print(f"Ponte caiu ({e}). Reconectando em {espera}s.", file=sys.stderr)
            await asyncio.sleep(espera)
            tentativa += 1


async def principal() -> None:
    calibracao = carregar_calibracao_ou_sair()
    print(f"Calibração: px_por_cm={calibracao['px_por_cm']:.2f} "
          f"y_chao={calibracao['y_chao']} regiao={calibracao.get('regiao')!r}")
    await asyncio.gather(servir(calibracao), laco_de_keep_alive())


if __name__ == "__main__":
    try:
        asyncio.run(principal())
    except KeyboardInterrupt:
        print("Ponte encerrada.")
