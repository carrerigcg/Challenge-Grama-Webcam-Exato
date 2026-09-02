"""Testes dos endpoints da API."""


def _payload(regiao="mato do matheus", altura=5.2, risco="MEDIA", **extras):
    corpo = {"regiao": regiao, "altura_cm": altura, "nivel_risco": risco}
    corpo.update(extras)
    return corpo


# --- POST /leituras ----------------------------------------------------------
def test_post_persiste_clima_enviado_pela_estacao(client, headers_escrita):
    """API só armazena — clima vem da estação (o IP compartilhado do Render
    toma 429 do Open-Meteo, o IP residencial da estação não)."""
    r = client.post(
        "/leituras",
        json=_payload(temperatura_c=21.5, clima="Nublado"),
        headers=headers_escrita,
    )
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["id"] == 1
    assert corpo["regiao"] == "mato do matheus"
    assert corpo["altura_cm"] == 5.2
    assert corpo["temperatura_c"] == 21.5
    assert corpo["clima"] == "Nublado"


def test_post_sem_clima_persiste_null(client, headers_escrita):
    """Se a estação estiver offline pro Open-Meteo, a medição salva sem clima."""
    r = client.post("/leituras", json=_payload(), headers=headers_escrita)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["temperatura_c"] is None
    assert corpo["clima"] is None


def test_post_persiste_de_fato_no_banco(client, headers_escrita, headers_leitura):
    """Prova que o dado sobrevive fora da memória do processo."""
    client.post("/leituras", json=_payload(altura=7.7), headers=headers_escrita)
    with client.app.state.pool.connection() as conn:
        row = conn.execute("SELECT altura_cm FROM leituras").fetchone()
    assert row["altura_cm"] == 7.7


def test_post_sem_regiao_e_rejeitado(client, headers_escrita):
    corpo = _payload()
    del corpo["regiao"]
    r = client.post("/leituras", json=corpo, headers=headers_escrita)
    assert r.status_code == 422


def test_post_com_regiao_vazia_e_rejeitado(client, headers_escrita):
    r = client.post("/leituras", json=_payload(regiao=""), headers=headers_escrita)
    assert r.status_code == 422


def test_post_com_altura_negativa_e_rejeitado(client, headers_escrita):
    r = client.post("/leituras", json=_payload(altura=-1), headers=headers_escrita)
    assert r.status_code == 422


def test_post_com_nivel_invalido_e_rejeitado(client, headers_escrita):
    r = client.post(
        "/leituras", json=_payload(risco="ALTISSIMA"), headers=headers_escrita
    )
    assert r.status_code == 422


# --- Autenticação ------------------------------------------------------------
def test_post_com_chave_de_leitura_e_negado(client, headers_leitura):
    """O consumidor externo só lê: a chave dele não pode inserir dado falso."""
    r = client.post("/leituras", json=_payload(), headers=headers_leitura)
    assert r.status_code == 401


def test_post_sem_chave_e_negado(client):
    r = client.post("/leituras", json=_payload())
    assert r.status_code == 401


def test_get_sem_chave_e_negado(client):
    r = client.get("/leituras")
    assert r.status_code == 401


def test_get_com_chave_de_leitura_funciona(client, headers_escrita, headers_leitura):
    client.post("/leituras", json=_payload(), headers=headers_escrita)
    r = client.get("/leituras", headers=headers_leitura)
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_chave_de_escrita_tambem_le(client, headers_escrita):
    """Conveniência para as estações e para debug."""
    client.post("/leituras", json=_payload(), headers=headers_escrita)
    r = client.get("/leituras", headers=headers_escrita)
    assert r.status_code == 200


# --- GET /leituras -----------------------------------------------------------
def test_get_filtra_por_regiao(client, headers_escrita, headers_leitura):
    client.post("/leituras", json=_payload(regiao="norte"), headers=headers_escrita)
    client.post("/leituras", json=_payload(regiao="sul"), headers=headers_escrita)
    r = client.get("/leituras", params={"regiao": "sul"}, headers=headers_leitura)
    assert r.status_code == 200
    corpo = r.json()
    assert len(corpo) == 1
    assert corpo[0]["regiao"] == "sul"


def test_get_sem_filtro_traz_todas_as_regioes(
    client, headers_escrita, headers_leitura
):
    client.post("/leituras", json=_payload(regiao="norte"), headers=headers_escrita)
    client.post("/leituras", json=_payload(regiao="sul"), headers=headers_escrita)
    r = client.get("/leituras", headers=headers_leitura)
    assert len(r.json()) == 2


def test_get_ordena_do_mais_recente_para_o_mais_antigo(
    client, headers_escrita, headers_leitura
):
    client.post("/leituras", json=_payload(altura=1.0), headers=headers_escrita)
    client.post("/leituras", json=_payload(altura=2.0), headers=headers_escrita)
    r = client.get("/leituras", headers=headers_leitura)
    assert [m["altura_cm"] for m in r.json()] == [2.0, 1.0]


def test_get_respeita_limit(client, headers_escrita, headers_leitura):
    for _ in range(3):
        client.post("/leituras", json=_payload(), headers=headers_escrita)
    r = client.get("/leituras", params={"limit": 2}, headers=headers_leitura)
    assert len(r.json()) == 2


def test_get_criado_em_vem_em_iso8601(client, headers_escrita, headers_leitura):
    """O consumidor parseia com pandas; ISO evita ambiguidade de formato."""
    from datetime import datetime

    client.post("/leituras", json=_payload(), headers=headers_escrita)
    r = client.get("/leituras", headers=headers_leitura)
    datetime.fromisoformat(r.json()[0]["criado_em"])  # não pode levantar


