# `/leituras` e `/previsoes` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Alinhar a API ao diagrama do consumidor externo — renomear `/medicoes` para `/leituras` (rota e tabela) sem derrubar as estações em campo, e acrescentar `/previsoes` para upload e download de planilhas `.xlsx`.

**Architecture:** FastAPI com autenticação por `X-API-Key` (chave de escrita e chave de leitura separadas) sobre Postgres no Neon. As planilhas são guardadas como `BYTEA` na tabela `previsoes`, não em disco: o filesystem do Render no plano free é efêmero e some a cada deploy. O schema nasce de `criar_schema()` no `lifespan` do app; não existe framework de migration, então o rename da tabela entra ali como bloco idempotente que roda **antes** do `CREATE TABLE IF NOT EXISTS`.

**Tech Stack:** Python 3.11, FastAPI, psycopg 3 (+ pool), Pydantic v2, pytest, Postgres (Neon), `python-multipart` para upload.

**Spec:** `docs/superpowers/specs/2026-09-02-leituras-e-previsoes-design.md`

---

## Contexto para quem nunca viu este repositório

- `api/main.py` — a API inteira: autenticação, schemas Pydantic e rotas.
- `api/db.py` — pool de conexões e o SQL do schema. `criar_schema(pool)` roda a cada boot e precisa ser idempotente.
- `medir_grama.py` — roda nas estações de captura (Raspberry Pi), mede a grama pela webcam e faz POST na API. **Não se atualiza sozinho em campo.**
- `scripts/backup.py` — baixa os dados de produção para CSV e SQL. É a garantia de posse dos dados: nada de lock-in.
- `scripts/seed_exemplos.py` — popula o banco com exemplos para o consumidor externo testar.
- `tests/conftest.py` — fixtures. O `client` é session-scoped (abrir conexão no Neon é caro) e dá `TRUNCATE` a cada teste.

**Os testes exigem `DATABASE_URL_TEST` no `.env`**, apontando para a branch `test` do Neon. Sem ela a suíte é pulada, não falha. Nunca aponte para a base de produção: os testes dão `TRUNCATE`.

Rodar tudo: `python -m pytest -v`

## Estrutura de arquivos

Nenhum arquivo novo. O trabalho é todo em arquivos existentes, cada um mantendo a responsabilidade que já tem:

| Arquivo | Responsabilidade | O que muda |
|---|---|---|
| `api/db.py` | schema e pool | rename idempotente, tabela `previsoes` |
| `api/main.py` | rotas, auth, schemas | rotas renomeadas + aliases ocultos + rotas de previsão |
| `medir_grama.py` | estação de captura | URL do POST |
| `scripts/backup.py` | export de produção | nome da tabela + export das planilhas |
| `scripts/seed_exemplos.py` | dados de exemplo | nome da tabela |
| `tests/conftest.py` | fixtures | `TRUNCATE` nas duas tabelas |
| `tests/test_db.py` | schema | rename e tabela nova |
| `tests/test_api.py` | rotas | rotas renomeadas, aliases, previsões |
| `requirements-api.txt` | deps da API | `python-multipart` |

`api/main.py` cresce com as rotas de previsão, mas continua abaixo de 300 linhas e com uma responsabilidade só. Não vale quebrar em módulos agora.

---

## Task 1: Renomear a tabela `medicoes` para `leituras`

Só a **tabela**. As rotas continuam `/medicoes` nesta task — assim a suíte fica verde no commit.

**Files:**
- Modify: `api/db.py`
- Modify: `api/main.py:105`, `api/main.py:131`, `api/main.py:150`
- Modify: `scripts/backup.py`, `scripts/seed_exemplos.py`
- Test: `tests/test_db.py`, `tests/conftest.py`, `tests/test_api.py:41`

- [ ] **Step 1: Escrever os testes que falham**

Substitua os três primeiros testes de `tests/test_db.py` (de `test_criar_schema_cria_tabela_medicoes` até `test_criar_schema_cria_indice_por_regiao`, inclusive) por este bloco. Mantenha o cabeçalho do arquivo e o último teste (`test_criar_pool_nao_conecta_antes_de_abrir`) como estão.

