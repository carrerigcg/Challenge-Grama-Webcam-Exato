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

# Mesmo número de api/main.py (TAMANHO_MAX_PREVISAO). Duplicado de propósito:
# o teste tem que travar se o valor do código de produção mudar sem querer.
TAMANHO_MAX_PREVISAO = 10 * 1024 * 1024

# Um .xlsx é um zip: começa com "PK\x03\x04". A API não abre a planilha, só
# guarda os bytes, então um zip de mentira serve e mantém o teste rápido.
CONTEUDO = b"PK\x03\x04 planilha de mentira"


def _upload(nome="previsao.xlsx", conteudo=CONTEUDO):
    return {"arquivo": (nome, conteudo, XLSX)}


def _contar_previsoes(client) -> int:
    """Prova direta no banco de que nada foi gravado — não basta confiar no
    status HTTP quando o que se quer garantir é a ausência de efeito
    colateral."""
    with client.app.state.pool.connection() as conn:
        return conn.execute("SELECT count(*) AS n FROM previsoes").fetchone()["n"]


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
        files=_upload(conteudo=b"x" * (TAMANHO_MAX_PREVISAO + 1)),
        headers=headers_escrita,
    )
    assert r.status_code == 413


def test_post_previsao_no_teto_exato_de_10mb_e_aceito(client, headers_escrita):
    """Fronteira de cima: exatamente 10 MB tem que passar — prova que o
    código usa ">" e não ">=". Também é o teste de regressão da margem do
    middleware de Content-Length (api/main.py, MARGEM_MULTIPART_BYTES): se
    a margem for pequena demais pro overhead do multipart, este upload
    LEGÍTIMO seria barrado com o 413 errado antes mesmo de chegar aqui."""
    r = client.post(
        "/previsoes",
        files=_upload(conteudo=b"x" * TAMANHO_MAX_PREVISAO),
        headers=headers_escrita,
    )
    assert r.status_code == 201
    assert r.json()["tamanho_bytes"] == TAMANHO_MAX_PREVISAO


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


# --- Content-Length gigante: rejeitado pelo middleware, antes do parsing ----
def test_post_previsao_content_length_gigante_e_rejeitado_antes_do_parsing(
    client, headers_escrita
):
    """O Starlette (formparsers.py) só limita o tamanho de campos de forms
    comuns (max_part_size); partes de ARQUIVO não têm teto nenhum ali — o
    corpo inteiro é recebido e vira um SpooledTemporaryFile que vaza pra
    disco depois de 1 MB, antes mesmo do handler começar a rodar. Por isso
    api/main.py tem um middleware que olha o header Content-Length antes do
    corpo ser lido. Este teste manda um corpo pequeno de propósito — o que
    prova a rejeição antecipada é o header mentiroso, não o tamanho real
    transmitido; se o middleware estivesse esperando o corpo chegar, isto
    daria erro de parsing, não 413."""
    headers = {
        **headers_escrita,
        "Content-Type": "multipart/form-data; boundary=x",
        "content-length": str(500 * 1024 * 1024),
    }
    r = client.post(
        "/previsoes", content=b"corpo pequeno de proposito", headers=headers
    )
    assert r.status_code == 413
    assert _contar_previsoes(client) == 0


# --- Caracteres proibidos no nome: protegem o Content-Disposition da Task 6 -
# O nome vai parar num header Content-Disposition no GET (Task 6): CR/LF
# injeta cabeçalho, aspas e barra invertida corrompem um quoted-string HTTP
# (RFC 6266/7230 — "\" é o caractere de escape ali), e um nome absurdo
# estoura limites de header. Task 5 recusa tudo isso antes de gravar.
#
# `_upload()` (via `files=` do httpx) não serve para estes testes: o httpx
# sanitiza defensivamente o filename do multipart, convertendo caracteres de
# controle e aspas em percent-encoding (`\n` -> "%0A") antes de enviar — o
# servidor nunca veria o byte cru. Um cliente HTTP arbitrário não tem essa
# cortesia, então o corpo multipart é montado à mão aqui para entregar o
# byte malicioso de verdade e exercitar a validação do servidor.
_BOUNDARY_TESTE = "boundary-teste-previsao"