# --- GET /leituras/{id} ------------------------------------------------------
def test_get_por_id_retorna_a_leitura(client, headers_escrita, headers_leitura):
    novo = client.post(
        "/leituras", json=_payload(), headers=headers_escrita
    ).json()
    r = client.get(f"/leituras/{novo['id']}", headers=headers_leitura)
    assert r.status_code == 200
    assert r.json()["id"] == novo["id"]


def test_get_por_id_inexistente_retorna_404(client, headers_leitura):
    r = client.get("/leituras/9999", headers=headers_leitura)
    assert r.status_code == 404


# --- Raiz --------------------------------------------------------------------
def test_raiz_nao_exige_chave(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# --- Aliases de compatibilidade ----------------------------------------------
# /medicoes continua respondendo porque duas partes fora deste repo dependem
# do nome antigo e nenhuma se atualiza sozinha: as estações em campo
# (medir_grama.py, só POST) e o consumidor externo (só GET). Some quando as
# duas migrarem — não dá pra confirmar isso pelo repo, ver comentário em
# api/main.py acima de POST /leituras.
def test_post_no_alias_medicoes_ainda_grava(client, headers_escrita):
    r = client.post("/medicoes", json=_payload(), headers=headers_escrita)
    assert r.status_code == 200
    assert r.json()["regiao"] == "mato do matheus"


def test_get_no_alias_medicoes_ainda_le(client, headers_escrita, headers_leitura):
    client.post("/leituras", json=_payload(), headers=headers_escrita)
    r = client.get("/medicoes", headers=headers_leitura)
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_get_por_id_no_alias_medicoes_ainda_funciona(
    client, headers_escrita, headers_leitura
):
    """Rota do consumidor externo — ele só lê, e é quem ainda não migrou aqui."""
    novo = client.post("/leituras", json=_payload(), headers=headers_escrita).json()
    r = client.get(f"/medicoes/{novo['id']}", headers=headers_leitura)
    assert r.status_code == 200
    assert r.json()["id"] == novo["id"]


def test_alias_medicoes_exige_chave(client):
    r = client.post("/medicoes", json=_payload())
    assert r.status_code == 401


def test_alias_medicoes_com_chave_de_leitura_nao_grava(client, headers_leitura):
    """A duplicação do decorador é o risco: a alias não pode virar rota de escrita."""
    r = client.post("/medicoes", json=_payload(), headers=headers_leitura)
    assert r.status_code == 401


def test_aliases_ficam_fora_da_documentacao(client):
    """Ninguém novo deve descobrir /medicoes e passar a depender dele."""
    caminhos = client.get("/openapi.json").json()["paths"]
    assert "/leituras" in caminhos
    assert "/medicoes" not in caminhos


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


# O nome vai parar num header Content-Disposition no GET (Task 6): CR/LF
# injeta cabeçalho, aspas corrompem o valor, e um nome absurdo estoura
# limites de header. Task 5 recusa tudo isso antes de gravar.
#
# `_upload()` (via `files=` do httpx) não serve para estes três testes: o
# httpx sanitiza defensivamente o filename do multipart, convertendo
# caracteres de controle e aspas em percent-encoding (`\n` -> "%0A") antes
# de enviar — o servidor nunca veria o byte cru. Um cliente HTTP arbitrário
# não tem essa cortesia, então o corpo multipart é montado à mão aqui para
# entregar o byte malicioso de verdade e exercitar a validação do servidor.
def _upload_raw(nome_cru: str) -> bytes:
    boundary = "boundary-teste-previsao"
    corpo = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="arquivo"; filename="{nome_cru}"\r\n'
        f"Content-Type: {XLSX}\r\n\r\n"
    ).encode("latin-1", errors="surrogateescape") + CONTEUDO + (
        f"\r\n--{boundary}--\r\n"
    ).encode("latin-1")
    return corpo


def _headers_multipart_cru(headers_escrita):
    boundary = "boundary-teste-previsao"
    return {**headers_escrita, "Content-Type": f"multipart/form-data; boundary={boundary}"}


def test_post_previsao_rejeita_nome_com_newline(client, headers_escrita):
    r = client.post(
        "/previsoes",
        content=_upload_raw("previsao\n.xlsx"),
        headers=_headers_multipart_cru(headers_escrita),
    )
    assert r.status_code == 400


def test_post_previsao_rejeita_nome_com_carriage_return(client, headers_escrita):
    # O \r sozinho quebra o parsing do multipart antes mesmo de chegar na
    # validação do nome (python-multipart trata CR como fim de cabeçalho) —
    # o 400 aqui vem do parser, não da checagem da rota. De qualquer forma
    # nenhuma linha é gravada, que é a garantia que este teste protege.
    r = client.post(
        "/previsoes",
        content=_upload_raw("previsao\r.xlsx"),
        headers=_headers_multipart_cru(headers_escrita),
    )
    assert r.status_code == 400


def test_post_previsao_rejeita_nome_com_aspas(client, headers_escrita):
    r = client.post(
        "/previsoes",
        content=_upload_raw('previsao".xlsx'),
        headers=_headers_multipart_cru(headers_escrita),
    )
    assert r.status_code == 400


def test_post_previsao_rejeita_nome_longo_demais(client, headers_escrita):
    nome = "a" * 197 + ".xlsx"  # 202 caracteres, acima do limite de 200
    r = client.post(
        "/previsoes", files=_upload(nome=nome), headers=headers_escrita
    )
    assert r.status_code == 400