```python
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
    db.criar_schema(pool)
    db.criar_schema(pool)  # rodar de novo não pode levantar
    with pool.connection() as conn:
        row = conn.execute("SELECT count(*) AS n FROM leituras").fetchone()
    assert row["n"] >= 0


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
```

- [ ] **Step 2: Rodar os testes e ver falhar**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL. `test_criar_schema_cria_tabela_leituras` falha com `assert None == 'leituras'`; os que fazem `SELECT ... FROM leituras` falham com `UndefinedTable: relation "leituras" does not exist`.

- [ ] **Step 3: Reescrever o schema em `api/db.py`**

Substitua o bloco de `SCHEMA_SQL` e `criar_schema` (linhas 7-20 e 39-43) por:

```python
# Roda ANTES do SCHEMA_SQL. A ordem não é negociável: se o
# `CREATE TABLE IF NOT EXISTS leituras` vier primeiro, ele cria a tabela vazia,
# este bloco desiste por ver que `leituras` já existe, e a `medicoes` de
# produção fica órfã com todo o histórico dentro. Falha silenciosa.
RENAME_SQL = """
DO $$
BEGIN
    IF to_regclass('public.medicoes') IS NOT NULL
       AND to_regclass('public.leituras') IS NULL THEN
        ALTER TABLE medicoes RENAME TO leituras;
        ALTER INDEX IF EXISTS idx_medicoes_regiao_criado_em
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
```

E a função:

```python
def criar_schema(pool: ConnectionPool) -> None:
    """Migra e cria o schema. Idempotente. Rename primeiro — veja RENAME_SQL."""
    with pool.connection() as conn:
        conn.execute(RENAME_SQL)
        conn.execute(SCHEMA_SQL)
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run: `python -m pytest tests/test_db.py -v`
Expected: PASS, 8 testes.

- [ ] **Step 5: Trocar o nome da tabela no resto do código**

Estas são as ocorrências de `medicoes` como **tabela** (nunca como URL — as rotas continuam `/medicoes` até a Task 2).

`api/main.py`, três lugares:

```
linha 105:  INSERT INTO medicoes                    ->  INSERT INTO leituras
linha 131:  sql = "SELECT * FROM medicoes"          ->  sql = "SELECT * FROM leituras"
linha 150:  "SELECT * FROM medicoes WHERE id = %s"  ->  "SELECT * FROM leituras WHERE id = %s"
```

`tests/conftest.py` linha 50:

```python
        conn.execute("TRUNCATE leituras RESTART IDENTITY")
```

`tests/test_api.py` linha 41:

```python
        row = conn.execute("SELECT altura_cm FROM leituras").fetchone()
```

`scripts/seed_exemplos.py` linha 62: `INSERT INTO medicoes` -> `INSERT INTO leituras`.

`scripts/backup.py`, cinco strings SQL — linhas 43, 48, 51, 53 e 66. O comando abaixo pega todas sem tocar em `medicoes-{carimbo}` (nome do arquivo de saída, que fica como está por causa dos backups já gravados):

```bash
sed -i 's/COPY medicoes /COPY leituras /; s/FROM medicoes /FROM leituras /; s/Backup de medicoes\./Backup de leituras./; s/CREATE TABLE IF NOT EXISTS medicoes (/CREATE TABLE IF NOT EXISTS leituras (/; s/INSERT INTO medicoes /INSERT INTO leituras /' scripts/backup.py
```

Confira que sobrou só o nome do arquivo:

```bash
grep -n medicoes scripts/backup.py
```
Expected: uma linha só, a do `f"medicoes-{carimbo}"`.

- [ ] **Step 6: Rodar a suíte inteira**

Run: `python -m pytest -v`
Expected: PASS, tudo verde. As rotas ainda são `/medicoes` e continuam funcionando sobre a tabela nova.

- [ ] **Step 7: Commit**

```bash
git add api/db.py api/main.py scripts/backup.py scripts/seed_exemplos.py tests/
git commit -m "refactor(db)!: renomeia tabela medicoes para leituras

Rename idempotente no criar_schema, antes do CREATE TABLE -- na ordem
inversa o CREATE cria uma leituras vazia, o rename desiste e o historico
de producao fica orfao sem erro no log.

