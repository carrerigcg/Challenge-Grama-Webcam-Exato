"""Máquina de estado da sala do jogo da feira.

Sem fixtures de banco de propósito: o jogo não tem persistência. A sala é um
dataclass em memória e estes testes são aritmética de estado, não integração.
"""
import ast
from pathlib import Path

import pytest

from jogo.sala import MAX_JOGADORES, MAX_NOME, ErroDeJogo, Estado, Sala


def test_sala_nasce_aguardando_e_aberta():
    sala = Sala()
    assert sala.estado is Estado.AGUARDANDO
    assert sala.aberta is True
    assert sala.jogadores == []


def test_entrar_devolve_jogador_com_id_e_nome():
    sala = Sala()
    jogador = sala.entrar("Ana")
    assert jogador.nome == "Ana"
    assert jogador.id
    assert jogador.chute_cm is None
    assert sala.jogadores == [jogador]


def test_entrar_gera_ids_diferentes():
    sala = Sala()
    a = sala.entrar("Ana")
    b = sala.entrar("Bruno")
    assert a.id != b.id


def test_entrar_recusa_nome_vazio_ou_em_branco():
    sala = Sala()
    for nome in ("", "   ", "\t"):
        with pytest.raises(ErroDeJogo, match="Digite"):
            sala.entrar(nome)


def test_entrar_corta_espacos_em_volta_do_nome():
    sala = Sala()
    assert sala.entrar("  Ana  ").nome == "Ana"


def test_entrar_recusa_nome_repetido_ignorando_caixa():
    sala = Sala()
    sala.entrar("Ana")
    # Asserts distintos de propósito: as duas mensagens contêm "nome", então um
    # match="nome" nos dois não detectaria erro trocado entre os casos.
    with pytest.raises(ErroDeJogo, match="já está em uso"):
        sala.entrar("ana")


def test_entrar_recusa_o_sexto_jogador():
    sala = Sala()
    for i in range(MAX_JOGADORES):
        sala.entrar(f"Jogador {i}")
    with pytest.raises(ErroDeJogo, match="cheia"):
        sala.entrar("Sexto")


def test_entrar_recusa_quando_a_sala_esta_travada():
    sala = Sala()
    sala.definir_trava(True)
    with pytest.raises(ErroDeJogo, match="travada"):
        sala.entrar("Ana")


def test_entrar_recusa_fora_de_aguardando():
    sala = Sala()
    sala.entrar("Ana")
    # Força o estado em vez de passar por chutar/iniciar_medicao: este teste é
    # sobre a recusa da entrada, não sobre como a sala chegou em MEDINDO. Assim
    # ele não depende de métodos que só nascem nas Tasks 2 e 3.
    sala.estado = Estado.MEDINDO
    with pytest.raises(ErroDeJogo, match="andamento"):
        sala.entrar("Bruno")


def test_entrar_aceita_nome_no_limite():
    sala = Sala()
    nome = "A" * MAX_NOME
    assert sala.entrar(nome).nome == nome


def test_entrar_recusa_nome_longo_demais():
    sala = Sala()
    with pytest.raises(ErroDeJogo, match="muito longo"):
        sala.entrar("A" * (MAX_NOME + 1))


# O que `jogo/sala.py` pode importar. Allowlist, não blocklist: um módulo novo
# de I/O não entra sozinho na lista.
IMPORTS_PERMITIDOS = {"__future__", "math", "secrets", "dataclasses", "enum"}


def test_sala_nao_ganha_io_sem_ninguem_notar():
    """Guarda da fronteira que o spec declara: a sala não fala com o mundo.

    A suíte inteira roda sem webcam e sem rede por causa disso. Um `import
    requests` acrescentado sem pensar dissolveria a garantia em silêncio — e
    doze tasks vão passar perto deste arquivo. Docstring avisa; teste impede.
    """
    codigo = (Path(__file__).parent.parent / "jogo" / "sala.py").read_text(
        encoding="utf-8"
    )
    importados = set()
    for no in ast.walk(ast.parse(codigo)):
        if isinstance(no, ast.Import):
            for apelido in no.names:
                importados.add(apelido.name.split(".")[0])
        elif isinstance(no, ast.ImportFrom) and no.module:
            importados.add(no.module.split(".")[0])
    proibidos = importados - IMPORTS_PERMITIDOS
    assert not proibidos, (
        f"jogo/sala.py passou a importar {sorted(proibidos)}. A sala tem que "
        "continuar sem I/O: nada de rede, câmera ou framework web."
    )


