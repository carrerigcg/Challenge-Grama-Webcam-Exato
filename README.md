<h1 align="center">Grama Webcam</h1>

<p align="center">
  <strong>Medição automática da altura da grama em margens de rodovia via visão computacional.</strong><br>
  Estações com webcam capturam frames, classificam risco de incêndio por altura da vegetação
  e persistem numa API pública consumida por planilha externa de previsão.
</p>

<p align="center">
  <img alt="python" src="https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white">
  <img alt="fastapi" src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white">
  <img alt="postgres" src="https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&logoColor=white">
  <img alt="neon" src="https://img.shields.io/badge/Neon-serverless-00E599?logo=neon&logoColor=white">
  <img alt="render" src="https://img.shields.io/badge/Render-deploy-46E3B7?logo=render&logoColor=white">
  <img alt="opencv" src="https://img.shields.io/badge/OpenCV-4-5C3EE8?logo=opencv&logoColor=white">
  <img alt="tests" src="https://img.shields.io/badge/tests-190%2B-2EA44F?logo=pytest&logoColor=white">
  <img alt="status" src="https://img.shields.io/badge/status-em%20produ%C3%A7%C3%A3o-brightgreen">
</p>

<p align="center">
  <a href="#-visão-geral">Visão geral</a> ·
  <a href="#-arquitetura">Arquitetura</a> ·
  <a href="#-quick-start">Quick start</a> ·
  <a href="#-referência-da-api">API</a> ·
  <a href="#-testes">Testes</a> ·
  <a href="#-deploy">Deploy</a> ·
  <a href="#-roadmap">Roadmap</a>
</p>

---

## Sumário

