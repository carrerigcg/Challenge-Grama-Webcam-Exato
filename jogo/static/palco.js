// Palco: a tela que o grupo olha junto. Só reage ao estado que o servidor
// transmite — não guarda jogo nenhum.
(function () {
  "use strict";

  var DURACAO_CONTADOR_MS = 2200;
  var MAX_CADEIRAS = 5;
  var ESCALA_LAMINA_CM = 30;   // 30 cm enche a lâmina; acima disso ela satura
  var INTERVALO_PODIO_MS = 300;
  var ESPERA_RECONEXAO_MS = 1500;

  var el = function (id) { return document.getElementById(id); };
  var token = new URLSearchParams(location.search).get("token") || "";
  var ws = null;
  var estadoAnterior = null;

  // A URL em texto ao lado do QR é a defesa contra QR errado: sem
  // JOGO_URL_PUBLICA definida, o servidor monta o QR com o que o proxy
  // disser, e isso pode apontar para um endereço interno. Com o texto à
  // vista, o apresentador percebe antes do primeiro grupo escanear.
  el("url-do-jogo").textContent = location.origin + "/";
  // NÃO tire o token da barra de endereço com `history.replaceState`: ele
  // precisa estar na URL para o `GET /host` passar, e sem ele o F5 leva 403 —
  // a página nem carrega, e o `sessionStorage` não salva, porque o servidor
  // recusa antes de qualquer JS rodar. O F5 do palco está na tabela de falhas
  // do spec como cenário suportado. A exposição do token já está coberta pelo
  // `Referrer-Policy: no-referrer` da resposta e pelo F11 do roteiro de
  // montagem, que esconde a barra de endereço.

  var CENAS = ["cena-aguardando", "cena-medindo", "cena-revelando", "cena-resultado"];
  function cena(id) {
    CENAS.forEach(function (c) { el(c).classList.toggle("oculto", c !== id); });
  }

  function cm(valor) {
    // Última linha de defesa: se um reset esvaziar a sala entre o broadcast e
    // o render, `toFixed` em null derrubaria a tela na frente do grupo. A sala
    // já impede isso, mas uma tela quebrada numa apresentação não tem segunda
    // chance, e o custo aqui é uma linha.
    if (typeof valor !== "number" || !isFinite(valor)) { return "—"; }
    return valor.toFixed(1).replace(".", ",") + " cm";
  }

  function conectar() {
    var protocolo = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(
      protocolo + "//" + location.host + "/ws/host?token=" + encodeURIComponent(token)
    );
    ws.onmessage = function (evento) {
      var msg = JSON.parse(evento.data);
      if (msg.tipo === "erro") { el("aviso-host").textContent = msg.mensagem; return; }
      if (msg.tipo === "estado") { aplicar(msg); }
    };
    ws.onclose = function () {
      el("aviso-host").textContent = "Conexão caiu. Reconectando…";
      // Mata os botoes junto com o socket, pelo mesmo motivo de cima.
      el("botao-medir").disabled = true;
      el("botao-travar").disabled = true;
      el("botao-nova").disabled = true;
      setTimeout(conectar, ESPERA_RECONEXAO_MS);
    };
  }

  function aplicar(estado) {
    el("semaforo").textContent = estado.ponte_conectada
      ? "● câmera conectada" : "○ câmera offline";
    el("semaforo").classList.toggle("ligado", estado.ponte_conectada);

    // Os tres botoes nascem `disabled` no HTML e voltam a morrer no `onclose`.
    // Botao vivo com socket morto engole o clique: `ws.send` num socket que
    // ainda esta CONNECTING estoura `InvalidStateError` e o host fica clicando
    // em MEDIR na frente do grupo sem nada acontecer.
    el("botao-travar").disabled = false;
    el("botao-nova").disabled = false;

    el("botao-travar").textContent = estado.aberta ? "Travar sala" : "Abrir sala";
    el("contagem-chutes").textContent =
      estado.quantos_chutaram + "/" + estado.jogadores.length + " chutaram";

    el("botao-medir").disabled = !(
      estado.estado === "AGUARDANDO" &&
      estado.ponte_conectada &&
      estado.quantos_chutaram > 0
    );

    // Motivo escrito na tela: sem isso você clica em MEDIR com a ponte caída e
    // fica esperando um fantasma na frente do grupo.
    if (estado.erro) {
      el("aviso-host").textContent = estado.erro;
    } else if (!estado.ponte_conectada) {
      el("aviso-host").textContent = "A ponte da câmera não está conectada.";
    } else if (estado.estado === "AGUARDANDO" && estado.quantos_chutaram === 0) {
      el("aviso-host").textContent = "Ninguém chutou ainda.";
    } else {
      el("aviso-host").textContent = "";
    }

    desenharCadeiras(estado);

    var mudouDeEstado = !estadoAnterior || estadoAnterior.estado !== estado.estado;

    if (estado.estado === "AGUARDANDO") {
      cena("cena-aguardando");
    } else if (estado.estado === "MEDINDO") {
      cena("cena-medindo");
    } else if (estado.estado === "REVELANDO") {
      // Só reanima na transição: um broadcast extra não pode reiniciar a
      // contagem no meio.
      if (mudouDeEstado) { cena("cena-revelando"); animarContador(estado.altura_cm); }
    } else if (estado.estado === "RESULTADO") {
      if (mudouDeEstado) { cena("cena-resultado"); montarPodio(estado); }
    }

    estadoAnterior = estado;
  }

  function desenharCadeiras(estado) {
    var lista = el("cadeiras");
    lista.innerHTML = "";
    for (var i = 0; i < MAX_CADEIRAS; i++) {
      var jogador = estado.jogadores[i];
      var li = document.createElement("li");
      if (jogador) {
        li.className = "ocupada";
        var nome = document.createElement("span");
        nome.textContent = (i + 1) + "  " + jogador.nome;
        var marca = document.createElement("span");
        marca.className = "marca-chute";
        // Só "chutou", nunca o valor: todos olham esta tela.
        marca.textContent = jogador.chutou ? "✓ chutou" : "… pensando";
        li.appendChild(nome);
        li.appendChild(marca);
      } else {
        li.className = "vazia";
        li.textContent = (i + 1) + "  vaga livre";
      }
      lista.appendChild(li);
    }
  }

  function animarContador(alvoCm) {
    // requestAnimationFrame e não CSS: o TEXTO muda a cada frame, não só o
    // estilo. O ease-out desacelera no fim, onde mora o suspense.
    var inicio = null;
    var lamina = el("lamina");
    var contador = el("contador");

    function passo(agora) {
      if (inicio === null) { inicio = agora; }
      var t = Math.min((agora - inicio) / DURACAO_CONTADOR_MS, 1);
      var suave = 1 - Math.pow(1 - t, 3);
      var valor = alvoCm * suave;
      contador.textContent = cm(valor);
      lamina.style.height = Math.min(valor / ESCALA_LAMINA_CM, 1) * 100 + "%";
      if (t < 1) { requestAnimationFrame(passo); }
    }

    contador.textContent = cm(0);
    lamina.style.height = "0%";
    requestAnimationFrame(passo);
  }

  function montarPodio(estado) {
    el("valor-final").textContent = estado.margem_cm
      ? cm(estado.altura_cm) + "  ±" + cm(estado.margem_cm)
      : cm(estado.altura_cm);

    var podio = el("podio");
    podio.innerHTML = "";

    // Campeão primeiro, premiando o vencedor no pico da atenção. O intervalo
    // entre as entradas dá tempo da plateia ler cada nome.
    estado.ranking.slice(0, 3).forEach(function (linha, indice) {
      var li = document.createElement("li");
      if (indice === 0) { li.className = "campeao"; }

      var pos = document.createElement("span");
      pos.className = "pos";
      pos.textContent = linha.posicao + "º";

      var nome = document.createElement("span");
      nome.className = "nome";
      nome.textContent = linha.nome;

      var erro = document.createElement("span");
      erro.className = "erro";
      erro.textContent = "chutou " + cm(linha.chute_cm) +
        " · errou por " + cm(linha.erro_cm);

      li.appendChild(pos);
      li.appendChild(nome);
      li.appendChild(erro);
      podio.appendChild(li);

      setTimeout(function () { li.classList.add("entrou"); },
                 indice * INTERVALO_PODIO_MS);
    });

    var imagem = el("imagem-anotada");
    if (estado.imagem_b64) {
      imagem.src = "data:image/png;base64," + estado.imagem_b64;
      imagem.classList.remove("oculto");
    } else {
      imagem.classList.add("oculto");
    }
  }

  el("botao-medir").onclick = function () {
    ws.send(JSON.stringify({ cmd: "medir" }));
  };

  el("botao-nova").onclick = function () {
    ws.send(JSON.stringify({ cmd: "nova_rodada" }));
  };

  el("botao-travar").onclick = function () {
    ws.send(JSON.stringify({
      cmd: "travar",
      travada: el("botao-travar").textContent === "Travar sala",
    }));
  };

  conectar();
})();