def _sala_com(*nomes: str) -> tuple[Sala, list[str]]:
    """Sala em AGUARDANDO com os jogadores dados. Devolve (sala, ids)."""
    sala = Sala()
    ids = [sala.entrar(nome).id for nome in nomes]
    return sala, ids


def test_chutar_guarda_valor_e_ordem():
    sala, (id_ana, id_bruno) = _sala_com("Ana", "Bruno")
    sala.chutar_por_id(id_bruno, 20.0)
    sala.chutar_por_id(id_ana, 10.0)
    bruno = sala.jogador(id_bruno)
    ana = sala.jogador(id_ana)
    assert bruno.chute_cm == 20.0
    assert ana.chute_cm == 10.0
    # Bruno chutou primeiro, então tem ordem menor — é o critério de desempate.
    assert bruno.ordem_do_chute < ana.ordem_do_chute


def test_chutar_aceita_editar_e_atualiza_a_ordem():
    sala, (id_ana, id_bruno) = _sala_com("Ana", "Bruno")
    sala.chutar_por_id(id_ana, 10.0)
    sala.chutar_por_id(id_bruno, 20.0)
    sala.chutar_por_id(id_ana, 12.5)
    assert sala.jogador(id_ana).chute_cm == 12.5
    # A regra é relativa, não absoluta: comparar a ordem da Ana só com ela
    # mesma passaria com qualquer implementação em que a ordem crescesse. O que
    # importa é que o Bruno, que cravou antes, agora está na frente dela.
    assert sala.jogador(id_bruno).ordem_do_chute < sala.jogador(id_ana).ordem_do_chute


def test_chutar_aceita_os_extremos():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 0.0)
    assert sala.jogador(id_ana).chute_cm == 0.0
    sala.chutar_por_id(id_ana, 200.0)
    assert sala.jogador(id_ana).chute_cm == 200.0


def test_chutar_recusa_fora_da_faixa():
    sala, (id_ana,) = _sala_com("Ana")
    for valor in (-0.1, 200.1, 99999.0):
        with pytest.raises(ErroDeJogo, match="0 e 200"):
            sala.chutar_por_id(id_ana, valor)


@pytest.mark.parametrize("nao_numero", [float("nan"), float("inf"), float("-inf")])
def test_chutar_recusa_nao_numero(nao_numero):
    sala, (id_ana,) = _sala_com("Ana")
    with pytest.raises(ErroDeJogo, match="número"):
        sala.chutar_por_id(id_ana, nao_numero)


def test_chutar_recusa_id_desconhecido():
    sala, _ = _sala_com("Ana")
    with pytest.raises(ErroDeJogo, match="não está mais na sala"):
        sala.chutar_por_id("id-que-nao-existe", 10.0)


@pytest.mark.parametrize(
    "estado", [Estado.MEDINDO, Estado.REVELANDO, Estado.RESULTADO]
)
def test_chutar_recusa_fora_de_aguardando(estado):
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    # Força o estado, como na Task 1: `iniciar_medicao` só nasce na Task 3, e
    # este teste é sobre a recusa do chute, não sobre a transição.
    sala.estado = estado
    # `match="já está valendo"` e não `match="andamento"`: as duas mensagens de
    # rodada em andamento contêm "andamento", então o match frouxo passaria
    # mesmo com a ramificação do `chute_cm is None` invertida. A Ana tem chute,
    # então é esta mensagem que ela tem que ouvir.
    with pytest.raises(ErroDeJogo, match="já está valendo"):
        sala.chutar_por_id(id_ana, 11.0)
    # O chute que já valia continua valendo.
    assert sala.jogador(id_ana).chute_cm == 10.0


def test_quantos_chutaram():
    sala, (id_ana, id_bruno) = _sala_com("Ana", "Bruno")
    assert sala.quantos_chutaram() == 0
    sala.chutar_por_id(id_ana, 10.0)
    assert sala.quantos_chutaram() == 1
    sala.chutar_por_id(id_ana, 11.0)
    assert sala.quantos_chutaram() == 1
    sala.chutar_por_id(id_bruno, 12.0)
    assert sala.quantos_chutaram() == 2


