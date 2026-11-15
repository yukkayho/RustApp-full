/**
 * Tier gates + plan modal (stable).
 */
(function () {
  "use strict";

  var TIER = "base";
  var DEMO = false;
  var LAST_SECTION = "";
  var PLAN_PRICES = { base: 0, plus: 30000 };

  function projectSlug() {
    var parts = (location.pathname || "").split("/").filter(Boolean);
    var slug = parts[0] || "";
    var skip = { client: 1, assets: 1, local: 1, login: 1, auth: 1, plugin: 1, utils: 1, uploads: 1, pricing: 1 };
    return skip[slug] ? "" : slug;
  }

  function authHeaders() {
    var headers = { Accept: "application/json", "Content-Type": "application/json" };
    try {
      var token = localStorage.getItem("token") || localStorage.getItem("access_token") || "";
      if (token) headers.Authorization = token.indexOf("Bearer") === 0 ? token : ("Bearer " + token);
    } catch (_) {}
    var slug = projectSlug();
    if (slug) headers["X-Checkapp-Project"] = slug;
    return headers;
  }

  function refreshTier() {
    return fetch("/tariff/", { credentials: "include", cache: "no-store", headers: authHeaders() })
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (data) {
        if (!data) return;
        TIER = String((data.tariff && (data.tariff.tier || data.tariff.slug)) || data.tier || "base").toLowerCase();
      })
      .catch(function () {});
  }

  function isPlus() {
    // Base has full feature access — gates disabled (freeze still handled by SPA billing)
    return true;
  }

  function pathCtx() {
    return (location.pathname || "") + (location.search || "");
  }

  function currentSection() {
    var m = pathCtx().match(/[?&]section=([^&]+)/i);
    return m ? String(m[1]).toLowerCase() : "";
  }

  function isAutokickSection(sec) {
    return sec === "auto-kick" || sec === "autokick";
  }

  function isApiPage() {
    return /(?:section=|tab=)api|\/settings\/.*api|\/integrations\/api/i.test(pathCtx());
  }

  function isAutokickPage() {
    return /(?:section=|tab=)(auto-kick|autokick)|\/auto-kick|autokick/i.test(pathCtx());
  }

  function isStatsPage() {
    return /\/stats(?:\/|$|\?)/i.test(location.pathname || "") || /\/project-stats/i.test(location.pathname || "");
  }

  function isGatedPage() {
    return isStatsPage() || isApiPage() || isAutokickPage();
  }

  function injectCss() {
    if (document.getElementById("checkapp-gates-css")) return;
    var st = document.createElement("style");
    st.id = "checkapp-gates-css";
    st.textContent = [
      "#checkapp-tier-gate{position:fixed;z-index:999999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.45);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px);padding:24px;pointer-events:auto;box-sizing:border-box;}",
      "#checkapp-tier-gate .ck-box{max-width:420px;text-align:center;color:#fff;}",
      "#checkapp-tier-gate .ck-icon{width:42px;height:42px;border-radius:10px;background:#1a3d2a;display:inline-flex;align-items:center;justify-content:center;margin:0 auto 14px;font-size:18px;}",
      "#checkapp-tier-gate .ck-title{font-size:18px;font-weight:700;margin-bottom:8px;}",
      "#checkapp-tier-gate .ck-sub{font-size:14px;color:#aaa;line-height:1.45;}",
      "#checkapp-tier-gate .ck-demo{margin-top:16px;background:#3a3a3a;color:#fff;border:none;border-radius:10px;padding:10px 18px;font-size:14px;font-weight:600;cursor:pointer;}",
      "#checkapp-api-banner{position:fixed;z-index:999998;box-sizing:border-box;border:1px solid #c47a2c;border-radius:6px;padding:22px 24px;background:repeating-linear-gradient(-45deg,#141414,#141414 10px,#171717 10px,#171717 20px);color:#fff;max-width:720px;width:min(720px,calc(100vw - 48px));pointer-events:auto;box-shadow:0 8px 32px rgba(0,0,0,.35);}",
      "#checkapp-api-banner h3{margin:0 0 10px;font-size:18px;font-weight:700;}",
      "#checkapp-api-banner p{margin:0 0 16px;font-size:14px;color:#aaa;line-height:1.5;}",
      "#checkapp-api-banner button{background:#3b82f6;color:#fff;border:none;border-radius:6px;padding:10px 16px;font-size:14px;font-weight:600;cursor:pointer;}",
      "#checkapp-plan-modal.checkapp-plan-root{position:fixed;inset:0;z-index:1000000;display:flex;align-items:center;justify-content:center;padding:16px;box-sizing:border-box;}",
      "#checkapp-plan-modal .checkapp-plan-overlay{position:absolute;inset:0;background:rgba(0,0,0,.45);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);}",
      "#checkapp-plan-modal .cpm-rustapp{position:relative;z-index:2;background:#121212;color:#fff;border-radius:12px;width:min(92vw,780px);box-shadow:0 24px 80px rgba(0,0,0,.75);border:1px solid #2a2a2a;overflow:hidden;}",
      "#checkapp-plan-modal .cpm-rustapp-head{display:flex;align-items:center;justify-content:space-between;padding:18px 20px 14px;}",
      "#checkapp-plan-modal .cpm-rustapp-head h2{margin:0;font-size:17px;font-weight:600;}",
      "#checkapp-plan-modal .cpm-rustapp-close{background:transparent;border:none;color:#888;font-size:24px;line-height:1;cursor:pointer;padding:0 4px;}",
      "#checkapp-plan-modal .cpm-rustapp-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));}",
      "#checkapp-plan-modal .cpm-rustapp-plan{padding:18px 16px 16px;border-right:1px solid #2a2a2a;display:flex;flex-direction:column;gap:10px;}",
      "#checkapp-plan-modal .cpm-rustapp-plan:last-child{border-right:none;}",
      "#checkapp-plan-modal .cpm-plan-top{display:flex;align-items:center;gap:8px;}",
      "#checkapp-plan-modal .cpm-plan-name{font-size:15px;font-weight:600;}",
      "#checkapp-plan-modal .cpm-plan-bolt{width:18px;height:18px;display:inline-flex;}",
      "#checkapp-plan-modal .cpm-plan-bolt.base{color:#3b82f6;}",
      "#checkapp-plan-modal .cpm-plan-bolt.plus{color:#22c55e;}",
      "#checkapp-plan-modal .cpm-plan-bolt.enterprise{color:#e8b86d;}",
      "#checkapp-plan-modal .cpm-plan-price{font-size:24px;font-weight:700;line-height:1.2;}",
      "#checkapp-plan-modal .cpm-plan-price span{font-size:13px;font-weight:400;color:#888;margin-left:2px;}",
      "#checkapp-plan-modal .cpm-plan-btn{width:100%;display:block;box-sizing:border-box;border:none;border-radius:8px;padding:9px 12px;font-size:13px;font-weight:600;cursor:pointer;min-height:38px;text-align:center;}",
      "#checkapp-plan-modal .cpm-plan-btn.current{background:#2a2a2a;color:#cfcfcf;cursor:default;}",
      "#checkapp-plan-modal .cpm-plan-btn.pick{background:#1a3d2a;color:#7dffa3;}",
      "#checkapp-plan-modal .cpm-plan-btn.contact{background:#3a2a1a;color:#e8b86d;}",
      "#checkapp-plan-modal .cpm-plan-divider{border:none;border-top:1px dashed #333;margin:4px 0 8px;}",
      "#checkapp-plan-modal .cpm-plan-features{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:9px;}",
      "#checkapp-plan-modal .cpm-plan-features li{display:flex;align-items:flex-start;gap:8px;font-size:12px;color:#ccc;}",
      "#checkapp-plan-modal .cpm-plan-features li svg{width:15px;height:15px;opacity:.75;flex:0 0 auto;}",
      "#checkapp-plan-modal .cpm-rustapp-foot{display:flex;align-items:flex-start;gap:8px;padding:12px 20px 16px;border-top:1px solid #2a2a2a;background:#1a1a1a;font-size:12px;color:#888;}",
      "#checkapp-plan-modal .cpm-rustapp-foot a{color:#aaa;text-decoration:underline;}",
      "#checkapp-funds-modal{position:fixed;inset:0;z-index:1000001;display:flex;align-items:center;justify-content:center;padding:16px;}",
      "#checkapp-funds-modal .ck-funds-overlay{position:absolute;inset:0;background:rgba(0,0,0,.52);}",
      "#checkapp-funds-modal .ck-funds-box{position:relative;z-index:2;background:#1a1a1a;color:#fff;border-radius:12px;padding:30px 24px 20px;width:min(92vw,356px);text-align:center;box-shadow:0 24px 70px rgba(0,0,0,.7);}",
      "#checkapp-funds-modal .ck-funds-icon{position:relative;width:120px;height:88px;margin:0 auto 10px;}",
      "#checkapp-funds-modal .ck-funds-glow{position:absolute;left:50%;top:38px;width:86px;height:52px;margin-left:-43px;background:radial-gradient(ellipse at center,rgba(245,197,24,.5) 0%,rgba(245,197,24,0) 70%);filter:blur(6px);pointer-events:none;}",
      "#checkapp-funds-modal .ck-funds-tri{position:absolute;left:50%;top:6px;width:64px;height:60px;margin-left:-32px;}",
      "#checkapp-funds-modal .ck-funds-tri.ghost{opacity:.38;}",
      "#checkapp-funds-modal .ck-funds-tri.left{transform:translate(-19px,11px) rotate(-21deg);}",
      "#checkapp-funds-modal .ck-funds-tri.right{transform:translate(19px,11px) rotate(19deg);}",
      "#checkapp-funds-modal .ck-funds-tri.main{z-index:2;filter:drop-shadow(0 7px 8px rgba(0,0,0,.38));}",
      "#checkapp-funds-modal .ck-funds-title{font-size:17px;font-weight:700;margin:0 0 8px;color:#fff;}",
      "#checkapp-funds-modal .ck-funds-text{font-size:13.5px;line-height:1.5;color:#a6a6a6;margin:0 4px 22px;}",
      "#checkapp-funds-modal .ck-funds-btn{width:100%;height:40px;border:none;border-radius:8px;background:#2b2b2b;color:#ececec;font-size:14px;font-weight:600;cursor:pointer;}",
      "body.checkapp-plan-open{overflow:hidden;}",
      "@media(max-width:860px){#checkapp-plan-modal .cpm-rustapp-grid{grid-template-columns:1fr;}}"
    ].join("");
    (document.head || document.documentElement).appendChild(st);
  }

  function mainRect() {
    var main = document.querySelector("main") || document.querySelector("#app > div > div:last-child") || document.querySelector("#app > div");
    if (!main) return null;
    var r = main.getBoundingClientRect();
    if (r.width < 80 || r.height < 80) return null;
    return r;
  }

  function paneRect() {
    var main = document.querySelector("main");
    if (!main) return mainRect();
    var mr = main.getBoundingClientRect();
    var tabs = main.querySelectorAll(".n-tabs-tab, [role='tab']");
    var bottom = 0;
    var n = 0;
    var i;
    for (i = 0; i < tabs.length; i++) {
      var t = String(tabs[i].textContent || "").trim().toLowerCase();
      if (!/(репорт|проверк|бан|авто|действ|api)/i.test(t)) continue;
      n++;
      var b = tabs[i].getBoundingClientRect().bottom;
      if (b > bottom) bottom = b;
    }
    if (n >= 3 && bottom > mr.top + 20) {
      return { top: bottom, left: mr.left, width: mr.width, height: mr.bottom - bottom };
    }
    return mr;
  }

  function positionGate(gate) {
    var r = isStatsPage() ? mainRect() : paneRect();
    if (!r) return;
    gate.style.top = Math.round(r.top) + "px";
    gate.style.left = Math.round(r.left) + "px";
    gate.style.width = Math.round(r.width) + "px";
    gate.style.height = Math.round(r.height) + "px";
  }

  function positionApiBanner(banner) {
    var r = mainRect();
    if (!r) return;
    var w = Math.min(720, Math.round(r.width - 32));
    banner.style.width = w + "px";
    banner.style.top = Math.round(r.top + 120) + "px";
    banner.style.left = Math.round(r.left + (r.width - w) / 2) + "px";
  }

  function removeGate() {
    var g = document.getElementById("checkapp-tier-gate");
    if (g) g.remove();
    var b = document.getElementById("checkapp-api-banner");
    if (b) b.remove();
  }

  function lockHtml(withDemo) {
    var html =
      '<div class="ck-box"><div class="ck-icon">⚡</div>' +
      '<div class="ck-title">Нет доступа к разделу!</div>' +
      '<div class="ck-sub">Текущий тариф не позволяет использовать этот функционал, перейдите на «plus» чтобы получить доступ.</div>';
    if (withDemo) html += '<button type="button" class="ck-demo">Показать демо</button>';
    return html + "</div>";
  }

  function resetAutokickSettings() {
    DEMO = false;
    window.__checkappAutokickDemo = false;
    var main = document.querySelector("main");
    if (!main) return;
    main.querySelectorAll(".n-switch.n-switch--active, .n-switch[aria-checked='true']").forEach(function (sw) {
      try { sw.click(); } catch (_) {}
    });
  }

  function onSectionChange() {
    var sec = currentSection();
    if (isAutokickSection(LAST_SECTION) && !isAutokickSection(sec)) resetAutokickSettings();
    LAST_SECTION = sec;
  }

  function showGate() {
    if (!document.body) return;
    injectCss();
    onSectionChange();
    if (!projectSlug() || isPlus() || !isGatedPage() || document.getElementById("checkapp-plan-modal")) {
      removeGate();
      return;
    }

    if (isApiPage()) {
      document.getElementById("checkapp-tier-gate") && document.getElementById("checkapp-tier-gate").remove();
      var banner = document.getElementById("checkapp-api-banner");
      if (!banner) {
        banner = document.createElement("div");
        banner.id = "checkapp-api-banner";
        banner.innerHTML =
          "<h3>У вас нет доступа к API</h3>" +
          "<p>Доступ к API предоставляется исключительно проектам с тарифным планом Plus. Переключитесь на этот тарифный план, чтобы использовать Checkapp API.</p>" +
          '<button type="button">Улучшить тариф</button>';
        document.body.appendChild(banner);
        banner.querySelector("button").onclick = function (e) {
          e.preventDefault();
          openPlanModal();
        };
      }
      positionApiBanner(banner);
      return;
    }

    document.getElementById("checkapp-api-banner") && document.getElementById("checkapp-api-banner").remove();

    if (isAutokickPage() && DEMO) {
      document.getElementById("checkapp-tier-gate") && document.getElementById("checkapp-tier-gate").remove();
      return;
    }

    var box = document.getElementById("checkapp-tier-gate");
    if (!box) {
      box = document.createElement("div");
      box.id = "checkapp-tier-gate";
      document.body.appendChild(box);
    }
    box.innerHTML = lockHtml(isAutokickPage());
    positionGate(box);
    var demoBtn = box.querySelector(".ck-demo");
    if (demoBtn) {
      demoBtn.onclick = function () {
        DEMO = true;
        window.__checkappAutokickDemo = true;
        box.remove();
      };
    }
  }

  function rub(n) {
    n = Number(n || 0);
    if (n >= 1000000) return "Custom";
    if (n <= 0) return "Free";
    return "₽" + Math.round(n / 100).toLocaleString("ru-RU");
  }

  function boltSvg() {
    return '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M13 2L3 14h8l-1 8 10-12h-8l1-8z"/></svg>';
  }

  function planFeatures(tier) {
    if (tier === "plus") return ["500 000 игроков в БД", "5 серверов", "Дополнительные возможности"];
    if (tier === "enterprise") return ["От 500 000 игроков в БД", "От 5 серверов", "Приоритетная поддержка"];
    return ["100 000 игроков в БД", "2 сервера", "Стандартные возможности"];
  }

  function openInsufficientFundsModal(need) {
    if (window.__checkappRenderFundsModal) {
      window.__checkappRenderFundsModal(need);
      return;
    }
    if (document.getElementById("checkapp-funds-modal")) return;
    injectCss();
    var n = Number(need || 0);
    if (n >= 10000) n = Math.round(n / 100);
    if (!n) n = 300;
    var tri = function (fill, cls) {
      return '<svg class="ck-funds-tri ' + cls + '" viewBox="0 0 64 58" width="64" height="60" fill="none" aria-hidden="true"><path fill="' + fill + '" d="M32 4.4c1.72 0 3.28.9 4.14 2.4L60.7 49.2c.88 1.52.86 3.38-.08 4.86C59.76 55.54 58.16 56.4 56.4 56.4H7.6c-1.76 0-3.36-.86-4.22-2.34-.94-1.48-.96-3.34-.08-4.86L27.86 6.8C28.72 5.3 30.28 4.4 32 4.4z"/><rect x="29.2" y="20.2" width="5.6" height="17.2" rx="2.8" fill="#1a1a1a"/><circle cx="32" cy="43.6" r="3.05" fill="#1a1a1a"/></svg>';
    };
    var root = document.createElement("div");
    root.id = "checkapp-funds-modal";
    root.innerHTML =
      '<div class="ck-funds-overlay"></div><div class="ck-funds-box">' +
      '<div class="ck-funds-icon"><i class="ck-funds-glow"></i>' +
      tri("#C4A016", "ghost left") + tri("#C4A016", "ghost right") + tri("#F5C518", "main") +
      "</div>" +
      '<div class="ck-funds-title">Не хватает средств</div>' +
      '<div class="ck-funds-text">Для перехода на выбранный тарифный план вам нужно ещё ₽' +
      n.toLocaleString("ru-RU") + " на балансе.</div>" +
      '<button type="button" class="ck-funds-btn">Понятно</button></div>';
    root.onclick = function (e) {
      if (e.target.classList.contains("ck-funds-overlay") || e.target.classList.contains("ck-funds-btn")) root.remove();
    };
    document.body.appendChild(root);
  }

  function purchasePlan(planId, tier, onDone) {
    if (String(tier || planId || "").toLowerCase() === "base" || String(planId) === "1") {
      if (window.__checkappShowBaseTariffToast) window.__checkappShowBaseTariffToast();
      else if (window.__checkappShowHumanError) {
        window.__checkappShowHumanError({ error: "base_not_purchasable" }, 400);
      }
      if (onDone) onDone(false);
      return;
    }
    fetch("/tariff/" + encodeURIComponent(tier || planId) + "/select", {
      method: "POST",
      headers: Object.assign({}, authHeaders(), { "X-Checkapp-Plan-Select": "1" }),
      body: "{}"
    })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (d) {
          return { s: r.status, d: d };
        });
      })
      .then(function (p) {
        var need = p.d && (p.d.needed_rub != null ? p.d.needed_rub : Math.ceil(Number(p.d.needed || 0) / 100));
        if (p.s === 402 || (p.d && (p.d.error === "insufficient_balance" || String(p.d.message || "").indexOf("Not enough balance") >= 0))) {
          openInsufficientFundsModal(need);
          if (onDone) onDone(false);
          return;
        }
        if (p.s === 403 || (p.d && p.d.error === "project_blocked")) {
          if (window.__checkappShowProjectBlocked) window.__checkappShowProjectBlocked();
          if (onDone) onDone(false);
          return;
        }
        if (p.s >= 400 || (p.d && p.d.ok === false)) {
          if (window.__checkappShowHumanError) window.__checkappShowHumanError(p.d || {}, p.s);
          if (onDone) onDone(false);
          return;
        }
        location.reload();
      })
      .catch(function () {
        if (window.__checkappOpenInsufficientFunds) window.__checkappOpenInsufficientFunds(300);
        else if (window.__checkappShowHumanError) {
          window.__checkappShowHumanError({ error: "insufficient_balance" }, 402);
        }
        if (onDone) onDone(false);
      });
  }

  function interceptNativePlanSelect(e) {
    var btn = e.target && e.target.closest && e.target.closest(
      ".change-plan-modal .select-button, .select-button.plus, .select-button.base, .plan .select-button, button.plus, button.base"
    );
    if (!btn) {
      var maybe = e.target && e.target.closest && e.target.closest("button");
      if (maybe && /billing/i.test(String(location.search || "") + String(location.pathname || ""))) {
        var txt = String(maybe.textContent || "").replace(/\s+/g, " ").trim();
        var card = maybe.closest && maybe.closest(".plan, .cpm-rustapp-plan, [class*='plan']");
        if (card && /^выбрать$/i.test(txt)) btn = maybe;
      }
    }
    if (!btn || btn.classList.contains("current") || btn.disabled) return;
    if (btn.classList.contains("enterprise") || btn.classList.contains("contact")) return;
    var tier = btn.classList.contains("plus") ? "plus" : (btn.classList.contains("base") ? "base" : "");
    if (!tier) {
      var cardCls = String((btn.closest && btn.closest(".plan, .cpm-rustapp-plan, [class*='plan']") && btn.closest(".plan, .cpm-rustapp-plan, [class*='plan']").className) || "") + " " + String(btn.className || "");
      if (/plus/i.test(cardCls)) tier = "plus";
      else if (/base/i.test(cardCls)) tier = "base";
    }
    if (!tier) return;
    var ids = { base: 1, plus: 2 };
    e.preventDefault();
    e.stopImmediatePropagation();
    btn.disabled = true;
    var prev = btn.textContent;
    btn.textContent = "...";
    purchasePlan(ids[tier], tier, function () {
      btn.disabled = false;
      btn.textContent = prev || "Выбрать";
    });
  }

  function openPlanModal() {
    if (document.getElementById("checkapp-plan-modal")) return;
    injectCss();
    removeGate();
    var root = document.createElement("div");
    root.id = "checkapp-plan-modal";
    root.className = "checkapp-plan-root";
    root.innerHTML =
      '<div class="checkapp-plan-overlay"></div><div class="cpm-rustapp" role="dialog">' +
      '<div class="cpm-rustapp-head"><h2>Выберите тариф</h2><button type="button" class="cpm-rustapp-close" data-close="1">×</button></div>' +
      '<div class="cpm-rustapp-grid"></div>' +
      '<div class="cpm-rustapp-foot"><span>Тарифы могут отличаться возможностями, смотрите <a href="/pricing">сравнение тарифов</a>.</span></div></div>';
    var grid = root.querySelector(".cpm-rustapp-grid");
    ["base", "plus", "enterprise"].forEach(function (tier) {
      var contact = tier === "enterprise";
      var price = contact ? "Custom" : rub(PLAN_PRICES[tier]);
      var suffix = contact || Number(PLAN_PRICES[tier] || 0) <= 0 ? "" : "<span>/месяц</span>";
      var current = TIER === tier;
      var col = document.createElement("div");
      col.className = "cpm-rustapp-plan";
      var feats = "";
      planFeatures(tier).forEach(function (f) { feats += "<li><span>" + f + "</span></li>"; });
      col.innerHTML =
        '<div class="cpm-plan-top"><span class="cpm-plan-name">' + tier.charAt(0).toUpperCase() + tier.slice(1) + '</span>' +
        '<span class="cpm-plan-bolt ' + tier + '">' + boltSvg() + "</span></div>" +
        '<div class="cpm-plan-price">' + price + suffix + "</div>" +
        '<button type="button" class="cpm-plan-btn ' + (current ? "current" : (contact ? "contact" : "pick")) + '" data-tier="' + tier + '"' + (current ? " disabled" : "") + ">" +
        (current ? "Текущий тариф" : (contact ? "Связаться" : "Выбрать")) + "</button>" +
        '<hr class="cpm-plan-divider"><ul class="cpm-plan-features">' + feats + "</ul>";
      grid.appendChild(col);
    });
    root.onclick = function (e) {
      var t = e.target;
      if (!t) return;
      if (t.getAttribute("data-close") || t.classList.contains("checkapp-plan-overlay") || t.classList.contains("cpm-rustapp-close")) {
        root.remove();
        document.body.classList.remove("checkapp-plan-open");
        showGate();
        return;
      }
      var btn = t.closest && t.closest(".cpm-plan-btn.pick, .cpm-plan-btn.contact");
      if (!btn || btn.disabled) return;
      if (btn.classList.contains("contact")) {
        window.open("https://t.me/RustCheckcc", "_blank");
        return;
      }
      btn.disabled = true;
      btn.textContent = "...";
      purchasePlan(btn.getAttribute("data-tier"), btn.getAttribute("data-tier"), function () {
        btn.disabled = false;
        btn.textContent = "Выбрать";
      });
    };
    document.body.appendChild(root);
    document.body.classList.add("checkapp-plan-open");
  }

  window.__checkappOpenPlanModal = openPlanModal;
  window.__checkappOpenInsufficientFunds = openInsufficientFundsModal;
  window.__checkappGatesOk = true;
  window.__checkappGatesVer = "funds-guard";

  function tick() {
    try { showGate(); } catch (_) {}
  }

  function boot() {
    LAST_SECTION = currentSection();
    refreshTier().then(tick);
    setInterval(refreshTier, 8000);
    setInterval(tick, 300);
    window.addEventListener("resize", tick);
    window.addEventListener("popstate", function () { onSectionChange(); refreshTier().then(tick); });
    document.addEventListener("click", function (e) {
      var btn = e.target && e.target.closest && e.target.closest("button, a");
      if (!btn) return;
      var txt = String(btn.textContent || "").trim();
      if (/сменить тариф|улучшить тариф|change plan|upgrade plan/i.test(txt)) {
        e.preventDefault();
        e.stopPropagation();
        openPlanModal();
      }
    }, true);
    document.addEventListener("click", interceptNativePlanSelect, true);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
