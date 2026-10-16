# Design: jogo da feira de ciências

**Data:** 2026-10-16
**Status:** aprovado

## Contexto

O projeto vai ser apresentado numa feira de ciências. Os visitantes chegam em grupo,
param na mesa, olham a grama e vão embora em poucos minutos. Explicar segmentação HSV
para quem passa não funciona; mostrar o sistema medindo na frente da pessoa, funciona.

A ideia é um jogo no formato Kahoot: até cinco visitantes entram numa sala pelo celular,
cada um chuta quanto mede aquela grama, o apresentador manda medir, o valor real sobe
numa animação e quem chegou mais perto ganha. A medição não é simulada — é o mesmo
pipeline de produção, com a mesma câmera e a mesma calibração.

O repositório hoje tem o pipeline de visão (`medir_grama.py`), a calibração
(`calibrar.py`) e a API de produção (`api/`). Nada de interface web interativa.

## Escopo

Um aplicativo web novo, hospedado, com duas interfaces:

| Interface | Quem usa | O que faz |
|---|---|---|
| **Palco** (`/host`) | o apresentador, na tela do notebook | QR de entrada, lista de jogadores, botão de medir, animação da revelação, pódio |
| **Controle** (`/`) | os visitantes, no celular | entra com o nome, manda o chute, vê a colocação pessoal |

Mais um processo que roda no notebook da feira:

| Componente | Onde roda | O que faz |
|---|---|---|
| **Ponte** (`jogo/ponte.py`) | notebook da feira | conecta no jogo, recebe a ordem de medir, roda o pipeline, devolve o resultado |

**Fora de escopo:**

- Modo totalmente local (jogo rodando no notebook, visitantes na rede local). Foi
  considerado e cortado: a feira tem infraestrutura de rede dedicada e vários projetos
  dependem de internet, então a dependência é aceitável e o modo duplo custaria código,
  testes e documentação sem pagar risco real.
- Qualquer alteração em `api/` ou no pipeline de `medir_grama.py`. O jogo **consome** o
  pipeline, não o modifica.
- Persistência das rodadas. A sala vive em memória e morre com o processo.
- Contas, cadastro, histórico por visitante.

## Decisões

### O jogo é uma app separada, não entra em `api/`

`api/main.py` vai pro Render a cada `push origin main` e instala apenas
`requirements-api.txt`. O jogo é um segundo serviço, com `requirements-jogo.txt` próprio.

O motivo é concreto, não organizacional: se o jogo morasse dentro da app de produção, o
próximo deploy da API tentaria importar o módulo do jogo e quebraria. A API de produção
não pode cair por causa de uma feira.

### Render, não Vercel

A Vercel é serverless: funções pedido-resposta, sem WebSocket persistente, e cada
invocação pode cair numa instância diferente. Uma sala guardada em memória desapareceria
entre requisições. Hospedar lá exigiria um serviço de tempo real por fora (Pusher, Ably)
mais um armazenamento de estado — duas dependências novas para resolver o que a Render
resolve com um processo vivo.

A Render roda um processo contínuo que segura a sala na memória e mantém os WebSockets
abertos. O projeto já tem conta, `render.yaml` e fluxo de deploy conhecido.

### A câmera fica no notebook; quem liga é o notebook

Nenhum servidor hospedado alcança uma webcam numa mesa de feira. A inversão resolve: a
ponte abre um WebSocket **de saída** para o jogo e fica pendurada esperando ordem.

Conexão de saída dispensa IP público, redirecionamento de porta, configuração de firewall
e qualquer exigência de que os celulares estejam na mesma rede do notebook. É o mesmo
mecanismo de ngrok e de runners de CI. Consequência prática: isolamento de cliente no
Wi-Fi do evento deixa de ser um problema, porque o notebook só precisa navegar para fora.

Os visitantes entram pelo 5G de cada um, sem Wi-Fi, sem senha, sem rede para configurar.

### O `cv2` não sobe para a nuvem

Quem tem câmera é a ponte. O serviço hospedado fica com `fastapi`, `uvicorn` e `qrcode`:
deploy leve, sem compilar visão computacional num container free. OpenCV e numpy ficam
só no notebook, via `requirements-station.txt`, que já existe.

