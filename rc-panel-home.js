(function () {
  if (window.__rcPanelHomeVer >= 11) return;
  window.__rcPanelHomeVer = 11;

  var I18N = {
    ru: {
      home: "Главная",
      subtitle: "Обзор системы и серверов",
      online: "Онлайн игроков",
      onlineHint: "Текущий онлайн на всех серверах",
      peak: "Пик онлайна за день",
      peakHint: "Максимум за сегодня",
      servers: "Активных блокировок",
      serversHint: "Сейчас действуют",
      joining: "Подключаются",
      joiningHint: "Игроки подключаются",
      queued: "В очереди",
      queuedHint: "Игроки в очереди",
      listTitle: "Список серверов",
      listSub: "Все подключенные серверы",
      empty: "Нет подключенных серверов",
      players: "Игроков",
      onlineBadge: "Online",
      offlineBadge: "Offline",
      updated: "Обновл."
    },
    en: {
      home: "Home",
      subtitle: "System and server overview",
      online: "Players online",
      onlineHint: "Current online on all servers",
      peak: "Peak online today",
      peakHint: "Maximum today",
      servers: "Active bans",
      serversHint: "Currently in effect",
      joining: "Joining",
      joiningHint: "Players connecting",
      queued: "In queue",
      queuedHint: "Players in queue",
      listTitle: "Server list",
      listSub: "All connected servers",
      empty: "No connected servers",
      players: "Players",
      onlineBadge: "Online",
      offlineBadge: "Offline",
      updated: "Updated"
    }
  };

  function t(key) {
    var dict = I18N[lang()] || I18N.ru;
    return dict[key] || I18N.ru[key] || key;
  }

  function lang() {
    try {
      var v = String(localStorage.getItem("rustcheck-lang") || localStorage.getItem("locale") || "").toLowerCase();
      if (v.indexOf("en") === 0) return "en";
    } catch (_) {}
    return "ru";
  }

  function slug() {
    var parts = String(location.pathname || "").split("/").filter(Boolean);
    var skip = { client: 1, home: 1, settings: 1, players: 1, profile: 1, auth: 1 };
    if (parts[0] && !skip[parts[0].toLowerCase()]) return parts[0];
    try { return String(localStorage.getItem("checkapp_project_slug") || ""); } catch (_) { return ""; }
  }

  function isHomePath() {
    var parts = String(location.pathname || "").split("/").filter(Boolean);
    return parts.length >= 2 && /^home$/i.test(parts[1]);
  }

  function homeUrl() {
    var s = slug();
    return s ? "/" + s + "/home" : "/home";
  }

  function serversUrl() {
    var s = slug();
    return s ? "/" + s + "/servers" : "/servers";
  }

  function authHeaders() {
    var h = { Accept: "application/json", "X-Checkapp-Project": slug() };
    try {
      var tok = localStorage.getItem("token") || localStorage.getItem("access_token") || "";
      if (tok) h.Authorization = tok.indexOf("Bearer") === 0 ? tok : ("Bearer " + tok);
    } catch (_) {}
    return h;
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtTime(sec) {
    var n = Number(sec || 0);
    if (!n) return "—";
    if (n > 1e12) n = Math.floor(n / 1000);
    var d = new Date(n * 1000);
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleTimeString(lang() === "en" ? "en-GB" : "ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  var ICO = {
    home: '<svg viewBox="0 0 24 24"><path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1v-9.5Z"/></svg>',
    users: '<svg viewBox="0 0 24 24"><path d="M8 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm9 1a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7ZM2.5 19.2C3.4 15.6 5.9 14 8 14s4.6 1.6 5.5 5.2c.2.7-.4 1.8-1.2 1.8H3.7c-.8 0-1.4-1.1-1.2-1.8ZM14.2 19.2c.6-2.3 1.9-4 3.8-4.8.6.3 1.3.6 2.1.6 1.5 0 2.9.7 3.6 2.4.3.8-.3 1.6-1.1 1.6h-7.6c-.6 0-1-.5-.8-1.8Z"/></svg>',
    peak: '<svg viewBox="0 0 24 24"><path d="M4 19h16v2H4v-2Zm1.7-6.3 3.8 3.8 5.2-8.3 3.6 4.3 1.5-1.3-5.4-6.4-5.3 8.5-2.2-2.2-2.2 1.6Z"/></svg>',
    rack: '<svg viewBox="0 0 24 24"><path d="M4 4h16v5H4V4Zm0 7h16v5H4v-5Zm0 7h16v5H4v-5ZM7 6.5h2V7H7v-.5Zm0 7h2V14H7v-.5Zm0 7h2V21H7v-.5Z"/></svg>',
    lock: '<svg viewBox="0 0 24 24"><path d="M7 10V8a5 5 0 0 1 10 0v2h1.5A1.5 1.5 0 0 1 20 11.5v8A1.5 1.5 0 0 1 18.5 21h-13A1.5 1.5 0 0 1 4 19.5v-8A1.5 1.5 0 0 1 5.5 10H7Zm2 0h6V8a3 3 0 0 0-6 0v2Zm3 3.25a1.75 1.75 0 0 0-.75 3.33V18h1.5v-1.42A1.75 1.75 0 0 0 12 13.25Z"/></svg>',
    join: '<svg viewBox="0 0 24 24"><path d="M12 3a9 9 0 1 0 9 9h-2a7 7 0 1 1-7-7V3Zm1 4v5.2l3.4 2-1 1.6L11 13V7h2Z"/></svg>',
    queue: '<svg viewBox="0 0 24 24"><path d="M7 6h14v2H7V6Zm0 5h14v2H7v-2Zm0 5h14v2H7v-2ZM4 6.5a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3Zm0 5a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3Zm0 5a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3Z"/></svg>'
  };

  function skeletonHtml() {
    return (
      '<div class="rph-head"><div class="rph-head-icon">' + ICO.home + '</div><div>' +
        '<h1 class="rph-title">' + esc(t("home")) + '</h1>' +
        '<p class="rph-sub">' + esc(t("subtitle")) + '</p></div></div>' +
      '<div class="rph-stats">' +
        statCard("blue", ICO.users, t("online"), "—", t("onlineHint")) +
        statCard("orange", ICO.peak, t("peak"), "—", t("peakHint")) +
        statCard("sky", ICO.lock, t("servers"), "—", t("serversHint")) +
        statCard("amber", ICO.join, t("joining"), "—", t("joiningHint")) +
        statCard("red", ICO.queue, t("queued"), "—", t("queuedHint")) +
      '</div>' +
      '<div class="rph-list-wrap"><div class="rph-list-head"><div class="rph-list-ico">' + ICO.rack + '</div><div>' +
        '<p class="rph-list-title">' + esc(t("listTitle")) + '</p>' +
        '<p class="rph-list-sub">' + esc(t("listSub")) + '</p></div></div>' +
        '<div class="rph-grid" data-rph-grid></div></div>'
    );
  }

  function statCard(tone, icon, label, value, hint) {
    var n = Number(String(value).replace(/[^\d.-]/g, ""));
    if (!isFinite(n)) n = 0;
    return (
      '<div class="rph-stat"><div class="rph-stat-top"><span class="rph-ico ' + tone + '">' + icon + '</span>' +
      '<span>' + esc(label) + '</span></div>' +
      '<div class="rph-stat-value" data-rc-count="' + n + '">0</div>' +
      '<div class="rph-stat-hint">' + esc(hint) + '</div></div>'
    );
  }

  function animateCounts(root) {
    if (!root) return;
    var nodes = root.querySelectorAll("[data-rc-count]");
    nodes.forEach(function (el) {
      var target = Number(el.getAttribute("data-rc-count") || 0);
      if (!isFinite(target)) target = 0;
      var from = Number(String(el.textContent || "0").replace(/[^\d.-]/g, "")) || 0;
      if (from === target && el.getAttribute("data-rc-count-done") === "1") {
        el.textContent = String(target);
        return;
      }
      el.setAttribute("data-rc-count-done", "1");
      var start = performance.now();
      var dur = 900;
      function frame(now) {
        var p = Math.min(1, (now - start) / dur);
        var eased = 1 - Math.pow(1 - p, 3);
        var cur = Math.round(from + (target - from) * eased);
        el.textContent = String(cur);
        if (p < 1) requestAnimationFrame(frame);
        else el.textContent = String(target);
      }
      requestAnimationFrame(frame);
    });
  }

  function render(root, data) {
    data = data || {};
    var servers = Array.isArray(data.servers) ? data.servers : [];
    var bans = Number(data.active_bans || 0) || 0;
    var firstPaint = !root.getAttribute("data-rc-home-ready");
    root.innerHTML =
      '<div class="rph-head"><div class="rph-head-icon">' + ICO.home + '</div><div>' +
        '<h1 class="rph-title">' + esc(t("home")) + '</h1>' +
        '<p class="rph-sub">' + esc(t("subtitle")) + '</p></div></div>' +
      '<div class="rph-stats">' +
        statCard("blue", ICO.users, t("online"), String(data.online || 0), t("onlineHint")) +
        statCard("orange", ICO.peak, t("peak"), String(data.peak_today || 0), t("peakHint")) +
        statCard("sky", ICO.lock, t("servers"), String(bans), t("serversHint")) +
        statCard("amber", ICO.join, t("joining"), String(data.joining || 0), t("joiningHint")) +
        statCard("red", ICO.queue, t("queued"), String(data.queued || 0), t("queuedHint")) +
      '</div>' +
      '<div class="rph-list-wrap"><div class="rph-list-head"><div class="rph-list-ico">' + ICO.rack + '</div><div>' +
        '<p class="rph-list-title">' + esc(t("listTitle")) + '</p>' +
        '<p class="rph-list-sub">' + esc(t("listSub")) + '</p></div></div>' +
        (servers.length ? ('<div class="rph-grid">' + servers.map(serverCard).join("") + '</div>') :
          ('<div class="rph-empty">' + esc(t("empty")) + '</div>')) +
      '</div>';
    root.setAttribute("data-rc-home-ready", "1");
    if (firstPaint) {
      root.querySelectorAll("[data-rc-count]").forEach(function (el) { el.textContent = "0"; el.removeAttribute("data-rc-count-done"); });
    }
    animateCounts(root);
  }

  function serverCard(s) {
    s = s || {};
    var on = !!s.connected;
    var name = s.name || s.hostname || "Rust";
    var online = on ? Number(s.online || 0) : 0;
    var slots = Number(s.slots || 0) || 100;
    return (
      '<a class="rph-server" href="' + esc(serversUrl()) + '">' +
        '<div class="rph-server-top"><div class="rph-server-name">' + esc(name) + '</div>' +
        '<div class="rph-slots">' + online + " / " + slots + '</div></div>' +
        '<div class="rph-server-meta">' +
          '<span class="rph-badge ' + (on ? "on" : "off") + '"><span class="rph-dot"></span>' +
          esc(on ? t("onlineBadge") : t("offlineBadge")) + '</span>' +
          '<span class="rph-upd">' + esc(t("updated")) + " " + esc(fmtTime(s.last_seen)) + '</span>' +
        '</div>' +
        '<div class="rph-players">' + esc(t("players")) + ": " + online + '</div>' +
      '</a>'
    );
  }

  var timer = 0;

  function loadInto(root) {
    fetch("/server/overview", { credentials: "include", cache: "no-store", headers: authHeaders() })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (data) { if (root && root.isConnected) render(root, data); })
      .catch(function () { if (root && root.isConnected) render(root, {}); });
  }

  var leavingUntil = 0;

  function unmountPanelHome() {
    if (timer) {
      clearInterval(timer);
      timer = 0;
    }
    var el = document.getElementById("rc-panel-home");
    if (el) el.remove();
    document.documentElement.classList.remove("rc-panel-home-on");
    syncNavActive();
  }

  function mountPanelHome() {
    if (Date.now() < leavingUntil) return;
    if (!isHomePath()) {
      unmountPanelHome();
      return;
    }
    document.documentElement.classList.add("rc-panel-home-on");
    var wrap = document.querySelector(".content-wrapper");
    if (!wrap) return;
    var root = document.getElementById("rc-panel-home");
    if (!root) {
      root = document.createElement("div");
      root.id = "rc-panel-home";
      root.innerHTML = skeletonHtml();
      wrap.appendChild(root);
      loadInto(root);
    }
    syncNavActive();
    if (!timer) {
      timer = setInterval(function () {
        var el = document.getElementById("rc-panel-home");
        if (el) loadInto(el);
      }, 8000);
    }
  }

  function syncNavActive() {
    var on = isHomePath();
    document.querySelectorAll(".navigation a.item-row").forEach(function (a) {
      var mine = a.getAttribute("data-rc-panel-home-link") === "1" || !!(a.closest && a.closest("[data-rc-panel-home-nav]"));
      if (mine) {
        a.classList.toggle("router-link-active", on);
        a.classList.toggle("router-link-exact-active", on);
      } else if (on) {
        a.classList.remove("router-link-active", "router-link-exact-active");
        a.removeAttribute("aria-current");
      }
    });
  }

  function vueRouter() {
    try {
      var app = document.querySelector("#app");
      return app && app.__vue_app__ && app.__vue_app__.config && app.__vue_app__.config.globalProperties && app.__vue_app__.config.globalProperties.$router;
    } catch (_) {
      return null;
    }
  }

  function routePath(href) {
    try {
      var u = new URL(href, location.origin);
      return u.pathname + u.search + u.hash;
    } catch (_) {
      return href || "";
    }
  }

  function currentVuePath() {
    var router = vueRouter();
    if (!router) return "";
    try {
      var cur = router.currentRoute && (router.currentRoute.value || router.currentRoute);
      return cur ? String(cur.fullPath || cur.path || "") : "";
    } catch (_) {
      return "";
    }
  }

  function goToPanel(href) {
    href = routePath(href);
    if (!href) return;
    leavingUntil = Date.now() + 2500;
    unmountPanelHome();
    try { history.pushState({ rcPanelHome: 0 }, "", href); } catch (_) {}
    var router = vueRouter();
    var already = currentVuePath().split("?")[0] === href.split("?")[0];
    try {
      if (!already && router && typeof router.push === "function") {
        router.push(href).catch(function () { location.assign(href); });
      } else if (!already && !router) {
        location.assign(href);
      }
    } catch (_) {
      location.assign(href);
    }
    setTimeout(function () {
      if (currentVuePath().split("?")[0] === href.split("?")[0]) return;
      location.assign(href);
    }, 450);
  }

  function goHome(ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopPropagation();
    }
    leavingUntil = 0;
    var url = homeUrl();
    try { history.pushState({ rcPanelHome: 1 }, "", url); } catch (_) {}
    mountPanelHome();
  }

  document.addEventListener("click", function (e) {
    var a = e.target && e.target.closest && e.target.closest(".navigation a");
    if (!a) return;
    if (a.getAttribute("data-rc-panel-home-link") === "1" || a.closest("[data-rc-panel-home-nav]")) {
      e.preventDefault();
      e.stopPropagation();
      if (e.stopImmediatePropagation) e.stopImmediatePropagation();
      goHome();
      return;
    }
    if (!isHomePath()) return;
    var href = routePath(a.href || a.getAttribute("href") || "");
    if (!href || /\/home(?:\/|$|\?|#)/i.test(href)) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
    goToPanel(href);
  }, true);

  window.addEventListener("popstate", function () {
    leavingUntil = 0;
    mountPanelHome();
  });

  function stampV(el, from) {
    if (!el || !from) return;
    [].forEach.call(from.attributes, function (attr) {
      if (attr.name.indexOf("data-v-") === 0) el.setAttribute(attr.name, attr.value);
    });
  }

  function injectNav() {
    var nav = document.querySelector(".navigation");
    if (!nav) return;
    var sections = nav.querySelector(".sections");
    if (!sections) return;
    var s = slug();
    if (!s) return;
    var sample = nav.querySelector(".sections .items .item-row:not([data-rc-panel-home-link])") || nav.querySelector(".sections .item-row:not([data-rc-panel-home-link])");
    var itemsWrap = sample && (sample.closest(".items") || sample.parentElement);
    var box = nav.querySelector("[data-rc-panel-home-nav]");
    if (!box) {
      box = document.createElement("div");
      box.setAttribute("data-rc-panel-home-nav", "1");
      box.className = itemsWrap ? itemsWrap.className : "items";
      box.classList.add("rc-home-nav");
      stampV(box, itemsWrap);
      sections.insertBefore(box, sections.firstChild);
    }
    var link = box.querySelector("a[data-rc-panel-home-link]");
    var stale = link && (!link.querySelector(".flex") || !link.querySelector("svg") || !link.querySelector(".item-name"));
    if (!link || stale) {
      if (link) link.remove();
      link = document.createElement("a");
      link.className = sample ? sample.className : "item-row";
      link.classList.remove("router-link-active", "router-link-exact-active");
      link.removeAttribute("aria-current");
      link.setAttribute("data-rc-panel-home-link", "1");
      var nameClass = "item-name";
      var wrapClass = "flex gap-2 items-center";
      if (sample) {
        var sp = sample.querySelector("p, .item-name");
        if (sp && sp.className) nameClass = sp.className;
        var wrap = sample.querySelector(".flex");
        if (wrap && wrap.className) wrapClass = wrap.className;
      }
      link.innerHTML = '<div class="' + wrapClass + '">' +
        ICO.home.replace("<svg ", '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" ') +
        '<p class="' + nameClass + '"></p></div>';
      stampV(link, sample);
      link.querySelectorAll("*").forEach(function (node) { stampV(node, sample); });
      if (sample) {
        var sWrap = sample.querySelector(".flex");
        var sSvg = sample.querySelector("svg");
        var sName = sample.querySelector("p, .item-name");
        stampV(link.querySelector(".flex"), sWrap);
        stampV(link.querySelector("svg"), sSvg);
        stampV(link.querySelector("p"), sName);
      }
      box.insertBefore(link, box.firstChild);
    }
    link.href = homeUrl();
    var label = link.querySelector("p, .item-name");
    if (label) label.textContent = t("home");
    if (box.parentNode !== sections) sections.insertBefore(box, sections.firstChild);
    syncNavActive();
    bootNavMotion();
  }

  window.__rcNavMotionClickGen = 10;

  function bootNavMotion() {
    var root = document.querySelector(".navigation .sections");
    if (!root) return;
    if (!window.__rcNavMotionObs) {
      window.__rcNavMotionObs = new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
          var el = muts[i].target;
          if (!el || el.nodeType !== 1) continue;
          if (!el.classList || !el.classList.contains("items")) continue;
          if (el.getAttribute("data-rc-panel-home-nav") === "1" || el.classList.contains("rc-home-nav")) continue;
          if (el.__rcAnim) continue;
          var hidden = el.style.display === "none";
          if (hidden && !el.__rcAccHidden) {
            el.__rcAccHidden = true;
          } else if (!hidden && el.__rcAccHidden) {
            el.__rcAccHidden = false;
            playAccOpen(el);
          }
        }
      });
    }
    try {
      window.__rcNavMotionObs.observe(root, { subtree: true, attributes: true, attributeFilter: ["style"] });
    } catch (_) {}
    root.querySelectorAll(":scope > div > .items").forEach(function (el) {
      if (el.classList.contains("rc-home-nav")) return;
      el.__rcAccHidden = el.style.display === "none" || getComputedStyle(el).display === "none";
    });
    relabelNavCategories();
  }

  function relabelNavCategories() {
    var root = document.querySelector(".navigation .sections");
    if (!root) return;
    root.querySelectorAll(":scope > div > .section, :scope > .section").forEach(function (el) {
      var txt = String(el.textContent || "").replace(/\s+/g, " ").trim();
      var low = txt.toLowerCase();
      var next = "";
      if (/модерац|moderat/.test(low)) next = "MODERATION";
      else if (/управл|control|^settings$|^настройки$/.test(low) || low === "settings") next = "CONTROL";
      else if (/^проект|^project$/.test(low)) next = "PROJECT";
      if (!next) return;
      var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      var node;
      while ((node = walker.nextNode())) {
        if (String(node.textContent || "").trim()) {
          node.textContent = next;
          break;
        }
      }
      el.classList.add("rc-nav-cat");
    });
    document.querySelectorAll(".navigation a .item-name, .navigation .item-name").forEach(function (el) {
      var t = String(el.textContent || "").replace(/\s+/g, " ").trim();
      if (/^Общее$|^General$|^About$/i.test(t)) el.textContent = "Настройки";
    });
  }

  document.addEventListener("click", function (e) {
    if (window.__rcNavMotionClickGen !== 10) return;
    var sec = e.target && e.target.closest && e.target.closest(".navigation .sections .section");
    if (!sec) return;
    var group = sec.parentElement;
    var items = group && group.querySelector(":scope > .items");
    if (!items || items.classList.contains("rc-home-nav")) return;
    if (items.__rcSkip) {
      items.__rcSkip = 0;
      return;
    }
    if (items.__rcAnim) {
      e.preventDefault();
      e.stopPropagation();
      if (e.stopImmediatePropagation) e.stopImmediatePropagation();
      return;
    }
    var hidden = items.style.display === "none" || getComputedStyle(items).display === "none";
    if (!hidden) {
      e.preventDefault();
      e.stopPropagation();
      if (e.stopImmediatePropagation) e.stopImmediatePropagation();
      playAccClose(items, function () {
        items.__rcSkip = 1;
        items.__rcAccHidden = true;
        try { sec.click(); } catch (_) {}
      });
      return;
    }
    items.style.overflow = "hidden";
    items.style.maxHeight = "0px";
    items.style.opacity = "0";
  }, true);

  function playAccClose(el, done) {
    if (el.__rcAnim) return;
    el.__rcAnim = 1;
    var h = el.scrollHeight || Math.round(el.getBoundingClientRect().height) || 0;
    el.style.display = "flex";
    el.style.overflow = "hidden";
    el.style.maxHeight = (h || 240) + "px";
    el.style.opacity = "1";
    el.style.pointerEvents = "none";
    void el.offsetHeight;
    el.style.transition = "max-height .3s cubic-bezier(.22,1,.36,1), opacity .2s ease";
    el.style.maxHeight = "0px";
    el.style.opacity = "0";
    clearTimeout(el.__rcT);
    el.__rcT = setTimeout(function () {
      el.style.removeProperty("max-height");
      el.style.removeProperty("opacity");
      el.style.removeProperty("overflow");
      el.style.removeProperty("transition");
      el.style.removeProperty("pointer-events");
      el.__rcAnim = 0;
      if (typeof done === "function") done();
    }, 300);
  }

  function playAccOpen(el) {
    if (el.__rcAnim) return;
    el.__rcAnim = 1;
    el.style.display = "flex";
    el.style.overflow = "hidden";
    if (!el.style.maxHeight) el.style.maxHeight = "0px";
    if (!el.style.opacity) el.style.opacity = "0";
    var h = el.scrollHeight;
    if (!h) {
      el.style.maxHeight = "none";
      h = el.scrollHeight;
      el.style.maxHeight = "0px";
    }
    void el.offsetHeight;
    el.style.transition = "max-height .3s cubic-bezier(.22,1,.36,1), opacity .2s ease";
    el.style.maxHeight = (h || 240) + "px";
    el.style.opacity = "1";
    clearTimeout(el.__rcT);
    el.__rcT = setTimeout(function () {
      el.style.removeProperty("max-height");
      el.style.removeProperty("opacity");
      el.style.removeProperty("overflow");
      el.style.removeProperty("transition");
      el.__rcAnim = 0;
    }, 300);
  }

  window.mountPanelHome = mountPanelHome;
  window.unmountPanelHome = unmountPanelHome;
  window.injectPanelHomeNav = injectNav;
  window.__rcPanelHomeGo = goHome;
})();
