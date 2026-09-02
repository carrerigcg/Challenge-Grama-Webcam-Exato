"""Testes de scripts/backup.py — a exportação de .xlsx de `previsoes`.

Roda contra DATABASE_URL_TEST, igual tests/test_db.py: nunca contra produção.
"""
import os

import pytest
from dotenv import load_dotenv

from api import db
from scripts.backup import _nome_seguro, exportar_previsoes

load_dotenv()


@pytest.fixture
def pool():
    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST não configurada — veja .env.example")
    p = db.criar_pool(url)
    p.open()
    db.criar_schema(p)
    # TRUNCATE por teste, igual ao fixture `client` do conftest.py: estes
    # testes contam arquivos exportados, então presumem a tabela vazia. Sem
    # isto eles passam sozinhos e falham na suíte inteira — `test_api.py` roda
    # antes (ordem alfabética) e a última leitura dele sobrevive, virando um
    # `assert 2 == 1` que parece bug do backup e é sujeira de outro arquivo.
    with p.connection() as conn:
        conn.execute("TRUNCATE previsoes RESTART IDENTITY")
    yield p
    p.close()


def _url():
    return os.environ["DATABASE_URL_TEST"]


def _inserir(pool, nome, conteudo):
    with pool.connection() as conn:
        row = conn.execute(
            "INSERT INTO previsoes (nome_arquivo, conteudo) VALUES (%s, %s) "
            "RETURNING id",
            (nome, conteudo),
        ).fetchone()
    return row["id"]


def _remover(pool, *ids):
    with pool.connection() as conn:
        conn.execute("DELETE FROM previsoes WHERE id = ANY(%s)", (list(ids),))


def test_exportar_previsoes_grava_bytes_identicos_ao_banco(pool, tmp_path):
    """O ponto do .xlsx em disco em vez de bytea num INSERT: tem que abrir
    exatamente igual ao que foi salvo, byte a byte."""
    conteudo = b"PK\x03\x04\x00\xff\xfe conteudo binario de verdade \x00\x01"
    id_ = _inserir(pool, "relatorio.xlsx", conteudo)
    try:
        n = exportar_previsoes(_url(), tmp_path)
        assert n == 1
        arquivos = list(tmp_path.iterdir())
        assert len(arquivos) == 1
        assert arquivos[0].name == f"{id_:04d}-relatorio.xlsx"
        assert arquivos[0].read_bytes() == conteudo
    finally:
        _remover(pool, id_)


def test_exportar_previsoes_sanitiza_nome_invalido_no_windows(pool, tmp_path):
    """`:` passa a validação de criar_previsao (api/main.py) — não é aspas,
    CR/LF, barra ou fora do Latin-1 — mas o NTFS recusa como nome de arquivo.
    Sem sanitização, `Path.write_bytes` levantaria OSError e abortaria o
    laço inteiro, inclusive as previsões que viriam depois na exportação."""
    id_ = _inserir(pool, "previsao:2026.xlsx", b"conteudo qualquer")
    try:
        n = exportar_previsoes(_url(), tmp_path)
        assert n == 1
        arquivos = list(tmp_path.iterdir())
        assert len(arquivos) == 1
        assert ":" not in arquivos[0].name
        assert arquivos[0].read_bytes() == b"conteudo qualquer"
    finally:
        _remover(pool, id_)


def test_nome_seguro_troca_caracteres_proibidos_no_windows():
    """Unitário e direto na função de sanitização, sem depender do banco —
    cobre o conjunto inteiro de caracteres que o NTFS recusa (a API só
    barra um subconjunto deles: aspas, barra invertida e controle)."""
    assert _nome_seguro('a:b*c?d"e<f>g|h.xlsx') == "a_b_c_d_e_f_g_h.xlsx"


def test_exportar_previsoes_tabela_vazia_nao_gera_arquivo(pool, tmp_path):
    """Sem previsão nenhuma o backup não pode inventar arquivo nem levantar —
    o fixture já entrega a tabela vazia."""
    n = exportar_previsoes(_url(), tmp_path)
    assert n == 0
    assert list(tmp_path.iterdir()) == []
