"""Rotas e WebSockets do jogo da feira.

Nenhuma fixture de `conftest.py` é usada: o jogo não tem banco. Os tokens são
injetados por `monkeypatch.setenv` e lidos a cada requisição, então não é
preciso recarregar o módulo entre casos.
"""
import pytest
from fastapi.testclient import TestClient

HOST_TOKEN = "token-de-host-de-teste"
PONTE_TOKEN = "token-de-ponte-de-teste"


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("HOST_TOKEN", HOST_TOKEN)
    monkeypatch.setenv("PONTE_TOKEN", PONTE_TOKEN)
    from jogo.main import app, medidor, sala

    # Estado global do processo: zera entre testes para não vazar jogador de um
    # caso para o outro.
    sala.nova_rodada()
    medidor.canal = None
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_raiz_serve_a_tela_do_controle(client):
    resposta = client.get("/")
    assert resposta.status_code == 200
    assert "text/html" in resposta.headers["content-type"]


def test_host_sem_token_responde_403(client):
    assert client.get("/host").status_code == 403


def test_host_com_token_errado_responde_403(client):
    assert client.get("/host?token=errado").status_code == 403


def test_host_com_token_certo_serve_a_tela_do_palco(client):
    resposta = client.get(f"/host?token={HOST_TOKEN}")
    assert resposta.status_code == 200
    assert "text/html" in resposta.headers["content-type"]


def test_host_sem_token_e_sem_variavel_responde_403(client, monkeypatch):
    """O caso que o guard `not esperado` protege.

    Sem ele, variável ausente e token ausente dariam `None != None`, que é
    falso, e o palco abriria para qualquer um numa URL pública. O teste
    anterior mandava um token junto, então passava mesmo sem o guard.
    """
    monkeypatch.delenv("HOST_TOKEN")
    assert client.get("/host").status_code == 403


def test_host_token_vazio_e_variavel_vazia_responde_403(client, monkeypatch):
    monkeypatch.setenv("HOST_TOKEN", "")
    assert client.get("/host?token=").status_code == 403


def test_qr_devolve_svg(client):
    resposta = client.get("/qr.svg")
    assert resposta.status_code == 200
    assert "svg" in resposta.headers["content-type"]
    assert b"<svg" in resposta.content


def test_qr_usa_a_url_publica_configurada(client, monkeypatch):
    """Prova que a variável entra no QR, não só que a rota responde.

    Status 200 passaria com a variável sendo ignorada — e aí o QR impresso
    apontaria para o endereço errado, o que só se descobre com um celular na
    mão, na feira. Sem decodificar o QR (seria dependência nova): URLs
    diferentes têm de gerar SVGs diferentes, e a mesma URL, o mesmo SVG.
    """
    monkeypatch.setenv("JOGO_URL_PUBLICA", "https://um.test/")
    um = client.get("/qr.svg").content
    monkeypatch.setenv("JOGO_URL_PUBLICA", "https://outro.test/")
    outro = client.get("/qr.svg").content
    monkeypatch.setenv("JOGO_URL_PUBLICA", "https://um.test/")
    um_de_novo = client.get("/qr.svg").content

    assert b"<svg" in um and b"<svg" in outro
    assert um != outro, "o QR não mudou com a URL: a variável está sendo ignorada"
    assert um == um_de_novo, "o QR não é determinístico para a mesma URL"


def test_saude_responde_sem_token(client):
    resposta = client.get("/saude")
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "ok"


def test_host_aceita_token_com_espaco_sobrando_na_variavel(client, monkeypatch):
    """Token colado no painel da Render com `\\n` ou espaço no fim trancaria o
    apresentador para fora, na feira, sem pista do motivo."""
    monkeypatch.setenv("HOST_TOKEN", f"  {HOST_TOKEN}\n")
    assert client.get(f"/host?token={HOST_TOKEN}").status_code == 200


def test_host_com_token_nao_ascii_responde_403_e_nao_500(client):
    """`compare_digest` com `str` não-ASCII levanta TypeError, que viraria 500."""
    assert client.get("/host?token=é").status_code == 403


