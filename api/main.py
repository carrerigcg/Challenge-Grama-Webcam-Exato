"""API de leituras de altura de grama."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
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
