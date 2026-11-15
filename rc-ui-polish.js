(function () {
  if (window.__rcUiPolishVer >= 7) return;
  window.__rcUiPolishVer = 7;

  /* Critical CSS early — kill billing flash before main stylesheet */
  if (!document.getElementById("rc-ui-polish-critical")) {
    var crit = document.createElement("style");
    crit.id = "rc-ui-polish-critical";
    crit.textContent =
      '.payments-tab-general .usage,.payments-tab-general .usage-container,' +
      '.content .usage:has(.usage-container),.content .usage:has(.text-head),' +
      '[data-rc-hide-billing-limits="1"]{display:none!important;height:0!important;overflow:hidden!important;opacity:0!important;}' +
                    '.signage-card .buttons > .ra-button.preset.default,.signage-card .buttons > .ra-button.preset.liked,' +
                    '.signage-card .buttons > button.preset.default,.signage-card .buttons > button.preset.liked,' +
                    '.signage-card .flex-shrink-0,.signage-card [class*="flex-shrink-0"]{display:none!important;width:0!important;min-width:0!important;padding:0!important;margin:0!important;opacity:0!important;pointer-events:none!important;}';
      (document.head || document.documentElement).appendChild(crit);
  }

  var ICO = {
    home: '<svg viewBox="0 0 24 24"><path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1v-9.5Z"/></svg>',
    users: '<svg viewBox="0 0 24 24"><path d="M8 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm9 1a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7ZM2.5 19.2C3.4 15.6 5.9 14 8 14s4.6 1.6 5.5 5.2c.2.7-.4 1.8-1.2 1.8H3.7c-.8 0-1.4-1.1-1.2-1.8Z"/></svg>',
    user: '<svg viewBox="0 0 24 24"><path d="M12 3a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9Zm0 11c3.8 0 7 1.7 7.8 4.4.2.8-.4 1.6-1.2 1.6H5.4c-.8 0-1.4-.8-1.2-1.6C5 15.7 8.2 14 12 14Z"/></svg>',
    chat: '<svg viewBox="0 0 24 24"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8A2.5 2.5 0 0 1 17.5 16H10l-4.2 3.2c-.7.5-1.8 0-1.8-.9V5.5Z"/></svg>',
    reports: '<svg viewBox="0 0 24 24"><path d="M12 2 2 21h20L12 2Zm0 6.5 5.2 9H6.8L12 8.5ZM11 12h2v3h-2v-3Zm0 4h2v2h-2v-2Z"/></svg>',
    checks: '<svg viewBox="0 0 24 24"><path d="M9.2 16.6 4.8 12.2l1.4-1.4 3 3 8-8 1.4 1.4-9.4 9.4Z"/></svg>',
    map: '<svg viewBox="0 0 24 24"><path d="M9.5 3.5 3 5.8v14.2l6.5-2.3 5 2.3L21 17.7V3.5l-6.5 2.3-5-2.3Zm1 2.2 3 1.4v11.2l-3-1.4V5.7Zm-2 .4v11.2L5 18.5V7.3l3.5-1.2Zm9 12.4-3.5 1.2V8.1l3.5-1.2v11.4Z"/></svg>',
    signage: '<svg viewBox="0 0 24 24"><path d="M4 5h16v11H8l-4 3V5Zm2 2v8h12V7H6Z"/></svg>',
    alerts: '<svg viewBox="0 0 24 24"><path d="M12 3a6 6 0 0 1 6 6v3.2l1.4 2.1c.4.6 0 1.7-.8 1.7H5.4c-.8 0-1.2-1.1-.8-1.7L6 12.2V9a6 6 0 0 1 6-6Zm-2.2 15h4.4a2.2 2.2 0 0 1-4.4 0Z"/></svg>',
    bags: '<svg viewBox="0 0 24 24"><path d="M7 8V6a5 5 0 0 1 10 0v2h2.5A1.5 1.5 0 0 1 21 9.5v10A1.5 1.5 0 0 1 19.5 21h-15A1.5 1.5 0 0 1 3 19.5v-10A1.5 1.5 0 0 1 4.5 8H7Zm2 0h6V6a3 3 0 0 0-6 0v2Z"/></svg>',
    mutes: '<svg viewBox="0 0 24 24"><path d="M12 3a4 4 0 0 1 4 4v5a4 4 0 0 1-8 0V7a4 4 0 0 1 4-4Zm7 9a7 7 0 0 1-14 0H3a9 9 0 0 0 8 8.9V23h2v-2.1A9 9 0 0 0 21 12h-2Z"/></svg>',
    bans: '<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20Zm0 2a8 8 0 0 0-6.3 12.9L16.9 5.7A7.9 7.9 0 0 0 12 4Zm0 16a8 8 0 0 0 6.3-12.9L7.1 18.3A7.9 7.9 0 0 0 12 20Z"/></svg>',
    stats: '<svg viewBox="0 0 24 24"><path d="M4 19h16v2H4v-2Zm2-7h2v5H6v-5Zm5-4h2v9h-2V8Zm5-3h2v12h-2V5Z"/></svg>',
    servers: '<svg viewBox="0 0 24 24"><path d="M4 4h16v5H4V4Zm0 7h16v5H4v-5Zm0 7h16v5H4v-5ZM7 6.5h2V7H7v-.5Zm0 7h2V14H7v-.5Zm0 7h2V21H7v-.5Z"/></svg>',
    audit: '<svg viewBox="0 0 24 24"><path d="M7 3h10a2 2 0 0 1 2 2v16l-7-3-7 3V5a2 2 0 0 1 2-2Zm0 2v12.2l5-2.1 5 2.1V5H7Z"/></svg>',
    integrations: '<svg viewBox="0 0 24 24"><path d="M8 3h3v3H8V3Zm5 0h3v3h-3V3ZM8 8h3v3H8V8Zm5 0h3v3h-3V8ZM3 13h3v3H3v-3Zm5 0h3v3H8v-3Zm5 0h3v3h-3v-3Zm5 0h3v3h-3v-3ZM8 18h3v3H8v-3Zm5 0h3v3h-3v-3Z"/></svg>',
    settings: '<svg viewBox="0 0 24 24"><path d="M10.2 2.5h3.6l.4 2.2a7.5 7.5 0 0 1 1.8.8l2-1.1 2.5 2.5-1.1 2a7.5 7.5 0 0 1 .8 1.8l2.2.4v3.6l-2.2.4a7.5 7.5 0 0 1-.8 1.8l1.1 2-2.5 2.5-2-1.1a7.5 7.5 0 0 1-1.8.8l-.4 2.2h-3.6l-.4-2.2a7.5 7.5 0 0 1-1.8-.8l-2 1.1-2.5-2.5 1.1-2a7.5 7.5 0 0 1-.8-1.8L2.5 13.8v-3.6l2.2-.4a7.5 7.5 0 0 1 .8-1.8l-1.1-2L6.9 3.5l2 1.1a7.5 7.5 0 0 1 1.8-.8l.5-2.3ZM12 8.5A3.5 3.5 0 1 0 12 15a3.5 3.5 0 0 0 0-7Z"/></svg>',
    staff: '<svg viewBox="0 0 24 24"><path d="M8 4a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7Zm8 1a3 3 0 1 1 0 6 3 3 0 0 1 0-6ZM3.2 18.5C4 15.8 5.9 14 8 14s4 1.8 4.8 4.5c.2.7-.4 1.5-1.1 1.5H4.3c-.7 0-1.3-.8-1.1-1.5Zm9.5-.3c.7-2.2 2.2-3.7 4.3-4.2.5.2 1.1.5 1.7.5 1.4 0 2.6.7 3.2 2.1.3.7-.2 1.4-.9 1.4h-7.5c-.5 0-.9-.4-.8-1.3Z"/></svg>',
    billing: '<svg viewBox="0 0 24 24"><path d="M3 6.5A2.5 2.5 0 0 1 5.5 4h13A2.5 2.5 0 0 1 21 6.5v11A2.5 2.5 0 0 1 18.5 20h-13A2.5 2.5 0 0 1 3 17.5v-11ZM5 8h14v2H5V8Zm0 5h6v2H5v-2Z"/></svg>',
    shield: '<svg viewBox="0 0 24 24"><path d="M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5l-8-3Zm0 4.2 5 1.9v3.7c0 3.5-2.2 6.7-5 8-2.8-1.3-5-4.5-5-8V8.1l5-1.9Z"/></svg>',
    search: '<svg viewBox="0 0 24 24"><path d="M10.5 3a7.5 7.5 0 1 1 0 15 7.5 7.5 0 0 1 0-15Zm0 2a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11Zm7.2 11.1 3.1 3.1-1.4 1.4-3.1-3.1 1.4-1.4Z"/></svg>',
    unban: '<svg viewBox="0 0 24 24"><path d="M9.2 16.6 4.8 12.2l1.4-1.4 3 3 8-8 1.4 1.4-9.4 9.4Z"/></svg>'
  };

  var PAGE_META = [
    { re: /\/players(?:\/|$)/i, ico: "users", tone: "blue" },
    { re: /\/chat(?:\/|$)/i, ico: "chat", tone: "sky" },
    { re: /\/reports(?:\/|$)/i, ico: "reports", tone: "amber" },
    { re: /\/checks?(?:\/|$)/i, ico: "checks", tone: "green" },
    { re: /\/map(?:\/|$)/i, ico: "map", tone: "sky" },
    { re: /\/signages?(?:\/|$)/i, ico: "signage", tone: "pink" },
    { re: /\/alerts?(?:\/|$)/i, ico: "alerts", tone: "amber" },
    { re: /\/bags?(?:\/|$)|sleeping/i, ico: "bags", tone: "slate" },
    { re: /\/mutes?(?:\/|$)/i, ico: "mutes", tone: "slate" },
    { re: /\/bans?(?:\/|$)/i, ico: "bans", tone: "red" },
    { re: /\/stats(?:\/|$)|project-stats/i, ico: "stats", tone: "purple" },
    { re: /\/servers(?:\/|$)/i, ico: "servers", tone: "blue" },
    { re: /\/audit(?:\/|$)/i, ico: "audit", tone: "slate" },
    { re: /\/integrations(?:\/|$)/i, ico: "integrations", tone: "sky" },
    { re: /\/billing|\/payments|\/settings\/billing/i, ico: "billing", tone: "green" },
    { re: /\/clients(?:\/|$)|\/staff/i, ico: "staff", tone: "blue" },
    { re: /\/settings(?:\/|$)|\/customization|\/info(?:\/|$)/i, ico: "settings", tone: "slate" },
    { re: /\/home(?:\/|$)/i, ico: "home", tone: "blue" }
  ];

  var TITLE_HINTS = [
    { re: /^(Players|Игроки)$/i, ico: "users", tone: "blue" },
    { re: /^(Chat|Чат)$/i, ico: "chat", tone: "sky" },
    { re: /^(Reports|Репорты)$/i, ico: "reports", tone: "amber" },
    { re: /^(Inspections|Checks|Проверки)$/i, ico: "checks", tone: "green" },
    { re: /^(Map|Карта)$/i, ico: "map", tone: "sky" },
    { re: /^(Signs|Signage|Рисунки|Drawings)$/i, ico: "signage", tone: "pink" },
    { re: /^(Alerts|Оповещения)$/i, ico: "alerts", tone: "amber" },
    { re: /^(Sleeping bags|Спальники|Bags)$/i, ico: "bags", tone: "slate" },
    { re: /^(Mutes|Муты)$/i, ico: "mutes", tone: "slate" },
    { re: /^(Bans|Блокировки)$/i, ico: "bans", tone: "red" },
    { re: /^(Statistics|Статистика|Статистика модераторов)$/i, ico: "stats", tone: "purple" },
    { re: /^(Servers|Серверы|Список серверов)$/i, ico: "servers", tone: "blue" },
    { re: /^(Audit log|Журнал аудита|Audit)$/i, ico: "audit", tone: "slate" },
    { re: /^(Integrations|Интеграции)$/i, ico: "integrations", tone: "sky" },
    { re: /^(Настройки проекта|Project settings|Settings|Настройки)$/i, ico: "settings", tone: "slate" },
    { re: /^(Staff|Сотрудники|Clients)$/i, ico: "staff", tone: "blue" },
    { re: /^(Billing|Биллинг|Payments)$/i, ico: "billing", tone: "green" },
    { re: /^(Home|Главная|Dashboard)$/i, ico: "home", tone: "blue" }
  ];

  function ensureCss() {
    var link = document.getElementById("rc-ui-polish-css");
    if (!link) {
      link = document.createElement("link");
      link.id = "rc-ui-polish-css";
      link.rel = "stylesheet";
      (document.head || document.documentElement).appendChild(link);
    }
    if (link.getAttribute("href") !== "/rc-ui-polish.css?v=11") link.href = "/rc-ui-polish.css?v=11";
  }

  function path() { return String(location.pathname || ""); }

  function metaForPath() {
    var p = path();
    for (var i = 0; i < PAGE_META.length; i++) {
      if (PAGE_META[i].re.test(p)) return PAGE_META[i];
    }
    return null;
  }

  function metaFromTitle(text) {
    var t = String(text || "").replace(/\s+/g, " ").trim();
    for (var i = 0; i < TITLE_HINTS.length; i++) {
      if (TITLE_HINTS[i].re.test(t)) return TITLE_HINTS[i];
    }
    return null;
  }

  function findPageHeader() {
    var content = document.querySelector(".content-wrapper, .layout-page .content, .content.ignore-side, .content");
    if (!content) return null;
    var title = document.querySelector(".content-wrapper .top-title, #rc-panel-home .rph-title");
    if (!title) {
      var header = content.querySelector(".layout-page > .content > .header, .layout-page > .header, :scope > .header");
      if (header) {
        title = header.querySelector(".text-grey-50");
        var nodes = header.querySelectorAll("h1, h2, p, span");
        for (var i = 0; !title && i < nodes.length; i++) {
          if (metaFromTitle(nodes[i].textContent)) { title = nodes[i]; break; }
        }
      }
    }
    if (!title || title.closest(".player-modal, .vfm, .n-modal")) return null;
    return {title:title, meta:metaFromTitle(title.textContent)};
  }

  function decoratePageHeader() {
    var found = findPageHeader();
    var meta = metaForPath() || (found && found.meta);
    var title = found && found.title;
    document.querySelectorAll(".rc-page-head-ico").forEach(function (icon) {
      if (icon.parentElement === title) return;
      var parent = icon.parentElement;
      icon.remove();
      if (parent) parent.classList.remove("rc-page-head");
    });
    if (!title || !meta) return;
    var sidebarIcon = null;
    document.querySelectorAll(".navigation a[href]").forEach(function (link) {
      if (new URL(link.href, location.href).pathname === path()) sidebarIcon = link.querySelector("svg");
    });
    var signature = sidebarIcon ? sidebarIcon.innerHTML : meta.ico;
    var existing = title.querySelector(":scope > .rc-page-head-ico");
    if (existing && existing.dataset.rcIco === signature) return;
    if (existing) existing.remove();
    title.classList.add("rc-page-head");
    var icon = document.createElement("span");
    icon.className = "rc-page-head-ico";
    icon.dataset.rcIco = signature;
    icon.setAttribute("aria-hidden", "true");
    if (sidebarIcon) icon.appendChild(sidebarIcon.cloneNode(true));
    else icon.innerHTML = ICO[meta.ico] || ICO.settings;
    title.prepend(icon);
  }

  function hideSectionHeroIcons() {
    if (!/\/(settings|integrations|customization|info|billing)(?:\/|$|\?)/i.test(path())) return;
    var content = document.querySelector(".content .router, .content");
    if (!content) return;
    content.querySelectorAll("svg, img, [class*='icon']").forEach(function (el) {
      if (el.closest(".rc-page-head-ico, .navigation, .n-switch, button, a, .ra-button, #rc-players-cards")) return;
      var r = el.getBoundingClientRect();
      if (r.width < 36 || r.width > 96 || r.height < 36 || r.height > 96) return;
      /* centered-ish hero icon under header */
      if (r.top > 220) return;
      var parent = el.parentElement;
      if (!parent) return;
      var txt = String(parent.textContent || "").replace(/\s+/g, " ").trim();
      /* alone or nearly alone in parent */
      if (txt.length > 40) return;
      el.setAttribute("data-rc-hide-section-ico", "1");
      if (parent.children.length <= 2 && txt.length < 8) parent.setAttribute("data-rc-hide-section-ico", "1");
    });
  }

  function hideBillingLimits() {
    document.querySelectorAll(".payments-tab-general .usage, .payments-tab-general .usage-container, .content .usage").forEach(function (el) {
      var blob = String(el.textContent || "");
      if (!/(Лимиты тарифа|Plan limits|Подключенные серверы|Connected servers|Игроков в базе|Players in)/i.test(blob)) return;
      el.setAttribute("data-rc-hide-billing-limits", "1");
      el.classList.add("rc-hide-billing-limits");
      el.style.setProperty("display", "none", "important");
    });
  }

  function slug() {
    var parts = String(location.pathname || "").split("/").filter(Boolean);
    var skip = { client: 1, players: 1, home: 1, settings: 1, auth: 1 };
    if (parts[0] && !skip[parts[0].toLowerCase()]) return parts[0];
    try { return String(localStorage.getItem("checkapp_project_slug") || ""); } catch (_) { return ""; }
  }

  function authHeaders() {
    var h = { Accept: "application/json", "X-Checkapp-Project": slug() };
    try {
      var tok = localStorage.getItem("token") || localStorage.getItem("access_token") || "";
      if (tok) h.Authorization = tok.indexOf("Bearer") === 0 ? tok : ("Bearer " + tok);
    } catch (_) {}
    return h;
  }

  function animateValue(el, to) {
    var target = Number(to) || 0;
    var from = Number(String(el.textContent || "0").replace(/[^\d.-]/g, "")) || 0;
    if (from === target) { el.textContent = String(target); return; }
    var start = performance.now();
    var dur = 700;
    function frame(now) {
      var p = Math.min(1, (now - start) / dur);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = String(Math.round(from + (target - from) * eased));
      if (p < 1) requestAnimationFrame(frame);
      else el.textContent = String(target);
    }
    requestAnimationFrame(frame);
  }

  function cardHtml(tone, icon, label, value, hint) {
    return (
      '<div class="rpc-card"><div class="rpc-ico ' + tone + '">' + icon + '</div><div>' +
      '<div class="rpc-label">' + label + '</div>' +
      '<div class="rpc-value" data-rpc="' + label + '">' + value + '</div>' +
      '<div class="rpc-hint">' + hint + '</div></div></div>'
    );
  }

  function insertPlayersCardsHost() {
    var host = document.querySelector(".content .router, .content.ignore-side, .layout-page .content, .content");
    if (!host) return null;
    var box = document.getElementById("rc-players-cards");
    if (box) return box;
    box = document.createElement("div");
    box.id = "rc-players-cards";
    box.innerHTML =
      cardHtml("blue", ICO.users, "Всего игроков", "0", "в базе данных") +
      cardHtml("green", ICO.user, "Онлайн", "0", "Сейчас в игре") +
      cardHtml("slate", ICO.user, "Оффлайн", "0", "Не в игре");
    var header = host.querySelector(".header, .rc-page-head, h1");
    if (header && header.parentElement) {
      var anchor = header.closest(".header") || header;
      if (anchor.parentElement) anchor.parentElement.insertBefore(box, anchor.nextSibling);
      else host.insertBefore(box, host.firstChild);
    } else {
      host.insertBefore(box, host.firstChild);
    }
    return box;
  }

  function loadPlayersCards(box) {
    if (!box || box._rcLoading) return;
    box._rcLoading = 1;
    Promise.all([
      fetch("/players/browse-minimal?online=1", { credentials: "include", headers: authHeaders() }).then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; }),
      fetch("/players/browse-minimal", { credentials: "include", headers: authHeaders() }).then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; }),
      fetch("/server/overview", { credentials: "include", headers: authHeaders() }).then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; })
    ]).then(function (arr) {
      box._rcLoading = 0;
      box._rcLoadedAt = Date.now();
      function list(x) {
        if (Array.isArray(x)) return x;
        if (Array.isArray(x.results)) return x.results;
        if (Array.isArray(x.data)) return x.data;
        if (Array.isArray(x.items)) return x.items;
        if (Array.isArray(x.players)) return x.players;
        return [];
      }
      var overview = arr[2] || {};
      var online = list(arr[0]).length || Number(overview.online || 0) || 0;
      var total = list(arr[1]).length || Number(overview.players_total || overview.players || 0) || online;
      if (total < online) total = online;
      var offline = Math.max(0, total - online);
      var map = { "Всего игроков": total, "Онлайн": online, "Оффлайн": offline };
      box.querySelectorAll("[data-rpc]").forEach(function (el) {
        animateValue(el, map[el.getAttribute("data-rpc")] || 0);
      });
    }).catch(function () { box._rcLoading = 0; });
  }

  function ensurePlayersCards() {
    if (!/\/players(?:\/|$|\?)/i.test(path())) {
      var old = document.getElementById("rc-players-cards");
      if (old) old.remove();
      return;
    }
    var box = insertPlayersCardsHost();
    if (!box) return;
    if (!box._rcLoadedAt || Date.now() - box._rcLoadedAt > 6000) loadPlayersCards(box);
  }

  function hideSignageLikes() {
    document.querySelectorAll(".signage-card").forEach(function (card) {
      card.querySelectorAll(".buttons > button, .buttons > [class*='ra-button'], button, [class*='ra-button']").forEach(function (btn) {
        if (btn.getAttribute("data-rc-hide-like") === "1") return;
        var cls = String(btn.className || "");
        if (/destructive/.test(cls)) return;
        var t = String(btn.textContent || "").replace(/\s+/g, " ").trim();
        if (/удал|delete|не существует|nonexistent/i.test(t)) return;
        var isLikePreset = /\bpreset\b/.test(cls) && /(^|\s)(default|liked|default-light)(\s|$)/.test(cls.replace(/!/g, ""));
        /* also: preset class list like "preset default" */
        isLikePreset = isLikePreset || /(^|\s)preset\s+(default|liked|default-light)(\s|$)/.test(cls);
        var html = String(btn.innerHTML || "");
        var looksHeart = /M12\.5836|heart/i.test(html);
        var isFlex = /flex-shrink-0/.test(cls);
        if (!isLikePreset && !looksHeart && !isFlex) return;
        btn.setAttribute("data-rc-hide-like", "1");
        btn.classList.add("rc-hide-like");
        btn.style.setProperty("display", "none", "important");
        btn.style.setProperty("width", "0", "important");
        btn.style.setProperty("height", "0", "important");
        btn.style.setProperty("opacity", "0", "important");
        btn.style.setProperty("pointer-events", "none", "important");
      });
    });
  }

  function polishModals() {
    document.querySelectorAll(".player-modal, .ip-details-modal, [class*='mute-view'], [class*='ban-view'], .permissions-modal, .profile, [class*='pair']").forEach(function (el) {
      if (el.getAttribute("data-rc-glass") === "1") return;
      el.setAttribute("data-rc-glass", "1");
      el.classList.add("rc-glass-modal");
      var wrap = el.closest(".vfm__content, .n-card, .n-modal, .modal, .modal-border");
      if (wrap) {
        wrap.style.setProperty("border", "none", "important");
        wrap.style.setProperty("outline", "none", "important");
        wrap.style.setProperty("box-shadow", "0 24px 80px rgba(0,0,0,.55)", "important");
        wrap.style.setProperty("border-radius", "22px", "important");
        wrap.style.setProperty("pointer-events", "auto", "important");
      }
      var vfm = el.closest(".vfm, .n-modal-container");
      if (vfm) {
        vfm.style.setProperty("pointer-events", "auto", "important");
        vfm.style.setProperty("z-index", "10050", "important");
      }
      var borderWrap = el.closest(".modal-border");
      if (borderWrap) {
        borderWrap.style.setProperty("border", "0", "important");
        borderWrap.style.setProperty("outline", "none", "important");
        borderWrap.style.setProperty("background", "transparent", "important");
        borderWrap.style.setProperty("box-shadow", "none", "important");
        borderWrap.style.setProperty("padding", "0", "important");
      }
    });
  }

  function sealPlayerModalClicks() {
    if (window.__rcPlayerModalSeal) return;
    window.__rcPlayerModalSeal = 1;
    /* bubble only — never capture/stop before Vue handles the tab click */
    document.addEventListener("click", function (e) {
      var t = e.target;
      if (!t || !t.closest) return;
      if (!t.closest(".player-modal, .vfm__content:has(.player-modal)")) return;
      e.stopPropagation();
    }, false);
  }

  function revertModStats() {
    var skin = document.getElementById("rc-mod-stats-skin");
    if (skin) skin.remove();
    document.querySelectorAll("[data-rc-hide-stock-stat]").forEach(function (el) {
      el.removeAttribute("data-rc-hide-stock-stat");
      el.style.removeProperty("display");
    });
  }

  function watchPairNameStep() {
    var modal = document.querySelector(".vfm__content, .vfm-content, .modal-border .modal");
    if (!modal) return;
    var txt = String(modal.textContent || "");
    if (!/ra\.pair|подключ|connect|pair|плагин|plugin|RustCheck\.cs/i.test(txt)) return;

    var paired =
      window.__rcPairUsedFlag ||
      /сервер подключен|server connected|придумать|короткую назв|enter (a |the )?name|введите назв|название сервера/i.test(txt) ||
      (!!modal.querySelector("input[placeholder*='назв' i], input[placeholder*='name' i], input[placeholder*='Enter' i]") &&
        !/выполните команду|execute the command|ra\.pair/i.test(txt));

    var waitingPair = /ra\.pair\s+\d+|выполните команду|execute the command/i.test(txt);

    if (paired && !document.getElementById("rc-pair-name-modal") && !window.__rcPairNameDone) {
      openPairNameModal(modal);
    }

    if (waitingPair) {
      modal.classList.add("rc-glass-modal");
      var wrap = modal.closest(".modal-border, .vfm__content") || modal;
      wrap.style.setProperty("border", "none", "important");
      wrap.style.setProperty("border-radius", "22px", "important");
    }
  }

  function openPairNameModal(sourceModal) {
    if (document.getElementById("rc-pair-name-modal")) return;
    var code = window.__rcPairCode || "";
    try {
      if (!code) {
        var m = String((sourceModal && sourceModal.textContent) || document.body.textContent || "").match(/ra\.pair\s+(\d+)/i);
        if (m) code = m[1];
      }
    } catch (_) {}
    var serverId = null;
    try {
      var sid = location.search.match(/server[_-]?id=(\d+)/i);
      if (sid) serverId = sid[1];
    } catch (_) {}

    var root = document.createElement("div");
    root.id = "rc-pair-name-modal";
    root.innerHTML =
      '<div class="rc-pair-box">' +
        "<h3>Название сервера</h3>" +
        "<p>Сервер успешно подключён. Придумайте короткое имя для отображения в панели.</p>" +
        '<label for="rc-pair-name-input">Название</label>' +
        '<input id="rc-pair-name-input" type="text" maxlength="80" placeholder="Например Test Server" autocomplete="off">' +
        '<div class="rc-pair-actions">' +
          '<button type="button" data-rc-pair-skip>Пропустить</button>' +
          '<button type="button" class="primary" data-rc-pair-save>Сохранить</button>' +
        "</div>" +
      "</div>";
    document.body.appendChild(root);
    var input = root.querySelector("#rc-pair-name-input");
    setTimeout(function () { try { input.focus(); } catch (_) {} }, 50);

    function finish(name) {
      window.__rcPairNameDone = 1;
      window.__checkappPairServerName = name || "";
      root.remove();
      if (!name && !code) return;
      try {
        var headers = { "Content-Type": "application/json", Accept: "application/json" };
        try {
          var tok = localStorage.getItem("token") || localStorage.getItem("access_token") || "";
          if (tok) headers.Authorization = tok.indexOf("Bearer") === 0 ? tok : ("Bearer " + tok);
          var sl = slug();
          if (sl) headers["X-Checkapp-Project"] = sl;
        } catch (_) {}
        var payload = { name: name || "Server" };
        if (code) payload.code = code;
        if (serverId) payload.server_id = Number(serverId);
        fetch("/server/pair", { method: "PUT", credentials: "include", headers: headers, body: JSON.stringify(payload) })
          .catch(function () {});
        /* also fill SPA name input if present */
        document.querySelectorAll("input[placeholder*='назв' i], input[placeholder*='name' i]").forEach(function (el) {
          if (!name) return;
          el.value = name;
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
        });
      } catch (_) {}
    }

    root.querySelector("[data-rc-pair-save]").addEventListener("click", function () {
      finish(String(input.value || "").trim());
    });
    root.querySelector("[data-rc-pair-skip]").addEventListener("click", function () {
      finish("");
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") finish(String(input.value || "").trim());
    });
  }

  function tick() {
    ensureCss();
    decoratePageHeader();
    hideBillingLimits();
    ensurePlayersCards();
    hideSignageLikes();
    polishModals();
    sealPlayerModalClicks();
    hideSectionHeroIcons();
    revertModStats();
    watchPairNameStep();
  }

  ensureCss();
  tick();
  setInterval(tick, 400);

  /* faster reaction on navigation */
  var lastPath = path();
  setInterval(function () {
    var p = path();
    if (p === lastPath) return;
    lastPath = p;
    setTimeout(tick, 30);
    setTimeout(tick, 120);
    setTimeout(tick, 350);
  }, 200);

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", tick);
  window.addEventListener("popstate", function () { setTimeout(tick, 40); });

  try {
    var mo = new MutationObserver(function () {
      if (/\/players(?:\/|$)/i.test(path()) && !document.getElementById("rc-players-cards")) ensurePlayersCards();
      hideSignageLikes();
      hideBillingLimits();
      watchPairNameStep();
    });
    mo.observe(document.documentElement, { childList: true, subtree: true });
  } catch (_) {}

  /* detect successful ra.pair via /server/pair poll */
  try {
    if (!window.__rcPairFetchHooked) {
      window.__rcPairFetchHooked = 1;
      var _fetch = window.fetch;
      if (typeof _fetch === "function") {
        window.fetch = function () {
          var args = arguments;
          var url = String((args[0] && args[0].url) || args[0] || "");
          return _fetch.apply(this, args).then(function (res) {
            try {
              if (/\/server\/pair/i.test(url)) {
                res.clone().json().then(function (data) {
                  if (data && (data.used === true || data.plugin || (data.server && data.used))) {
                    window.__rcPairUsedFlag = 1;
                    window.__rcPairCode = String(data.code || window.__rcPairCode || "");
                    setTimeout(watchPairNameStep, 80);
                  }
                }).catch(function () {});
              }
            } catch (_) {}
            return res;
          });
        };
      }
    }
  } catch (_) {}
})();