As rotas seguem /medicoes nesta etapa."
```

---

## Task 2: Rotas `/leituras`, com `/medicoes` sobrevivendo como alias oculto

**Files:**
- Modify: `api/main.py:67-154`
- Test: `tests/test_api.py`

- [ ] **Step 1: Renomear as rotas nos testes que já existem**

```bash
sed -i 's|"/medicoes|"/leituras|g; s|f"/medicoes/|f"/leituras/|g; s|--- POST /medicoes|--- POST /leituras|; s|--- GET /medicoes|--- GET /leituras|' tests/test_api.py
grep -n medicoes tests/test_api.py
```
Expected do `grep`: nada. Todas as chamadas agora batem em `/leituras`.

- [ ] **Step 2: Escrever os testes dos aliases**

Acrescente ao fim de `tests/test_api.py`:

```python
# --- Aliases de compatibilidade ----------------------------------------------
# As estações em campo (medir_grama.py) postam em /medicoes e não se atualizam
# sozinhas. Sem estes aliases, o primeiro deploy derruba toda a captura até
# alguém ir de máquina em máquina. Some quando as estações estiverem atualizadas.
def test_post_no_alias_medicoes_ainda_grava(client, headers_escrita):
    r = client.post("/medicoes", json=_payload(), headers=headers_escrita)
    assert r.status_code == 200
    assert r.json()["regiao"] == "mato do matheus"


def test_get_no_alias_medicoes_ainda_le(client, headers_escrita, headers_leitura):
    client.post("/leituras", json=_payload(), headers=headers_escrita)
    r = client.get("/medicoes", headers=headers_leitura)
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_alias_medicoes_exige_chave(client):
    r = client.post("/medicoes", json=_payload())
    assert r.status_code == 401


def test_aliases_ficam_fora_da_documentacao(client):
    """Ninguém novo deve descobrir /medicoes e passar a depender dele."""
    caminhos = client.get("/openapi.json").json()["paths"]
    assert "/leituras" in caminhos
    assert "/medicoes" not in caminhos
```

- [ ] **Step 3: Rodar os testes e ver falhar**

Run: `python -m pytest tests/test_api.py -v`
Expected: FAIL com 404 em todas as chamadas a `/leituras` (a rota ainda não existe).

- [ ] **Step 4: Renomear as rotas e registrar os aliases em `api/main.py`**

Renomeie os schemas — `MedicaoIn` -> `LeituraIn`, `MedicaoOut` -> `LeituraOut` — e o nome das funções, e empilhe um segundo decorador em cada rota. O decorador de rota do FastAPI devolve a função sem alterar nada, então empilhar registra os dois caminhos no mesmo handler.

Substitua o bloco de schemas e endpoints (linha 67 até o fim do arquivo) por:

```python
class LeituraIn(BaseModel):
    # Sem default: cada estação precisa se identificar, senão leituras de
    # locais diferentes colidem numa região só.
    regiao: str = Field(min_length=1)
    altura_cm: float = Field(ge=0)
    nivel_risco: NivelRisco
    # Clima vem da estação (IP residencial, sem rate-limit compartilhado do
    # Render). Opcional: se a estação estiver offline pro Open-Meteo, a
    # medição salva mesmo assim.
    temperatura_c: float | None = None
    clima: str | None = None


class LeituraOut(BaseModel):
    id: int
    regiao: str
    altura_cm: float
    nivel_risco: NivelRisco
    temperatura_c: float | None
    clima: str | None
    criado_em: datetime


# --- Endpoints ---------------------------------------------------------------
@app.get("/")
def raiz():
    return {"status": "ok", "mensagem": "API no ar"}