def _upload_raw(nome_cru: str) -> bytes:
    # latin-1 mapeia cada byte 0-255 pro seu code point (round-trip exato) —
    # é o jeito de colocar um byte cru arbitrário num f-string sem que o
    # Python tente decodificar/recodificar nada. `surrogateescape` é só uma
    # defesa a mais para o caso de um dia um teste passar um code point
    # acima de 0x7F: nenhum dos payloads atuais (\n, \r, ", \) chega perto
    # disso, então o parâmetro fica inerte por enquanto.
    corpo = (
        f"--{_BOUNDARY_TESTE}\r\n"
        f'Content-Disposition: form-data; name="arquivo"; filename="{nome_cru}"\r\n'
        f"Content-Type: {XLSX}\r\n\r\n"
    ).encode("latin-1", errors="surrogateescape") + CONTEUDO + (
        f"\r\n--{_BOUNDARY_TESTE}--\r\n"
    ).encode("latin-1")
    return corpo


def _headers_multipart_cru(headers_escrita):
    return {
        **headers_escrita,
        "Content-Type": f"multipart/form-data; boundary={_BOUNDARY_TESTE}",
    }


def test_post_previsao_rejeita_nome_com_newline(client, headers_escrita):
    r = client.post(
        "/previsoes",
        content=_upload_raw("previsao\n.xlsx"),
        headers=_headers_multipart_cru(headers_escrita),
    )
    assert r.status_code == 400
    assert _contar_previsoes(client) == 0


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
    assert _contar_previsoes(client) == 0


def test_post_previsao_rejeita_nome_com_aspas(client, headers_escrita):
    r = client.post(
        "/previsoes",
        content=_upload_raw('previsao".xlsx'),
        headers=_headers_multipart_cru(headers_escrita),
    )
    assert r.status_code == 400
    assert _contar_previsoes(client) == 0


def test_post_previsao_barra_invertida_no_nome(client, headers_escrita):
    """"\\" está na lista de caracteres proibidos (api/main.py) porque é o
    caractere de escape dentro de um quoted-string HTTP — um nome terminado
    em "\\" quebraria uma formatação ingênua do Content-Disposition da
    Task 6 mesmo sem conter aspas.

    ACHADO ao escrever este teste (rodando em Windows, onde `os.path` é
    `ntpath`): `os.path.basename()`, chamado ANTES da checagem explícita de
    caracteres, já trata "\\" como separador de caminho e corta tudo até o
    último "\\" — então este payload chega em `criar_previsao` como
    ".xlsx", sem barra nenhuma, e a checagem nova nunca roda pra este caso
    específico. Em produção (Render, Linux) `os.path` é `posixpath`, que
    NÃO trata "\\" como separador: lá a barra sobrevive ao basename e é a
    checagem explícita — não o basename — que barra o upload com 400. A
    garantia que interessa (o nome gravado nunca carrega "\\") vale nas
    duas plataformas, só que por mecanismos diferentes; este teste aceita
    os dois desfechos e checa a garantia real em cada um, em vez de fixar
    um status_code que já se provou dependente de SO.
    """
    r = client.post(
        "/previsoes",
        content=_upload_raw("previsao\\.xlsx"),
        headers=_headers_multipart_cru(headers_escrita),
    )
    assert r.status_code in (201, 400)
    if r.status_code == 201:
        assert "\\" not in r.json()["nome_arquivo"]
        assert _contar_previsoes(client) == 1
    else:
        assert _contar_previsoes(client) == 0


def test_post_previsao_rejeita_nome_longo_demais(client, headers_escrita):
    nome = "a" * 197 + ".xlsx"  # 202 caracteres, acima do limite de 200
    r = client.post(
        "/previsoes", files=_upload(nome=nome), headers=headers_escrita
    )
    assert r.status_code == 400


def test_post_previsao_nome_no_limite_exato_de_200_e_aceito(client, headers_escrita):
    """Fronteira de cima do nome: exatamente 200 caracteres tem que passar —
    prova que o código usa ">" e não ">=" aqui também."""
    nome = "a" * 195 + ".xlsx"  # exatamente 200 caracteres
    assert len(nome) == 200
    r = client.post("/previsoes", files=_upload(nome=nome), headers=headers_escrita)
    assert r.status_code == 201
    assert r.json()["nome_arquivo"] == nome