def test_quem_nao_chutou_nao_ouve_que_tem_chute_valendo():
    sala, (id_ana,) = _sala_com("Ana")
    sala.estado = Estado.MEDINDO
    with pytest.raises(ErroDeJogo, match="sem chute"):
        sala.chutar_por_id(id_ana, 11.0)


@pytest.mark.parametrize("chute_ruim", [999.0, -5.0, float("nan"), float("inf")])
def test_chute_recusado_nao_apaga_o_chute_anterior(chute_ruim):
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    ordem_original = sala.jogador(id_ana).ordem_do_chute
    with pytest.raises(ErroDeJogo):
        sala.chutar_por_id(id_ana, chute_ruim)
    # Nada é gravado até as validações passarem.
    assert sala.jogador(id_ana).chute_cm == 10.0
    assert sala.jogador(id_ana).ordem_do_chute == ordem_original


def test_iniciar_medicao_exige_pelo_menos_um_chute():
    sala, _ = _sala_com("Ana")
    with pytest.raises(ErroDeJogo, match="Ninguém chutou"):
        sala.iniciar_medicao()


def test_iniciar_medicao_muda_para_medindo():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    sala.iniciar_medicao()
    assert sala.estado is Estado.MEDINDO


def test_segundo_iniciar_medicao_e_recusado():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    sala.iniciar_medicao()
    with pytest.raises(ErroDeJogo, match="andamento"):
        sala.iniciar_medicao()


def test_concluir_medicao_vai_para_revelando_e_guarda_o_resultado():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, altura_cm=17.5, margem_cm=0.4, categoria="ALTA",
                          imagem_b64="iVBOR")
    assert sala.estado is Estado.REVELANDO
    assert sala.altura_cm == 17.5
    assert sala.margem_cm == 0.4
    assert sala.categoria == "ALTA"
    assert sala.imagem_b64 == "iVBOR"
    assert sala.erro is None


def test_revelacao_terminou_vai_para_resultado():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, 17.5, 0.4, "ALTA", "iVBOR")
    sala.revelacao_terminou(ticket)
    assert sala.estado is Estado.RESULTADO


def test_falhar_medicao_volta_para_aguardando_preservando_chutes():
    sala, (id_ana, id_bruno) = _sala_com("Ana", "Bruno")
    sala.chutar_por_id(id_ana, 10.0)
    sala.chutar_por_id(id_bruno, 20.0)
    ticket = sala.iniciar_medicao()
    sala.falhar_medicao(ticket, "A câmera não respondeu.")
    assert sala.estado is Estado.AGUARDANDO
    assert sala.erro == "A câmera não respondeu."
    # O grupo não digita tudo de novo por causa de um cabo solto.
    assert sala.jogador(id_ana).chute_cm == 10.0
    assert sala.jogador(id_bruno).chute_cm == 20.0


def test_erro_e_limpo_na_medicao_seguinte():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    ticket = sala.iniciar_medicao()
    sala.falhar_medicao(ticket, "A câmera não respondeu.")
    sala.iniciar_medicao()
    assert sala.erro is None


def test_ranking_ordena_por_erro_absoluto():
    sala, (id_ana, id_bruno, id_caio) = _sala_com("Ana", "Bruno", "Caio")
    sala.chutar_por_id(id_ana, 16.0)    # erra 1.5
    sala.chutar_por_id(id_bruno, 25.0)  # erra 7.5
    sala.chutar_por_id(id_caio, 17.0)   # erra 0.5
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, 17.5, 0.4, "ALTA", "iVBOR")
    nomes = [linha["nome"] for linha in sala.ranking()]
    assert nomes == ["Caio", "Ana", "Bruno"]
    assert sala.ranking()[0]["posicao"] == 1
    assert sala.ranking()[0]["erro_cm"] == 0.5
    assert sala.ranking()[0]["chute_cm"] == 17.0


def test_ranking_desempata_por_quem_chutou_primeiro():
    sala, (id_ana, id_bruno) = _sala_com("Ana", "Bruno")
    sala.chutar_por_id(id_bruno, 20.0)  # erra 2.5, chutou primeiro
    sala.chutar_por_id(id_ana, 15.0)    # erra 2.5, chutou depois
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, 17.5, 0.4, "ALTA", "iVBOR")
    assert [linha["nome"] for linha in sala.ranking()] == ["Bruno", "Ana"]


