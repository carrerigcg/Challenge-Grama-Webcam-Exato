import os
import sqlite3
from contextlib import contextmanager
from enum import Enum

import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

load_dotenv()

DB_PATH = "medicoes.db"

API_KEY = os.environ.get("API_KEY")
if not API_KEY:
    raise RuntimeError(
        "API_KEY não configurada. Crie um arquivo .env com API_KEY=sua_chave"
    )

# São Paulo/SP — usado pra buscar clima no Open-Meteo
SP_LAT = -23.55
SP_LON = -46.63

# Mapeia weather_code (padrão WMO) do Open-Meteo pra descrição simples
WEATHER_CODE_MAP = {
    0: "Ensolarado",
    1: "Parcialmente nublado",
    2: "Parcialmente nublado",
    3: "Nublado",
    45: "Neblina",
    48: "Neblina",
    51: "Chuvisco",
    53: "Chuvisco",
    55: "Chuvisco",
    61: "Chuvoso",
    63: "Chuvoso",
    65: "Chuva forte",
    71: "Neve",
    73: "Neve",
    75: "Neve forte",
    80: "Pancadas de chuva",
    81: "Pancadas de chuva",
    82: "Pancadas de chuva fortes",
    95: "Tempestade",
    96: "Tempestade com granizo",
    99: "Tempestade com granizo",
}

app = FastAPI(title="API Grama Webcam")


# --- Autenticação ------------------------------------------------------------
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verificar_api_key(api_key: str | None = Depends(api_key_header)) -> None:
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="API key inválida ou ausente")


# --- Banco de dados ----------------------------------------------------------
@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@app.on_event("startup")
def criar_tabela():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS medicoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                regiao TEXT NOT NULL,
                altura_cm REAL NOT NULL,
                nivel_risco TEXT NOT NULL,
                temperatura_c REAL,
                clima TEXT,
                criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


# --- Cliente Open-Meteo ------------------------------------------------------
def buscar_clima(lat: float, lon: float) -> tuple[float | None, str | None]:
    """Consulta Open-Meteo. Retorna (temperatura_c, clima) ou (None, None) se falhar."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,weather_code",
        "timezone": "America/Sao_Paulo",
    }
    try:
        r = requests.get(url, params=params, timeout=5)
        r.raise_for_status()
        dados = r.json()["current"]
        temperatura = dados["temperature_2m"]
        clima = WEATHER_CODE_MAP.get(dados["weather_code"], "Desconhecido")
        return temperatura, clima
    except (requests.RequestException, KeyError, ValueError):
        return None, None


# --- Schemas -----------------------------------------------------------------
class NivelRisco(str, Enum):
    AUSENTE = "AUSENTE"
    BAIXA = "BAIXA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"


class MedicaoIn(BaseModel):
    regiao: str = "mato do matheus"
    altura_cm: float = Field(ge=0)
    nivel_risco: NivelRisco


class MedicaoOut(BaseModel):
    id: int
    regiao: str
    altura_cm: float
    nivel_risco: NivelRisco
    temperatura_c: float | None
    clima: str | None
    criado_em: str


# --- Endpoints ---------------------------------------------------------------
@app.get("/")
def raiz():
    return {"status": "ok", "mensagem": "API no ar"}


@app.post(
    "/medicoes",
    response_model=MedicaoOut,
    dependencies=[Depends(verificar_api_key)],
)
def criar_medicao(medicao: MedicaoIn):
    temperatura, clima = buscar_clima(SP_LAT, SP_LON)
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO medicoes (regiao, altura_cm, nivel_risco, temperatura_c, clima)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                medicao.regiao,
                medicao.altura_cm,
                medicao.nivel_risco.value,
                temperatura,
                clima,
            ),
        )
        novo_id = cursor.lastrowid
        row = conn.execute(
            "SELECT * FROM medicoes WHERE id = ?", (novo_id,)
        ).fetchone()
        return dict(row)


@app.get(
    "/medicoes",
    response_model=list[MedicaoOut],
    dependencies=[Depends(verificar_api_key)],
)
def listar_medicoes(limit: int = 100):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM medicoes ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


@app.get(
    "/medicoes/{medicao_id}",
    response_model=MedicaoOut,
    dependencies=[Depends(verificar_api_key)],
)
def buscar_medicao(medicao_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM medicoes WHERE id = ?", (medicao_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Medição não encontrada")
        return dict(row)