def test_docs_e_openapi_estao_desligados(client):
    for rota in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(rota).status_code == 404, rota


def test_static_serve_o_css_e_nao_escapa_da_pasta(client):
    """Guarda a regra das Tasks 10-12: nada entra em `static/` que não possa
    ser público, e nada em `static/` dá acesso a fora dela."""
    assert client.get("/static/comum.css").status_code == 200
    for tentativa in ("/static/../main.py", "/static/%2e%2e/main.py", "/static/"):
        assert client.get(tentativa).status_code == 404, tentativa


def _entrar(ws, nome):
    """Entra na sala e devolve o id. Consome o `voce` e o primeiro `estado`."""
    ws.send_json({"cmd": "entrar", "nome": nome})
    boas_vindas = ws.receive_json()
    ws.receive_json()  # estado transmitido depois da entrada
    return boas_vindas["id"]


def test_jogador_entra_e_recebe_o_proprio_id(client):
    with client.websocket_connect("/ws/jogador") as ws:
        ws.send_json({"cmd": "entrar", "nome": "Ana"})
        boas_vindas = ws.receive_json()
        assert boas_vindas["tipo"] == "voce"
        assert boas_vindas["id"]
        assert boas_vindas["nome"] == "Ana"


def test_estado_chega_depois_de_entrar(client):
    with client.websocket_connect("/ws/jogador") as ws:
        ws.send_json({"cmd": "entrar", "nome": "Ana"})
        ws.receive_json()  # voce
        estado = ws.receive_json()
        assert estado["tipo"] == "estado"
        assert estado["estado"] == "AGUARDANDO"
        assert len(estado["jogadores"]) == 1
        assert estado["jogadores"][0]["nome"] == "Ana"
        assert estado["jogadores"][0]["chutou"] is False


def test_nome_repetido_devolve_erro_sem_derrubar_o_socket(client):
    with client.websocket_connect("/ws/jogador") as primeiro:
        _entrar(primeiro, "Ana")
        with client.websocket_connect("/ws/jogador") as segundo:
            segundo.send_json({"cmd": "entrar", "nome": "Ana"})
            resposta = segundo.receive_json()
            assert resposta["tipo"] == "erro"
            assert "nome" in resposta["mensagem"]
            # O socket continua vivo: dá pra tentar outro nome.
            segundo.send_json({"cmd": "entrar", "nome": "Bruno"})
            assert segundo.receive_json()["tipo"] == "voce"


def test_chute_fora_da_faixa_devolve_erro(client):
    with client.websocket_connect("/ws/jogador") as ws:
        id_ana = _entrar(ws, "Ana")
        ws.send_json({"cmd": "chutar", "id": id_ana, "valor_cm": 300})
        resposta = ws.receive_json()
        assert resposta["tipo"] == "erro"
        assert "0 e 200" in resposta["mensagem"]


def test_entrada_de_um_jogador_chega_no_palco(client):
    with client.websocket_connect("/ws/palco") as palco:
        palco.receive_json()  # estado inicial
        with client.websocket_connect("/ws/jogador") as jogador:
            jogador.send_json({"cmd": "entrar", "nome": "Ana"})
            jogador.receive_json()  # voce
            estado = palco.receive_json()
            assert [j["nome"] for j in estado["jogadores"]] == ["Ana"]


def test_jogador_reconecta_na_mesma_cadeira(client):
    with client.websocket_connect("/ws/jogador") as ws:
        id_ana = _entrar(ws, "Ana")
        ws.send_json({"cmd": "chutar", "id": id_ana, "valor_cm": 15.5})
        ws.receive_json()

    # Celular bloqueou a tela e o socket caiu.
    with client.websocket_connect("/ws/jogador") as ws:
        ws.send_json({"cmd": "voltar", "id": id_ana})
        resposta = ws.receive_json()
        assert resposta["tipo"] == "voce"
        assert resposta["id"] == id_ana
        assert resposta["nome"] == "Ana"
        estado = ws.receive_json()
        # Não virou fantasma nem cadeira nova.
        assert len(estado["jogadores"]) == 1
        assert estado["quantos_chutaram"] == 1