def test_ranking_desempata_por_ordem_quando_o_erro_arredondado_empata():
    sala, (id_ana, id_bruno) = _sala_com("Ana", "Bruno")
    # Medida 12,3: o erro do Bruno é 0.7000000000000011 e o da Ana é
    # 0.6999999999999993. O palco mostra "0,7 cm" nos dois. Sem arredondar
    # antes de ordenar, a Ana ganharia por uma diferença invisível, apesar de
    # o Bruno ter cravado primeiro.
    sala.chutar_por_id(id_bruno, 11.6)
    sala.chutar_por_id(id_ana, 13.0)
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, 12.3, 0.1, "ALTA", "iVBOR")
    linhas = sala.ranking()
    assert linhas[0]["erro_cm"] == linhas[1]["erro_cm"] == 0.7
    assert linhas[0]["nome"] == "Bruno"


def test_ranking_ignora_quem_nao_chutou():
    sala, (id_ana, _id_bruno) = _sala_com("Ana", "Bruno")
    sala.chutar_por_id(id_ana, 16.0)
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, 17.5, 0.4, "ALTA", "iVBOR")
    assert [linha["nome"] for linha in sala.ranking()] == ["Ana"]


def test_ranking_com_dois_jogadores_nao_inventa_terceiro_lugar():
    sala, (id_ana, id_bruno) = _sala_com("Ana", "Bruno")
    sala.chutar_por_id(id_ana, 16.0)
    sala.chutar_por_id(id_bruno, 19.0)
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, 17.5, 0.4, "ALTA", "iVBOR")
    # Grupo de dois é comum na feira e não pode parecer defeito.
    assert len(sala.ranking()) == 2


def test_ranking_vazio_antes_da_medicao():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 16.0)
    assert sala.ranking() == []


def test_ticket_velho_nao_afeta_a_medicao_nova():
    """O coração da correção: resposta atrasada não entra na rodada seguinte."""
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    t1 = sala.iniciar_medicao()
    sala.falhar_medicao(t1, "A câmera não respondeu.")
    t2 = sala.iniciar_medicao()
    assert t1 != t2
    # A resposta da medição 1 chega agora, atrasada.
    assert sala.concluir_medicao(t1, 17.5, 0.4, "ALTA", "iVBOR") is False
    assert sala.estado is Estado.MEDINDO
    assert sala.altura_cm is None
    # A medição 2 conclui normalmente.
    assert sala.concluir_medicao(t2, 9.0, 0.2, "MÉDIA", None) is True
    assert sala.altura_cm == 9.0


def test_falhar_medicao_obsoleta_nao_derruba_a_medicao_nova():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    t1 = sala.iniciar_medicao()
    sala.falhar_medicao(t1, "primeira falhou")
    t2 = sala.iniciar_medicao()
    # A falha atrasada da medição 1 não pode derrubar a 2 por baixo — era o
    # buraco que a guarda de estado sozinha deixava.
    assert sala.falhar_medicao(t1, "falha atrasada") is False
    assert sala.estado is Estado.MEDINDO
    assert sala.erro is None
    assert t2 == sala._medicao


def test_concluir_medicao_duas_vezes_descarta_a_segunda():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    t = sala.iniciar_medicao()
    assert sala.concluir_medicao(t, 17.5, 0.4, "ALTA", "iVBOR") is True
    assert sala.concluir_medicao(t, 99.0, 0.4, "ALTA", None) is False
    assert sala.altura_cm == 17.5


def test_revelacao_terminou_duas_vezes_descarta_a_segunda():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    t = sala.iniciar_medicao()
    sala.concluir_medicao(t, 17.5, 0.4, "ALTA", None)
    assert sala.revelacao_terminou(t) is True
    assert sala.revelacao_terminou(t) is False
    assert sala.estado is Estado.RESULTADO


@pytest.mark.parametrize("ruim", [float("nan"), float("inf"), float("-inf"), -1.0])
def test_concluir_medicao_recusa_altura_invalida(ruim):
    """NaN e infinito quebrariam o JSON de TODOS os clientes de uma vez."""
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    t = sala.iniciar_medicao()
    with pytest.raises(ValueError):
        sala.concluir_medicao(t, ruim, 0.4, "ALTA", None)
    # Nada gravado pela metade: a validação roda antes de qualquer mutação.
    assert sala.estado is Estado.MEDINDO
    assert sala.altura_cm is None