### A medição entra por uma costura fina, com uma implementação só

`jogo/medicao.py` expõe uma função de medição com uma implementação: a que fala com a
ponte. Quem a chama é `jogo/main.py`, não a `sala.py` — a sala apenas recebe o resultado
já pronto e muda de estado. É isso que mantém a sala sem I/O nenhum.

A costura não é abstração especulativa — é o que permite falsificar a medição nos testes
e rodar a suíte inteira sem webcam, na máquina de desenvolvimento. O benefício é presente.

### A ponte reconecta sozinha

Backoff exponencial, teto de 30s. Internet boa não quer dizer conexão sem soluço: trocar
de ponto de acesso ou um Wi-Fi piscando por dois segundos já derruba o socket. Com
reconexão automática isso passa sem ninguém notar; sem ela, descobre-se na hora errada
que a ponte precisa ser reiniciada à mão.

### A ponte também faz keep-alive por HTTP

Além do WebSocket aberto, um `GET /` a cada 10 minutos. O free tier da Render hiberna
após ~15 minutos de inatividade e demora ~50s para acordar; não há garantia documentada
de que um WebSocket pendurado conte como atividade. O `GET` elimina a dúvida por um custo
desprezível e entrega o item "keep-alive do Render free" que já estava no roadmap.

### A sala é uma máquina de estado de quatro estados

```
AGUARDANDO ──host: medir──▶ MEDINDO ──resultado──▶ REVELANDO ──fim da animação──▶ RESULTADO
     ▲                                                                                │
     └────────────────────────── host: nova rodada ───────────────────────────────────┘
```

A máquina não é formalismo: é o que garante que um chute não entre depois da captura e
que o botão de medir não dispare duas vezes. Um segundo clique em MEDIR morre sozinho,
porque o estado já não é `AGUARDANDO` — não precisa de trava à parte.

Transições permitidas:

| Ação | Quem | Estado exigido |
|---|---|---|
| entrar na sala | visitante | `AGUARDANDO`, sala aberta, < 5 jogadores |
| mandar ou editar chute | visitante | `AGUARDANDO` |
| medir | host | `AGUARDANDO`, com ≥ 1 chute e ponte conectada |
| nova rodada | host | qualquer estado |
| travar/abrir sala | host | qualquer estado |

O host pode resetar de qualquer estado. Se a câmera travar ou o grupo for embora no meio,
ele precisa de válvula de escape, não de um jogo preso.

### Os chutes ficam escondidos até a revelação

O palco mostra quem já chutou, nunca o valor. Todos estão olhando a mesma tela grande, e
mostrar os números deixaria o último a chutar copiar o vizinho.

Enquanto o estado é `AGUARDANDO`, cada jogador pode editar o próprio chute.

### Nome vazio ou repetido é recusado

Dois "Ana" no pódio não dizem quem ganhou, e o cartão pessoal no celular fica ambíguo.
A recusa vem com mensagem pedindo outro nome, não com erro genérico.

### Chute entre 0 e 200 cm, uma decimal

O teto existe por motivo prático: alguém vai digitar 99999 de brincadeira, e isso
explodiria a escala da animação e o layout do pódio.

### Ranking por erro absoluto, empate por ordem de envio

`|chute − medido|`, menor primeiro. Empate resolve por quem enviou antes. Quem entrou e
não chutou não é ranqueado.

Com menos de três jogadores que chutaram, o pódio mostra só os que existem — não há
posição vazia nem lugar reservado. Um grupo de dois é comum na feira e não pode parecer
defeito.

### O servidor é a fonte única da verdade

Nenhum estado de jogo vive no navegador. A cada mudança, o servidor transmite o estado
inteiro para todos os clientes conectados.

WebSocket e não polling porque a revelação tem que ser simultânea: com polling de 1s, um
celular mostraria o pódio um segundo antes do outro e estragaria o suspense.

Cada jogador guarda um id em `localStorage`. Celular bloqueia a tela e derruba a conexão;
ao reconectar, o jogador volta para a mesma cadeira em vez de virar um fantasma na lista.
O host recarregar a página (F5) não afeta a sala — o estado está no servidor.

