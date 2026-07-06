// ============================================
// SPA router: shows/hides <div class="view">
// sections based on the URL hash, e.g. #/login,
// #/dashboard. Plain in-page anchors like #contato
// or #demo (no leading slash) are left alone so
// the browser scrolls to them normally.
// ============================================
(function () {
  const views = document.querySelectorAll(".view");
  if (!views.length) return;

  const defaultView = document.body.dataset.defaultView || "home";

  const showView = (name) => {
    let found = false;
    views.forEach((view) => {
      const match = view.id === `view-${name}`;
      view.hidden = !match;
      if (match) found = true;
    });
    if (!found) {
      views.forEach((view) => {
        view.hidden = view.id !== `view-${defaultView}`;
      });
    }
    window.scrollTo(0, 0);
  };

  const route = () => {
    const hash = window.location.hash;
    if (!hash.startsWith("#/")) {
      if (hash === "" || hash === "#") showView(defaultView);
      return; // plain in-page anchor (#contato, #demo…) — let the browser handle it
    }
    const name = hash.slice(2) || defaultView;
    showView(name);
  };

  window.addEventListener("hashchange", route);
  route();
})();

// ============================================
// Scroll-triggered WhatsApp demo
// Each "track-step" acts as an invisible cue.
// When it crosses the center of the viewport,
// the matching chat bubble fades/slides in and
// the phone auto-scrolls to reveal it.
// ============================================
(function () {
  const chatBody = document.getElementById("chatBody");
  const statusEl = document.getElementById("chatStatus");
  const steps = document.querySelectorAll(".track-step");

  if (!steps.length) return;

  const revealMessage = (index) => {
    const msg = chatBody.querySelector(`.chat-msg[data-index="${index}"]`);
    if (!msg || msg.classList.contains("visible")) return;

    msg.classList.add("visible");

    // little "digitando..." beat before a bot reply lands
    if (msg.classList.contains("out") && statusEl) {
      statusEl.textContent = "digitando…";
      setTimeout(() => {
        statusEl.textContent = "online";
      }, 500);
    }

    chatBody.scrollTo({
      top: chatBody.scrollHeight,
      behavior: "smooth",
    });
  };

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          revealMessage(entry.target.dataset.target);
        }
      });
    },
    {
      root: null,
      // trigger when a step crosses the vertical center of the screen
      rootMargin: "-45% 0px -45% 0px",
      threshold: 0,
    }
  );

  steps.forEach((step) => observer.observe(step));
})();

// ============================================
// Contact form (front-end only, no backend)
// ============================================
(function () {
  const form = document.getElementById("contactForm");
  if (!form) return;

  const fields = document.getElementById("formFields");
  const success = document.getElementById("formSuccess");

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    fields.hidden = true;
    success.hidden = false;
  });
})();

// ============================================
// Login page (front-end only, no backend)
// ============================================
(function () {
  const form = document.getElementById("loginForm");
  if (!form) return;

  const senhaInput = document.getElementById("senhaInput");
  const toggleBtn = document.getElementById("togglePassword");

  if (toggleBtn && senhaInput) {
    toggleBtn.addEventListener("click", () => {
      const isPassword = senhaInput.type === "password";
      senhaInput.type = isPassword ? "text" : "password";
      toggleBtn.textContent = isPassword ? "ocultar" : "ver";
    });
  }

  const fields = document.getElementById("loginFields");
  const loading = document.getElementById("loginLoading");

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    fields.hidden = true;
    loading.hidden = false;

    // simulação de autenticação — sem backend real ainda
    setTimeout(() => {
      window.location.href = "dashboard.html";
    }, 1200);
  });
})();

// ============================================
// Dashboard: mobile sidebar toggle
// (runs for every dashboard-style view: dashboard,
// conversas, agendamentos, relatorios, configuracoes)
// ============================================
(function () {
  document.querySelectorAll(".dash-menu-toggle").forEach((toggle) => {
    const view = toggle.closest(".view") || document;
    const sidebar = view.querySelector(".dash-sidebar");
    if (!sidebar) return;

    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      sidebar.classList.toggle("open");
    });
  });

  document.addEventListener("click", (e) => {
    document.querySelectorAll(".dash-sidebar.open").forEach((sidebar) => {
      const view = sidebar.closest(".view") || document;
      const toggle = view.querySelector(".dash-menu-toggle");
      if (!sidebar.contains(e.target) && !(toggle && toggle.contains(e.target))) {
        sidebar.classList.remove("open");
      }
    });
  });
})();

