"""Testes da camada de banco."""
import os

import psycopg
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
    """Rede de segurança contra contaminação ENTRE EXECUÇÕES da suíte — não
    entre testes desta execução. Sendo module-scoped, roda uma vez só, depois
    do último teste do módulo: se um teste no meio quebrar tudo, os testes
    seguintes NA MESMA RODADA ainda veem o banco quebrado (medido na prática:
    trocar pra function-scoped isolaria cada teste, mas custou ~26s a mais
    nesta suíte — 62s contra 36s — e não vale o preço aqui).

    O que ela evita de verdade: vários testes aqui dropam `leituras`/
    `medicoes` e contam com a chamada a `criar_schema` mais adiante NO MESMO
    teste pra devolver o estado normal; se isso falhar no meio do caminho, a
    tabela fica dropada até o fim da rodada. Sem essa rede, a PRÓXIMA
    execução da suíte herdaria esse banco quebrado — por exemplo, o stub de
    uma coluna só de `test_criar_schema_nao_mexe_se_as_duas_tabelas_existirem`
    sobrevivendo e sendo renomeado pra `leituras`, com `CREATE TABLE IF NOT
    EXISTS` recusando completar as colunas que faltam.
    """
    yield
    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        return
    p = db.criar_pool(url)
    p.open()
    try:
        with p.connection() as conn:
            # As três — não só `medicoes`. Um `leituras` malformado (o stub de
            # uma coluna só de test_criar_schema_nao_mexe_se_as_duas_tabelas_existirem,
            # por exemplo) faz o `CREATE TABLE IF NOT EXISTS` da SCHEMA_SQL virar
            # no-op e o `CREATE INDEX ... (regiao, ...)` seguinte estourar
            # UndefinedColumn — a própria função de restauração quebraria e
            # deixaria o banco de teste no estado exato que ela deveria evitar.
            # `previsoes` entra pelo mesmo motivo: um `CREATE TABLE IF NOT
            # EXISTS` também não conserta uma tabela malformada existente.
            conn.execute("DROP TABLE IF EXISTS leituras")
            conn.execute("DROP TABLE IF EXISTS medicoes")
            conn.execute("DROP TABLE IF EXISTS previsoes")
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
    ela teria sumido. Conta em vez de `.fetchone()` pra rodagens repetidas
    não acumularem duplicata silenciosa e ainda passar; limpa a própria linha
    no final — `test_db.py` não tem TRUNCATE por teste."""
    db.criar_schema(pool)
    try:
        with pool.connection() as conn:
            conn.execute(
                "INSERT INTO leituras (regiao, altura_cm, nivel_risco) "
                "VALUES ('sobrevive', 9.9, 'ALTA')"
            )

        db.criar_schema(pool)  # rodar de novo não pode dropar nem recriar a tabela

        with pool.connection() as conn:
            row = conn.execute(
                "SELECT count(*) AS n FROM leituras "
                "WHERE regiao = 'sobrevive' AND altura_cm = 9.9"
            ).fetchone()
        assert row["n"] == 1
    finally:
        with pool.connection() as conn:
            conn.execute("DELETE FROM leituras WHERE regiao = 'sobrevive'")


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


def test_criar_schema_nao_deixa_indice_ou_sequence_orfaos(pool):
    """`idx_leituras_regiao_criado_em` sozinho não pega tudo: a sequence da
    IDENTITY e o índice da PK também são renomeados pelo RENAME_SQL, e um
    teste que olhasse só pro índice nomeado explicitamente não pegaria uma
    regressão ali — passaria mesmo com `leituras` carregando sequence/pkey
    ainda chamados `medicoes_*`.

    Não cobre TODO objeto: as constraints NOT NULL (nomeadas em pg_constraint
    a partir do PG 18) ficam `medicoes_*_not_null` de propósito — não têm
    `RENAME CONSTRAINT ... IF EXISTS`, e forçar isso arriscaria abortar o
    boot da API por um nome cosmético. Ver o comentário do RENAME_SQL.
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
            "WHERE relkind = 'S' AND relnamespace = 'public'::regnamespace "
            "AND relname LIKE 'medicoes%'"
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