### Dois tokens, separados

| Token | Onde vive | Protege |
|---|---|---|
| `HOST_TOKEN` | na URL que o apresentador abre | comandos de host: medir, nova rodada, travar sala |
| `PONTE_TOKEN` | arquivo no notebook, lido pela ponte | a identidade da ponte |

Separados porque vivem em lugares diferentes e vazam de formas diferentes: ao mostrar a
tela para alguém, o token do host aparece na barra de endereço, e esse mesmo segredo não
deve dar controle da câmera.

Esconder o botão no CSS não é controle de acesso. O servidor **recusa** comando de host
sem token, com 403. A rota do visitante não conhece esses comandos: mandá-los na mão,
pelo WebSocket de jogador, não faz nada.

### O host pode travar a sala

A URL é pública: qualquer pessoa com o endereço entra e ocupa uma das cinco cadeiras. O
risco é pequeno — URL não divulgada, ninguém procurando — mas uma cadeira ocupada por
alguém que não está na mesa é um problema na hora que o grupo chega.

O host abre a sala quando o grupo chega e trava depois que os cinco entraram. A sala
**nasce aberta**, e "nova rodada" sempre reabre: esquecer a sala travada entre dois grupos
é o erro mais provável de se cometer com pressa, e ele deixa o grupo seguinte sem entrar
sem dizer por quê.

### O POST para a API de produção sai do servidor do jogo

A medição nasce na ponte, mas o envio para a API de produção acontece no servidor do
jogo, que sempre tem internet. Em background: o jogo nunca espera a rede para revelar o
valor.

Vai com `regiao = "Feira de Ciências"`, não com a região da calibração. Um dia de feira
são dezenas de medições; entrar como `"Rod. Anchieta"` contaminaria a série temporal da
rodovia com dado que não é da rodovia.

Falha de envio é silenciosa e não toca o jogo. Dá um momento bom de demonstração: abrir o
`/docs` da API e mostrar o dado que acabou de nascer já no Postgres.

### Sem CDN e sem fonte do Google

Font stack do sistema (`-apple-system, Segoe UI, Roboto, sans-serif`) e nenhum script de
terceiros. Um `<link>` de fonte que não carrega faz o navegador cair no fallback no meio
da apresentação, e o layout aprovado vira outro.

O QR code é gerado no servidor, em Python, com a lib `qrcode`, servido em `/qr.svg`. A
saída óbvia seria um `qrcode.js` de CDN — exatamente o que falha quando a rede oscila.
Nenhum `node_modules` entra no repositório.

### Nenhuma grama detectada é falha de medição, não resultado

Se o pipeline devolver `AUSENTE`, a sala volta para `AGUARDANDO` com aviso, preservando
os chutes. Ranquear gente em cima de um `0,0 cm` que foi erro de enquadramento confunde o
visitante e deslegitima o sistema.

## Interfaces

### Palco (`/host?token=...`)

```
┌───────────────────────────────────────────────────────────────┐
│  GRAMA WEBCAM                        ● câmera conectada       │
│                                                                │
│   ┌─────────┐      Quanto mede essa grama?                    │
│   │ ███ ███ │                                                  │
│   │ █ ▄▄▄ █ │      ┌────────────────────────────────────┐     │
│   │ ███ ███ │      │ 1  Ana      ✓ chutou               │     │
│   └─────────┘      │ 2  Bruno    ✓ chutou               │     │
│   escaneia e entra │ 3  Caio     … pensando             │     │
│                    │ 4  —        vaga livre             │     │
│                    │ 5  —        vaga livre             │     │
│                    └────────────────────────────────────┘     │
│                                                                │
│                     ┌──────────────────────┐                   │
│                     │   📷  MEDIR GRAMA    │   2/3 chutaram    │
│                     └──────────────────────┘                   │
│                     [ travar sala ]  [ nova rodada ]           │
└───────────────────────────────────────────────────────────────┘
```

Por estado:

- **`AGUARDANDO`** — como acima. Botão MEDIR habilitado com ≥ 1 chute e ponte conectada;
  desabilitado com o motivo escrito ao lado.
