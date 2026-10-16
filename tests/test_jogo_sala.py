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
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    primeira_ordem = sala.jogador(id_ana).ordem_do_chute
    sala.chutar_por_id(id_ana, 12.5)
    assert sala.jogador(id_ana).chute_cm == 12.5
    assert sala.jogador(id_ana).ordem_do_chute > primeira_ordem


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


def test_chutar_recusa_nao_numero():
    sala, (id_ana,) = _sala_com("Ana")
    with pytest.raises(ErroDeJogo, match="número"):
        sala.chutar_por_id(id_ana, float("nan"))


def test_chutar_recusa_id_desconhecido():
    sala, _ = _sala_com("Ana")
    with pytest.raises(ErroDeJogo, match="sala"):
        sala.chutar_por_id("id-que-nao-existe", 10.0)


def test_chutar_recusa_fora_de_aguardando():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    # Força o estado, como na Task 1: `iniciar_medicao` só nasce na Task 3, e
    # este teste é sobre a recusa do chute, não sobre a transição.
    sala.estado = Estado.MEDINDO
    with pytest.raises(ErroDeJogo, match="andamento"):
        sala.chutar_por_id(id_ana, 11.0)


def test_quantos_chutaram():
    sala, (id_ana, id_bruno) = _sala_com("Ana", "Bruno")
    assert sala.quantos_chutaram() == 0
    sala.chutar_por_id(id_ana, 10.0)
    assert sala.quantos_chutaram() == 1
    sala.chutar_por_id(id_ana, 11.0)
    assert sala.quantos_chutaram() == 1
    sala.chutar_por_id(id_bruno, 12.0)
    assert sala.quantos_chutaram() == 2