def test_criar_schema_cria_tabela_previsoes(pool):
    db.criar_schema(pool)
    with pool.connection() as conn:
        row = conn.execute("SELECT to_regclass('public.previsoes') AS t").fetchone()
    assert row["t"] == "previsoes"


def test_previsoes_guarda_bytes_intactos(pool):
    """BYTEA tem que devolver byte a byte o que entrou — xlsx é binário.

    Também pina o `tamanho_bytes` GERADO: é o comportamento que a coluna
    generated existe pra garantir (nunca diverge do blob real). Limpa a
    própria linha no final — mesma convenção de test_criar_schema_e_idempotente,
    já que `test_db.py` não tem TRUNCATE por teste."""
    db.criar_schema(pool)
    conteudo = b"PK\x03\x04\x00\xff\xfe qualquer binario"
    try:
        with pool.connection() as conn:
            conn.execute(
                "INSERT INTO previsoes (nome_arquivo, conteudo) VALUES (%s, %s)",
                ("p.xlsx", conteudo),
            )
            row = conn.execute(
                "SELECT conteudo, tamanho_bytes FROM previsoes "
                "WHERE nome_arquivo = 'p.xlsx'"
            ).fetchone()
        assert bytes(row["conteudo"]) == conteudo
        assert row["tamanho_bytes"] == len(conteudo)
    finally:
        with pool.connection() as conn:
            conn.execute("DELETE FROM previsoes WHERE nome_arquivo = 'p.xlsx'")


def test_previsoes_tamanho_bytes_rejeita_insert_explicito(pool):
    """GENERATED ALWAYS não aceita valor explícito.

    A coluna só pode vir de `length(conteudo)` — se aceitasse um valor à
    parte, voltaria a poder divergir do blob, que é exatamente o problema
    que a coluna generated existe pra fechar (scripts/ grava direto no banco,
    sem passar pela validação da API)."""
    db.criar_schema(pool)
    with pool.connection() as conn:
        with pytest.raises(psycopg.errors.GeneratedAlways):
            conn.execute(
                "INSERT INTO previsoes (nome_arquivo, conteudo, tamanho_bytes) "
                "VALUES (%s, %s, %s)",
                ("p.xlsx", b"x", 1),
            )


def test_previsoes_rejeita_conteudo_vazio(pool):
    """`''::bytea` passa pelo NOT NULL mas não é um xlsx válido — sem o CHECK,
    um GET nessa linha serviria um download que não abre em nada."""
    db.criar_schema(pool)
    with pool.connection() as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO previsoes (nome_arquivo, conteudo) VALUES (%s, %s)",
                ("vazio.xlsx", b""),
            )


def test_previsoes_rejeita_conteudo_maior_que_10mb(pool):
    """Backstop contra um INSERT feito fora da API (scripts/, psql direto)
    que não passaria pelo limite que a Task 5 vai aplicar.

    `repeat('x', ...)::bytea` gera o blob grande dentro do próprio Postgres —
    não faz sentido mandar 10 MB de verdade pela rede só pra provar que o
    CHECK dispara."""
    db.criar_schema(pool)
    with pool.connection() as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO previsoes (nome_arquivo, conteudo) "
                "VALUES ('grande.xlsx', repeat('x', 10*1024*1024 + 1)::bytea)"
            )


def test_criar_schema_cria_indice_de_previsoes_por_data(pool):
    """O GET pega a mais recente; sem índice isso vira scan da tabela toda."""
    db.criar_schema(pool)
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'previsoes' AND indexname = %s",
            ("idx_previsoes_criado_em",),
        ).fetchone()
    assert row is not None