def test_voltar_com_id_desconhecido_devolve_erro(client):
    with client.websocket_connect("/ws/jogador") as ws:
        ws.send_json({"cmd": "voltar", "id": "nao-existe"})
        assert ws.receive_json()["tipo"] == "erro"


@pytest.mark.parametrize("nome_torto", [None, 123, ["Ana"], {"a": 1}])
def test_entrar_com_nome_de_tipo_errado_e_recusado_sem_derrubar_o_socket(
    client, nome_torto
):
    """A URL é pública: o payload pode vir de qualquer cliente, não só do nosso.

    Nome que não é texto é recusado: `str(["Ana"])` criaria um jogador chamado
    `['Ana']`. E a conexão não pode morrer — um socket derrubado por payload
    torto deixaria o visitante com a tela travada sem explicação.
    """
    with client.websocket_connect("/ws/jogador") as ws:
        ws.send_json({"cmd": "entrar", "nome": nome_torto})
        resposta = ws.receive_json()
        assert resposta["tipo"] == "erro"
        # O socket continua utilizável depois da recusa.
        ws.send_json({"cmd": "entrar", "nome": "Ana"})
        assert ws.receive_json()["tipo"] == "voce"


def test_payload_tem_exatamente_as_chaves_do_contrato(app):
    """O payload é o contrato que os dois frontends consomem.

    Testado direto, sem WebSocket: `estado_atual` é função comum. Chave que
    entra ou sai sem o JS saber quebra uma tela que só se vê no navegador.
    """
    from jogo.main import estado_atual

    assert set(estado_atual()) == {
        "tipo", "estado", "aberta", "ponte_conectada", "jogadores",
        "quantos_chutaram", "altura_cm", "margem_cm", "categoria",
        "imagem_b64", "erro", "ranking",
    }


def test_payload_esconde_o_ranking_antes_do_resultado(app):
    from jogo.main import estado_atual, sala

    id_ana = sala.entrar("Ana").id
    sala.chutar_por_id(id_ana, 16.0)
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, 17.5, 0.4, "ALTA", None)

    # A sala já devolve ranking em REVELANDO, mas o payload é um só para
    # todos: o vencedor não pode chegar ao celular antes de o palco revelar.
    assert estado_atual()["estado"] == "REVELANDO"
    assert estado_atual()["ranking"] == []

    sala.revelacao_terminou(ticket)
    assert estado_atual()["ranking"][0]["nome"] == "Ana"


def test_comando_de_host_pelo_socket_de_jogador_nao_faz_nada(client):
    from jogo.main import sala as sala_do_app

    with client.websocket_connect("/ws/jogador") as ws:
        id_ana = _entrar(ws, "Ana")
        ws.send_json({"cmd": "chutar", "id": id_ana, "valor_cm": 10.0})
        ws.receive_json()
        for comando in ({"cmd": "medir"}, {"cmd": "nova_rodada"},
                        {"cmd": "travar", "travada": True}):
            ws.send_json(comando)
            assert ws.receive_json()["tipo"] == "erro"
        assert sala_do_app.estado.value == "AGUARDANDO"
        assert sala_do_app.aberta is True
        assert len(sala_do_app.jogadores) == 1


def test_payload_nao_expoe_o_id_de_ninguem(app):
    """O `id` é credencial: o `chutar` e o `voltar` o exigem.

    No broadcast, qualquer visitante com a aba Rede aberta leria o id dos
    outros e chutaria em nome deles. Ele chega só no frame `voce`, que vai
    para um socket só.
    """
    from jogo.main import estado_atual, sala

    jogador = sala.entrar("Ana")
    sala.chutar_por_id(jogador.id, 16.0)
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, 17.5, 0.4, "ALTA", None)
    sala.revelacao_terminou(ticket)

    payload = estado_atual()
    assert payload["jogadores"] == [{"nome": "Ana", "chutou": True}]
    assert payload["ranking"], "o ranking deveria estar preenchido em RESULTADO"
    for linha in payload["ranking"]:
        assert "id" not in linha
    assert jogador.id not in str(payload)


