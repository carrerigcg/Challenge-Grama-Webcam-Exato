"""Envio da medição da feira para a API de produção."""
import jogo.envio as envio


class RespostaFalsa:
    status_code = 200


def test_monta_o_payload_com_a_regiao_da_feira():
    payload = envio.montar_payload({"altura_cm": 17.5, "categoria": "ALTA"})
    # Dezenas de medições de feira não podem entrar como se fossem da rodovia.
    assert payload["regiao"] == "Feira de Ciências"
    assert payload["altura_cm"] == 17.5
    assert payload["nivel_risco"] == "ALTA"


def test_traduz_media_acentuada_para_o_enum_da_api():
    payload = envio.montar_payload({"altura_cm": 5.0, "categoria": "MÉDIA"})
    assert payload["nivel_risco"] == "MEDIA"


def test_inclui_clima_quando_a_ponte_mandou():
    payload = envio.montar_payload({
        "altura_cm": 5.0, "categoria": "BAIXA",
        "temperatura_c": 25.7, "clima": "Nublado",
    })
    assert payload["temperatura_c"] == 25.7
    assert payload["clima"] == "Nublado"


def test_omite_clima_quando_nao_veio():
    payload = envio.montar_payload({"altura_cm": 5.0, "categoria": "BAIXA"})
    assert "temperatura_c" not in payload
    assert "clima" not in payload


def test_altura_none_vai_como_zero():
    payload = envio.montar_payload({"altura_cm": None, "categoria": "AUSENTE"})
    assert payload["altura_cm"] == 0.0


def test_enviar_faz_post_com_a_chave_de_escrita(monkeypatch):
    monkeypatch.setenv("API_URL", "https://api.test")
    monkeypatch.setenv("API_KEY_WRITE", "chave")
    chamadas = []

    def post_falso(url, json, headers, timeout):
        chamadas.append((url, json, headers, timeout))
        return RespostaFalsa()

    monkeypatch.setattr(envio.requests, "post", post_falso)
    envio.enviar({"altura_cm": 17.5, "categoria": "ALTA"})

    url, corpo, headers, _timeout = chamadas[0]
    assert url == "https://api.test/leituras"
    assert headers["X-API-Key"] == "chave"
    assert corpo["regiao"] == "Feira de Ciências"


def test_enviar_sem_chave_nao_faz_post(monkeypatch):
    monkeypatch.delenv("API_KEY_WRITE", raising=False)
    chamadas = []

    def post_falso(*args, **kwargs):
        chamadas.append(1)
        return RespostaFalsa()

    monkeypatch.setattr(envio.requests, "post", post_falso)
    envio.enviar({"altura_cm": 17.5, "categoria": "ALTA"})
    assert chamadas == []


def test_enviar_engole_erro_de_rede(monkeypatch):
    monkeypatch.setenv("API_KEY_WRITE", "chave")

    def explodir(*args, **kwargs):
        raise envio.requests.RequestException("sem rede")

    monkeypatch.setattr(envio.requests, "post", explodir)
    # O jogo nunca pode cair por causa da API de produção.
    envio.enviar({"altura_cm": 17.5, "categoria": "ALTA"})
