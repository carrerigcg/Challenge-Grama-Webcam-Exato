"""A ponte que roda no notebook da feira.

Importar `jogo.ponte` puxa `medir_grama`, que importa `cv2` no topo. Em máquina
sem OpenCV a suíte pula estes testes em vez de falhar — é o mesmo motivo pelo
qual o serviço hospedado não instala `requirements-station.txt`.
"""
import json

import pytest

pytest.importorskip("cv2")

import numpy as np  # noqa: E402

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