# O segundo decorador mantém /medicoes vivo para as estações que ainda não
# foram atualizadas. `include_in_schema=False` esconde da documentação para
# ninguém novo passar a depender dele. Remover quando o campo estiver atualizado.
@app.post(
    "/leituras",
    response_model=LeituraOut,
    dependencies=[Depends(requer_escrita)],
)
@app.post(
    "/medicoes",
    response_model=LeituraOut,
    dependencies=[Depends(requer_escrita)],
    include_in_schema=False,
)
def criar_leitura(leitura: LeituraIn, request: Request):
    with request.app.state.pool.connection() as conn:
        row = conn.execute(
            """
            INSERT INTO leituras
                (regiao, altura_cm, nivel_risco, temperatura_c, clima)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                leitura.regiao,
                leitura.altura_cm,
                leitura.nivel_risco.value,
                leitura.temperatura_c,
                leitura.clima,
            ),
        ).fetchone()
    return row


@app.get(
    "/leituras",
    response_model=list[LeituraOut],
    dependencies=[Depends(requer_leitura)],
)
@app.get(
    "/medicoes",
    response_model=list[LeituraOut],
    dependencies=[Depends(requer_leitura)],
    include_in_schema=False,
)
def listar_leituras(
    request: Request,
    regiao: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
):
    sql = "SELECT * FROM leituras"
    params: list = []
    if regiao:
        sql += " WHERE regiao = %s"
        params.append(regiao)
    sql += " ORDER BY id DESC LIMIT %s"
    params.append(limit)
    with request.app.state.pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


@app.get(
    "/leituras/{leitura_id}",
    response_model=LeituraOut,
    dependencies=[Depends(requer_leitura)],
)
@app.get(
    "/medicoes/{leitura_id}",
    response_model=LeituraOut,
    dependencies=[Depends(requer_leitura)],
    include_in_schema=False,
)
def buscar_leitura(leitura_id: int, request: Request):
    with request.app.state.pool.connection() as conn:
        row = conn.execute(
            "SELECT * FROM leituras WHERE id = %s", (leitura_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Leitura não encontrada")
    return row
```

- [ ] **Step 5: Rodar os testes e ver passar**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS, incluindo os quatro testes de alias.

- [ ] **Step 6: Commit**

```bash
git add api/main.py tests/test_api.py
git commit -m "feat(api): renomeia /medicoes para /leituras, mantendo alias oculto

Segue o diagrama do consumidor externo. /medicoes continua registrado com
include_in_schema=False porque as estacoes em campo nao se atualizam
sozinhas -- sem isso o deploy derruba a captura toda."
```

---

## Task 3: Estação passa a postar em `/leituras`

**Files:**
- Modify: `medir_grama.py:451`
- Test: `tests/test_medir_grama.py`

- [ ] **Step 1: Ver se algum teste prende a URL antiga**

Run: `grep -n "medicoes" tests/test_medir_grama.py medir_grama.py`
Expected: a ocorrência em `medir_grama.py` (a URL do POST). Se `tests/test_medir_grama.py` também citar `/medicoes`, atualize junto no Step 2.

- [ ] **Step 2: Trocar a URL**

Em `medir_grama.py:451`:

```python
                f"{API_URL}/leituras",
```

Se o `grep` do Step 1 achou `/medicoes` em `tests/test_medir_grama.py`, troque por `/leituras` lá também.

- [ ] **Step 3: Rodar a suíte**

Run: `python -m pytest -v`
Expected: PASS. O alias garante que uma estação não atualizada continua funcionando; esta mudança só serve para as que forem atualizadas.

- [ ] **Step 4: Commit**

```bash
git add medir_grama.py tests/
git commit -m "feat(estacao): posta em /leituras

O alias /medicoes segue no ar para as estacoes ainda nao atualizadas."
```

---

## Task 4: Tabela `previsoes`

**Files:**
- Modify: `api/db.py`
- Test: `tests/test_db.py`, `tests/conftest.py`

- [ ] **Step 1: Escrever os testes que falham**

Acrescente a `tests/test_db.py`:

```python
def test_criar_schema_cria_tabela_previsoes(pool):
    db.criar_schema(pool)
    with pool.connection() as conn:
        row = conn.execute("SELECT to_regclass('public.previsoes') AS t").fetchone()
    assert row["t"] == "previsoes"


def test_previsoes_guarda_bytes_intactos(pool):
    """BYTEA tem que devolver byte a byte o que entrou — xlsx é binário."""
    db.criar_schema(pool)
    conteudo = b"PK\x03\x04\x00\xff\xfe qualquer binario"
    with pool.connection() as conn:
        conn.execute("TRUNCATE previsoes RESTART IDENTITY")
        conn.execute(
            "INSERT INTO previsoes (nome_arquivo, conteudo) VALUES (%s, %s)",
            ("p.xlsx", conteudo),
        )
        row = conn.execute("SELECT conteudo FROM previsoes").fetchone()
    assert bytes(row["conteudo"]) == conteudo


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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL — `assert None == 'previsoes'` e `UndefinedTable: relation "previsoes" does not exist`.

- [ ] **Step 3: Acrescentar a tabela ao `SCHEMA_SQL` em `api/db.py`**

No fim da string `SCHEMA_SQL`, depois do `CREATE INDEX` de `leituras`:

```sql
CREATE TABLE IF NOT EXISTS previsoes (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome_arquivo  TEXT NOT NULL,
    conteudo      BYTEA NOT NULL,
    tamanho_bytes BIGINT NOT NULL,
    criado_em     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_previsoes_criado_em
    ON previsoes (criado_em DESC);
```

- [ ] **Step 4: Limpar as duas tabelas entre testes**

`tests/conftest.py` linha 50:

```python
        conn.execute("TRUNCATE leituras, previsoes RESTART IDENTITY")
```

- [ ] **Step 5: Rodar e ver passar**

Run: `python -m pytest -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/db.py tests/
git commit -m "feat(db): tabela previsoes com o xlsx em bytea

Em bytea e nao em disco: o filesystem do Render free e efemero e perde o
arquivo a cada deploy ou hibernacao."
```

---

## Task 5: `POST /previsoes`

**Files:**
- Modify: `api/main.py`, `requirements-api.txt`
- Test: `tests/test_api.py`

- [ ] **Step 1: Instalar a dependência de upload**

O FastAPI não lê `multipart/form-data` sem ela — sem instalar, o app levanta na hora de registrar a rota.

```bash
printf 'python-multipart\n' >> requirements-api.txt
pip install python-multipart
```

- [ ] **Step 2: Escrever os testes que falham**

Acrescente ao fim de `tests/test_api.py`:

```python
# --- POST /previsoes ---------------------------------------------------------
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Um .xlsx é um zip: começa com "PK\x03\x04". A API não abre a planilha, só
# guarda os bytes, então um zip de mentira serve e mantém o teste rápido.
CONTEUDO = b"PK\x03\x04 planilha de mentira"


def _upload(nome="previsao.xlsx", conteudo=CONTEUDO):
    return {"arquivo": (nome, conteudo, XLSX)}


def test_post_previsao_grava_e_devolve_metadado(client, headers_escrita):
    r = client.post("/previsoes", files=_upload(), headers=headers_escrita)
    assert r.status_code == 201
    corpo = r.json()
    assert corpo["id"] == 1
    assert corpo["nome_arquivo"] == "previsao.xlsx"
    assert corpo["tamanho_bytes"] == len(CONTEUDO)
    assert "conteudo" not in corpo, "não devolva o binário na resposta do POST"


def test_post_previsao_rejeita_extensao_errada(client, headers_escrita):
    r = client.post(
        "/previsoes", files=_upload(nome="previsao.csv"), headers=headers_escrita
    )
    assert r.status_code == 400


def test_post_previsao_rejeita_arquivo_vazio(client, headers_escrita):
    r = client.post(
        "/previsoes", files=_upload(conteudo=b""), headers=headers_escrita
    )
    assert r.status_code == 400


def test_post_previsao_rejeita_arquivo_grande_demais(client, headers_escrita):
    """Teto de 10 MB: o Neon free tem 0,5 GB e é o banco inteiro do projeto."""
    r = client.post(
        "/previsoes",
        files=_upload(conteudo=b"x" * (10 * 1024 * 1024 + 1)),
        headers=headers_escrita,
    )
    assert r.status_code == 413


def test_post_previsao_descarta_caminho_no_nome(client, headers_escrita):
    """Nome vem do cliente e vai parar num header HTTP — guarda só o basename."""
    r = client.post(
        "/previsoes",
        files=_upload(nome="../../etc/previsao.xlsx"),
        headers=headers_escrita,
    )
    assert r.status_code == 201
    assert r.json()["nome_arquivo"] == "previsao.xlsx"


def test_post_previsao_com_chave_de_leitura_e_negado(client, headers_leitura):
    r = client.post("/previsoes", files=_upload(), headers=headers_leitura)
    assert r.status_code == 401


def test_post_previsao_sem_chave_e_negado(client):
    r = client.post("/previsoes", files=_upload())
    assert r.status_code == 401
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `python -m pytest tests/test_api.py -k previsao -v`
Expected: FAIL com 404 — a rota não existe.

- [ ] **Step 4: Implementar a rota**

Em `api/main.py`, troque a linha de import do FastAPI por:

```python
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
```

Acrescente ao fim do arquivo:

```python
# --- Previsões ---------------------------------------------------------------
# Teto de 10 MB. O Neon free tem 0,5 GB no total e é o banco inteiro do projeto;
# uma planilha de previsão tem alguns KB, então 10 MB já é folga larga.
TAMANHO_MAX_PREVISAO = 10 * 1024 * 1024
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class PrevisaoOut(BaseModel):
    id: int
    nome_arquivo: str
    tamanho_bytes: int
    criado_em: datetime


@app.post(
    "/previsoes",
    response_model=PrevisaoOut,
    status_code=201,
    dependencies=[Depends(requer_escrita)],
)
def criar_previsao(request: Request, arquivo: UploadFile = File(...)):
    # `def` e não `async def`: o psycopg aqui é síncrono, e num handler async
    # ele travaria o event loop. Sendo `def`, o FastAPI joga num threadpool.
    nome = os.path.basename(arquivo.filename or "")
    if not nome.lower().endswith(".xlsx"):
        raise HTTPException(400, "O arquivo precisa ser .xlsx")
    # O nome vem do cliente e vai parar num header Content-Disposition no GET.
    # CR/LF ali dentro é injeção de header; aspas e caracteres de controle
    # corrompem o valor; um nome absurdamente longo também quebra. Recusa
    # antes de guardar — o banco não tem como desfazer isso depois.
    if len(nome) > 200:
        raise HTTPException(400, "Nome de arquivo longo demais")
    if '"' in nome or any(ord(c) < 32 or ord(c) == 127 for c in nome):
        raise HTTPException(400, "Nome de arquivo inválido")

    conteudo = arquivo.file.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio")
    if len(conteudo) > TAMANHO_MAX_PREVISAO:
        raise HTTPException(413, "Arquivo acima de 10 MB")

    with request.app.state.pool.connection() as conn:
        row = conn.execute(
            """
            INSERT INTO previsoes (nome_arquivo, conteudo)
            VALUES (%s, %s)
            RETURNING id, nome_arquivo, tamanho_bytes, criado_em
            """,
            (nome, conteudo),
        ).fetchone()
    return row
```

`os` já está importado no topo do arquivo (linha 4).

- [ ] **Step 5: Rodar e ver passar**

Run: `python -m pytest tests/test_api.py -k previsao -v`
Expected: PASS, 7 testes.

- [ ] **Step 6: Rodar a suíte inteira e commitar**

Run: `python -m pytest -v`
Expected: PASS.

```bash
git add api/main.py requirements-api.txt tests/test_api.py
git commit -m "feat(api): POST /previsoes recebe a planilha xlsx

Chave de escrita, valida extensao, corpo vazio e teto de 10 MB. Guarda o
basename: o nome vai para um header Content-Disposition no GET."
```

---

## Task 6: `GET /previsoes`

**Files:**
- Modify: `api/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/test_api.py`:

```python
# --- GET /previsoes ----------------------------------------------------------
def test_get_previsao_devolve_a_mais_recente(client, headers_escrita, headers_leitura):
    client.post(
        "/previsoes",
        files=_upload(nome="antiga.xlsx", conteudo=b"PK\x03\x04 velha"),
        headers=headers_escrita,
    )
    client.post(
        "/previsoes",
        files=_upload(nome="nova.xlsx", conteudo=b"PK\x03\x04 nova"),
        headers=headers_escrita,
    )
    r = client.get("/previsoes", headers=headers_leitura)
    assert r.status_code == 200
    assert r.content == b"PK\x03\x04 nova"


def test_get_previsao_vem_como_download_de_xlsx(
    client, headers_escrita, headers_leitura
):
    """O app salva o arquivo direto: precisa do content-type e do nome certos."""
    client.post("/previsoes", files=_upload(), headers=headers_escrita)
    r = client.get("/previsoes", headers=headers_leitura)
    assert r.headers["content-type"] == XLSX
    assert r.headers["content-disposition"] == 'attachment; filename="previsao.xlsx"'


def test_get_previsao_por_id(client, headers_escrita, headers_leitura):
    antiga = client.post(
        "/previsoes",
        files=_upload(nome="antiga.xlsx", conteudo=b"PK\x03\x04 velha"),
        headers=headers_escrita,
    ).json()
    client.post(
        "/previsoes",
        files=_upload(nome="nova.xlsx", conteudo=b"PK\x03\x04 nova"),
        headers=headers_escrita,
    )
    r = client.get("/previsoes", params={"id": antiga["id"]}, headers=headers_leitura)
    assert r.status_code == 200
    assert r.content == b"PK\x03\x04 velha"


def test_get_previsao_com_id_inexistente_retorna_404(client, headers_leitura):
    r = client.get("/previsoes", params={"id": 9999}, headers=headers_leitura)
    assert r.status_code == 404


def test_get_previsao_sem_nenhuma_cadastrada_retorna_404(client, headers_leitura):
    r = client.get("/previsoes", headers=headers_leitura)
    assert r.status_code == 404


def test_get_previsao_sem_chave_e_negado(client):
    r = client.get("/previsoes")
    assert r.status_code == 401
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_api.py -k "get_previsao" -v`
Expected: FAIL com 405 (Method Not Allowed) — o caminho `/previsoes` só aceita POST hoje.

- [ ] **Step 3: Implementar a rota**

Em `api/main.py`, acrescente `Response` ao import do FastAPI:

```python
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
```

E acrescente ao fim do arquivo:

```python
@app.get("/previsoes", dependencies=[Depends(requer_leitura)])
def baixar_previsao(request: Request, id: int | None = None):
    """Devolve a previsão mais recente, ou a de `id` se pedido.

    Sem `response_model`: a resposta são os bytes do arquivo, não JSON.
    """
    sql = "SELECT nome_arquivo, conteudo FROM previsoes"
    params: list = []
    if id is not None:
        sql += " WHERE id = %s"
        params.append(id)
    # O desempate por id importa: dois uploads na mesma transação compartilham
    # o `now()`, e sem ele a "mais recente" viraria sorteio.
    sql += " ORDER BY criado_em DESC, id DESC LIMIT 1"
    with request.app.state.pool.connection() as conn:
        row = conn.execute(sql, params).fetchone()
    if row is None:
        raise HTTPException(404, "Nenhuma previsão encontrada")

    nome = row["nome_arquivo"]
    return Response(
        content=bytes(row["conteudo"]),
        media_type=MIME_XLSX,
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_api.py -k "get_previsao" -v`
Expected: PASS, 6 testes.

- [ ] **Step 5: Rodar a suíte inteira e commitar**

Run: `python -m pytest -v`
Expected: PASS.

```bash
git add api/main.py tests/test_api.py
git commit -m "feat(api): GET /previsoes baixa a planilha mais recente

Devolve os bytes com content-type de xlsx e Content-Disposition, para o
app salvar direto. ?id=N pega uma especifica."
```

---

## Task 7: Backup passa a levar as previsões

Sem isto, as planilhas ficam só no Neon — e o `backup.py` existe justamente para o projeto nunca depender de um fornecedor.

**Files:**
- Modify: `scripts/backup.py`

- [ ] **Step 1: Escrever a função de export**

Em `scripts/backup.py`, acrescente depois de `exportar()` (que termina com `return csv_path, sql_path, len(linhas)`):

```python
def exportar_previsoes(url: str, destino: Path) -> int:
    """Grava cada previsão como .xlsx dentro de <destino>/. Retorna quantas.

    Arquivo de verdade em vez de bytea codificado dentro de um INSERT: abre
    no Excel na hora, que é o ponto do backup. NÃO acrescente `previsoes` ao
    export .sql: `_literal` cai no `str(valor)` pra tipos desconhecidos, o que
    num `bytes` emite o repr do Python (`'b'PK''`) e gera um .sql que
    restaura dado corrompido sem erro nenhum.
    """
    destino.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(url) as conn:
        linhas = conn.execute(
            "SELECT id, nome_arquivo, conteudo FROM previsoes ORDER BY id"
        ).fetchall()

    for linha in linhas:
        id_, nome, conteudo = linha
        # Prefixo com o id: dois uploads podem ter o mesmo nome de arquivo.
        (destino / f"{id_:04d}-{nome}").write_bytes(bytes(conteudo))
    return len(linhas)
```

- [ ] **Step 2: Chamar no `main()`**

Em `scripts/backup.py`, dentro de `main()`, logo depois da linha que chama `exportar(...)`:

```python
    n_previsoes = exportar_previsoes(url, RAIZ / "backups" / f"previsoes-{carimbo}")
```

E depois das linhas que imprimem o CSV e o SQL:

```python
    print(f"{n_previsoes} previsões exportadas")
    if n_previsoes:
        print(f"  XLSX: backups/previsoes-{carimbo}/")
```

- [ ] **Step 3: Rodar contra a base de teste**

O script lê `DATABASE_URL`. Para não tocar em produção, aponte para a de teste só neste comando:

```bash
DATABASE_URL="$DATABASE_URL_TEST" python scripts/backup.py
```
Expected: imprime "N leituras exportadas" e "N previsões exportadas" sem levantar. Com a base de teste vazia os dois números podem ser 0 — o que importa é não dar erro.

- [ ] **Step 4: Não versionar os backups**

Run: `grep -n backups .gitignore`
Expected: uma linha ignorando `backups/`. Se não houver, acrescente `backups/` ao `.gitignore` e inclua o arquivo no commit do Step 5.

- [ ] **Step 5: Rodar a suíte e commitar**

Run: `python -m pytest -v`
Expected: PASS.

```bash
git add scripts/backup.py .gitignore
git commit -m "feat(backup): exporta as previsoes como .xlsx

backup.py exporta tabela por nome, entao previsoes nao vinha junto. Grava
arquivo de verdade em vez de bytea num INSERT -- abre no Excel na hora."
```

---

## Task 8: Fechamento

- [ ] **Step 1: Suíte inteira**

Run: `python -m pytest -v`
Expected: PASS, tudo.

- [ ] **Step 2: Subir a API local e conferir a documentação**

```bash
uvicorn api.main:app --reload
```

Abra `http://localhost:8000/docs`. Confira: aparecem `/leituras`, `/leituras/{leitura_id}` e `/previsoes` (POST e GET). **Não** aparece nenhum `/medicoes` — eles existem, mas fora do schema. Encerre com Ctrl+C.

- [ ] **Step 3: Tirar backup de produção antes do deploy**

O deploy é automático no push para `main`, e o `criar_schema` roda no boot contra o Neon de produção — é ali que o rename acontece de verdade. Antes de empurrar:

```bash
python scripts/backup.py
```
Expected: o CSV e o SQL com o histórico real. Guarde-os: é a rede de segurança caso o rename dê errado.

- [ ] **Step 4: Push e verificação em produção**

```bash
git push origin main
```

Depois do deploy, confirme que o histórico atravessou o rename:

```bash
curl -s -H "X-API-Key: $API_KEY_READ" https://api-grama-webcam.onrender.com/leituras | head -c 400
```
Expected: JSON com as leituras de sempre. Se vier `[]` e o backup do Step 3 mostrava linhas, o rename não aconteceu — restaure pelo `.sql` do Step 3 e investigue a ordem dentro de `criar_schema`.

- [ ] **Step 5: Avisar o consumidor externo**

Texto pronto para copiar e mandar:

> A API agora tem os quatro endpoints do diagrama: `POST /leituras`, `GET /leituras`, `POST /previsoes` e `GET /previsoes`. O `/medicoes` continua funcionando por compatibilidade, mas saiu da documentação e vai ser removido — migre para `/leituras`. O `POST /previsoes` recebe o `.xlsx` como `multipart/form-data` no campo `arquivo`, com a chave de escrita, e devolve `{id, nome_arquivo, tamanho_bytes, criado_em}`. O `GET /previsoes` devolve a planilha mais recente já como download, ou uma específica com `?id=N`, com a chave de leitura. Limite de 10 MB por arquivo.
