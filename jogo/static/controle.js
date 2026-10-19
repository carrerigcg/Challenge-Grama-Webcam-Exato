// Controle do celular. Guarda o próprio id no localStorage: o celular bloqueia
// a tela, o socket cai, e ao voltar o jogador precisa cair na mesma cadeira em
// vez de virar um fantasma na lista.
(function () {
  "use strict";

  var CHAVE_ID = "grama-jogo-id";
  var CHAVE_NOME = "grama-jogo-nome";
  var CHAVE_CHUTE = "grama-jogo-chute";
  var ESPERA_RECONEXAO_MS = 1500;

  var el = function (id) { return document.getElementById(id); };

  var TELAS = ["tela-entrada", "tela-chute", "tela-espera", "tela-resultado"];
  function mostrar(id) {
    TELAS.forEach(function (t) {
      el(t).classList.toggle("oculto", t !== id);
    });
  }

  function avisar(texto) {
    el("aviso").textContent = texto || "";
    el("aviso").classList.toggle("oculto", !texto);
  }

  function cm(valor) {
    // Última linha de defesa: se um reset esvaziar a sala entre o broadcast e
    // o render, `toFixed` em null derrubaria a tela na frente do grupo. A sala
    // já impede isso, mas uma tela quebrada numa apresentação não tem segunda
    // chance, e o custo aqui é uma linha.
    if (typeof valor !== "number" || !isFinite(valor)) { return "—"; }
    return valor.toFixed(1).replace(".", ",") + " cm";
  }

  // O id é a credencial que o servidor exige em `chutar` e `voltar`, e ele
  // chega só no frame `voce`. O nome é o que identifica a própria linha no
  // payload de broadcast, que não traz id de ninguém — senão qualquer
  // visitante com a aba Rede aberta chutaria em nome de outro.
  var meuId = localStorage.getItem(CHAVE_ID);
  var meuNome = localStorage.getItem(CHAVE_NOME);
  var meuChute = localStorage.getItem(CHAVE_CHUTE);
  // Chute digitado e ainda não confirmado pelo servidor. Não vai pro
  // localStorage antes da confirmação: o payload esconde o valor do chute de
  // propósito, então o celular não tem como verificar qual valor o servidor
  // guardou — e gravar antes mostrava "Chute enviado: 300,0 cm" para um chute
  // que foi recusado, confirmação falsa na frente do visitante.
  var chutePendente = null;
  var ws = null;

  function conectar() {
    var protocolo = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(protocolo + "//" + location.host + "/ws/jogador");

    ws.onopen = function () {
      avisar("");
      if (meuId) { ws.send(JSON.stringify({ cmd: "voltar", id: meuId })); }
    };

    ws.onmessage = function (evento) {
      var msg = JSON.parse(evento.data);
      if (msg.tipo === "voce") {
        meuId = msg.id;
        meuNome = msg.nome;
        localStorage.setItem(CHAVE_ID, meuId);
        localStorage.setItem(CHAVE_NOME, meuNome);
        el("meu-nome").textContent = msg.nome;
        mostrar("tela-chute");
        avisar("");
        return;
      }
      if (msg.tipo === "erro") {
        // O servidor recusou: o pendente não vira confirmação.
        chutePendente = null;
        avisar(msg.mensagem);
        return;
      }
      if (msg.tipo === "estado") { aplicarEstado(msg); }
    };

    // O celular dorme e o socket cai. 1,5s é curto o bastante para a pessoa não
    // perceber e longo o bastante para não martelar o servidor.
    ws.onclose = function () {
      avisar("Reconectando…");
      setTimeout(conectar, ESPERA_RECONEXAO_MS);
    };
  }

  function aplicarEstado(estado) {
    // Compara por nome: o payload não traz id. A sala garante nome único por
    // rodada, então isso identifica sem expor credencial.
    var souJogador = estado.jogadores.some(function (j) { return j.nome === meuNome; });

    if (!souJogador) {
      // Saiu da sala (nova rodada, por exemplo): limpa e volta pra entrada.
      localStorage.removeItem(CHAVE_ID);
      localStorage.removeItem(CHAVE_NOME);
      localStorage.removeItem(CHAVE_CHUTE);
      meuId = null;
      meuNome = null;
      meuChute = null;
      el("chute").value = "";
      el("confirmacao").classList.add("oculto");
      mostrar("tela-entrada");
      avisar(estado.aberta ? "" : "A sala está travada. Fale com o apresentador.");
      return;
    }

    if (estado.estado === "AGUARDANDO") {
      mostrar("tela-chute");
      var eu = null;
      estado.jogadores.forEach(function (j) {
        if (j.nome === meuNome) { eu = j; }
      });
      if (chutePendente !== null && eu && eu.chutou) {
        meuChute = chutePendente;
        chutePendente = null;
        localStorage.setItem(CHAVE_CHUTE, meuChute);
      }
      if (meuChute) {
        el("chute").value = meuChute;
        el("confirmacao").textContent =
          "Chute enviado: " + meuChute.replace(".", ",") +
          " cm — pode mudar até a medição.";
        el("confirmacao").classList.remove("oculto");
      }
      avisar(estado.erro || "");
      return;
    }

    if (estado.estado === "MEDINDO" || estado.estado === "REVELANDO") {
      el("texto-espera").textContent = "Olha pra tela grande!";
      mostrar("tela-espera");
      avisar("");
      return;
    }

    if (estado.estado === "RESULTADO") {
      var minha = null;
      estado.ranking.forEach(function (linha) {
        if (linha.nome === meuNome) { minha = linha; }
      });
      if (!minha) {
        el("texto-espera").textContent = "Você não chutou nessa rodada!";
        mostrar("tela-espera");
        return;
      }
      el("posicao").textContent = minha.posicao + "º lugar";
      el("meu-chute").textContent = cm(minha.chute_cm);
      el("valor-real").textContent = cm(estado.altura_cm);
      el("meu-erro").textContent = cm(minha.erro_cm);
      mostrar("tela-resultado");
    }
  }

  el("botao-entrar").onclick = function () {
    var nome = el("nome").value.trim();
    if (!nome) { avisar("Digite um nome."); return; }
    ws.send(JSON.stringify({ cmd: "entrar", nome: nome }));
  };

  el("botao-chutar").onclick = function () {
    // Vírgula é o separador que o teclado brasileiro oferece no celular.
    var valor = parseFloat(el("chute").value.replace(",", "."));
    if (isNaN(valor)) { avisar("Digite um número."); return; }
    chutePendente = valor.toFixed(1);
    ws.send(JSON.stringify({ cmd: "chutar", id: meuId, valor_cm: valor }));
  };

  conectar();
})();
