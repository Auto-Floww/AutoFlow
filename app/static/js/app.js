(() => {
  "use strict";

  const doc = document;
  const $ = (selector, root = doc) => root.querySelector(selector);
  const $$ = (selector, root = doc) => Array.from(root.querySelectorAll(selector));
  const csrfToken = () => $("meta[name='csrf-token']")?.content || $("input[name='csrf_token']")?.value || "";
  const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
  const debounce = (fn, delay = 300) => {
    let timer;
    return (...args) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => fn(...args), delay);
    };
  };

  const refreshIcons = (root = doc) => {
    if (window.lucide?.createIcons) window.lucide.createIcons({ attrs: { "aria-hidden": "true" }, root });
  };

  const parseJSON = (value, fallback = {}) => {
    if (!value) return fallback;
    try { return JSON.parse(value); } catch (_) { return fallback; }
  };

  const responsePayload = async (response) => {
    const type = response.headers.get("content-type") || "";
    if (type.includes("application/json")) return response.json();
    return { ok: response.ok, message: response.ok ? "Alterações salvas." : "Não foi possível concluir a ação." };
  };

  const apiFetch = async (url, options = {}) => {
    const headers = new Headers(options.headers || {});
    headers.set("X-Requested-With", "XMLHttpRequest");
    const token = csrfToken();
    if (token) headers.set("X-CSRFToken", token);
    if (options.body && !(options.body instanceof FormData) && typeof options.body !== "string") {
      headers.set("Content-Type", "application/json");
      options.body = JSON.stringify(options.body);
    }
    const response = await fetch(url, { credentials: "same-origin", ...options, headers });
    const payload = await responsePayload(response);
    if (!response.ok) {
      const error = new Error(payload.message || payload.error || `Erro ${response.status}`);
      error.response = response;
      error.payload = payload;
      throw error;
    }
    return payload;
  };

  const toast = (message, type = "success", title = "") => {
    const region = $("[data-toast-region]");
    if (!region || !message) return;
    const labels = { success: "Tudo certo", error: "Algo deu errado", warning: "Atenção", info: "Informação" };
    const icons = { success: "circle-check", error: "circle-x", warning: "triangle-alert", info: "info" };
    const node = doc.createElement("div");
    node.className = `toast toast-${type}`;
    node.setAttribute("role", type === "error" ? "alert" : "status");
    const iconWrap = doc.createElement("span");
    iconWrap.className = "toast-icon";
    const icon = doc.createElement("i");
    icon.dataset.lucide = icons[type] || icons.info;
    iconWrap.append(icon);
    const copy = doc.createElement("span");
    copy.className = "toast-copy";
    const strong = doc.createElement("strong");
    strong.textContent = title || labels[type] || labels.info;
    const small = doc.createElement("small");
    small.textContent = message;
    copy.append(strong, small);
    const close = doc.createElement("button");
    close.type = "button";
    close.setAttribute("aria-label", "Fechar notificação");
    const closeIcon = doc.createElement("i");
    closeIcon.dataset.lucide = "x";
    close.append(closeIcon);
    node.append(iconWrap, copy, close);
    region.append(node);
    refreshIcons(node);
    const remove = () => {
      node.classList.add("is-leaving");
      window.setTimeout(() => node.remove(), reduceMotion ? 0 : 220);
    };
    close.addEventListener("click", remove);
    window.setTimeout(remove, type === "error" ? 6500 : 4300);
  };

  window.AutoFlow = { apiFetch, toast, refreshIcons };

  const setLoading = (button, loading) => {
    if (!button) return;
    button.classList.toggle("is-loading", loading);
    button.disabled = loading;
    button.setAttribute("aria-busy", String(loading));
  };

  const closeDropdowns = (except = null) => {
    $$('[data-dropdown]:not([hidden])').forEach((menu) => {
      if (menu === except) return;
      menu.hidden = true;
      const trigger = $(`[data-dropdown-trigger="${CSS.escape(menu.dataset.dropdown)}"]`);
      trigger?.setAttribute("aria-expanded", "false");
    });
  };

  const initDropdowns = () => {
    doc.addEventListener("click", (event) => {
      const trigger = event.target.closest("[data-dropdown-trigger]");
      if (trigger) {
        event.preventDefault();
        event.stopPropagation();
        const menu = $(`[data-dropdown="${CSS.escape(trigger.dataset.dropdownTrigger)}"]`);
        if (!menu) return;
        const willOpen = menu.hidden;
        closeDropdowns(menu);
        menu.hidden = !willOpen;
        trigger.setAttribute("aria-expanded", String(willOpen));
        return;
      }
      if (!event.target.closest("[data-dropdown]")) closeDropdowns();
    });
    doc.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeDropdowns();
    });
  };

  let activeModal = null;
  let modalOpener = null;
  const fillEntityForm = (modal, data, entity) => {
    const form = modal.querySelector(`[data-entity-form="${entity}"]`);
    if (!form) return;
    form.reset();
    Object.entries(data || {}).forEach(([key, value]) => {
      const field = form.elements.namedItem(key) || (key === "company" ? form.elements.namedItem("organization") : null);
      if (!field) return;
      if (field.type === "checkbox") field.checked = Boolean(value);
      else field.value = value ?? "";
    });
    const title = $("[data-create-title][data-edit-title]", modal);
    if (title) title.textContent = data?.id ? title.dataset.editTitle : title.dataset.createTitle;
    if (data?.id) {
      const base = (form.dataset.baseAction || form.getAttribute("action") || "").replace(/\/$/, "");
      form.action = `${base}/${encodeURIComponent(data.id)}`;
    } else if (form.dataset.baseAction) {
      form.action = form.dataset.baseAction;
    }
  };

  const openModal = (id, opener = null) => {
    const modal = doc.getElementById(id);
    if (!modal) return;
    modalOpener = opener || doc.activeElement;
    activeModal = modal;
    modal.hidden = false;
    doc.body.classList.add("has-modal");
    const form = $("form", modal);
    if (form && !form.dataset.baseAction) form.dataset.baseAction = form.getAttribute("action") || "";
    window.requestAnimationFrame(() => {
      const focusable = $("input:not([type='hidden']):not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])", modal);
      focusable?.focus({ preventScroll: true });
    });
  };

  const closeModal = (modal = activeModal) => {
    if (!modal) return;
    modal.hidden = true;
    doc.body.classList.remove("has-modal");
    activeModal = null;
    modalOpener?.focus?.({ preventScroll: true });
    modalOpener = null;
  };

  const initModals = () => {
    doc.addEventListener("click", (event) => {
      const opener = event.target.closest("[data-modal-open]");
      if (opener) {
        event.preventDefault();
        const modal = doc.getElementById(opener.dataset.modalOpen);
        if (!modal) return;
        $$("form", modal).forEach((form) => { if (!form.dataset.baseAction) form.dataset.baseAction = form.getAttribute("action") || ""; });
        const dataMap = [
          ["editCustomer", "customer"], ["editProduct", "product"], ["editDelivery", "delivery"],
          ["editFaq", "faq"], ["movementItem", "movement"]
        ];
        let editing = false;
        dataMap.forEach(([key, entity]) => {
          if (!opener.dataset[key]) return;
          editing = true;
          const data = parseJSON(opener.dataset[key], {});
          if (entity === "movement") {
            const select = $("select[name='inventory_id']", modal);
            if (select) {
              select.value = data.inventory_id ?? "";
              select.dispatchEvent(new Event("change", { bubbles: true }));
            }
          } else fillEntityForm(modal, data, entity);
        });
        const entityForm = $("[data-entity-form]", modal);
        if (entityForm && !editing) fillEntityForm(modal, {}, entityForm.dataset.entityForm);
        if (opener.dataset.defaultStage) {
          const stage = $("[data-opportunity-stage]", modal);
          if (stage) stage.value = opener.dataset.defaultStage;
        }
        openModal(opener.dataset.modalOpen, opener);
        return;
      }
      const closer = event.target.closest("[data-modal-close]");
      if (closer) {
        event.preventDefault();
        closeModal(closer.closest("[data-modal]") || activeModal);
      }
    });
    doc.addEventListener("keydown", (event) => {
      if (!activeModal) return;
      if (event.key === "Escape") closeModal();
      if (event.key !== "Tab") return;
      const focusable = $$("a[href], button:not([disabled]), input:not([disabled]):not([type='hidden']), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])", activeModal).filter((node) => node.offsetParent !== null);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && doc.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && doc.activeElement === last) { event.preventDefault(); first.focus(); }
    });
  };

  const initSidebar = () => {
    const sidebar = $("#sidebar");
    if (!sidebar) return;
    const open = () => { doc.body.classList.add("sidebar-open"); sidebar.setAttribute("aria-hidden", "false"); };
    const close = () => { doc.body.classList.remove("sidebar-open"); if (window.innerWidth < 1024) sidebar.setAttribute("aria-hidden", "true"); };
    $$('[data-sidebar-open]').forEach((button) => button.addEventListener("click", open));
    $$('[data-sidebar-close]').forEach((button) => button.addEventListener("click", close));
    if (window.innerWidth < 1024) sidebar.setAttribute("aria-hidden", "true");
    else sidebar.removeAttribute("aria-hidden");
    window.addEventListener("resize", debounce(() => {
      if (window.innerWidth >= 1024) { doc.body.classList.remove("sidebar-open"); sidebar.removeAttribute("aria-hidden"); }
      else sidebar.setAttribute("aria-hidden", String(!doc.body.classList.contains("sidebar-open")));
    }, 120));
  };

  const initCommandPalette = () => {
    const palette = $("[data-command-palette]");
    if (!palette) return;
    const input = $("[data-command-input]", palette);
    const open = () => { palette.hidden = false; doc.body.classList.add("has-modal"); window.setTimeout(() => input?.focus(), 0); };
    const close = () => { palette.hidden = true; doc.body.classList.remove("has-modal"); };
    $("[data-command-search]")?.addEventListener("focus", (event) => { event.target.blur(); open(); });
    $$('[data-command-close]', palette).forEach((button) => button.addEventListener("click", close));
    doc.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); palette.hidden ? open() : close(); }
      if (event.key === "Escape" && !palette.hidden) close();
    });
    input?.addEventListener("input", () => {
      const term = input.value.trim().toLocaleLowerCase("pt-BR");
      $$(".command-results a", palette).forEach((item) => { item.hidden = Boolean(term) && !item.textContent.toLocaleLowerCase("pt-BR").includes(term); });
    });
  };

  const initPasswordFields = () => {
    $$('[data-password-toggle]').forEach((button) => button.addEventListener("click", () => {
      const input = $("input", button.closest(".input-with-icon, .secret-input"));
      if (!input) return;
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      button.setAttribute("aria-label", show ? "Ocultar senha" : "Mostrar senha");
      button.innerHTML = `<i data-lucide="${show ? "eye-off" : "eye"}"></i>`;
      refreshIcons(button);
    }));
    $$('[data-password-strength]').forEach((input) => {
      const meter = input.closest(".field")?.querySelector(".password-meter");
      const hint = input.closest(".field")?.querySelector("[data-password-hint]");
      const update = () => {
        const value = input.value;
        let score = 0;
        if (value.length >= 8) score += 1;
        if (/[a-z]/.test(value) && /[A-Z]/.test(value)) score += 1;
        if (/\d/.test(value)) score += 1;
        if (/[^\w\s]/.test(value) && value.length >= 10) score += 1;
        if (meter) meter.dataset.strength = String(score);
        if (hint && value) hint.textContent = ["Muito curta", "Senha fraca", "Senha razoável", "Senha boa", "Senha forte"][score];
      };
      input.addEventListener("input", update);
    });
    $$('[data-password-form]').forEach((form) => form.addEventListener("submit", (event) => {
      const password = $("input[name='password']", form);
      const confirmation = $("input[name='confirm_password'], input[name='password_confirm']", form);
      if (!password || !confirmation || password.value === confirmation.value) return;
      event.preventDefault();
      confirmation.setCustomValidity("As senhas não coincidem.");
      confirmation.reportValidity();
      confirmation.addEventListener("input", () => confirmation.setCustomValidity(""), { once: true });
    }));
  };

  const initMasks = () => {
    const digits = (value) => value.replace(/\D/g, "");
    $$('[data-phone]').forEach((input) => input.addEventListener("input", () => {
      const value = digits(input.value).slice(0, 11);
      input.value = value.length <= 10 ? value.replace(/^(\d{0,2})(\d{0,4})(\d{0,4})$/, (_, a, b, c) => `${a ? `(${a}${a.length === 2 ? ") " : ""}` : ""}${b}${c ? `-${c}` : ""}`) : value.replace(/^(\d{2})(\d{5})(\d{0,4})$/, "($1) $2-$3");
    }));
    $$('[data-zip]').forEach((input) => input.addEventListener("input", () => {
      const value = digits(input.value).slice(0, 8);
      input.value = value.replace(/^(\d{0,5})(\d{0,3})$/, (_, a, b) => b ? `${a}-${b}` : a);
    }));
    $$('[data-currency]').forEach((input) => input.addEventListener("blur", () => {
      const raw = input.value.trim().replace(/\s/g, "").replace(/\./g, "").replace(",", ".").replace(/[^\d.-]/g, "");
      if (!raw) return;
      const value = Number(raw);
      if (Number.isFinite(value)) input.value = value.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }));
  };

  const initCounters = () => {
    $$("textarea[maxlength]").forEach((textarea) => {
      const field = textarea.closest(".field");
      if (!field) return;
      const output = $("[data-char-count]", field);
      if (!output) return;
      const update = () => { output.textContent = String(textarea.value.length); };
      textarea.addEventListener("input", update); update();
    });
  };

  const applyFilters = (list) => {
    const listId = list.id;
    const search = listId ? $(`[data-filter-input="${CSS.escape(listId)}"]`) : null;
    const term = search?.value.trim().toLocaleLowerCase("pt-BR") || "";
    const filters = listId ? $$(`[data-table-filter]`).filter((select) => select.closest("section, .card, .modal")?.querySelector(`#${CSS.escape(listId)}`) || list.closest("section, .card, .modal")?.contains(select)) : [];
    let visible = 0;
    $$('[data-filter-item]', list).forEach((item) => {
      const matchesSearch = !term || (item.dataset.search || item.textContent).toLocaleLowerCase("pt-BR").includes(term);
      const matchesFilters = filters.every((select) => !select.value || (item.dataset[select.dataset.tableFilter] || "").toLocaleLowerCase("pt-BR") === select.value.toLocaleLowerCase("pt-BR"));
      const show = matchesSearch && matchesFilters;
      item.hidden = !show;
      if (show) visible += 1;
    });
    const empty = $("[data-filter-empty]", list) || list.parentElement?.querySelector("[data-filter-empty]");
    if (empty) empty.hidden = visible > 0;
  };

  const initFilters = () => {
    $$('[data-filter-list]').forEach((list) => {
      if (!list.id) return;
      const search = $(`[data-filter-input="${CSS.escape(list.id)}"]`);
      search?.addEventListener("input", debounce(() => applyFilters(list), 100));
      $$('[data-table-filter]').filter((select) => select.closest("section, .card, .modal")?.contains(list)).forEach((select) => select.addEventListener("change", () => applyFilters(list)));
    });
    $$('[data-conversation-filter]').forEach((button) => button.addEventListener("click", () => {
      const list = $("#conversation-items");
      if (!list) return;
      $$('[data-conversation-filter]').forEach((item) => item.classList.toggle("is-active", item === button));
      const status = button.dataset.conversationFilter;
      let visible = 0;
      $$('[data-filter-item]', list).forEach((item) => {
        const show = status === "all" || (item.dataset.status || "").includes(status);
        item.hidden = !show;
        if (show) visible += 1;
      });
      const empty = $("[data-filter-empty]", list);
      if (empty) empty.hidden = visible > 0;
    }));
    $("[data-filter-low-stock]")?.addEventListener("click", () => {
      const select = $("[data-table-filter='stock']");
      if (select) { select.value = "low"; select.dispatchEvent(new Event("change", { bubbles: true })); select.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth" }); }
    });
  };

  const initBulkSelection = () => {
    const selectAll = $("[data-select-all]");
    const rows = $$('[data-row-select]');
    const bar = $("[data-bulk-bar]");
    if (!selectAll || !rows.length || !bar) return;
    const update = () => {
      const count = rows.filter((input) => input.checked).length;
      bar.hidden = count === 0;
      $("[data-selected-count]", bar).textContent = String(count);
      selectAll.checked = count === rows.length;
      selectAll.indeterminate = count > 0 && count < rows.length;
    };
    selectAll.addEventListener("change", () => { rows.forEach((input) => { input.checked = selectAll.checked; }); update(); });
    rows.forEach((input) => input.addEventListener("change", update));
  };

  const initTabs = () => {
    $$('[data-tabs]').forEach((tabs) => {
      const buttons = $$('[data-tab]', tabs);
      buttons.forEach((button) => button.addEventListener("click", () => {
        buttons.forEach((item) => { const active = item === button; item.classList.toggle("is-active", active); item.setAttribute("aria-selected", String(active)); });
        $$('[data-tab-panel]').forEach((panel) => { panel.hidden = panel.dataset.tabPanel !== button.dataset.tab; });
        const url = new URL(window.location.href);
        url.searchParams.set("tab", button.dataset.tab);
        history.replaceState({}, "", url);
      }));
      const initial = new URLSearchParams(window.location.search).get("tab");
      const initialButton = initial ? buttons.find((button) => button.dataset.tab === initial) : null;
      initialButton?.click();
    });
  };

  const initAccordions = () => {
    $$('[data-accordion-trigger]').forEach((button) => button.addEventListener("click", () => {
      const answer = button.nextElementSibling;
      if (!answer) return;
      const open = button.getAttribute("aria-expanded") !== "true";
      button.setAttribute("aria-expanded", String(open));
      answer.hidden = !open;
    }));
  };

  const submitAjaxForm = async (form) => {
    const submitter = form.querySelector("button[type='submit'], input[type='submit']");
    if (!form.reportValidity()) return;
    setLoading(submitter, true);
    try {
      const formData = new FormData(form);
      const checkboxNames = new Set($$("input[type='checkbox'][name]", form).map((input) => input.name));
      checkboxNames.forEach((name) => {
        if (!$$(`input[type='checkbox'][name="${CSS.escape(name)}"]`, form).some((input) => input.checked)) formData.append(name, "0");
      });
      const payload = await apiFetch(form.action || window.location.href, { method: (form.method || "POST").toUpperCase(), body: formData });
      toast(payload.message || "Alterações salvas com sucesso.");
      const modal = form.closest("[data-modal]");
      if (modal) closeModal(modal);
      const redirect = payload.redirect || payload.data?.redirect || form.dataset.successRedirect;
      if (redirect) window.location.assign(redirect);
      else if (form.dataset.successReload === "true" || payload.reload) window.location.reload();
      else form.dispatchEvent(new CustomEvent("autoflow:success", { bubbles: true, detail: payload }));
    } catch (error) {
      toast(error.message || "Não foi possível salvar. Tente novamente.", "error");
      const firstError = error.payload?.errors ? Object.keys(error.payload.errors)[0] : null;
      if (firstError && form.elements[firstError]) form.elements[firstError].focus();
    } finally { setLoading(submitter, false); }
  };

  const initForms = () => {
    $$('[data-ajax-form]').forEach((form) => form.addEventListener("submit", (event) => { event.preventDefault(); submitAjaxForm(form); }));
    $$('[data-loading-form]:not([data-ajax-form])').forEach((form) => form.addEventListener("submit", () => { if (form.checkValidity()) setLoading(form.querySelector("button[type='submit']"), true); }));
    $$('[data-auto-submit]').forEach((input) => input.addEventListener("change", () => {
      const form = input.closest("form"); if (form?.matches("[data-ajax-form]")) submitAjaxForm(form); else form?.requestSubmit();
    }));
    doc.addEventListener("click", async (event) => {
      const confirmButton = event.target.closest("[data-confirm-action]");
      if (confirmButton) {
        event.preventDefault();
        const message = `${confirmButton.dataset.confirmTitle || "Confirmar ação?"}\n\n${confirmButton.dataset.confirmMessage || "Esta ação pode alterar dados da operação."}`;
        if (!window.confirm(message)) return;
        setLoading(confirmButton, true);
        try { const payload = await apiFetch(confirmButton.dataset.confirmAction, { method: "POST", body: {} }); toast(payload.message || "Ação concluída."); window.setTimeout(() => window.location.reload(), 450); }
        catch (error) { toast(error.message, "error"); setLoading(confirmButton, false); }
        return;
      }
      const toggle = event.target.closest("[data-toggle-action]");
      if (toggle) {
        event.preventDefault(); setLoading(toggle, true);
        try { const payload = await apiFetch(toggle.dataset.toggleAction, { method: "POST", body: {} }); toast(payload.message || "Status atualizado."); window.setTimeout(() => window.location.reload(), 350); }
        catch (error) { toast(error.message, "error"); setLoading(toggle, false); }
      }
    });
  };

  const initDashboard = () => {
    if (doc.body.dataset.page !== "dashboard") return;
    $("[data-refresh-dashboard]")?.addEventListener("click", (event) => { setLoading(event.currentTarget, true); window.location.reload(); });
    const source = $("#dashboard-chart-data");
    if (!source || !window.Chart) return;
    const data = parseJSON(source.textContent, {});
    const labels = data.labels || [];
    const textColor = "#7c908b";
    const gridColor = "rgba(221,228,226,.7)";
    const conversationCanvas = $("#conversationsChart");
    if (conversationCanvas) new Chart(conversationCanvas, {
      type: "line",
      data: { labels, datasets: [{ label: "Iniciadas", data: data.started || [], borderColor: "#0f766e", backgroundColor: "rgba(15,118,110,.08)", fill: true, tension: .36, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4 }, { label: "Resolvidas", data: data.resolved || [], borderColor: "#72d8cb", backgroundColor: "transparent", tension: .36, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4 }] },
      options: { responsive: true, maintainAspectRatio: false, interaction: { intersect: false, mode: "index" }, plugins: { legend: { display: false }, tooltip: { padding: 10, cornerRadius: 8, displayColors: true, titleFont: { family: "DM Sans", size: 10 }, bodyFont: { family: "DM Sans", size: 10 } } }, scales: { x: { grid: { display: false }, border: { display: false }, ticks: { color: textColor, font: { size: 9 } } }, y: { beginAtZero: true, grid: { color: gridColor }, border: { display: false }, ticks: { color: textColor, precision: 0, font: { size: 9 } } } } }
    });
    const resolutionCanvas = $("#resolutionChart");
    if (resolutionCanvas) new Chart(resolutionCanvas, { type: "doughnut", data: { labels: ["IA", "Humano"], datasets: [{ data: data.resolution || [0, 0], backgroundColor: ["#0f766e", "#a8e8df"], borderWidth: 0, hoverOffset: 2 }] }, options: { responsive: true, maintainAspectRatio: false, cutout: "76%", plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => ` ${context.label}: ${context.raw} atendimento${Number(context.raw) === 1 ? "" : "s"}` } } } } });
  };

  const appendOutgoingMessage = (content, timeLabel = "Agora") => {
    const list = $("[data-message-list]");
    if (!list) return;
    $(".empty-chat", list)?.remove();
    const row = doc.createElement("div"); row.className = "message-row outgoing";
    const group = doc.createElement("div"); group.className = "message-group";
    const bubble = doc.createElement("div"); bubble.className = "message-bubble";
    const p = doc.createElement("p"); p.textContent = content;
    const time = doc.createElement("span"); time.className = "message-time"; time.textContent = `${timeLabel} `;
    const icon = doc.createElement("i"); icon.dataset.lucide = "check"; time.append(icon);
    bubble.append(p, time); group.append(bubble); row.append(group); list.append(row);
    refreshIcons(row); list.scrollTop = list.scrollHeight;
    return row;
  };

  const initConversations = () => {
    const app = $("[data-conversation-app]");
    if (!app) return;
    const list = $("[data-message-list]", app); if (list) list.scrollTop = list.scrollHeight;
    $$('[data-mobile-conversation]').forEach((button) => button.addEventListener("click", () => { app.dataset.mobilePanel = button.dataset.mobileConversation; }));
    const input = $("[data-composer-input]", app);
    const resize = () => { if (input) { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 115)}px`; } };
    input?.addEventListener("input", resize);
    input?.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); input.closest("form")?.requestSubmit(); } });
    const quick = $("[data-quick-replies]", app);
    $("[data-quick-reply-trigger]", app)?.addEventListener("click", () => { if (quick) quick.hidden = !quick.hidden; });
    $$('button', quick || doc.createElement("div")).forEach((button) => button.addEventListener("click", () => { if (input) { input.value = button.textContent.trim(); resize(); input.focus(); } if (quick) quick.hidden = true; }));
    const chatForm = $("[data-chat-form]", app);
    chatForm?.addEventListener("submit", async (event) => {
      event.preventDefault(); if (!input?.value.trim()) return;
      const content = input.value.trim(); const button = $("button[type='submit']", chatForm); const formData = new FormData(chatForm); setLoading(button, true);
      const optimistic = appendOutgoingMessage(content);
      input.value = ""; resize();
      try { const payload = await apiFetch(chatForm.action, { method: "POST", body: formData }); optimistic?.setAttribute("data-message-id", payload.data?.message?.id || payload.message?.id || payload.id || ""); }
      catch (error) { optimistic?.classList.add("message-failed"); input.value = content; resize(); toast(error.message || "Mensagem não enviada.", "error"); }
      finally { setLoading(button, false); input.focus(); }
    });
    $$('[data-stage-select]').forEach((select) => select.addEventListener("change", async () => {
      if (!select.dataset.customerId) return;
      try { await apiFetch(`/customers/${encodeURIComponent(select.dataset.customerId)}/stage`, { method: "POST", body: { stage: select.value } }); toast("Etapa do CRM atualizada."); }
      catch (error) { toast(error.message, "error"); }
    }));
    const note = $("[data-customer-note]");
    if (note) note.addEventListener("input", debounce(async () => {
      const status = $("[data-note-status]"); if (status) status.textContent = "Salvando...";
      try { await apiFetch(note.dataset.url, { method: "POST", body: { notes: note.value } }); if (status) status.textContent = "Salvo"; }
      catch (_) { if (status) status.textContent = "Não salvo"; }
    }, 700));
    $("[data-focus-note]")?.addEventListener("click", () => note?.focus());
    if (app.dataset.pollUrl && !doc.hidden) {
      let lastId = Number($$('[data-message-id]', app).at(-1)?.dataset.messageId || 0);
      window.setInterval(async () => {
        if (doc.hidden) return;
        try {
          const payload = await apiFetch(`${app.dataset.pollUrl}${app.dataset.pollUrl.includes("?") ? "&" : "?"}after=${lastId}`);
          const fresh = payload.messages || [];
          fresh.forEach((message) => { lastId = Math.max(lastId, Number(message.id) || 0); });
          if (fresh.length) window.location.reload();
        } catch (_) { /* Polling is best-effort. */ }
      }, 10000);
    }
  };

  const initKanban = () => {
    const board = $("[data-kanban]"); if (!board) return;
    let dragged = null;
    $$('[data-kanban-card]', board).forEach((card) => {
      card.addEventListener("dragstart", () => { dragged = card; card.classList.add("is-dragging"); });
      card.addEventListener("dragend", () => { card.classList.remove("is-dragging"); $$('[data-kanban-dropzone]', board).forEach((zone) => zone.classList.remove("is-drag-over")); dragged = null; });
    });
    $$('[data-kanban-dropzone]', board).forEach((zone) => {
      zone.addEventListener("dragover", (event) => { event.preventDefault(); zone.classList.add("is-drag-over"); });
      zone.addEventListener("dragleave", () => zone.classList.remove("is-drag-over"));
      zone.addEventListener("drop", async (event) => {
        event.preventDefault(); zone.classList.remove("is-drag-over"); if (!dragged) return;
        const oldZone = dragged.parentElement; const column = zone.closest("[data-kanban-column]"); const stage = column?.dataset.kanbanColumn; if (!stage || oldZone === zone) return;
        zone.prepend(dragged); updateKanbanCounts(board);
        const template = board.dataset.stageUrlTemplate || "/customers/{id}/stage";
        try { await apiFetch(template.replace("{id}", encodeURIComponent(dragged.dataset.id)), { method: "POST", body: { stage } }); toast("Oportunidade movida."); }
        catch (error) { oldZone.append(dragged); updateKanbanCounts(board); toast(error.message, "error"); }
      });
    });
    $("[data-kanban-search]")?.addEventListener("input", (event) => {
      const term = event.target.value.trim().toLocaleLowerCase("pt-BR");
      $$('[data-kanban-card]', board).forEach((card) => { card.hidden = Boolean(term) && !(card.dataset.search || "").toLocaleLowerCase("pt-BR").includes(term); });
    });
  };

  const updateKanbanCounts = (board) => {
    $$('[data-kanban-column]', board).forEach((column) => {
      const cards = $$('[data-kanban-card]', column);
      const count = $("[data-column-count]", column); if (count) count.textContent = String(cards.length);
      const empty = $("[data-column-empty]", column); if (empty) empty.hidden = cards.length > 0;
    });
  };

  const initProducts = () => {
    const container = $("[data-view-container]");
    $$('[data-view-switch]').forEach((button) => button.addEventListener("click", () => {
      $$('[data-view-switch]').forEach((item) => item.classList.toggle("is-active", item === button));
      if (container) { container.classList.toggle("product-grid", button.dataset.viewSwitch === "grid"); container.classList.toggle("product-table", button.dataset.viewSwitch === "table"); }
    }));
    const list = $("[data-variant-list]"); const template = $("#variant-row-template");
    $("[data-add-variant]")?.addEventListener("click", () => {
      if (!list || !template) return; const node = template.content.cloneNode(true); list.append(node); $("[data-variant-empty]", list).hidden = true; refreshIcons(list); $("[data-variant-row]:last-child input", list)?.focus();
    });
    list?.addEventListener("click", (event) => { const remove = event.target.closest("[data-remove-variant]"); if (!remove) return; remove.closest("[data-variant-row]")?.remove(); const empty = $("[data-variant-empty]", list); if (empty) empty.hidden = Boolean($("[data-variant-row]", list)); });
    $$('[data-image-input]').forEach((input) => input.addEventListener("change", () => {
      const file = input.files?.[0]; const preview = $("[data-image-preview]", input.closest("label")); if (!file || !preview) return;
      if (!file.type.startsWith("image/") || file.size > 5 * 1024 * 1024) { toast("Escolha uma imagem PNG, JPG ou WebP de até 5 MB.", "error"); input.value = ""; return; }
      const img = new Image(); img.alt = "Prévia da imagem"; img.src = URL.createObjectURL(file); img.onload = () => URL.revokeObjectURL(img.src); preview.replaceChildren(img);
    }));
  };

  const initInventory = () => {
    const form = $("[data-movement-form]"); if (!form) return;
    const select = $("select[name='inventory_id']", form); const quantity = $("input[name='quantity']", form); const currentBox = $("[data-current-stock]", form); const preview = $("[data-movement-preview] strong", form);
    const update = () => {
      const current = Number(select?.selectedOptions?.[0]?.dataset.stock || 0); const amount = Number(quantity?.value || 0); const type = $("input[name='type']:checked", form)?.value;
      if (currentBox) { currentBox.hidden = !select?.value; const output = $("b", currentBox); if (output) output.textContent = String(current); }
      const next = type === "ENTRY" ? current + amount : type === "EXIT" ? Math.max(0, current - amount) : amount;
      if (preview) preview.textContent = select?.value ? `${next} unidades` : "—";
    };
    [select, quantity, ...$$("input[name='type']", form)].filter(Boolean).forEach((field) => field.addEventListener("change", update)); quantity?.addEventListener("input", update);
  };

  const initDelivery = () => {
    const form = $("[data-delivery-simulator]"); if (!form) return;
    form.addEventListener("submit", async (event) => {
      event.preventDefault(); const button = $("button[type='submit']", form); const result = $("[data-simulation-result]"); const placeholder = $("[data-simulation-placeholder]"); setLoading(button, true);
      try {
        const payload = await apiFetch(form.dataset.url, { method: "POST", body: new FormData(form) });
        if (result) { result.replaceChildren(); const strong = doc.createElement("strong"); strong.textContent = payload.available ? (payload.price_label || "Entrega disponível") : "Região não atendida"; const span = doc.createElement("span"); span.textContent = payload.available ? (payload.deadline_label || "Consulte o prazo no atendimento.") : (payload.message || "Não há regra cadastrada para este CEP."); result.append(strong, span); result.hidden = false; }
        if (placeholder) placeholder.hidden = true;
      } catch (error) { toast(error.message, "error"); } finally { setLoading(button, false); }
    });
  };

  const initAppointments = () => {
    const professionalFilter = $("[data-appointment-filter='professional']");
    professionalFilter?.addEventListener("change", () => {
      const selected = professionalFilter.value;
      $$(".appointment-day").forEach((day) => {
        const cards = $$(".appointment-card", day);
        let visible = 0;
        cards.forEach((card) => {
          const show = !selected || card.dataset.professional === selected;
          card.hidden = !show;
          if (show) visible += 1;
        });
        day.hidden = visible === 0;
        const count = $("[data-day-count]", day);
        if (count) count.textContent = `${visible} agendamento${visible === 1 ? "" : "s"}`;
      });
    });
    $$('[data-appointment-confirm]').forEach((button) => button.addEventListener("click", async () => {
      setLoading(button, true);
      try {
        const payload = await apiFetch(button.dataset.appointmentConfirm, { method: "POST", body: {} });
        toast(payload.message || "Agendamento confirmado.");
        window.setTimeout(() => window.location.reload(), 350);
      } catch (error) {
        toast(error.message || "Não foi possível confirmar o agendamento.", "error");
        setLoading(button, false);
      }
    }));
    const availabilityPanel = $("[data-tab-panel='availability'][data-slot-interval]");
    const slotInterval = $("select[name='slot_interval']", availabilityPanel || doc);
    if (availabilityPanel && slotInterval) slotInterval.value = availabilityPanel.dataset.slotInterval || "30";
    const form = $("[data-appointment-form]");
    if (form) {
      const fields = $$('[data-availability-field], [data-service-select], select[name="professional_id"]', form); const slots = $("[data-time-slots]", form); const feedback = $("[data-availability-feedback]", form);
      const load = debounce(async () => {
        const service = $("select[name='service_id']", form)?.value; const professional = $("select[name='professional_id']", form)?.value; const date = $("input[name='date']", form)?.value;
        if (!service || !professional || !date || !slots) return;
        slots.disabled = true; slots.replaceChildren(new Option("Consultando horários...", ""));
        try {
          const params = new URLSearchParams({ service_id: service, professional_id: professional, date }); const payload = await apiFetch(`/appointments/availability?${params}`);
          slots.replaceChildren(new Option(payload.slots?.length ? "Selecione um horário" : "Nenhum horário disponível", ""));
          (payload.slots || []).forEach((slot) => {
            const startsAt = typeof slot === "string" ? slot : slot.starts_at || slot.time || slot.value;
            if (!startsAt) return;
            const timeValue = startsAt.includes("T") ? startsAt.split("T")[1].slice(0, 5) : startsAt.slice(0, 5);
            const label = typeof slot === "object" && slot.label ? slot.label : timeValue;
            slots.add(new Option(label, timeValue));
          });
          if (feedback) { feedback.hidden = false; feedback.className = `availability-feedback ${payload.slots?.length ? "success" : "error"}`; feedback.textContent = payload.slots?.length ? `${payload.slots.length} horários disponíveis nesta data.` : "Não há disponibilidade. Escolha outra data ou profissional."; }
        } catch (error) { slots.replaceChildren(new Option("Não foi possível consultar", "")); toast(error.message, "error"); }
        finally { slots.disabled = false; }
      }, 250);
      fields.forEach((field) => field.addEventListener("change", load));
    }
    $$('[data-agenda-nav]').forEach((button) => button.addEventListener("click", () => { const url = new URL(window.location.href); const current = Number(url.searchParams.get("week") || 0); url.searchParams.set("week", String(current + (button.dataset.agendaNav === "next" ? 1 : -1))); window.location.assign(url); }));
    $("[data-agenda-today]")?.addEventListener("click", () => { const url = new URL(window.location.href); url.searchParams.delete("week"); window.location.assign(url); });
  };

  const initKnowledge = () => {
    $$('[data-file-dropzone]').forEach((dropzone) => {
      const input = $("input[type='file']", dropzone); const name = $("[data-file-name]", dropzone); if (!input) return;
      ["dragenter", "dragover"].forEach((type) => dropzone.addEventListener(type, (event) => { event.preventDefault(); dropzone.classList.add("is-dragover"); }));
      ["dragleave", "drop"].forEach((type) => dropzone.addEventListener(type, (event) => { event.preventDefault(); dropzone.classList.remove("is-dragover"); }));
      dropzone.addEventListener("drop", (event) => { if (event.dataTransfer?.files?.length) { input.files = event.dataTransfer.files; input.dispatchEvent(new Event("change")); } });
      input.addEventListener("change", () => { const file = input.files?.[0]; if (file && name) name.textContent = file.name; });
    });
  };

  const initAISettings = () => {
    const add = $("[data-add-rule]"); const list = $("[data-rule-list]"); const template = $("#rule-row-template");
    add?.addEventListener("click", () => { if (!list || !template) return; list.append(template.content.cloneNode(true)); refreshIcons(list); $(".rule-row:last-child input", list)?.focus(); });
    list?.addEventListener("click", (event) => event.target.closest("[data-remove-rule]")?.closest(".rule-row")?.remove());
    const name = $("#ai-name"); const previewName = $("[data-preview-ai-name]"); name?.addEventListener("input", () => { if (previewName) previewName.textContent = name.value.trim() || "Assistente"; });
    const welcome = $("[data-preview-source='welcome']"); const preview = $("[data-ai-preview-message]"); welcome?.addEventListener("input", debounce(() => { if (preview) preview.childNodes[0].textContent = welcome.value.replaceAll("{nome}", "cliente").replaceAll("{empresa}", "sua empresa"); }, 80));
  };

  const initWhatsApp = () => {
    $$('[data-copy-target]').forEach((button) => button.addEventListener("click", async () => {
      const target = doc.getElementById(button.dataset.copyTarget); const value = target?.value || target?.textContent?.trim(); if (!value) return;
      try { await navigator.clipboard.writeText(value); toast("Copiado para a área de transferência.", "info"); } catch (_) { toast("Não foi possível copiar automaticamente.", "error"); }
    }));
    $("[data-test-whatsapp]")?.addEventListener("click", async (event) => {
      const button = event.currentTarget; const phone = window.prompt("Informe o número com DDD para receber a mensagem de teste:"); if (!phone) return; setLoading(button, true);
      try { const payload = await apiFetch(button.dataset.url, { method: "POST", body: { phone } }); toast(payload.message || "Mensagem de teste enviada."); } catch (error) { toast(error.message, "error"); } finally { setLoading(button, false); }
    });
    $("[data-check-webhook]")?.addEventListener("click", async (event) => {
      const button = event.currentTarget; setLoading(button, true);
      try { const payload = await apiFetch(button.dataset.url, { method: "POST", body: {} }); toast(payload.message || "Conexão verificada."); } catch (error) { toast(error.message, "error"); } finally { setLoading(button, false); }
    });
  };

  const initMisc = () => {
    $$('[data-dismiss]').forEach((button) => button.addEventListener("click", () => button.closest(".alert")?.remove()));
    $$('[data-auto-dismiss]').forEach((alert) => window.setTimeout(() => alert.remove(), 6500));
    $("[data-mark-read]")?.addEventListener("click", () => $$('[data-dropdown="notifications"] .is-unread').forEach((item) => item.classList.remove("is-unread")));
    $$('[data-export-url]').forEach((button) => button.addEventListener("click", () => window.location.assign(button.dataset.exportUrl)));
    $$('[data-history-back]').forEach((button) => button.addEventListener("click", () => { if (history.length > 1) history.back(); else window.location.assign("/dashboard"); }));
    $$('[data-page-reload]').forEach((button) => button.addEventListener("click", () => window.location.reload()));
  };

  doc.addEventListener("DOMContentLoaded", () => {
    refreshIcons();
    initSidebar(); initDropdowns(); initModals(); initCommandPalette(); initPasswordFields(); initMasks(); initCounters();
    initFilters(); initBulkSelection(); initTabs(); initAccordions(); initForms(); initDashboard(); initConversations();
    initKanban(); initProducts(); initInventory(); initDelivery(); initAppointments(); initKnowledge(); initAISettings(); initWhatsApp(); initMisc();
  });
})();
