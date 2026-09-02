"""API de leituras de altura de grama."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum

from dotenv import load_dotenv
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
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from api import db

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não configurada. Veja .env.example")

API_KEY_WRITE = os.environ.get("API_KEY_WRITE")
API_KEY_READ = os.environ.get("API_KEY_READ")
if not API_KEY_WRITE or not API_KEY_READ:
    raise RuntimeError(
        "API_KEY_WRITE e API_KEY_READ são obrigatórias. Veja .env.example"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = db.criar_pool(DATABASE_URL)
    pool.open()
    db.criar_schema(pool)
    app.state.pool = pool
    yield
    pool.close()


app = FastAPI(title="API Grama Webcam", lifespan=lifespan)
logger = logging.getLogger(__name__)


# --- Autenticação ------------------------------------------------------------
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def requer_escrita(api_key: str | None = Depends(api_key_header)) -> None:
    if api_key != API_KEY_WRITE:
        raise HTTPException(401, "API key de escrita inválida ou ausente")


def requer_leitura(api_key: str | None = Depends(api_key_header)) -> None:
    # A chave de escrita também lê — conveniente pras estações e pra debug.
    # O contrário não vale: quem só lê nunca escreve.
    if api_key not in (API_KEY_READ, API_KEY_WRITE):
        raise HTTPException(401, "API key inválida ou ausente")


# --- Schemas -----------------------------------------------------------------
class NivelRisco(str, Enum):
    AUSENTE = "AUSENTE"
    BAIXA = "BAIXA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"


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


# Aliases de compatibilidade (POST e os dois GET abaixo): /medicoes continua
# respondendo ao lado de /leituras porque duas partes fora deste repo
# dependem do nome antigo e nenhuma se atualiza sozinha — as estações em
# campo (POST) e o consumidor externo (GET). `include_in_schema=False`
# esconde da documentação pra ninguém novo passar a depender dele.
#
# Some quando (a) as estações em campo postarem em /leituras e (b) o
# consumidor externo migrar os GETs — são duas partes independentes, as
# duas fora deste repo. Não dá pra deduzir daqui: confirme com a equipe
# antes de apagar. O aviso logado por `_avisar_uso_do_alias` é a evidência:
# uma semana limpa de produção sem essa mensagem indica que as duas já
# migraram.
def _avisar_uso_do_alias(request: Request) -> None:
    if request.url.path.startswith("/medicoes"):
        logger.warning(
            "Rota antiga em uso: %s %s (ver comentário de alias em api/main.py)",
            request.method,
            request.url.path,
        )


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
    _avisar_uso_do_alias(request)
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


# Alias de compatibilidade — motivo e critério de remoção no comentário
# acima de POST /leituras.
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
    _avisar_uso_do_alias(request)
    sql = "SELECT * FROM leituras"
    params: list = []
    if regiao:
        sql += " WHERE regiao = %s"
        params.append(regiao)
    sql += " ORDER BY id DESC LIMIT %s"
    params.append(limit)
    with request.app.state.pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


# Alias de compatibilidade — motivo e critério de remoção no comentário
# acima de POST /leituras.
@app.get(
    "/leituras/{leitura_id}",
    response_model=LeituraOut,
    dependencies=[Depends(requer_leitura)],
)
# O path usa /medicoes (nome antigo) mas {leitura_id} (nome novo) de
# propósito: o FastAPI casa parâmetros de path com a assinatura da função
# pelo nome. Trocar por {medicao_id} "pra ficar consistente" não dá erro
# nenhum — vira query param obrigatório e GET /medicoes/5 passa a
# devolver 422 silenciosamente.
@app.get(
    "/medicoes/{leitura_id}",
    response_model=LeituraOut,
    dependencies=[Depends(requer_leitura)],
    include_in_schema=False,
)
def buscar_leitura(leitura_id: int, request: Request):
    _avisar_uso_do_alias(request)
    with request.app.state.pool.connection() as conn:
        row = conn.execute(
            "SELECT * FROM leituras WHERE id = %s", (leitura_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Leitura não encontrada")
    return row


# --- Previsões ---------------------------------------------------------------
# Teto de 10 MB. O Neon free tem 0,5 GB no total e é o banco inteiro do projeto;
# uma planilha de previsão tem alguns KB, então 10 MB já é folga larga.
# Este número TEM que ser o mesmo da constraint previsoes_conteudo_ate_10mb
# em api/db.py — ver o comentário lá.
TAMANHO_MAX_PREVISAO = 10 * 1024 * 1024
# Usado no GET de download (Task 6), pra devolver o Content-Type certo da
# planilha — não usado ainda nesta rota de upload.
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Overhead da framing do multipart (linha de boundary, headers de cada parte,
# boundary final) por cima do arquivo em si — medido empiricamente em ~230
# bytes pra um upload de um arquivo só. NÃO é folga do limite de negócio:
# é só a diferença entre "tamanho do arquivo" e "tamanho do corpo HTTP que
# carrega o arquivo". Sem essa margem, um upload de exatamente 10 MB seria
# barrado aqui com o erro errado (413 por causa da framing, não do conteúdo).
MARGEM_MULTIPART_BYTES = 4096


@app.middleware("http")
async def rejeitar_previsao_grande_por_content_length(request: Request, call_next):
    # Reordenar os checks de tamanho pra dentro do handler não adianta: pelo
    # tempo em que `criar_previsao` começa a rodar, o Starlette já recebeu e
    # fez parse do multipart inteiro pra resolver o parâmetro `UploadFile` —
    # partes de arquivo não têm teto de tamanho no parser (só campos de
    # formulário comuns têm, via `max_part_size`), e o SpooledTemporaryFile
    # que recebe os bytes já vaza pra disco depois de 1 MB. Um corpo de
    # 500 MB já foi lido e gravado em disco antes do handler ver uma linha
    # de código. Rejeitar aqui, olhando só o header Content-Length ANTES do
    # router (e portanto antes do parser) processar o corpo, evita isso.
    #
    # Só se aplica a POST /previsoes — não é um teto global pra toda rota.
    #
    # O que isto NÃO cobre: uma requisição sem Content-Length (por exemplo
    # Transfer-Encoding: chunked) passa direto por aqui sem checagem — quem
    # barra esse caso é o teto de tamanho de `criar_previsao`, só que depois
    # do corpo inteiro já ter sido lido. Este middleware é uma rejeição
    # antecipada de casos óbvios via header, não a fonte de verdade do
    # limite — essa continua sendo o check dentro do handler.
    if request.method == "POST" and request.url.path == "/previsoes":
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declarado = int(content_length)
            except ValueError:
                declarado = None
            teto = TAMANHO_MAX_PREVISAO + MARGEM_MULTIPART_BYTES
            if declarado is not None and declarado > teto:
                return JSONResponse(
                    status_code=413, content={"detail": "Arquivo acima de 10 MB"}
                )
    return await call_next(request)


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
    #
    # O nome vem de um cliente HTTP qualquer, não do filesystem do servidor,
    # então os.path.basename é a ferramenta errada: no Windows ele corta em
    # "\", no Linux não, e a mesma entrada seria sanitizada de dois jeitos
    # conforme onde a API estivesse rodando (achado testando isto: em
    # produção, Render/Linux, "\" nem seria tratado como separador — a
    # checagem de caracteres proibidos abaixo é que faria o trabalho; no
    # Windows do dev, o basename já cortava antes da checagem rodar).
    # Normaliza os dois separadores explicitamente, sem depender do SO.
    nome = (arquivo.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not nome.lower().endswith(".xlsx"):
        raise HTTPException(400, "O arquivo precisa ser .xlsx")
    # O nome vem do cliente e vai parar num header Content-Disposition no GET.
    # CR/LF ali dentro é injeção de header; aspas corrompem o valor; barra
    # invertida é o caractere de escape dentro de um quoted-string HTTP
    # (RFC 6266/7230) — um nome terminado em "\" quebraria uma formatação
    # ingênua tipo f'filename="{nome}"' mesmo sem conter aspas; um nome
    # absurdamente longo também estoura limites de header. Recusa antes de
    # guardar — o banco não tem como desfazer isso depois.
    #
    # A normalização acima já garante que "\" e "/" nunca sobrevivem em
    # `nome` — então checar "\" aqui de novo é defesa em profundidade, não a
    # guarda principal. Mantém mesmo assim: se um dia a normalização mudar
    # (ou alguém remover o rsplit acima), esta lista é o que ainda protege
    # o header.
    if len(nome) > 200:
        raise HTTPException(400, "Nome de arquivo longo demais")
    if (
        '"' in nome
        or "\\" in nome
        or any(ord(c) < 32 or ord(c) == 127 for c in nome)
    ):
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