@pytest.mark.parametrize("lixo", ['[1, 2]', '"abc"', '42', 'nao e json', '{'])
def test_mensagem_torta_nao_derruba_o_socket_do_jogador(client, lixo):
    """A URL é pública: qualquer cliente pode mandar qualquer coisa.

    Socket derrubado deixa o visitante com a tela travada até o JS reconectar,
    e enche o log de 1011.
    """
    with client.websocket_connect("/ws/jogador") as ws:
        ws.send_text(lixo)
        assert ws.receive_json()["tipo"] == "erro"
        # E o socket continua utilizável.
        ws.send_json({"cmd": "entrar", "nome": "Ana"})
        assert ws.receive_json()["tipo"] == "voce"


def test_chute_com_inteiro_gigante_nao_derruba_o_socket(client):
    """`float()` de um inteiro de 400 dígitos levanta OverflowError."""
    id_ana = _entrar(client_ws := client.websocket_connect("/ws/jogador").__enter__(), "Ana")
    try:
        client_ws.send_json({"cmd": "chutar", "id": id_ana, "valor_cm": int("9" * 400)})
        assert client_ws.receive_json()["tipo"] == "erro"
        client_ws.send_json({"cmd": "chutar", "id": id_ana, "valor_cm": 16.0})
        assert client_ws.receive_json()["tipo"] == "estado"
    finally:
        client_ws.close()


def test_entrar_com_nome_que_nao_e_texto_e_recusado(client):
    with client.websocket_connect("/ws/jogador") as ws:
        ws.send_json({"cmd": "entrar", "nome": ["Ana"]})
        resposta = ws.receive_json()
        assert resposta["tipo"] == "erro"
        assert "nome" in resposta["mensagem"]


def test_clientes_saem_do_difusor_ao_desconectar(client):
    from jogo.main import difusor

    assert difusor.quantos == 0
    with client.websocket_connect("/ws/jogador"):
        with client.websocket_connect("/ws/palco"):
            assert difusor.quantos == 2
    assert difusor.quantos == 0


def test_texto_torto_no_palco_nao_derruba_o_socket(client):
    """O palco não manda comando, mas a URL é pública: lixo não pode derrubá-lo."""
    from jogo.main import difusor

    with client.websocket_connect("/ws/palco") as palco:
        palco.receive_json()
        palco.send_text("nao e json")
        with client.websocket_connect("/ws/jogador") as jogador:
            jogador.send_json({"cmd": "entrar", "nome": "Ana"})
            jogador.receive_json()
            assert palco.receive_json()["jogadores"][0]["nome"] == "Ana"
            assert difusor.quantos == 2


def test_chute_nao_vaza_o_valor_no_estado(client):
    with client.websocket_connect("/ws/jogador") as ws:
        id_ana = _entrar(ws, "Ana")
        ws.send_json({"cmd": "chutar", "id": id_ana, "valor_cm": 15.5})
        estado = ws.receive_json()
        assert estado["jogadores"][0]["chutou"] is True
        assert estado["quantos_chutaram"] == 1
        # O valor não pode estar em lugar nenhum do payload: todos olham a mesma
        # tela grande e o último a chutar copiaria.
        assert "15.5" not in str(estado)


def test_payload_nunca_traz_o_valor_do_chute(app):
    from jogo.main import estado_atual, sala

    id_ana = sala.entrar("Ana").id
    sala.chutar_por_id(id_ana, 15.5)
    payload = estado_atual()
    assert payload["jogadores"][0]["chutou"] is True
    assert payload["quantos_chutaram"] == 1
    # Todos olham a mesma tela grande: o último a chutar copiaria o vizinho.
    assert "15.5" not in str(payload)
