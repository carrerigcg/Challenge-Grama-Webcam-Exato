"""Testes da camada de banco."""
import os

import pytest
from dotenv import load_dotenv

from api import db

load_dotenv()


@pytest.fixture
def pool():
    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST não configurada — veja .env.example")
    p = db.criar_pool(url)
    p.open()
    yield p
    p.close()


@pytest.fixture(scope="module", autouse=True)
def _restaura_schema_no_fim_do_modulo():
    """Rede de segurança: vários testes aqui dropam `leituras`/`medicoes` e
    contam com a chamada a `criar_schema` mais adiante NO MESMO teste pra
    devolver o estado normal. Se uma asserção ou o próprio `criar_schema`
    levantar no meio do caminho, a tabela fica dropada — e, como o banco de
    teste é compartilhado entre os testes (não há TRUNCATE por teste aqui),
    isso viraria uma cascata de falhas escondendo a falha real, ou pior:
    o stub de uma coluna só de `test_criar_schema_nao_mexe_se_as_duas_tabelas_existirem`
    sobreviveria e seria renomeado pra `leituras` na PRÓXIMA execução, com o
    `CREATE TABLE IF NOT EXISTS` recusando completar as colunas que faltam.
    Roda uma vez, no fim do módulo, independente de sucesso ou falha.
    """
    yield
    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        return
    p = db.criar_pool(url)
    p.open()
    try:
        with p.connection() as conn:
            conn.execute("DROP TABLE IF EXISTS medicoes")
        db.criar_schema(p)
    finally:
        p.close()


def _criar_legado(pool):
    """Recria o estado antigo: tabela `medicoes` com índice e uma linha dentro."""
    with pool.connection() as conn:
        conn.execute("DROP TABLE IF EXISTS leituras")
        conn.execute("DROP TABLE IF EXISTS medicoes")
        conn.execute(
            """
            CREATE TABLE medicoes (
                id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                regiao        TEXT NOT NULL,
                altura_cm     DOUBLE PRECISION NOT NULL,
                nivel_risco   TEXT NOT NULL,
                temperatura_c DOUBLE PRECISION,
                clima         TEXT,
                criado_em     TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            "CREATE INDEX idx_medicoes_regiao_criado_em "
            "ON medicoes (regiao, criado_em DESC)"
        )
        conn.execute(
            "INSERT INTO medicoes (regiao, altura_cm, nivel_risco) "
            "VALUES ('legado', 4.2, 'MEDIA')"
        )


def test_criar_schema_cria_tabela_leituras(pool):
    db.criar_schema(pool)
    with pool.connection() as conn:
        row = conn.execute("SELECT to_regclass('public.leituras') AS t").fetchone()
    assert row["t"] == "leituras"


def test_criar_schema_cria_do_zero_sem_tabela_antiga(pool):
    """Banco novo, sem `medicoes` nenhuma: o rename é no-op e o CREATE resolve.

    Sem este teste, os outros passariam mesmo com um RENAME_SQL que só
    funcionasse a partir de uma base já existente.
    """
    with pool.connection() as conn:
        conn.execute("DROP TABLE IF EXISTS leituras")
        conn.execute("DROP TABLE IF EXISTS medicoes")

    db.criar_schema(pool)

    with pool.connection() as conn:
        row = conn.execute("SELECT count(*) AS n FROM leituras").fetchone()
    assert row["n"] == 0


def test_criar_schema_e_idempotente(pool):
    """`assert n >= 0` nunca falharia — o que prova idempotência de verdade é
    a linha sobreviver: se a segunda chamada dropasse e recriasse a tabela,
    ela teria sumido."""
    db.criar_schema(pool)
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO leituras (regiao, altura_cm, nivel_risco) "
            "VALUES ('sobrevive', 9.9, 'ALTA')"
        )

    db.criar_schema(pool)  # rodar de novo não pode dropar nem recriar a tabela

    with pool.connection() as conn:
        row = conn.execute(
            "SELECT altura_cm FROM leituras WHERE regiao = 'sobrevive'"
        ).fetchone()
    assert row is not None
    assert row["altura_cm"] == 9.9


def test_criar_schema_cria_indice_por_regiao(pool):
    db.criar_schema(pool)
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'leituras' AND indexname = %s",
            ("idx_leituras_regiao_criado_em",),
        ).fetchone()
    assert row is not None


def test_criar_schema_renomeia_medicoes_preservando_as_linhas(pool):
    """O teste que pega a inversão de ordem.

    Se o `CREATE TABLE IF NOT EXISTS leituras` rodar antes do rename, ele cria
    uma `leituras` vazia, o rename desiste por ver que ela já existe, e o
    histórico de produção fica órfão em `medicoes` — sem erro nenhum no log.
    """
    _criar_legado(pool)

    db.criar_schema(pool)

    with pool.connection() as conn:
        antiga = conn.execute(
            "SELECT to_regclass('public.medicoes') AS t"
        ).fetchone()
        linha = conn.execute("SELECT regiao, altura_cm FROM leituras").fetchone()
    assert antiga["t"] is None, "a tabela antiga devia ter sumido no rename"
    assert linha["regiao"] == "legado"
    assert linha["altura_cm"] == 4.2


def test_criar_schema_renomeia_o_indice_junto(pool):
    _criar_legado(pool)

    db.criar_schema(pool)

    with pool.connection() as conn:
        row = conn.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'leituras' AND indexname = %s",
            ("idx_leituras_regiao_criado_em",),
        ).fetchone()
    assert row is not None


def test_criar_schema_nao_deixa_objeto_nenhum_chamado_medicoes(pool):
    """`idx_leituras_regiao_criado_em` sozinho não pega tudo: a sequence da
    IDENTITY e o índice da PK também são renomeados pelo RENAME_SQL, e um
    teste que olhasse só pro índice nomeado explicitamente não pegaria uma
    regressão ali — passaria mesmo com `leituras` carregando sequence/pkey
    ainda chamados `medicoes_*`.
    """
    _criar_legado(pool)

    db.criar_schema(pool)

    with pool.connection() as conn:
        indices_orfaos = conn.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'leituras' AND indexname LIKE 'medicoes%'"
        ).fetchall()
        sequences_orfas = conn.execute(
            "SELECT relname FROM pg_class "
            "WHERE relkind = 'S' AND relname LIKE 'medicoes%'"
        ).fetchall()
    assert indices_orfaos == []
    assert sequences_orfas == []


def test_criar_schema_nao_mexe_se_as_duas_tabelas_existirem(pool):
    """Estado meio-migrado: preservar `leituras` importa mais que limpar."""
    db.criar_schema(pool)
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO leituras (regiao, altura_cm, nivel_risco) "
            "VALUES ('nova', 1.0, 'BAIXA')"
        )
        conn.execute("DROP TABLE IF EXISTS medicoes")
        conn.execute("CREATE TABLE medicoes (id BIGINT PRIMARY KEY)")

    db.criar_schema(pool)

    with pool.connection() as conn:
        row = conn.execute(
            "SELECT regiao FROM leituras WHERE regiao = 'nova'"
        ).fetchone()
        conn.execute("DROP TABLE IF EXISTS medicoes")
    assert row is not None, "leituras não podia ter sido tocada"


def test_criar_pool_nao_conecta_antes_de_abrir():
    """open=False deixa quem chama decidir a hora de conectar (lifespan/fixture)."""
    p = db.criar_pool("postgresql://ninguem@localhost:1/inexistente")
    assert p.closed