- **`MEDINDO`** — "capturando…" com pulso. Semáforo da ponte visível.
- **`REVELANDO`** — número grande subindo, lâmina de grama em SVG crescendo atrás como
  referência de escala.
- **`RESULTADO`** — pódio na ordem campeão → 2º → 3º, erro de cada um em cm, imagem
  anotada do `save_debug`, botão NOVA RODADA.

O semáforo da ponte é obrigatório: sem ele, um clique em MEDIR com a ponte caída deixa o
jogo esperando um fantasma na frente do grupo.

A imagem anotada depois do pódio mostra as colunas de amostragem, a linha do chão e a
régua em cm. Já é gerada a cada medição pelo `save_debug`, custa quase nada e troca "o
computador disse 17,5" por "veja como ele chegou lá" — numa feira de ciências, isso é
metade do valor.

### Controle (`/`)

Três telas curtas:

1. **entrada** — campo de nome, botão entrar. Sala cheia ou travada: mensagem explicando.
2. **chute** — campo numérico em cm, enviar. Depois: "chute enviado: 15,0 — pode mudar até
   a medição".
3. **resultado** — cartão pessoal: `2º lugar · seu chute 16,0 · real 17,5 · errou por 1,5 cm`.

Em `MEDINDO` e `REVELANDO`, o celular mostra apenas **"olha pra tela grande!"**. Tirar o
olho do aparelho na hora da revelação é o ponto todo.

## Identidade visual

Mesma paleta do `scripts/gerar_orcamento_pdf.py`, para o jogo não parecer anexo de outro
projeto:

```
VERDE_ESCURO   #1B5E20   títulos, botão MEDIR, nome do campeão
VERDE_MEDIO    #2E7D32   barras, destaques, estado "ao vivo"
VERDE_CLARO    #E8F5E9   fundo de blocos, cadeira que acabou de acender
BRANCO         #FFFFFF   fundo dominante
CINZA_TEXTO    #212121   corpo
CINZA_SEC      #616161   rótulos, "vaga livre"
```

Branco domina, verde pontua: verde escuro reservado para o botão, o número revelado e o
campeão. Alvo de layout: palco em 1366×768, controle em 375px.

### Animações

| Animação | Como | Por quê assim |
|---|---|---|
| contador `0 → 17,5 cm` | `requestAnimationFrame`, ~2,2s, ease-out cúbico | o texto muda a cada frame, não só o estilo — CSS puro não resolve. O ease-out desacelera no fim, onde mora o suspense |
| cadeira acendendo | fundo para `VERDE_CLARO` em 300ms ao entrar ou chutar | é o feedback de que o toque no celular chegou; sem ele a pessoa duvida e aperta de novo |
| campeão | cartão `0.8 → 1.0` com overshoot, 600ms, confete em CSS | overshoot faz parecer comemoração e não transição; confete em CSS porque lib de confete é CDN |
| 2º e 3º | sobem de baixo, 400ms cada, encadeados com 300ms de intervalo | o intervalo dá tempo da plateia ler cada nome; tudo junto vira borrão |

Pódio na ordem campeão → 2º → 3º, premiando o vencedor no pico da atenção. Três linhas de
`prefers-reduced-motion` desligam o movimento.

## Tratamento de falhas

Cada falha acontece com o grupo olhando. Nenhuma pode virar stack trace na tela.

| Falha | Comportamento |
|---|---|
| ponte nunca conectou | MEDIR desabilitado, motivo escrito no palco |
| ponte cai no meio da medição | timeout de 30s, volta para `AGUARDANDO`, **chutes preservados**, host avisado |
| duas pontes conectam | a segunda é recusada com mensagem, em vez de duas câmeras disputando a ordem |
| câmera não abre no notebook | a ponte devolve erro; palco mostra "a câmera não respondeu", chutes preservados |
| nenhuma grama no quadro | tratada como falha de medição, chutes preservados |
| `calibration.json` ausente | a **ponte recusa subir** com "rode `python calibrar.py` nesta máquina". Falhar no boot às 8h é melhor que falhar no primeiro clique com cinco pessoas esperando |
| API de produção fora | POST em background falha calado; o jogo não percebe |
| celular bloqueia a tela | reconecta na mesma cadeira pelo id do `localStorage` |
| host recarrega a página | a sala sobrevive; o estado está no servidor |
| host clica MEDIR duas vezes | o segundo clique morre na máquina de estado |