@pytest.mark.parametrize("ruim", [float("nan"), float("inf")])
def test_concluir_medicao_recusa_margem_invalida(ruim):
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    t = sala.iniciar_medicao()
    with pytest.raises(ValueError):
        sala.concluir_medicao(t, 17.5, ruim, "ALTA", None)
    assert sala.estado is Estado.MEDINDO


def test_iniciar_medicao_apaga_o_resultado_da_rodada_anterior():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    t1 = sala.iniciar_medicao()
    sala.concluir_medicao(t1, 17.5, 0.4, "ALTA", "iVBOR")
    # Na Task 4 isto acontece por `nova_rodada`; forçar o estado testa só a
    # limpeza, sem depender do método que ainda não existe.
    sala.estado = Estado.AGUARDANDO
    sala.iniciar_medicao()
    assert sala.altura_cm is None
    assert sala.margem_cm is None
    assert sala.categoria is None
    assert sala.imagem_b64 is None


def test_ranking_vazio_depois_de_falha_na_medicao():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    t = sala.iniciar_medicao()
    sala.falhar_medicao(t, "A câmera não respondeu.")
    assert sala.ranking() == []


def test_ranking_com_chute_exato_tem_erro_zero():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 17.5)
    t = sala.iniciar_medicao()
    sala.concluir_medicao(t, 17.5, 0.4, "ALTA", None)
    assert sala.ranking()[0]["erro_cm"] == 0.0


def test_ranking_desempata_por_ordem_reatribuida_na_edicao():
    sala, (id_ana, id_bruno) = _sala_com("Ana", "Bruno")
    sala.chutar_por_id(id_ana, 15.0)    # erra 2.5, cravou primeiro
    sala.chutar_por_id(id_bruno, 20.0)  # erra 2.5, cravou depois
    sala.chutar_por_id(id_ana, 15.0)    # reedita o MESMO número
    t = sala.iniciar_medicao()
    sala.concluir_medicao(t, 17.5, 0.4, "ALTA", None)
    # Mexer no chute custa a vantagem do desempate mesmo sem mudar o número.
    # É a interação entre a regra de edição (Task 2) e o ranking (Task 3).
    assert [linha["nome"] for linha in sala.ranking()] == ["Bruno", "Ana"]


def test_nova_rodada_limpa_tudo_e_reabre():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    sala.definir_trava(True)
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, 17.5, 0.4, "ALTA", "iVBOR")
    sala.revelacao_terminou(ticket)

    sala.nova_rodada()

    assert sala.estado is Estado.AGUARDANDO
    assert sala.jogadores == []
    assert sala.altura_cm is None
    assert sala.margem_cm is None
    assert sala.categoria is None
    assert sala.imagem_b64 is None
    assert sala.erro is None
    assert sala.ranking() == []
    # Reabrir é proposital: esquecer a sala travada entre dois grupos deixa o
    # grupo seguinte sem entrar e sem saber por quê.
    assert sala.aberta is True


@pytest.mark.parametrize("estado_antes", list(Estado))
def test_nova_rodada_funciona_de_qualquer_estado(estado_antes):
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    sala.estado = estado_antes  # força o estado: é a válvula de escape do host
    sala.nova_rodada()
    assert sala.estado is Estado.AGUARDANDO


def test_nova_rodada_permite_entrar_de_novo_com_o_mesmo_nome():
    sala, _ = _sala_com("Ana")
    sala.nova_rodada()
    assert sala.entrar("Ana").nome == "Ana"


def test_nova_rodada_descarta_a_medicao_em_voo():
    """A corrida real da feira: grupo vai embora durante a medição."""
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    ticket = sala.iniciar_medicao()

    sala.nova_rodada()
    id_bruno = sala.entrar("Bruno").id
    sala.chutar_por_id(id_bruno, 50.0)

    # A câmera responde agora, com a medida do grupo que já foi embora.
    assert sala.concluir_medicao(ticket, 17.5, 0.4, "ALTA", None) is False
    assert sala.estado is Estado.AGUARDANDO
    assert sala.altura_cm is None
    # O Bruno não pode ser coroado contra uma medida que não é dele.
    assert sala.ranking() == []
