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
