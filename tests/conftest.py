"""Fixtures compartilhadas dos testes de API."""
import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

load_dotenv()

CHAVE_ESCRITA = "chave-de-escrita-teste"
CHAVE_LEITURA = "chave-de-leitura-teste"


@pytest.fixture(scope="session")
def _env_de_teste():
    """Aponta a API para a branch `test` do Neon antes de importar o app.

    Sem autouse de propósito: só quem pede o `client` depende de banco.
    Com autouse, o skip abaixo pularia a suíte inteira.
    """
    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST não configurada — veja .env.example")
    # Definir antes do import de api.main: load_dotenv() não sobrescreve
    # variáveis já presentes, então o .env de produção não vaza pro teste.
    os.environ["DATABASE_URL"] = url
    os.environ["API_KEY_WRITE"] = CHAVE_ESCRITA
    os.environ["API_KEY_READ"] = CHAVE_LEITURA
    return url


@pytest.fixture
def client(_env_de_teste):
    from api import clima
    from api.main import app

    app.dependency_overrides[clima.clima_atual] = lambda: (21.5, "Nublado")
    # O `with` é o que dispara o lifespan e abre o pool.
    with TestClient(app) as c:
        with app.state.pool.connection() as conn:
            conn.execute("TRUNCATE medicoes RESTART IDENTITY")
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def headers_escrita():
    return {"X-API-Key": CHAVE_ESCRITA}


@pytest.fixture
def headers_leitura():
    return {"X-API-Key": CHAVE_LEITURA}
