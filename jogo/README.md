# Jogo da feira de ciências

Jogo no formato Kahoot para apresentar o Grama Webcam. Até cinco visitantes
chutam pelo celular quanto mede a grama; o apresentador manda medir pela webcam
real; o valor sobe numa animação e quem chegou mais perto ganha.

## Como as peças se encaixam

```
VISITANTES (cada um no seu 5G)          ESTE SERVIÇO (Render)
  📱 📱 📱  ──── escaneiam o QR ────▶   sala, chutes, ranking
                                               ▲
                                               │ WebSocket de SAÍDA
                                     NOTEBOOK DA FEIRA
                                     python -m jogo.ponte
                                     (a webcam está aqui)
```

Quem abre a conexão é o notebook. Por isso não é preciso IP público, porta
liberada nem que os celulares estejam na mesma rede.

## Rodar local

Os comandos abaixo são PowerShell, que é o shell do Windows.

```powershell
pip install -r requirements-jogo.txt -r requirements-ponte.txt
```

O `.env` não vem no repositório (é gitignored), então um clone novo não tem
nenhum. Crie o seu e preencha `HOST_TOKEN`, `PONTE_TOKEN` e `JOGO_URL_PUBLICA`
antes de subir qualquer coisa:

```powershell
Copy-Item .env.example .env
```

```powershell
# terminal 1 — o jogo
python -m uvicorn jogo.main:app --reload
```

```powershell
# terminal 2 — a ponte (precisa de calibration.json nesta máquina)
python -m jogo.ponte
```

Controle (o que os visitantes abrem): `http://localhost:8000`

O palco exige o token na própria URL, porque o servidor responde 403 antes de
qualquer JavaScript rodar. Barra de endereço de navegador não expande variável
de ambiente, então monte a URL no terminal e abra o que ele imprimir:

```powershell
"http://localhost:8000/host?token=$($env:HOST_TOKEN)"
```

## Roteiro de montagem na feira

1. Copiar o repositório para o notebook da feira.
2. `pip install -r requirements-ponte.txt`
3. Criar o `.env` com `Copy-Item .env.example .env`. Ele **não** vem no
   repositório, então um clone novo não tem nenhum. Preencher `PONTE_TOKEN` e
   `JOGO_URL_PUBLICA` com os mesmos valores do painel da Render — se o
   `PONTE_TOKEN` daqui não for idêntico ao de lá, a ponte apanha 403 e o
   semáforo nunca acende.
4. Posicionar e **fixar** a câmera. Se ela encostar depois, recalibre.
5. `python calibrar.py` — nesta máquina, com a câmera no lugar final.
6. `python -m jogo.ponte`, **a partir da raiz do repositório**, deixando rodando
   o dia todo. Ela procura o `calibration.json` no diretório de onde foi
   chamada: de outra pasta, falha pedindo calibração que já existe.
7. Pegar o `HOST_TOKEN` no painel da Render, em Environment do serviço
   `jogo-grama-webcam`. Ele **não** está no repositório nem no `.env` do
   notebook: é `sync: false`, existe só lá.
8. Abrir `JOGO_URL_PUBLICA/host?token=HOST_TOKEN` no notebook — a URL inteira,
   com os dois valores colados no lugar — e apertar F11 para tela cheia.
9. Confirmar o semáforo "● câmera conectada" no palco.
10. Testar uma rodada com o próprio celular **antes** do primeiro grupo.
11. Imprimir o QR do jogo, se houver impressora. O palco também mostra o dele,
    gerado na hora, e o visitante escaneia direto da tela.

O passo 5 não é opcional: `px_por_cm` e `y_chao` são da câmera **e** da posição
dela. Sem recalibrar nesta máquina, a altura sai torta.

## Operação durante a feira

| Situação | O que fazer |
|---|---|
| grupo novo chegando | "Nova rodada" — limpa jogadores e reabre a sala |
| os cinco já entraram | "Travar sala" — ninguém mais ocupa cadeira |
| semáforo apagado | a ponte caiu; ela reconecta sozinha, veja o terminal dela |
| medição falhou | clique MEDIR de novo; os chutes foram preservados |
| alguém travou no meio | "Nova rodada" funciona de qualquer estado |

## Testes

Uma linha por comando: no PowerShell a continuação de linha é crase, e um
comando quebrado com barra invertida roda pela metade sem avisar.

```powershell
python -m pytest tests/test_jogo_sala.py tests/test_jogo_medicao.py tests/test_jogo_difusor.py tests/test_jogo_envio.py tests/test_jogo_api.py -v
```

```powershell
python -m pytest tests/test_jogo_ponte.py -v   # pula sem cv2 instalado
```

A suíte roda sem webcam: `jogo/sala.py` não tem I/O e a medição é falsificada.
Só `tests/test_jogo_ponte.py` precisa de `cv2`, e ele é pulado onde não houver.
