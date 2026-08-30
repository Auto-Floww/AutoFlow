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

// CSP-safe fallback: reveal the page if the Three.js intro cannot finish.
window.setTimeout(() => {
  if (window.__autoflowIntroDone) return;

  document.body.classList.remove("intro-pending");
  document.getElementById("intro-canvas")?.remove();
}, 4500);

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
// Auth pages: login and account creation
// ============================================
(function () {
  const loginForm = document.getElementById("loginForm");
  const registerForm = document.getElementById("registerForm");
  if (!loginForm || !registerForm) return;

  const authTitle = document.getElementById("authTitle");
  const authSub = document.getElementById("authSub");
  const authMessage = document.getElementById("authMessage");
  const authFooterText = document.getElementById("authFooterText");
  const tabs = document.querySelectorAll("[data-auth-mode]");

  const copy = {
    login: {
      title: "Bem-vindo de volta.",
      sub: "Entre para acompanhar os atendimentos automáticos da sua empresa.",
      footer: 'Não tem conta ainda? <a href="#" class="auth-link" data-auth-mode="register">Criar conta</a>',
      showcaseLabel: "Atendimento inteligente no WhatsApp",
      showcaseTitle: "Seu atendimento continua. Suas vendas também.",
      showcaseSub: "O AutoFlow responde, consulta os dados da empresa e conduz cada cliente para o próximo passo.",
    },
    register: {
      title: "Criar conta.",
      sub: "Cadastre sua empresa para acessar o painel do AutoFlow.",
      footer: 'Já tem conta? <a href="#" class="auth-link" data-auth-mode="login">Entrar</a>',
      showcaseLabel: "Comece com o AutoFlow",
      showcaseTitle: "Prepare sua empresa para atender melhor.",
      showcaseSub: "Crie sua conta, cadastre as informações da operação e deixe a IA pronta para conversar com seus clientes.",
    },
  };

  const authShowcaseLabel = document.getElementById("authShowcaseLabel");
  const authShowcaseTitle = document.getElementById("authShowcaseTitle");
  const authShowcaseSub = document.getElementById("authShowcaseSub");

  const showMessage = (message, type = "error") => {
    authMessage.textContent = message;
    authMessage.classList.toggle("success", type === "success");
    authMessage.hidden = false;
  };

  const clearMessage = () => {
    authMessage.textContent = "";
    authMessage.classList.remove("success");
    authMessage.hidden = true;
  };

  const setMode = (mode) => {
    const isRegister = mode === "register";
    document.body.classList.toggle("auth-register-mode", isRegister);
    loginForm.hidden = isRegister;
    registerForm.hidden = !isRegister;
    authTitle.textContent = copy[mode].title;
    authSub.textContent = copy[mode].sub;
    authFooterText.innerHTML = copy[mode].footer;
    if (authShowcaseLabel) authShowcaseLabel.textContent = copy[mode].showcaseLabel;
    if (authShowcaseTitle) authShowcaseTitle.textContent = copy[mode].showcaseTitle;
    if (authShowcaseSub) authShowcaseSub.textContent = copy[mode].showcaseSub;
    tabs.forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.authMode === mode);
    });
    clearMessage();
  };

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-auth-mode]");
    if (!trigger) return;
    event.preventDefault();
    setMode(trigger.dataset.authMode);
  });

  const bindPasswordToggle = (buttonId, inputId) => {
    const input = document.getElementById(inputId);
    const button = document.getElementById(buttonId);
    if (!button || !input) return;

    button.addEventListener("click", () => {
      const isPassword = input.type === "password";
      input.type = isPassword ? "text" : "password";
      button.classList.toggle("is-visible", isPassword);
    });
  };

  const requestJson = async (url, payload) => {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(data.message || "Não foi possível completar a operação.");
    }

    return data;
  };

  const setSubmitting = (form, submitting) => {
    const submit = form.querySelector(".auth-submit");
    if (!submit) return;

    if (!submit.dataset.label) {
      submit.dataset.label = submit.textContent;
    }

    submit.disabled = submitting;
    submit.textContent = submitting ? "Aguarde..." : submit.dataset.label;
  };

  bindPasswordToggle("togglePassword", "senhaInput");
  bindPasswordToggle("toggleRegisterPassword", "registerSenhaInput");
  bindPasswordToggle("toggleConfirmarPassword", "confirmarSenhaInput");

  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearMessage();
    setSubmitting(loginForm, true);

    const formData = new FormData(loginForm);

    try {
      await requestJson("/api/login", {
        email: formData.get("email"),
        senha: formData.get("senha"),
        lembrar: formData.get("lembrar") === "on",
      });
      window.location.href = "dashboard.html";
    } catch (error) {
      showMessage(error.message);
    } finally {
      setSubmitting(loginForm, false);
    }
  });

  registerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearMessage();

    const formData = new FormData(registerForm);
    const senha = String(formData.get("senha") || "");
    const confirmarSenha = String(formData.get("confirmarSenha") || "");

    if (senha !== confirmarSenha) {
      showMessage("As senhas precisam ser iguais.");
      return;
    }

    setSubmitting(registerForm, true);

    try {
      await requestJson("/api/register", {
        nome: formData.get("nome"),
        empresa: formData.get("empresa"),
        email: formData.get("email"),
        senha,
      });
      window.location.href = "dashboard.html";
    } catch (error) {
      showMessage(error.message);
    } finally {
      setSubmitting(registerForm, false);
    }
  });
})();

// ============================================
// Dashboard session guard and logout
// ============================================
(function () {
  if (!document.body.dataset.defaultView) return;

  const initialsFromName = (name) =>
    String(name || "AF")
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part[0])
      .join("")
      .toUpperCase();

  const applyUser = (user) => {
    const displayName = user.empresa || user.nome || "AutoFlow";
    document.querySelectorAll(".dash-avatar").forEach((avatar) => {
      avatar.textContent = initialsFromName(displayName);
    });

    const firstTitle = document.querySelector("#view-dashboard .dash-topbar h1");
    if (firstTitle) {
      firstTitle.textContent = `Olá, ${displayName}`;
    }
  };

  fetch("/api/me", { credentials: "same-origin" })
    .then(async (response) => {
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.message || "Sessão expirada.");
      applyUser(data.user);
    })
    .catch(() => {
      window.location.href = "login.html";
    });

  document.querySelectorAll(".dash-logout").forEach((link) => {
    link.addEventListener("click", async (event) => {
      event.preventDefault();

      try {
        await fetch("/api/logout", {
          method: "POST",
          credentials: "same-origin",
        });
      } finally {
        window.location.href = "login.html";
      }
    });
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
