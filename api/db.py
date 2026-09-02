"""Pool de conexões e schema do Postgres."""
from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# Roda ANTES do SCHEMA_SQL. A ordem não é negociável: se o
# `CREATE TABLE IF NOT EXISTS leituras` vier primeiro, ele cria a tabela vazia,
# este bloco desiste por ver que `leituras` já existe, e a `medicoes` de
# produção fica órfã com todo o histórico dentro. Falha silenciosa.
#
# Renomeia tabela, sequence e índices juntos — confirmado empiricamente que
# uma tabela `medicoes` criada com IDENTITY tem sequence `medicoes_id_seq` e
# índice de PK `medicoes_pkey`; sem renomear os três, produção fica com
# `leituras` cujos objetos internos ainda se chamam `medicoes_*`, divergente
# de qualquer banco novo (que já nasce com tudo `leituras_*` via SCHEMA_SQL).
# Renomear o índice da PK também renomeia a constraint correspondente
# (mesmo objeto internamente) — não precisa de ALTER TABLE RENAME CONSTRAINT
# à parte.
#
# Decisão consciente: as constraints NOT NULL (`medicoes_id_not_null`,
# `medicoes_regiao_not_null` etc. — nomeadas em pg_constraint a partir do
# PG 18) NÃO são renomeadas e ficam com o nome antigo pra sempre. Elas não
# têm `RENAME CONSTRAINT ... IF EXISTS`: renomear uma que não existe levanta
# UndefinedObject e aborta o bloco `DO` inteiro, virando um jeito de a API
# não subir por causa de um nome que ninguém consulta. A alternativa — um
# loop com `EXECUTE format(...)` descobrindo os nomes em tempo de execução —
# é SQL dinâmico sem supervisão rodando uma vez contra produção; não vale a
# pena pra um detalhe cosmético. Se um dia importar, isso pede um bloco
# `DO` novo e guardado, não um ajuste aqui.
#
# Só dispara uma vez contra produção: no instante em que rodar,
# to_regclass('public.leituras') deixa de ser NULL pra sempre e o bloco vira
# no-op — não dá pra "consertar depois" com uma segunda passada deste mesmo
# bloco. Pode ser apagado assim que o deploy tiver rodado em produção (a
# partir de 2026-09-02); uma futura migração precisa do próprio bloco, não
# deve se acumular aqui.
RENAME_SQL = """
DO $$
BEGIN
    IF to_regclass('public.medicoes') IS NOT NULL
       AND to_regclass('public.leituras') IS NULL THEN
        ALTER TABLE public.medicoes RENAME TO leituras;
        ALTER SEQUENCE IF EXISTS public.medicoes_id_seq RENAME TO leituras_id_seq;
        ALTER INDEX IF EXISTS public.medicoes_pkey RENAME TO leituras_pkey;
        ALTER INDEX IF EXISTS public.idx_medicoes_regiao_criado_em
            RENAME TO idx_leituras_regiao_criado_em;
    END IF;
END $$;
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS leituras (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    regiao        TEXT NOT NULL,
    altura_cm     DOUBLE PRECISION NOT NULL,
    nivel_risco   TEXT NOT NULL,
    temperatura_c DOUBLE PRECISION,
    clima         TEXT,
    criado_em     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_leituras_regiao_criado_em
    ON leituras (regiao, criado_em DESC);
"""


def criar_pool(database_url: str) -> ConnectionPool:
    """Cria o pool fechado. Quem chama decide quando abrir (lifespan/fixture).

    Abrir/fechar conexão a cada request custa TCP + TLS + auth contra um
    Postgres remoto — caro o bastante pra valer o pool, ainda mais no plano
    gratuito, que limita conexões simultâneas.
    """
    return ConnectionPool(
        database_url,
        min_size=1,
        max_size=5,
        kwargs={"row_factory": dict_row},
        open=False,
    )


def criar_schema(pool: ConnectionPool) -> None:
    """Migra e cria o schema. Idempotente. Rename primeiro — veja RENAME_SQL."""
    with pool.connection() as conn:
        conn.execute(RENAME_SQL)
        conn.execute(SCHEMA_SQL)
