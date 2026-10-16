"""Rotas e WebSockets do jogo da feira.

Nenhuma fixture de `conftest.py` é usada: o jogo não tem banco. Os tokens são
injetados por `monkeypatch.setenv` e lidos a cada requisição, então não é
preciso recarregar o módulo entre casos.
"""
import asyncio
import faulthandler
import threading

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


@pytest.fixture(autouse=True)
def _watchdog():
    """Teste que trava bloqueia o CI sem dizer por quê; este mata o processo
    com o traceback de todas as threads. Só dispara se algo travar de verdade."""
    faulthandler.dump_traceback_later(30, exit=True)
    yield
    faulthandler.cancel_dump_traceback_later()


@pytest.fixture
def client(app):
    """TestClient como context manager: UMA thread/loop para todos os sockets.

    Sem o `with`, cada `websocket_connect` abre o próprio portal (thread +
    loop). O servidor, que em produção roda num loop só, passa a escrever num
    socket cujo loop mora em outra thread; `asyncio.Event.set` não é
    thread-safe, e se o leitor já estava esperando o loop dele não acorda — o
    `receive_json()` do teste pendura para sempre. Todo socket aberto aqui tem
    de ser fechado com `__exit__` (não só `.close()`): o portal compartilhado
    espera as sessões terminarem para encerrar.
    """
    from jogo.main import _tarefas_em_voo

    async def drenar():
        # Task de medição que sobrou de um teste não pode vazar para o próximo.
        pendentes = list(_tarefas_em_voo)
        for t in pendentes:
            t.cancel()
        await asyncio.gather(*pendentes, return_exceptions=True)

    with TestClient(app) as c:
        yield c
        c.portal.call(drenar)


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
        client_ws.__exit__(None, None, None)


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


def test_payload_nunca_traz_o_valor_do_chute(app):
    """Prova estrutural, não textual.

    `"13.37" not in str(payload)` passaria com o valor saindo arredondado, ou
    como string com vírgula. O que garante é cada jogador ter exatamente as
    chaves do contrato — nada a mais.
    """
    from jogo.main import estado_atual, sala

    jogador = sala.entrar("Ana")
    sala.chutar_por_id(jogador.id, 13.37)
    payload = estado_atual()

    for linha in payload["jogadores"]:
        assert set(linha) == {"nome", "chutou"}
    assert payload["quantos_chutaram"] == 1

    # Cinto, além da prova estrutural: nenhum escalar do payload parece o chute.
    def escalares(valor):
        if isinstance(valor, dict):
            for v in valor.values():
                yield from escalares(v)
        elif isinstance(valor, list):
            for v in valor:
                yield from escalares(v)
        else:
            yield valor

    assert 13.37 not in list(escalares(payload))
    assert "13.37" not in str(payload) and "13,37" not in str(payload)


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


def _jogador_que_chutou(client, nome="Ana", valor=16.0):
    """Abre um socket de jogador, entra, chuta e devolve (socket, id).

    Devolve o socket aberto em vez de usar `with`: aninhar mais um nível de
    contexto dentro dos testes de host deixaria a leitura ilegível.
    """
    ws = client.websocket_connect("/ws/jogador").__enter__()
    ws.send_json({"cmd": "entrar", "nome": nome})
    id_jogador = ws.receive_json()["id"]
    ws.receive_json()
    ws.send_json({"cmd": "chutar", "id": id_jogador, "valor_cm": valor})
    ws.receive_json()
    return ws, id_jogador