- [Visão geral](#-visão-geral)
- [Como funciona a medição](#-como-funciona-a-medição)
- [Arquitetura](#-arquitetura)
- [Modelo de dados](#-modelo-de-dados)
- [Quick start](#-quick-start)
- [Referência da API](#-referência-da-api)
- [Estrutura do repositório](#-estrutura-do-repositório)
- [Testes](#-testes)
- [Backup e restore](#-backup-e-restore)
- [Deploy](#-deploy)
- [Decisões de design](#-decisões-de-design)
- [Roadmap](#-roadmap)
- [Licença](#-licença)

---

## 🌱 Visão geral

O **Grama Webcam** transforma qualquer câmera fixa apontada para o chão em um sensor de altura de grama.
Substitui a inspeção humana em quilômetros de rodovia por uma coleta contínua, barata, auditável e independente de vendor.

**Contexto de uso.** Faixas de vegetação em canteiros e taludes de rodovias precisam ser roçadas antes que virem risco de incêndio. Sem instrumentação, a decisão sobre *onde* e *quando* roçar depende de vistoria manual. Este sistema entrega a mesma informação como série temporal consultável, com histórico e clima.

**Valor entregue**

| | |
|---|---|
| 🎥 **Zero hardware caro** | Webcam USB comum ou câmera CSI da Raspberry Pi |
| 📐 **Calibração em ~60s** | Dois cliques no segmento de referência, um clique no chão |
| 🧠 **Sem modelo treinado** | Segmentação HSV — determinística, auditável, sem GPU |
| 🌐 **API pública** | Consumidores externos leem sem escrever código do sistema |
| 💰 **Custo zero em produção** | Render free + Neon free + Open-Meteo free |
| 📦 **Sem lock-in** | Backup local em `.csv`, `.sql` e `.xlsx` (`scripts/backup.py`) |

---

## 🔬 Como funciona a medição

Pipeline determinístico rodando na estação, do frame ao POST:

```
┌────────────┐   ┌──────────────┐   ┌──────────────┐   ┌────────────┐   ┌─────────┐
│  webcam    │──▶│ 5 frames     │──▶│ máscara HSV  │──▶│ mediana    │──▶│ altura  │
│  (OpenCV)  │   │ empilhados   │   │ verde (35..85)│   │ por coluna │   │  cm     │
└────────────┘   └──────────────┘   └──────────────┘   └────────────┘   └────┬────┘
                                                                              │
                        ┌────────────────┬─────────────────────┬──────────────┘
                        ▼                ▼                     ▼
                  ┌──────────┐    ┌─────────────┐       ┌──────────────┐
                  │ AUSENTE  │    │ Open-Meteo  │       │ POST /leitura│
                  │ BAIXA    │    │ (do IP da   │──────▶│  X-API-Key   │
                  │ MEDIA    │    │  estação)   │       │              │
                  │ ALTA     │    └─────────────┘       └──────────────┘
                  └──────────┘
```

**Por que HSV e não deep learning.** O problema tem baixa variância visual (grama verde contra fundo neutro em câmera fixa) e alto custo de manutenção pra um modelo (dataset, GPU, drift). Uma máscara HSV com faixas conservadoras (35–85 em H, 40+ em S/V) resolve o problema com **zero dependência de peso**, roda em qualquer CPU e é debugável com `debug/ultima_medicao.png` — cada medição salva a imagem anotada com colunas, chão, régua em cm e categoria.

**Mediana em vez de média.** Amostra em 3 colunas (25%, 50%, 75% do frame), calcula altura em cada, agrega por mediana. Um ramo isolado ou sombra numa coluna não move a leitura toda.

**Faixas de classificação** (`medir_grama.py`):
- **AUSENTE** — nenhum pixel verde
- **BAIXA** — altura ≤ 3 cm
- **MEDIA** — 3 cm < altura ≤ 7 cm
- **ALTA** — altura > 7 cm

---

## 🏗️ Arquitetura

```
       ┌────────────────────────┐                                       ┌─────────────────────┐
       │  ESTAÇÃO (Windows / Pi)│                                       │  CONSUMIDOR EXTERNO │
       │                        │                                       │  (planilha / BI)    │
       │  calibrar.py (1x)      │                                       │                     │
       │  medir_grama.py (cron) │                                       │  GET /leituras      │
       │  ├─ OpenCV             │                                       │  GET /previsoes     │
       │  ├─ Open-Meteo         │                                       │  POST /previsoes    │
       │  └─ POST /leituras     │                                       │                     │
       └───────────┬────────────┘                                       └──────────┬──────────┘
                   │ API_KEY_WRITE                                                 │ API_KEY_READ
                   │ (HTTPS)                                                       │ ou WRITE
                   ▼                                                               ▼
       ┌──────────────────────────────────────────────────────────────────────────────────┐
       │                       API  ·  FastAPI + Uvicorn                                  │
       │                       api-grama-webcam.onrender.com                              │
       │                                                                                  │
       │  ├─ APIKeyHeader (X-API-Key)  · dois níveis: WRITE  ·  READ                      │
       │  ├─ Pool psycopg (1..5 conns) · lifespan-managed                                 │
       │  ├─ POST /leituras  · POST /previsoes (≤10MB, .xlsx)                             │
       │  ├─ GET  /leituras  · GET  /leituras/{id}  · GET /previsoes                      │
       │  └─ Alias /medicoes (compat) — some quando duas partes externas migrarem         │
       └───────────────────────────────────┬──────────────────────────────────────────────┘
                                           │ psycopg (async pool)
                                           ▼
                    ┌─────────────────────────────────────────┐
                    │        PostgreSQL 17  ·  Neon           │
                    │                                         │
                    │   leituras (série temporal)             │
                    │   previsoes (BYTEA + TOAST, ≤10MB)      │
                    │   índices: (regiao, criado_em DESC),    │
                    │            (criado_em DESC, id DESC)    │
                    └─────────────────────────────────────────┘
```

**Fluxo de escrita** (estação → banco): webcam → OpenCV → classificação → clima → `POST /leituras` com `X-API-Key`. Falha de rede vira aviso, nunca crash — a estação tenta 2 vezes com 90s de timeout (Render free hiberna após ~15min).

**Fluxo de leitura** (consumidor → banco): consumidor externo (planilha, BI, etc.) faz `GET /leituras` com `API_KEY_READ`. Também sobe suas próprias previsões via `POST /previsoes` (planilha `.xlsx`) e as recupera por `GET /previsoes`.

**Fronteira de responsabilidade.** A API **só persiste dados brutos**. Geração de previsão, análise e planilha ficam do lado do consumidor — daí o `/previsoes` ser um simples cofre de bytes, não um endpoint de cálculo.

---

## 🗃️ Modelo de dados

### `leituras`

Cada linha é uma medição de uma estação. Sem UPDATE — série temporal apenas.

| coluna | tipo | notas |
|---|---|---|
| `id` | `BIGINT IDENTITY PK` | monotônico |
| `regiao` | `TEXT NOT NULL` | identifica a estação; vem de `calibration.json` |
| `altura_cm` | `DOUBLE PRECISION NOT NULL` | mediana das 3 colunas |
| `nivel_risco` | `TEXT NOT NULL` | `AUSENTE` / `BAIXA` / `MEDIA` / `ALTA` |
| `temperatura_c` | `DOUBLE PRECISION NULL` | Open-Meteo; `NULL` se estação estava offline |
| `clima` | `TEXT NULL` | descrição WMO traduzida |
| `criado_em` | `TIMESTAMPTZ DEFAULT now()` | UTC |

Índice: `(regiao, criado_em DESC)` — casa com o padrão dominante de consulta ("últimas N leituras da região X").

### `previsoes`

Cofre de planilhas geradas pelo consumidor externo. Blob mora dentro do Postgres via **TOAST** — evita depender de object storage terceiro e do filesystem efêmero do Render free.

| coluna | tipo | notas |
|---|---|---|
| `id` | `BIGINT IDENTITY PK` | |
| `nome_arquivo` | `TEXT NOT NULL` | validado em Latin-1 para o `Content-Disposition` |
| `conteudo` | `BYTEA NOT NULL` | comprimido e detoastado sob demanda |
| `tamanho_bytes` | `BIGINT GENERATED ... STORED` | `length(bytea)` sem detoast |
| `criado_em` | `TIMESTAMPTZ DEFAULT now()` | |

Constraints:
- `previsoes_conteudo_nao_vazio` — `length(conteudo) > 0`
- `previsoes_conteudo_ate_10mb` — `length(conteudo) <= 10 * 1024 * 1024` (mesmo teto do handler HTTP; um mais frouxo que o outro torna o 413 impossível de testar)

---

## 🚀 Quick start

### 1. Clonar e instalar

```bash
git clone https://github.com/<voce>/challenge-grama-webcam.git
cd challenge-grama-webcam

python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

pip install -r requirements-dev.txt  # api + testes
# para a estação de captura, adicione:
pip install -r requirements-station.txt
```

### 2. Configurar `.env`

```bash
cp .env.example .env
```

Gere as duas API keys:

```bash
python -c "import secrets; print('WRITE=', secrets.token_urlsafe(32))"
python -c "import secrets; print('READ=',  secrets.token_urlsafe(32))"
```

Preencha `DATABASE_URL` (Neon connection string ou Postgres local via Docker) e `DATABASE_URL_TEST` (**obrigatoriamente** uma branch/database diferente — os testes fazem `TRUNCATE`).

### 3. Postgres local (opcional, para dev offline)

```bash
docker compose up -d
docker compose exec db createdb -U grama grama_test
# no .env:
# DATABASE_URL=postgresql://grama:grama@localhost:5432/grama
# DATABASE_URL_TEST=postgresql://grama:grama@localhost:5432/grama_test
```

### 4. Subir a API

```bash
uvicorn api.main:app --reload
# http://localhost:8000
# http://localhost:8000/docs  (Swagger UI)
```

### 5. Rodar a estação de captura

```bash
python calibrar.py                    # 1x por câmera fixa
python medir_grama.py                 # captura + envio (com preview)
python medir_grama.py --auto          # sem preview (cron / headless)
```

---

## 📡 Referência da API

Base: `https://api-grama-webcam.onrender.com`
Docs interativas: `/docs` (Swagger) e `/redoc`
Autenticação: header **`X-API-Key`** — duas chaves, escrita e leitura.

| Chave | Pode ler? | Pode escrever? | Uso |
|---|---|---|---|
| `API_KEY_WRITE` | ✅ | ✅ | Estações de captura, admin, debug |
| `API_KEY_READ` | ✅ | ❌ | Consumidor externo, dashboards |

> Requisições sem chave, ou com chave inválida, respondem **401**.

---

### `GET /`

Health check, sem autenticação.

<details>
<summary>Exemplo</summary>

```bash
curl https://api-grama-webcam.onrender.com/
# {"status":"ok","mensagem":"API no ar"}
```
</details>

---

### `POST /leituras`

Registra uma leitura de estação. **Requer `API_KEY_WRITE`.**

**Body**

| campo | tipo | obrigatório | notas |
|---|---|---|---|
| `regiao` | `string` | ✅ | não pode ser vazio |
| `altura_cm` | `float ≥ 0` | ✅ | |
| `nivel_risco` | `enum` | ✅ | `AUSENTE` \| `BAIXA` \| `MEDIA` \| `ALTA` |
| `temperatura_c` | `float` | ❌ | `null` se estação sem internet no Open-Meteo |
| `clima` | `string` | ❌ | |

<details>
<summary>Exemplo</summary>

```bash
curl -X POST https://api-grama-webcam.onrender.com/leituras \
  -H "X-API-Key: $API_KEY_WRITE" \
  -H "Content-Type: application/json" \
  -d '{"regiao":"Rod. Anchieta","altura_cm":12.4,"nivel_risco":"ALTA","temperatura_c":25.7,"clima":"Nublado"}'
```

Resposta `200`:
```json
{
  "id": 42,
  "regiao": "Rod. Anchieta",
  "altura_cm": 12.4,
  "nivel_risco": "ALTA",
  "temperatura_c": 25.7,
  "clima": "Nublado",
  "criado_em": "2026-09-03T14:00:00Z"
}
```
</details>

---

### `GET /leituras`

Lista leituras, mais recentes primeiro. **Requer `API_KEY_READ` ou `WRITE`.**

**Query**

| param | default | limite | notas |
|---|---|---|---|
| `regiao` | — | — | filtro exato |
| `limit` | `100` | 1..1000 | |

<details>
<summary>Exemplo</summary>

```bash
curl -H "X-API-Key: $API_KEY_READ" \
  "https://api-grama-webcam.onrender.com/leituras?regiao=Rod.%20Anchieta&limit=10"
```
</details>

---

### `GET /leituras/{id}`

Busca por id. `404` se não existir.

---

### `POST /previsoes`

Upload de planilha `.xlsx` gerada pelo consumidor externo. **Requer `API_KEY_WRITE`.**

- Formato: `multipart/form-data` com campo `arquivo`
- Tipo: **`.xlsx` obrigatório**
- Tamanho: **≤ 10 MB** (checado por header `Content-Length` **antes** do parse, para não carregar o corpo inteiro em memória)
- Nome do arquivo: sanitizado (path traversal, CR/LF, Latin-1 apenas)

Códigos:

| status | quando |
|---|---|
| `201` | criado |
| `400` | arquivo vazio, extensão errada, nome inválido |
| `401` | chave errada ou ausente |
| `413` | > 10 MB (barrado no middleware, sem ler o corpo) |

<details>
<summary>Exemplo</summary>

```bash
curl -X POST https://api-grama-webcam.onrender.com/previsoes \
  -H "X-API-Key: $API_KEY_WRITE" \
  -F "arquivo=@previsao-semana-36.xlsx"
```

Resposta `201`:
```json
{
  "id": 7,
  "nome_arquivo": "previsao-semana-36.xlsx",
  "tamanho_bytes": 18432,
  "criado_em": "2026-09-03T14:05:00Z"
}
```
</details>

---

### `GET /previsoes`

Baixa a planilha. Por padrão devolve a **mais recente**; passe `?id=N` para uma específica.

- `Content-Type`: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- `Content-Disposition`: `attachment; filename="..."`
- `404` se o cofre estiver vazio

<details>
<summary>Exemplo</summary>

```bash
curl -H "X-API-Key: $API_KEY_READ" \
  https://api-grama-webcam.onrender.com/previsoes \
  -o previsao-mais-recente.xlsx
```
</details>

---

### Compatibilidade: `/medicoes`

Aliases legados de `/leituras` continuam respondendo (ocultos do Swagger). Serão removidos quando as estações em campo e o consumidor externo migrarem — o log da API imprime aviso a cada hit no path antigo.

---

## 📁 Estrutura do repositório

```
.
├── api/                       # backend FastAPI
│   ├── main.py               # rotas, autenticação, middleware de tamanho
│   └── db.py                 # pool psycopg, DDL, migração rename `medicoes`→`leituras`
│
├── calibrar.py               # gera calibration.json (interativo, 1x por câmera)
├── medir_grama.py            # captura + classificação + envio (cron)
├── camera.py                 # detecção de backend/index por plataforma (MSMF/V4L2)
├── clima.py                  # cliente Open-Meteo, mapa WMO → PT-BR
│
├── scripts/
│   ├── seed_exemplos.py     # 21 pontos de demo (--confirm-prod obrigatório)
│   └── backup.py            # exporta leituras (CSV + SQL) e previsoes (XLSX)
│
├── tests/                    # ~190 testes, todos com Postgres real na branch test
│   ├── conftest.py          # fixtures: pool session-scoped, truncate por teste
│   ├── test_api.py          # 53
│   ├── test_medir_grama.py  # 88
│   ├── test_db.py           # 15
│   ├── test_calibrar.py     # 15
│   ├── test_camera.py       # 8
│   ├── test_clima.py        # 4
│   └── test_backup.py       # 7
│
├── requirements-api.txt      # FastAPI stack (produção)
├── requirements-station.txt  # OpenCV + numpy (estação)
├── requirements-dev.txt      # tudo acima + pytest + httpx
│
├── render.yaml               # IaC do Render (build/start/env)
├── docker-compose.yml        # Postgres local para dev offline
├── .env.example              # segredos e URLs, todos comentados
└── calibration.json          # gerado por calibrar.py (gitignored)
```

---

## 🧪 Testes

Nada de mock de banco. **Toda suíte de API roda contra Postgres real** — Neon (branch `test`) ou Postgres local via Docker.

```bash
pytest                                     # tudo
pytest tests/test_api.py -v                # só API
pytest -k previsoes                        # só previsões
pytest --lf                                # só o que falhou da última vez
```

**Por que Postgres real:** o comportamento crítico da API mora em constraints (`length(bytea) <= 10MB`), tipos (`BYTEA` vs `TOAST`), colunas geradas (`STORED`) e migrações (rename `medicoes`→`leituras`). Um mock que "aceita tudo" mascara justamente o que quebra em produção. Custo: uma branch dedicada no Neon (0 R$ no free) e ~15s de suíte.

**Isolamento:** cada teste roda com `TRUNCATE ... RESTART IDENTITY` numa fixture — pool session-scoped (uma conexão só na suíte inteira), tabela limpa por caso. **Nunca aponte `DATABASE_URL_TEST` pra branch de produção**: a fixture apaga tudo.

Cobertura por área:

| arquivo | testes | foco |
|---|---:|---|
| `test_api.py` | 53 | endpoints, auth, validações, headers |
| `test_medir_grama.py` | 88 | pipeline de visão, envio, argparse |
| `test_db.py` | 15 | schema, rename, constraints, generated columns |
| `test_calibrar.py` | 15 | matemática pura + I/O do JSON |
| `test_camera.py` | 8 | overrides via env |
| `test_backup.py` | 7 | CSV/SQL/XLSX, sanitização de nomes |
| `test_clima.py` | 4 | mapa WMO, fallback em erro |

---

## 💾 Backup e restore

O sistema não depende de snapshot do provedor. Um script exporta tudo com o mesmo `psycopg` que a API usa:

```bash
python scripts/backup.py
# → backups/medicoes-2026-09-04-1430.csv    (abre no Excel)
# → backups/medicoes-2026-09-04-1430.sql    (restaura em QUALQUER Postgres)
# → backups/previsoes-2026-09-04-1430/*.xlsx  (planilhas cruas)
```

O `.sql` recria a tabela `leituras` e faz `INSERT` linha a linha. **Não** despeja `previsoes` como SQL (blob binário dentro de INSERT vira dado corrompido silencioso) — planilhas viram arquivo mesmo.

Restore num Postgres qualquer:

```bash
psql "$DATABASE_URL_NOVO" < backups/medicoes-2026-09-04-1430.sql
```

---

## ☁️ Deploy

### API — Render

Definido em `render.yaml`. Deploy contínuo em `push origin main`.

```yaml
services:
  - type: web
    runtime: python
    region: oregon              # mesma do Neon → sem hop transcontinental
    plan: free
    buildCommand: pip install -r requirements-api.txt
    startCommand: uvicorn api.main:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /
```

**Segredos** (`DATABASE_URL`, `API_KEY_WRITE`, `API_KEY_READ`) ficam com `sync: false` — o Render pede o valor no dashboard, nada de segredo no Git.

**Cold start.** Render free hiberna após ~15min ociosos e demora ~50s pra acordar. A estação de captura lida com isso: `ENVIO_TENTATIVAS = 2` — a primeira acorda, a segunda entrega.

### Banco — Neon

- Projeto na região **AWS us-west-2** (Oregon) — casa com o Render pra latência mínima
- Duas branches: **`main`** (produção) e **`test`** (a fixture apaga a cada rodada)
- Free tier: 0.5 GB de storage — folgado pra `leituras` como série temporal e `previsoes` na casa dos KB

---

## 🧭 Decisões de design

Decisões que não são óbvias lendo o código — o *porquê* de cada uma:

- **Duas API keys em vez de OAuth/JWT.** O universo de clientes é fechado (poucas estações + um consumidor externo). Two-tier `WRITE`/`READ` cobre todo o modelo de ameaça sem introduzir provider de identidade. `WRITE` também lê pra facilitar debug de campo.
- **Pool psycopg (1..5)** aberto no `lifespan`. Abrir e fechar TCP+TLS+auth a cada request contra o Neon é caro; o free tier limita conexões simultâneas.
- **Middleware de `Content-Length` antes do parse do multipart** (`api/main.py:249`). Um POST de 500 MB com Starlette padrão é lido inteiro pra `SpooledTemporaryFile` (vaza pra disco em 1 MB) antes do handler ver uma linha. Barrar via header é a única forma de rejeitar de graça.
- **BYTEA + TOAST em vez de S3/R2.** Zero conta e zero credencial a mais contra o requisito de custo zero. TOAST comprime e guarda fora da linha automaticamente; `length(bytea)` lê o header do ponteiro sem detoastar.
- **Migração de rename** (`medicoes` → `leituras`) rodando no `criar_schema` idempotente. Chegou em produção sem downtime — o bloco `DO` só executa se a tabela nova ainda não existir.
- **Alias `/medicoes` mantido** até dois clientes fora do repo migrarem (estações em campo + consumidor externo). O aviso logado a cada hit é a sonda: uma semana sem log = pode apagar.
- **Clima buscado na estação, não na API.** O IP compartilhado do Render tomava HTTP 429 no Open-Meteo por vizinho barulhento. Estação tem IP residencial com cota própria (10k/dia). Documentado em `clima.py:1`.
- **`def` síncrono em vez de `async def`.** O psycopg síncrono num handler `async` trava o event loop. `def` faz o FastAPI jogar no threadpool.
- **HSV em vez de deep learning.** Câmera fixa, alvo consistente. Um modelo treinado agrega manutenção (dataset, GPU, drift) sem ganho mensurável.

---

## 🗺️ Roadmap

### Curto prazo

- [ ] **Keep-alive do Render free** — cron leve batendo `/` a cada 10min para evitar cold start em demo
- [ ] **Segunda estação em campo** — validar `regiao` como discriminante real, não valor único
- [ ] **Retenção da tabela `leituras`** — política de arquivamento antes de ocupar 0.5 GB do Neon

### Médio prazo

- [ ] **Ingest resiliente com store-and-forward** — instalação real do rodoanel não tem energia estável, sinal celular nem internet contínua; o design atual assume conectividade
- [ ] **Autenticação por estação** — hoje é uma chave `WRITE` compartilhada; JWT por dispositivo evita rotação global se uma estação for comprometida
- [ ] **Migração real** — substituir o bloco `DO` inline por [Alembic](https://alembic.sqlalchemy.org/) quando houver a próxima mudança de schema

### Longo prazo

- [ ] **Dashboard interno** com Grafana + Postgres datasource — visualização barata sem escrever front
- [ ] **Alerta de anomalia** — altura caindo bruscamente = alguém já roçou; altura subindo rápido demais = câmera desalinhada
- [ ] **Multi-tenant** — cada cliente com seu par de chaves e sua branch no Neon

---

## 📜 Licença

Uso interno da Grama Exato. Todos os direitos reservados.

---

<p align="center">
  <sub>Feito com atenção aos detalhes que só aparecem em produção.</sub>
</p>