// ============================================
// Conversas: switch thread when picking a contact
// ============================================
(function () {
  const list = document.getElementById("convoList");
  const threadBody = document.getElementById("threadBody");
  if (!list || !threadBody) return;

  const threads = {
    mariana: {
      name: "Mariana Jorge",
      initials: "MJ",
      status: "Respondido pela IA",
      messages: [
        { from: "in", text: "Oi! Vocês abrem amanhã?", time: "23:47" },
        { from: "out", text: "Oi! 👋 Estamos fechados agora, mas já te ajudo!", time: "23:47" },
        { from: "out", text: "Amanhã abrimos às 9h. Quer agendar um horário?", time: "23:47" },
        { from: "in", text: "Quero sim! Tem de manhã?", time: "23:48" },
        { from: "out", text: "Tenho 9h30 disponível amanhã. Fechado?", time: "23:48" },
        { from: "in", text: "9h30 amanhã tá ótimo, obrigada!", time: "23:49" },
      ],
    },
    rafael: {
      name: "Rafael Souza",
      initials: "RS",
      status: "Respondido pela IA",
      messages: [
        { from: "in", text: "Boa noite, qual o valor da limpeza de pele?", time: "22:12" },
        { from: "out", text: "Boa noite! A limpeza de pele profunda sai por R$150.", time: "22:13" },
        { from: "in", text: "Qual o valor da limpeza de pele?", time: "22:14" },
      ],
    },
    carla: {
      name: "Carla Prado",
      initials: "CP",
      status: "Aguardando resposta humana",
      messages: [
        { from: "in", text: "Oi, preciso remarcar minha consulta de sexta", time: "21:00" },
        { from: "out", text: "Claro! Deixa eu verificar a agenda com a equipe.", time: "21:01" },
        { from: "in", text: "Preciso remarcar minha consulta de sexta", time: "21:02" },
      ],
    },
    lucas: {
      name: "Lucas Tavares",
      initials: "LT",
      status: "Respondido pela IA",
      messages: [
        { from: "out", text: "Lucas, seu retorno ficou para sábado às 11h, ok?", time: "19:38" },
        { from: "in", text: "Perfeito, até sábado então 👍", time: "19:40" },
      ],
    },
    fernanda: {
      name: "Fernanda Alves",
      initials: "FA",
      status: "Aguardando resposta humana",
      messages: [
        { from: "in", text: "Oi, vocês atendem convênio?", time: "18:55" },
        { from: "out", text: "Vou confirmar isso com a equipe e já te retorno!", time: "18:57" },
      ],
    },
    bruno: {
      name: "Bruno Melo",
      initials: "BM",
      status: "Aguardando resposta humana",
      messages: [
        { from: "in", text: "Ainda dá pra agendar pra hoje?", time: "17:22" },
      ],
    },
  };

  const threadName = document.getElementById("threadName");
  const threadAvatar = document.getElementById("threadAvatar");
  const threadStatus = document.getElementById("threadStatus");

  const renderThread = (id) => {
    const data = threads[id];
    if (!data) return;

    threadName.textContent = data.name;
    threadAvatar.textContent = data.initials;
    threadStatus.textContent = data.status;

    threadBody.innerHTML = "";
    data.messages.forEach((msg) => {
      const bubble = document.createElement("div");
      bubble.className = `chat-msg ${msg.from}`;
      bubble.innerHTML = `<p>${msg.text}</p><time>${msg.time}</time>`;
      threadBody.appendChild(bubble);
    });
  };

  list.querySelectorAll("li").forEach((item) => {
    item.addEventListener("click", () => {
      list.querySelectorAll("li").forEach((li) => li.classList.remove("active"));
      item.classList.add("active");
      renderThread(item.dataset.id);
    });
  });

  renderThread("mariana");
})();

// ============================================
// Agendamentos: filter tabs (visual grouping)
// ============================================
(function () {
  const tabs = document.getElementById("agendaTabs");
  if (!tabs) return;

  const groups = document.querySelectorAll(".agenda-group");

  tabs.querySelectorAll(".agenda-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.querySelectorAll(".agenda-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");

      const filter = tab.dataset.filter;
      groups.forEach((group) => {
        group.style.display =
          filter === "todos" || group.dataset.day === filter ? "" : "none";
      });
    });
  });
})();

// ============================================
// Configurações: fake save
// ============================================
(function () {
  const form = document.getElementById("settingsForm");
  const success = document.getElementById("settingsSuccess");
  if (!form || !success) return;

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    success.hidden = false;
    setTimeout(() => {
      success.hidden = true;
    }, 2500);
  });
})();