def test_ponte_sem_token_e_recusada(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/ponte") as ws:
            ws.receive_json()


def test_ponte_conectada_aparece_no_estado(client):
    with client.websocket_connect(f"/ws/ponte?token={PONTE_TOKEN}"):
        with client.websocket_connect("/ws/palco") as palco:
            assert palco.receive_json()["ponte_conectada"] is True


def test_ponte_nova_assume_e_recebe_a_ordem_de_medir(client):
    """Reconexão depois de o Wi-Fi piscar assume na hora.

    Antes a segunda ponte era recusada, e a retomada ficava travada até o
    servidor notar o socket morto — dezenas de segundos com o palco mostrando
    "câmera offline". Prova funcional: a ordem de medir vai para a ponte nova.
    """
    ws_jogador, _ = _jogador_que_chutou(client)
    primeira = client.websocket_connect(f"/ws/ponte?token={PONTE_TOKEN}").__enter__()
    try:
        with client.websocket_connect(f"/ws/ponte?token={PONTE_TOKEN}") as segunda:
            with client.websocket_connect(f"/ws/host?token={HOST_TOKEN}") as host:
                host.receive_json()
                host.send_json({"cmd": "medir"})
                assert host.receive_json()["estado"] == "MEDINDO"
                assert segunda.receive_json()["cmd"] == "medir"
    finally:
        try:
            primeira.__exit__(None, None, None)  # o servidor já fechou este; fechar de novo levanta
        except Exception:
            pass
        ws_jogador.__exit__(None, None, None)


def test_host_sem_token_no_socket_e_recusado(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/host") as ws:
            ws.receive_json()


def test_medir_sem_ponte_devolve_erro_ao_host(client):
    ws_jogador, _ = _jogador_que_chutou(client)
    try:
        with client.websocket_connect(f"/ws/host?token={HOST_TOKEN}") as host:
            host.receive_json()  # estado inicial
            host.send_json({"cmd": "medir"})
            resposta = host.receive_json()
            assert resposta["tipo"] == "erro"
            assert "ponte" in resposta["mensagem"]
    finally:
        ws_jogador.__exit__(None, None, None)


def test_medir_percorre_medindo_revelando_resultado(client, monkeypatch):
    monkeypatch.setenv("DURACAO_REVELACAO_S", "0.05")
    ws_jogador, _ = _jogador_que_chutou(client, "Ana", 16.0)
    try:
        with client.websocket_connect(f"/ws/ponte?token={PONTE_TOKEN}") as ponte:
            with client.websocket_connect(f"/ws/host?token={HOST_TOKEN}") as host:
                host.receive_json()  # estado inicial
                host.send_json({"cmd": "medir"})

                assert host.receive_json()["estado"] == "MEDINDO"
                ordem = ponte.receive_json()
                assert ordem["cmd"] == "medir"
                # O `id` de correlação: a ponte tem de devolvê-lo, senão o
                # servidor descarta a resposta como se fosse de uma ordem que
                # já estourou o timeout.
                assert isinstance(ordem["id"], int)

                ponte.send_json({
                    "tipo": "resultado", "altura_cm": 17.5, "margem_cm": 0.4,
                    "categoria": "ALTA", "imagem_b64": "iVBOR",
                    "id": ordem["id"],
                })

                revelando = host.receive_json()
                assert revelando["estado"] == "REVELANDO"
                assert revelando["altura_cm"] == 17.5

                resultado = host.receive_json()
                assert resultado["estado"] == "RESULTADO"
                assert resultado["ranking"][0]["nome"] == "Ana"
                assert resultado["ranking"][0]["erro_cm"] == 1.5
    finally:
        ws_jogador.__exit__(None, None, None)


def test_erro_da_ponte_volta_para_aguardando_preservando_chutes(client):
    ws_jogador, _ = _jogador_que_chutou(client, "Ana", 16.0)
    try:
        with client.websocket_connect(f"/ws/ponte?token={PONTE_TOKEN}") as ponte:
            with client.websocket_connect(f"/ws/host?token={HOST_TOKEN}") as host:
                host.receive_json()
                host.send_json({"cmd": "medir"})
                host.receive_json()  # MEDINDO
                ordem = ponte.receive_json()
                ponte.send_json({
                    "tipo": "erro", "mensagem": "A câmera não respondeu.",
                    "id": ordem["id"],
                })
                estado = host.receive_json()
                assert estado["estado"] == "AGUARDANDO"
                assert estado["erro"] == "A câmera não respondeu."
                assert estado["quantos_chutaram"] == 1
    finally:
        ws_jogador.__exit__(None, None, None)


def test_medir_sem_ninguem_ter_chutado_devolve_erro(client):
    with client.websocket_connect("/ws/jogador") as jogador:
        _entrar(jogador, "Ana")
        with client.websocket_connect(f"/ws/ponte?token={PONTE_TOKEN}"):
            jogador.receive_json()  # estado com a ponte ligada
            with client.websocket_connect(f"/ws/host?token={HOST_TOKEN}") as host:
                host.receive_json()
                host.send_json({"cmd": "medir"})
                resposta = host.receive_json()
                assert resposta["tipo"] == "erro"
                assert "chutou" in resposta["mensagem"]


def test_resposta_atrasada_depois_de_reset_nao_revela_nada(client):
    """A corrida da feira, de ponta a ponta.

    O grupo vai embora durante a medição, o apresentador reseta, e só então a
    câmera responde. A resposta é da rodada que acabou: se entrasse, o palco
    revelaria uma altura que não é da sala atual — plausível e falso, que é
    pior que um erro visível.

    A sala prova isso em `test_ticket_velho_nao_afeta_a_medicao_nova`, mas só
    no nível dela: um teste de mutação mostrou que tirar a checagem de ticket
    do `concluir_medicao` não quebra nenhum teste da API. Aqui a prova
    atravessa o WebSocket.
    """
    ws_jogador, _ = _jogador_que_chutou(client, "Ana", 16.0)
    try:
        with client.websocket_connect(f"/ws/ponte?token={PONTE_TOKEN}") as ponte:
            with client.websocket_connect(f"/ws/host?token={HOST_TOKEN}") as host:
                host.receive_json()
                host.send_json({"cmd": "medir"})
                assert host.receive_json()["estado"] == "MEDINDO"
                ordem = ponte.receive_json()

                # O apresentador reseta antes de a câmera responder.
                host.send_json({"cmd": "nova_rodada"})
                assert host.receive_json()["estado"] == "AGUARDANDO"

                # A resposta da rodada que já acabou chega agora.
                ponte.send_json({
                    "tipo": "resultado", "altura_cm": 17.5, "margem_cm": 0.4,
                    "categoria": "ALTA", "imagem_b64": None, "id": ordem["id"],
                })

                # Barreira: um comando que responde. Se a resposta atrasada
                # tivesse entrado, o próximo frame seria REVELANDO, não a
                # resposta ao travar.
                host.send_json({"cmd": "travar", "travada": True})
                estado = host.receive_json()
                assert estado["estado"] == "AGUARDANDO"
                assert estado["aberta"] is False
                assert estado["altura_cm"] is None
    finally:
        ws_jogador.__exit__(None, None, None)


def test_erro_da_ponte_sem_id_nao_derruba_a_medicao(client):
    """Sem o `id` não há como saber de qual medição é o erro.

    O `None` do `entregar_erro` significa falha local (a desconexão do socket),
    e a ponte não pode herdar esse passe livre por omissão: um erro atrasado da
    ordem anterior derrubaria a medição em curso. Um teste de mutação mostrou
    que essa defesa não tinha consumidor nenhum.
    """
    ws_jogador, _ = _jogador_que_chutou(client)
    try:
        with client.websocket_connect(f"/ws/ponte?token={PONTE_TOKEN}") as ponte:
            with client.websocket_connect(f"/ws/host?token={HOST_TOKEN}") as host:
                host.receive_json()
                host.send_json({"cmd": "medir"})
                assert host.receive_json()["estado"] == "MEDINDO"
                ponte.receive_json()

                ponte.send_json({"tipo": "erro", "mensagem": "falha sem id"})

                host.send_json({"cmd": "travar", "travada": True})
                estado = host.receive_json()
                assert estado["estado"] == "MEDINDO"
                assert estado["erro"] is None
    finally:
        ws_jogador.__exit__(None, None, None)


def test_host_trava_e_destrava_a_sala(client):
    with client.websocket_connect(f"/ws/host?token={HOST_TOKEN}") as host:
        host.receive_json()
        host.send_json({"cmd": "travar", "travada": True})
        assert host.receive_json()["aberta"] is False
        host.send_json({"cmd": "travar", "travada": False})
        assert host.receive_json()["aberta"] is True


def test_host_nova_rodada_limpa_a_sala(client):
    ws_jogador, _ = _jogador_que_chutou(client)
    try:
        with client.websocket_connect(f"/ws/host?token={HOST_TOKEN}") as host:
            host.receive_json()
            host.send_json({"cmd": "nova_rodada"})
            estado = host.receive_json()
            assert estado["jogadores"] == []
            assert estado["estado"] == "AGUARDANDO"
    finally:
        ws_jogador.__exit__(None, None, None)


def _receber(ws, prazo_s=5.0):
    """`receive_json` com prazo: falha em vez de pendurar."""
    saida = {}

    def ler():
        try:
            saida["v"] = ws.receive_json()
        except BaseException as e:  # noqa: BLE001 - repassado abaixo
            saida["e"] = e

    t = threading.Thread(target=ler, daemon=True)
    t.start()
    t.join(prazo_s)
    if t.is_alive():
        pytest.fail(f"nenhum frame em {prazo_s}s: o frame nunca saiu, ou o wake-up do socket se perdeu")
    if "e" in saida:
        raise saida["e"]
    return saida["v"]


def test_ordem_chega_na_ponte_mesmo_quando_a_task_de_medicao_demora(client, monkeypatch):
    """Regressão do pendurado intermitente da suíte (1 em ~100 execuções).

    O teste lê da ponte (`receive`) ANTES de a task de medição escrever nela. Se
    ponte e host moram em loops de threads diferentes, o `set` do evento de
    leitura vem de outra thread e o loop da ponte não acorda. O atraso de 50 ms
    na task transforma a corrida rara em determinística.
    """
    import jogo.medicao as medicao

    original = medicao.Medidor.medir

    async def medir_atrasado(self):
        await asyncio.sleep(0.05)
        return await original(self)

    monkeypatch.setattr(medicao.Medidor, "medir", medir_atrasado)
    ws_jogador, _ = _jogador_que_chutou(client)
    try:
        with client.websocket_connect(f"/ws/ponte?token={PONTE_TOKEN}") as ponte:
            with client.websocket_connect(f"/ws/host?token={HOST_TOKEN}") as host:
                host.receive_json()
                host.send_json({"cmd": "medir"})
                assert _receber(host)["estado"] == "MEDINDO"
                assert _receber(ponte)["cmd"] == "medir"
    finally:
        ws_jogador.__exit__(None, None, None)


def _ate(ws, condicao, max_frames=8):
    """Lê frames (com prazo) até um satisfazer `condicao`; devolve esse frame.

    A task da medição cancelada ainda transmite um frame de falha depois do
    reset, então o número de frames entre dois eventos não é fixo.
    """
    for _ in range(max_frames):
        frame = _receber(ws)
        if condicao(frame):
            return frame
    pytest.fail("o frame esperado não chegou")


def test_medir_funciona_logo_depois_de_reset_no_meio_da_medicao(client):
    """O cenário real da feira: o grupo vai embora durante a medição.

    Antes, o MEDIR seguinte era recusado com "já existe uma medição em
    andamento" por até 15s, porque o `nova_rodada` não alcançava o medidor.

    A ponte e o host ficam conectados o teste todo: fechar a ponte entre as
    duas medições também falharia a espera (pelo `desconectar`) e esconderia o
    defeito — foi assim que a primeira versão deste teste passou sem a correção.
    """
    ws_ana, _ = _jogador_que_chutou(client, "Ana", 16.0)
    ws_bruno = None
    try:
        with client.websocket_connect(f"/ws/ponte?token={PONTE_TOKEN}") as ponte:
            with client.websocket_connect(f"/ws/host?token={HOST_TOKEN}") as host:
                host.receive_json()
                host.send_json({"cmd": "medir"})
                assert _receber(host)["estado"] == "MEDINDO"
                _receber(ponte)  # a ordem da primeira medição

                # A câmera não responde e o apresentador reseta.
                host.send_json({"cmd": "nova_rodada"})
                assert _ate(host, lambda f: f["jogadores"] == [])["estado"] == "AGUARDANDO"
                ws_ana.__exit__(None, None, None)
                ws_ana = None

                # Grupo novo, e o MEDIR tem de funcionar na hora.
                ws_bruno, _ = _jogador_que_chutou(client, "Bruno", 9.0)
                _ate(host, lambda f: f["quantos_chutaram"] == 1)
                host.send_json({"cmd": "medir"})
                _ate(host, lambda f: f["estado"] == "MEDINDO")
                # A ordem chega na ponte, em vez de a medição ser recusada.
                assert _receber(ponte)["cmd"] == "medir"
                # E nenhuma recusa chega ao palco.
                host.send_json({"cmd": "travar", "travada": True})
                estado = _receber(host)
                assert estado["estado"] == "MEDINDO", estado.get("erro")
                assert estado["erro"] is None
    finally:
        for ws in (ws_ana, ws_bruno):
            if ws is not None:
                ws.__exit__(None, None, None)
