/* ============================================================
   BARBEARIA KLEVER — agendar.js
   Responsável por:
   - Marcar horários passados (baseado na data selecionada)
   - Marcar horários ocupados (baseado no barbeiro + duração do serviço)
   - Marcar barbeiros ocupados (baseado no horário + duração do serviço)
   ============================================================ */

(function () {
  'use strict';

  /* ── Lê variáveis do servidor via data-attributes no HTML ─── */
  var form      = document.getElementById('form-agendamento');
  var HOJE      = form.dataset.hoje;
  var HORA_ATUAL = form.dataset.horaAtual;

  /* ── Utilidade: estado "limpo" de um hora-chip ────────────── */
  function chipEstaFixo(chip) {
    /* Retorna true se o chip está bloqueado por razão permanente
       (hora-passada), não deve ser reativado por outras funções */
    return chip.classList.contains('hora-passada');
  }

  /* ── Utilidade: gera slots de 30 min que um serviço ocupa ─── */
  function getSlotsServico(horarioStr, minutos) {
    var slots  = [];
    var partes = horarioStr.split(':');
    var base   = new Date(2000, 0, 1, parseInt(partes[0], 10), parseInt(partes[1], 10));
    var qtd    = Math.ceil(minutos / 30);
    for (var i = 0; i < qtd; i++) {
      var t = new Date(base.getTime() + i * 30 * 60000);
      slots.push(
        String(t.getHours()).padStart(2, '0') + ':' +
        String(t.getMinutes()).padStart(2, '0')
      );
    }
    return slots;
  }

  /* ── Retorna a data selecionada ou o primeiro dia disponível ─ */
  function getDataSelecionada() {
    var checked = document.querySelector('input[name="data"]:checked');
    if (checked) return checked.value;
    /* Fallback: primeiro dia da lista */
    var primeiro = document.querySelector('input[name="data"]');
    return primeiro ? primeiro.value : null;
  }

  /* ── Retorna os minutos do serviço selecionado ───────────────*/
  function getMinutosSelecionados() {
    var servicoSel = document.querySelector('input[name="servico"]:checked');
    return servicoSel ? parseInt(servicoSel.dataset.minutos || 30, 10) : 30;
  }

  /* ══════════════════════════════════════════════════════════
     1. HORÁRIOS PASSADOS
     Bloqueia horários anteriores à hora atual quando a data
     selecionada for hoje. Libera todos para datas futuras.
     ══════════════════════════════════════════════════════════ */
  function atualizarPassados() {
    var data = getDataSelecionada();
    var ehHoje = (data === HOJE);

    document.querySelectorAll('.hora-chip').forEach(function (chip) {
      var hora  = chip.dataset.hora;
      var input = chip.querySelector('input');
      var passou = ehHoje && (hora <= HORA_ATUAL);

      if (passou) {
        chip.classList.add('hora-passada');
        chip.classList.remove('hora-ocupada'); /* passada tem prioridade */
        input.disabled = true;
        input.checked  = false;
      } else {
        chip.classList.remove('hora-passada');
        /* Só reativa se não estiver marcado como ocupado */
        if (!chip.classList.contains('hora-ocupada')) {
          input.disabled = false;
        }
      }
    });
  }

  /* ══════════════════════════════════════════════════════════
     2. HORÁRIOS OCUPADOS
     Para o barbeiro selecionado, busca todos os slots já
     reservados e bloqueia os que conflitam com o serviço
     escolhido (considerando a duração).
     ══════════════════════════════════════════════════════════ */
  function atualizarHorariosOcupados() {
    var data        = getDataSelecionada();
    var barbeiroSel = document.querySelector('[id^="barbeiro-label-"] input:checked');
    var minutos     = getMinutosSelecionados();

    /* Remove bloqueios de ocupado, respeitando os passados */
    document.querySelectorAll('.hora-chip').forEach(function (chip) {
      if (chipEstaFixo(chip)) return; /* não mexe em hora-passada */
      chip.classList.remove('hora-ocupada');
      chip.querySelector('input').disabled = false;
    });

    /* Sem barbeiro selecionado não há nada a bloquear */
    if (!data || !barbeiroSel) return;

    fetch('/api/bloqueados?barbeiro_id=' + barbeiroSel.value + '&data=' + data)
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (bloqueados) {
        document.querySelectorAll('.hora-chip').forEach(function (chip) {
          if (chipEstaFixo(chip)) return; /* respeita hora-passada */

          var hora     = chip.dataset.hora;
          var input    = chip.querySelector('input');
          /* Verifica se algum slot que o serviço ocuparia já está tomado */
          var slots    = getSlotsServico(hora, minutos);
          var conflito = slots.some(function (s) {
            return bloqueados.indexOf(s) !== -1;
          });

          if (conflito) {
            chip.classList.add('hora-ocupada');
            input.disabled = true;
            input.checked  = false;
          }
        });
      })
      .catch(function (err) {
        console.error('[Barbearia] Erro ao buscar horários bloqueados:', err);
      });
  }

  /* ══════════════════════════════════════════════════════════
     3. BARBEIROS OCUPADOS
     Para o horário selecionado, verifica quais barbeiros já
     têm agendamento (considerando duração do serviço).
     ══════════════════════════════════════════════════════════ */
  function atualizarBarbeirosOcupados() {
    var data       = getDataSelecionada();
    var horarioSel = document.querySelector('input[name="horario"]:checked');
    var minutos    = getMinutosSelecionados();

    /* Restaura todos os barbeiros antes de recalcular */
    document.querySelectorAll('[id^="barbeiro-label-"]').forEach(function (label) {
      if (label.classList.contains('indisponivel')) return;
      label.classList.remove('ocupado');
      label.querySelector('input').disabled = false;
    });

    if (!data || !horarioSel) return;

    fetch('/api/ocupados_duracao?data=' + data +
          '&horario=' + horarioSel.value +
          '&minutos=' + minutos)
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (ocupados) {
        document.querySelectorAll('[id^="barbeiro-label-"]').forEach(function (label) {
          if (label.classList.contains('indisponivel')) return;
          var bid   = parseInt(label.id.replace('barbeiro-label-', ''), 10);
          var input = label.querySelector('input');

          if (ocupados.indexOf(bid) !== -1) {
            label.classList.add('ocupado');
            input.disabled = true;
            input.checked  = false;
          }
        });
      })
      .catch(function (err) {
        console.error('[Barbearia] Erro ao buscar barbeiros ocupados:', err);
      });
  }

  /* ══════════════════════════════════════════════════════════
     4. EVENT LISTENERS
     ══════════════════════════════════════════════════════════ */

  /* Ao mudar data */
  document.querySelectorAll('input[name="data"]').forEach(function (r) {
    r.addEventListener('change', function () {
      atualizarPassados();        /* 1º: marca passados */
      atualizarHorariosOcupados(); /* 2º: marca ocupados (respeita passados) */
      atualizarBarbeirosOcupados(); /* 3º: atualiza barbeiros */
    });
  });

  /* Ao clicar num horário */
  document.querySelectorAll('.hora-chip').forEach(function (chip) {
    chip.addEventListener('click', function () {
      /* Aguarda o radio ser marcado antes de consultar */
      setTimeout(atualizarBarbeirosOcupados, 80);
    });
  });

  /* Ao mudar serviço */
  document.querySelectorAll('input[name="servico"]').forEach(function (r) {
    r.addEventListener('change', function () {
      atualizarHorariosOcupados();
      atualizarBarbeirosOcupados();
    });
  });

  /* Ao mudar barbeiro */
  document.querySelectorAll('[id^="barbeiro-label-"] input').forEach(function (r) {
    r.addEventListener('change', function () {
      setTimeout(atualizarHorariosOcupados, 80);
    });
  });

  /* ══════════════════════════════════════════════════════════
     5. INICIALIZAÇÃO
     Roda ao carregar a página com o primeiro dia já selecionado
     ══════════════════════════════════════════════════════════ */
  var primeiroDia = document.querySelector('input[name="data"]');
  if (primeiroDia) {
    primeiroDia.checked = true; /* pré-seleciona o primeiro dia */
  }
  atualizarPassados(); /* marca passados imediatamente */

})();