Chutes preservados em toda falha de medição é regra, não detalhe: o grupo não vai digitar
tudo de novo por causa de um cabo solto.

## Arquivos

| Arquivo | Responsabilidade |
|---|---|
| `jogo/__init__.py` | pacote |
| `jogo/sala.py` | máquina de estado: entrar, chutar, medir, ranquear, travar, resetar. **Zero I/O** |
| `jogo/medicao.py` | costura da medição; fala com a ponte, falsificável nos testes |
| `jogo/main.py` | rotas, WebSockets de jogador/palco/ponte, tokens, `/qr.svg`. Cola, sem regra de negócio |
| `jogo/ponte.py` | roda no notebook: conecta para fora, mede, devolve, reconecta, keep-alive |
| `jogo/templates/palco.html` | tela do palco |
| `jogo/templates/controle.html` | tela do celular |
| `jogo/static/palco.css`, `controle.css`, `palco.js`, `controle.js` | estilo e comportamento |
| `requirements-jogo.txt` | `fastapi`, `uvicorn`, `qrcode` — serviço hospedado |
| `requirements-ponte.txt` | `websockets` + o que `requirements-station.txt` já traz |
| `render.yaml` | segundo serviço web, sem tocar no primeiro |
| `tests/test_jogo_sala.py` | máquina de estado |
| `tests/test_jogo_api.py` | rotas, WebSockets, tokens |
| `tests/test_jogo_ponte.py` | ponte: ordem das chamadas do pipeline, reconexão |

`jogo/sala.py` não importa FastAPI, WebSocket, OpenCV nem HTTP. É função pura sobre um
dicionário de estado — o que a torna testável sem câmera, sem rede e sem navegador.

## Testes

A suíte inteira roda **sem webcam**, seguindo a cultura do repositório: nada de mock onde
o real serve, mas o hardware é falsificado porque não existe no CI nem na máquina de
desenvolvimento.

**`tests/test_jogo_sala.py`** — sala lotada no 6º jogador; sala travada recusa entrada;
chute fora de `AGUARDANDO`; edição de chute; nome vazio e nome duplicado; chute fora de
0–200; ranking; empate por ordem de envio; jogador que entrou e não chutou; reset de cada
estado; medir sem chute nenhum; segundo MEDIR ignorado.

**`tests/test_jogo_api.py`** — `TestClient` do FastAPI com WebSocket: `/host` sem token
responde 403; comando de host pelo socket de jogador não faz nada; broadcast chega em
palco e celular; reconexão recupera a cadeira; `/qr.svg` devolve SVG; medição falsificada
percorre `MEDINDO → REVELANDO → RESULTADO`; ponte desconectada bloqueia MEDIR; segunda
ponte recusada.

**`tests/test_jogo_ponte.py`** — a ponte chama o pipeline na ordem certa, headless, com
frames sintéticos, no mesmo padrão dos 88 testes de `tests/test_medir_grama.py`;
`calibration.json` ausente impede o boot; reconexão com backoff; keep-alive dispara.

## Roteiro de montagem na feira

```
1. copiar o repo pro notebook da feira
2. pip install -r requirements-ponte.txt
3. posicionar e FIXAR a câmera (se encostar depois, recalibra)
4. python calibrar.py                 ← nesta máquina, câmera no lugar final
5. conferir PONTE_TOKEN e a URL do jogo no .env
6. python -m jogo.ponte               ← deixar rodando o dia todo
7. abrir /host?token=... no notebook e apertar F11
8. confirmar o semáforo "câmera conectada" no palco
9. testar uma rodada com o próprio celular ANTES do primeiro grupo
10. imprimir o QR do jogo (a tela do palco também mostra o dele)
```

O passo 4 não é opcional: `px_por_cm` e `y_chao` do `calibration.json` atual foram medidos
em outra câmera, em outra altura. Sem recalibrar na máquina da feira, a altura sai torta.
