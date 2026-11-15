/**
 * Checkapp local bridge: same UI, no rustapp.io, local API only.
 */
(function () {
  /* Classic mode (window.__RC_CLASSIC__ = true, set in index.html) keeps the
     original rustapp.io design: no rc-home / rc-panel-home / rc-ui-polish /
     rc-app-bg layers are injected. All entry points below honour this flag. */
  var RC_CLASSIC = !!window.__RC_CLASSIC__;
  /* Instant hide: billing limits + signage like — before Vue paints */
  try {
    if (!RC_CLASSIC && !document.getElementById("rc-ui-polish-critical")) {
      var __rcCrit = document.createElement("style");
      __rcCrit.id = "rc-ui-polish-critical";
      __rcCrit.textContent =
        ".payments-tab-general .usage,.payments-tab-general .usage-container," +
        ".content .usage:has(.usage-container),.content .usage:has(.text-head)," +
        '[data-rc-hide-billing-limits="1"],.rc-hide-billing-limits{display:none!important;height:0!important;overflow:hidden!important;opacity:0!important;visibility:hidden!important;}' +
        '.signage-card .buttons > .ra-button.preset.default,.signage-card .buttons > .ra-button.preset.liked,' +
        '.signage-card .buttons > button.preset.default,.signage-card .buttons > button.preset.liked,' +
        '.signage-card .flex-shrink-0,.signage-card [class*="flex-shrink-0"],.rc-hide-like{display:none!important;width:0!important;min-width:0!important;padding:0!important;margin:0!important;opacity:0!important;pointer-events:none!important;}';
      (document.head || document.documentElement).appendChild(__rcCrit);
    }
  } catch (_) {}

  /* Insecure-context clipboard polyfill.
     navigator.clipboard exists only in secure contexts (https / localhost).
     On plain http (our deployment) it is undefined, so every SPA copy button
     (server connection code, API key, …) dies inside
     `await navigator.clipboard.writeText(...)` with a TypeError and silently
     does nothing. Provide an execCommand/textarea-based polyfill instead. */
  try {
    var __rcHasNativeClip = false;
    try {
      __rcHasNativeClip = !!(navigator.clipboard && navigator.clipboard.writeText);
    } catch (_) { __rcHasNativeClip = false; }
    if (!__rcHasNativeClip) {
      function __rcCopyWithTextarea(text) {
        var ta = document.createElement("textarea");
        ta.value = text == null ? "" : String(text);
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.top = "-9999px";
        ta.style.left = "-9999px";
        ta.style.opacity = "0";
        var host = document.body || document.documentElement;
        host.appendChild(ta);
        var sel = document.getSelection();
        var prevRange = null;
        try { prevRange = sel && sel.rangeCount > 0 ? sel.getRangeAt(0) : null; } catch (_) {}
        var prevFocus = null;
        try { prevFocus = document.activeElement; } catch (_) {}
        ta.focus();
        ta.select();
        try { ta.setSelectionRange(0, ta.value.length); } catch (_) {}
        var ok = false;
        try { ok = !!document.execCommand("copy"); } catch (_) { ok = false; }
        try { ta.remove(); } catch (_) { try { host.removeChild(ta); } catch (_) {} }
        try {
          if (sel && prevRange) { sel.removeAllRanges(); sel.addRange(prevRange); }
        } catch (_) {}
        try { if (prevFocus && prevFocus.focus) prevFocus.focus(); } catch (_) {}
        return ok;
      }
      var __rcClipPolyfill = {
        writeText: function (text) {
          return new Promise(function (resolve, reject) {
            function run() {
              try {
                if (__rcCopyWithTextarea(text)) {
                  window.__RC_CLIPBOARD_POLYFILLED = true;
                  resolve(undefined);
                } else {
                  reject(new Error("clipboard: execCommand copy failed"));
                }
              } catch (err) { reject(err); }
            }
            if (document.body) run();
            else document.addEventListener("DOMContentLoaded", run, { once: true });
          });
        },
        write: function (items) {
          var text = "";
          try {
            if (items && items.length && items[0] && typeof items[0].getType === "function") {
              var t = items[0].getType("text/plain");
              /* ClipboardItem blobs are async; text-only write is enough here */
              text = t && typeof t.text === "function" ? t.text() : "";
            }
          } catch (_) {}
          return this.writeText(text);
        }
      };
      try {
        Object.defineProperty(navigator, "clipboard", {
          value: __rcClipPolyfill,
          configurable: true,
          writable: true
        });
      } catch (_) {
        try { navigator.clipboard = __rcClipPolyfill; } catch (_) {}
      }
    }
  } catch (_) {}

  var REVOKED_SESSIONS_KEY = "ca_revoked_sessions";
  var DISCORD_CACHE_KEY = "ca_discord_link";
  function readJsonStore(key, fallback) {
    try {
      var raw = localStorage.getItem(key);
      if (!raw) return fallback;
      var parsed = JSON.parse(raw);
      return parsed != null ? parsed : fallback;
    } catch (_) {
      return fallback;
    }
  }
  function writeJsonStore(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); } catch (_) {}
  }
  function rememberRevokedSession(row) {
    if (row && (row.current || row.is_current)) return;
    var keys = [];
    var ip = String((row && (row.ip || (row.ip_details && row.ip_details.ip))) || "").trim();
    if (ip) keys.push(ip);
    if (row && row.id != null) keys.push(String(row.id));
    if (row && row.key) keys.push(String(row.key));
    if (row && row.serial) keys.push(String(row.serial));
    var list = readJsonStore(REVOKED_SESSIONS_KEY, []);
    if (!Array.isArray(list)) list = [];
    keys.forEach(function (k) {
      if (k && list.indexOf(k) < 0) list.push(k);
    });
    writeJsonStore(REVOKED_SESSIONS_KEY, list);
  }
  function extractSessionIdent(url, body) {
    var parsed = {};
    try { parsed = typeof body === "string" ? JSON.parse(body || "{}") : (body || {}); } catch (_) { parsed = {}; }
    if (!parsed || typeof parsed !== "object") parsed = {};
    var ident = String(parsed.id || parsed.key || parsed.serial || parsed.ip || "").trim();
    var pathId = "";
    try {
      var rawUrl = String(url || "");
      var pathMatch = rawUrl.match(/sessions\/([^/?#]+)/i);
      if (pathMatch) pathId = decodeURIComponent(pathMatch[1] || "");
      var queryMatch = rawUrl.match(/[?&](?:id|key|serial|ip)=([^&]+)/i);
      if (queryMatch) ident = ident || decodeURIComponent(queryMatch[1] || "");
    } catch (_) {}
    ident = String(ident || pathId || "").replace(/^client_serials:/, "");
    var ip = String(parsed.ip || "").trim();
    var ipMatch = ident.match(/(\d{1,3}(?:\.\d{1,3}){3})/);
    if (!ip && ipMatch) ip = ipMatch[1];
    return { ident: ident, ip: ip, parsed: parsed };
  }
  function rememberRevokedIpFromUrl(url, body) {
    var info = extractSessionIdent(url, body);
    var rows = window.__caSessionRows || [];
    rows.forEach(function (row) {
      if (!row) return;
      var ip = String((row.ip || (row.ip_details && row.ip_details.ip) || "")).trim();
      var ids = [String(row.id || ""), String(row.key || ""), String(row.serial || ""), ip, "client_serials:" + ip];
      if (info.ip && ip === info.ip) rememberRevokedSession(row);
      else if (info.ident && ids.indexOf(info.ident) >= 0) rememberRevokedSession(row);
    });
    try { if (info.parsed) rememberRevokedSession(info.parsed); } catch (_) {}
    if (info.ip) rememberRevokedSession({ ip: info.ip, id: info.ident || info.ip, key: "client_serials:" + info.ip, serial: info.ident || info.ip });
    else if (info.ident) rememberRevokedSession({ id: info.ident, key: info.ident, serial: info.ident });
    return info;
  }
  function sessionIsRevoked(row) {
    if (row && (row.current || row.is_current)) return false;
    var list = readJsonStore(REVOKED_SESSIONS_KEY, []);
    if (!row || !Array.isArray(list) || !list.length) return false;
    var ip = String((row.ip || (row.ip_details && row.ip_details.ip) || "")).trim();
    return list.indexOf(ip) >= 0 || list.indexOf(String(row.id || "")) >= 0 || list.indexOf(String(row.key || "")) >= 0 || list.indexOf(String(row.serial || "")) >= 0 || list.indexOf("client_serials:" + ip) >= 0;
  }
  function rememberDiscordProfile(profile) {
    if (!profile || typeof profile !== "object") return;
    var did = String(profile.discord_id || (profile.discord && (profile.discord.discord_id || profile.discord.id)) || (profile.integrations && profile.integrations.discord && profile.integrations.discord.discord_id) || "").trim();
    if (!did) return;
    var d = profile.discord && typeof profile.discord === "object" ? profile.discord : {};
    var steamName = String(profile.steam_name || (profile.steam && (profile.steam.steam_name || profile.steam.personaname)) || "").trim();
    var accountName = String(profile.name || "").trim();
    var dname = String(d.discord_name || d.global_name || profile.discord_name || "").trim();
    var handle = String(d.username || d.discord_username || "").trim();
    if (!dname || dname === did || dname === steamName || dname === accountName) dname = handle;
    if (dname === steamName || dname === accountName) dname = handle || "";
    var dav = String(d.discord_avatar || d.avatar || profile.discord_avatar || "").trim();
    if (!/cdn\.discordapp\.com/i.test(dav)) dav = discordDefaultAvatar(did);
    writeJsonStore(DISCORD_CACHE_KEY, {
      discord_id: did,
      discord_name: dname,
      discord_avatar: dav,
      user_id: profile.id || 0
    });
  }
  function discordDefaultAvatar(did) {
    var id = String(did || "").replace(/\D/g, "");
    var idx = 0;
    try { idx = Number((BigInt(id) >> 22n) % 6n); } catch (_) {
      idx = (parseInt(id.slice(-2), 10) || 0) % 6;
    }
    return "https://cdn.discordapp.com/embed/avatars/" + idx + ".png";
  }
  function clearDiscordProfile() {
    try { localStorage.removeItem(DISCORD_CACHE_KEY); } catch (_) {}
  }
  function applyCachedDiscord(obj) {
    // An explicit disconnected response from the API always wins over cache.
    if (obj && Object.prototype.hasOwnProperty.call(obj, "discord_id") && !obj.discord_id && !(obj.discord && obj.discord.discord_id)) {
      clearDiscordProfile();
      return obj;
    }
    var cached = readJsonStore(DISCORD_CACHE_KEY, null);
    if (!obj || !cached || !cached.discord_id) return obj;
    var selfId = String(cached.user_id || window.__caMeId || "");
    if (selfId && String(obj.id || "") !== selfId) return obj;
    var have = String((obj.discord_id || (obj.discord && (obj.discord.discord_id || obj.discord.id))) || "").trim();
    if (have && have !== String(cached.discord_id) && String(obj.id || "") !== String(cached.user_id || "")) return obj;
    var steamName = String(obj.steam_name || (obj.steam && obj.steam.steam_name) || "").trim();
    var accountName = String(obj.name || "").trim();
    var name = String(cached.discord_name || "").trim();
    if (!name || name === String(cached.discord_id) || name === steamName || name === accountName) {
      name = String((obj.discord && (obj.discord.discord_name || obj.discord.global_name || obj.discord.username)) || obj.discord_name || "").trim();
    }
    if (name === steamName || name === accountName || name === String(cached.discord_id)) name = String(cached.discord_name || "").trim();
    if (name === steamName || name === accountName) name = "";
    var avatar = String(cached.discord_avatar || "").trim();
    if (!/cdn\.discordapp\.com/i.test(avatar)) avatar = discordDefaultAvatar(cached.discord_id);
    obj.discord_id = have || cached.discord_id;
    if (name) obj.discord_name = name;
    obj.discord_avatar = avatar;
    obj.discord = obj.discord && typeof obj.discord === "object" ? obj.discord : {};
    obj.discord.discord_id = obj.discord_id;
    obj.discord.id = obj.discord_id;
    if (name) {
      obj.discord.discord_name = name;
      obj.discord.name = name;
      obj.discord.username = obj.discord.username || name;
      obj.discord.global_name = name;
    }
    obj.discord.avatar = avatar;
    obj.discord.discord_avatar = avatar;
    obj.discord.connected = true;
    obj.discord.is_connected = true;
    obj.discord.status = "connected";
    if (!obj.integrations || typeof obj.integrations !== "object") obj.integrations = {};
    if (!obj.integrations.discord || typeof obj.integrations.discord !== "object") obj.integrations.discord = {};
    obj.integrations.discord.connected = true;
    obj.integrations.discord.is_connected = true;
    obj.integrations.discord.discord_id = obj.discord_id;
    obj.integrations.discord.id = obj.discord_id;
    if (name) {
      obj.integrations.discord.name = name;
      obj.integrations.discord.username = name;
      obj.integrations.discord.global_name = name;
      obj.integrations.discord.personaname = name;
    }
    obj.integrations.discord.avatar = avatar;
    obj.integrations.discord.discord_avatar = avatar;
    obj.integrations.discord.status = "connected";
    return obj;
  }
  function dropChatAfterCheckFinished(items) {
    if (!Array.isArray(items) || !items.length) return items;
    var finishedAt = 0;
    items.forEach(function (item) {
      var k = String((item && (item.type || item.kind)) || "");
      if (k !== "Finished" && k !== "Canceled") return;
      var t = Number((item && (item.created_at || item.createdAt)) || 0) || 0;
      if (t > finishedAt) finishedAt = t;
    });
    if (!finishedAt) return items;
    return items.filter(function (item) {
      if (!item || typeof item !== "object") return true;
      var k = String(item.type || item.kind || "");
      if (k === "Finished" || k === "Canceled" || k === "Started") return true;
      if (k !== "MessageFromPlayer" && k !== "MessageFromModerator") return true;
      var t = Number(item.created_at || item.createdAt || 0) || 0;
      return !t || t <= finishedAt + 1500;
    });
  }
  (function patchLandingS3() {
    if (window.__checkappLandingS3Fix) return;
    window.__checkappLandingS3Fix = 1;
    const FILES = {
      "landing-mt-bg-2.png": 1,
      "landing_stats_01.webp": 1,
      "landing_stats_02.webp": 1,
      "landing_stats_03.webp": 1,
      "landing_stats_05.webp": 1,
      "stats-4.jpg": 1
    };
    function fileName(u) {
      return String(u || "").split("?")[0].split("#")[0].split("/").pop();
    }
    function fix(u) {
      u = String(u || "");
      const name = fileName(u);
      if (FILES[name]) return location.origin + "/local/landing/" + name;
      return u;
    }
    function needsFix(u) {
      u = String(u || "");
      return !!(FILES[fileName(u)] && /(?:s3|r2)\.|rustapp\.io/i.test(u));
    }
    function fixCss(css) {
      return String(css || "").replace(/url\(\s*(['"]?)(.*?)\1\s*\)/g, function (_, q, u) {
        return "url(" + q + (needsFix(u) ? fix(u) : u) + q + ")";
      });
    }
    const origReplace = String.prototype.replace;
    String.prototype.replace = function (search, replacer) {
      const out = origReplace.apply(this, arguments);
      if (typeof out === "string" && needsFix(out)) return fix(out);
      return out;
    };
    try {
      const proto = CSSStyleDeclaration.prototype;
      ["backgroundImage", "background", "cssText"].forEach(function (prop) {
        const desc = Object.getOwnPropertyDescriptor(proto, prop);
        if (!desc || !desc.set) return;
        Object.defineProperty(proto, prop, {
          configurable: true,
          enumerable: desc.enumerable,
          get: desc.get,
          set: function (v) { desc.set.call(this, fixCss(String(v || ""))); }
        });
      });
      const setProp = proto.setProperty;
      proto.setProperty = function (name, value, priority) {
        if (value) value = fixCss(String(value));
        return setProp.call(this, name, value, priority);
      };
    } catch (_) {}
  })();
  try {
    const NativeES = window.EventSource;
    if (NativeES && !window.__checkappEsPatched) {
      window.__checkappEsPatched = true;
      window.EventSource = function (url, opts) {
        const href = String(url || "");
        if (/\/realtime\/(stream|sse)|\/events\/stream/i.test(href)) {
          return {
            // Polling below is the live transport.  Report this legacy stream
            // as open so Vue does not raise a false connection error.
            readyState: 1,
            url: href,
            close: function () {},
            addEventListener: function () {},
            removeEventListener: function () {},
            dispatchEvent: function () { return false; },
            onopen: null,
            onmessage: null,
            onerror: null
          };
        }
        return new NativeES(url, opts);
      };
      try { window.EventSource.prototype = NativeES.prototype; } catch (_) {}
      try {
        window.EventSource.CONNECTING = NativeES.CONNECTING;
        window.EventSource.OPEN = NativeES.OPEN;
        window.EventSource.CLOSED = NativeES.CLOSED;
      } catch (_) {}
    }
  } catch (_) {}
  try {
    const NativeAudio = window.Audio;
    if (NativeAudio && !window.__checkappAudioPatched) {
      window.__checkappAudioPatched = true;
      window.Audio = function (src) {
        if (src && /ding-dong|\/sound\/ping|s3\.rustcheck\.cc\/sound/i.test(String(src))) {
          src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=";
        }
        return new NativeAudio(src);
      };
      try { window.Audio.prototype = NativeAudio.prototype; } catch (_) {}
    }
  } catch (_) {}
  try {
    const amp = {
      init: function () {},
      track: function () {},
      logEvent: function () {},
      setUserId: function () {},
      identify: function () {},
      flush: function () {},
      add: function () {},
      remove: function () {},
      setOptOut: function () {},
      getDeviceId: function () { return ""; },
      _log: { warn: function () {}, error: function () {}, log: function () {} }
    };
    Object.defineProperty(window, "amplitude", { configurable: true, value: amp, writable: false });
    window.Amplitude = amp;
  } catch (_) {}
  window.__checkappMessages = window.__checkappMessages || [];
  window.__checkappPlayers = window.__checkappPlayers || [];
  window.__checkappTeamHistory = window.__checkappTeamHistory || [];
  window.__checkappNotifications = window.__checkappNotifications || [];
  window.__checkappAuditLogs = window.__checkappAuditLogs || [];
  (function injectPricingFlashFix() {
    if (document.getElementById("checkapp-pricing-flash-fix")) return;
    const st = document.createElement("style");
    st.id = "checkapp-pricing-flash-fix";
    st.textContent = ".landing-page .plan-card .mb-5:not(:has(.plan-icon)):not([data-checkapp-price-ready='1']){opacity:0!important;min-height:2.25rem!important;pointer-events:none!important;}.landing-page .plan-card .mb-5[data-checkapp-price-ready='1']{opacity:1!important;transition:opacity .45s ease .15s!important;}html.checkapp-home:not(.checkapp-home-ready) .landing-page .plan-card .mb-5{opacity:0!important;}";
    (document.head || document.documentElement).appendChild(st);
  })();

  fetch("/auth/google/config", { credentials: "include", cache: "no-store" }).then(function (res) {
    return res.json();
  }).then(function (cfg) {
    if (!cfg || !cfg.client_id) return;
    window.__GOOGLE_CLIENT_ID__ = cfg.client_id;
  }).catch(function () {});

  (function injectLandingFlashFix() {
    if (RC_CLASSIC) return;
    const path = location.pathname || "/";
    if (path !== "/" && path.replace(/\/+$/, "") !== "") return;
    document.documentElement.classList.add("checkapp-home", "rc-home-on");
    if (document.getElementById("checkapp-landing-antiflash")) return;
    const st = document.createElement("style");
    st.id = "checkapp-landing-antiflash";
    st.textContent = [
      "html.checkapp-home img[src*='players.webp'],html.checkapp-home img[src*='chat.webp'],html.checkapp-home img[src*='check.webp'],html.checkapp-home img[src*='drawings.webp'],html.checkapp-home img[src*='bans.webp'],html.checkapp-home img[src*='stats-players.webp'],html.checkapp-home [style*='landing-mt-bg'],html.checkapp-home [style*='landing-mt-bg-2'],html.checkapp-home [data-checkapp-hide-demo-tabs='1'],html.checkapp-home [data-checkapp-hide-demo-shot='1'],html.checkapp-home [data-checkapp-hide-online='1'],html.checkapp-home [data-checkapp-hide-feature-tab='1']{display:none!important;visibility:hidden!important;height:0!important;max-height:0!important;overflow:hidden!important;opacity:0!important;pointer-events:none!important;}",
      "html.checkapp-home .landing-page main>section:has([style*='landing-mt-bg']):not(:has(.stats-card)),html.checkapp-home .landing-page main>section:has([style*='landing-mt-bg-2']):not(:has(.stats-card)),html.checkapp-home .landing-page main>section:has(img[src*='players.webp']):not(:has(.stats-card)),html.checkapp-home .landing-page main>section:has(img[src*='chat.webp']):not(:has(.stats-card)){display:none!important;visibility:hidden!important;height:0!important;min-height:0!important;margin:0!important;padding:0!important;overflow:hidden!important;}",
      "html.checkapp-home:not(.checkapp-home-ready) .landing-page{visibility:hidden!important;pointer-events:none!important;}",
      "html.checkapp-home.checkapp-home-ready .landing-page{visibility:visible!important;pointer-events:auto!important;}",
      "html.checkapp-home:not(.checkapp-home-ready) .landing-page>header,html.checkapp-home:not(.checkapp-home-ready) .landing-page main>section,html.checkapp-home:not(.checkapp-home-ready) .landing-page footer{opacity:0!important;transform:translate3d(0,20px,0)}",
      "html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page>header,html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page main>section:not([data-checkapp-hide='1']):not([data-checkapp-hide-trust='1']),html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page footer{opacity:1!important;transform:translate3d(0,0,0)!important;transition:opacity .75s cubic-bezier(.22,1,.36,1),transform .75s cubic-bezier(.22,1,.36,1)}",
      "html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page>header{transition-delay:.05s}",
      "html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page main>section:nth-of-type(1):not([data-checkapp-hide='1']):not([data-checkapp-hide-trust='1']){opacity:1!important;transform:none!important;transition:none!important;}",
      "html.checkapp-home .landing-page main>section:first-of-type p.text-grey-400,html.checkapp-home .landing-page main>section:first-of-type p[data-checkapp-hero-subtitle='1']{color:#eaeaea!important;-webkit-text-fill-color:#eaeaea!important;opacity:1!important;transition:none!important;animation:none!important;}",
      "html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page main>section:nth-of-type(2):not([data-checkapp-hide='1']):not([data-checkapp-hide-trust='1']){transition-delay:.20s}",
      "html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page main>section:nth-of-type(3):not([data-checkapp-hide='1']):not([data-checkapp-hide-trust='1']){transition-delay:.28s}",
      "html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page main>section:nth-of-type(4):not([data-checkapp-hide='1']):not([data-checkapp-hide-trust='1']){transition-delay:.36s}",
      "html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page main>section:nth-of-type(5):not([data-checkapp-hide='1']):not([data-checkapp-hide-trust='1']){transition-delay:.44s}",
      "html.checkapp-home .landing-page main>section[data-checkapp-hide-trust='1'],html.checkapp-home .landing-page main>section[data-checkapp-hide-feed='1']{display:none!important;visibility:hidden!important;height:0!important;min-height:0!important;max-height:0!important;margin:0!important;padding:0!important;overflow:hidden!important;opacity:0!important;pointer-events:none!important;}",
      "html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page footer{transition-delay:.58s}",
      "html.checkapp-home.checkapp-home-ready .landing-page .stats-card{transition-property:all!important;transition-duration:.3s!important;transition-timing-function:cubic-bezier(.4,0,.2,1)!important;transition-delay:0s!important;}",
      "html.checkapp-home,html.checkapp-home body{background:#1e1e1e!important;}",
      "@media (prefers-reduced-motion:reduce){html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page>header,html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page main>section:not([data-checkapp-hide='1']):not([data-checkapp-hide-trust='1']),html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page footer{transition-duration:.35s;transition-delay:0s!important;transform:none!important}html.checkapp-home:not(.checkapp-home-ready) .landing-page>header,html.checkapp-home:not(.checkapp-home-ready) .landing-page main>section,html.checkapp-home:not(.checkapp-home-ready) .landing-page footer{transform:none}}"
    ].join("");
    (document.head || document.documentElement).appendChild(st);
    try { injectLandingStatsBgStyles(); } catch (_) {}
  })();

  function finishLandingReveal() {
    if (window.__checkappLandingRevealFallback) {
      clearTimeout(window.__checkappLandingRevealFallback);
      window.__checkappLandingRevealFallback = null;
    }
    if (!RC_CLASSIC) document.documentElement.classList.add("checkapp-home-ready");
    if (window.__checkappLandingRevealDoneTimer) clearTimeout(window.__checkappLandingRevealDoneTimer);
    window.__checkappLandingRevealDoneTimer = setTimeout(function () {
      if (!RC_CLASSIC) document.documentElement.classList.add("checkapp-home-revealed");
      try { lockLandingHomeStable(); } catch (_) {}
    }, 850);
  }

  function lockLandingHomeStable() {
    if (window.__checkappLandingStable) return;
    window.__checkappLandingStable = true;
    if (!RC_CLASSIC) document.documentElement.classList.add("checkapp-home-stable");
    injectLandingStableStyles();
  }
  window.__checkappLockLandingHomeStable = lockLandingHomeStable;

  function injectLandingStableStyles() {
    if (document.getElementById("checkapp-landing-stable-style")) return;
    const st = document.createElement("style");
    st.id = "checkapp-landing-stable-style";
    st.textContent = [
      "html.checkapp-home-stable.checkapp-home .landing-page>header,html.checkapp-home-stable.checkapp-home .landing-page main>section:not([data-checkapp-hide='1']):not([data-checkapp-hide-trust='1']):not([data-checkapp-hide-feed='1']):not(:has(.stats-card)):not(:has(.scroll-container)),html.checkapp-home-stable.checkapp-home .landing-page footer{opacity:1!important;transform:none!important;transition:none!important;animation:none!important;}"
    ].join("");
    (document.head || document.documentElement).appendChild(st);
  }

  function revealLandingHomePage() {
    const path = location.pathname || "/";
    if (path !== "/" && path.replace(/\/+$/, "") !== "" && path !== "/index.html" && !/^\/client\/auth/.test(path)) {
      document.documentElement.classList.remove("checkapp-home", "checkapp-home-ready", "checkapp-home-revealed", "rc-home-on");
      if (window.__checkappLandingRevealTimer) {
        clearTimeout(window.__checkappLandingRevealTimer);
        window.__checkappLandingRevealTimer = null;
      }
      return;
    }
    if (RC_CLASSIC) return;
    document.documentElement.classList.add("checkapp-home", "rc-home-on");
  }

  function projectPlayersPath() {
    const parts = String(location.pathname || "").split("/").filter(Boolean);
    if (parts.length && !/^(client|settings|pricing|auth|players|onboarding)$/i.test(parts[0])) {
      return "/" + parts[0] + "/players" + location.search + location.hash;
    }
    return "/client/auth" + location.search + location.hash;
  }

  function checkDestForId(id) {
    const n = String(Number(id) || 0);
    if (!n || n === "0") return "";
    let slug = "";
    try { slug = currentProjectSlug(); } catch (_) {}
    if (!slug) {
      try {
        const pinia = typeof piniaRoot === "function" ? piniaRoot() : null;
        const panel = pinia && pinia._s && pinia._s.get("panel");
        const p = panel && panel.project;
        slug = String((p && (p.domain || p.tag || p.url)) || "").trim();
      } catch (_) {}
    }
    if (/^(client|profile|settings|checks|check|auth)$/i.test(slug)) slug = "";
    const parts = String(location.pathname || "").split("/").filter(Boolean);
    if (!slug && parts[0] && !/^(client|profile|settings|checks|check|auth)$/i.test(parts[0])) slug = parts[0];
    if (!slug) return "";
    return "/" + slug + "/checks/" + n;
  }

  if (/^\/admin(?:\/|$|\?|#)/i.test(location.pathname || "")) {
    if (!/\/admin\.html$/i.test(location.pathname || "")) {
      location.replace("/admin.html" + location.search + location.hash);
    }
    return;
  }

  if (/^\/profile(?:\/|$|\?|#)/i.test(location.pathname || "")) {
    try {
      const fc = JSON.parse(sessionStorage.getItem("ca_force_check") || "null");
      if (fc && fc.id && Date.now() < Number(fc.until || 0)) {
        const slug = String(fc.slug || "").replace(/^\/+|\/+$/g, "");
        location.replace((slug ? "/" + slug : "") + "/checks/" + fc.id);
        return;
      }
    } catch (_) {}
    location.replace("/client/profile" + location.search + location.hash);
    return;
  }
  if (/\/onboarding(?:\/|$|\?|#)/i.test(location.pathname || "")) {
    if (!/\/onboarding\/(?:username|nickname|profile|setup|start|welcome)/i.test(location.pathname || "")) {
      location.replace(projectPlayersPath());
      return;
    }
  }
  function hideMapUi() {}
  function hideSidebarSearchUi() {
    const sels = [
      ".navigation .search",
      ".navigation .search-full",
      ".navigation .search-small",
      ".fake-wrapper",
      ".fake-modal"
    ];
    document.querySelectorAll(".navigation .navigation-state-btn").forEach(function (el) {
      el.style.removeProperty("display");
      el.style.removeProperty("pointer-events");
      el.style.removeProperty("visibility");
      el.style.removeProperty("height");
      el.style.removeProperty("width");
      el.style.removeProperty("min-height");
      el.style.removeProperty("min-width");
      el.style.removeProperty("opacity");
      el.style.removeProperty("overflow");
      el.style.removeProperty("margin");
      el.style.removeProperty("padding");
      el.removeAttribute("data-checkapp-hide-sidebar-search");
    });
    for (let i = 0; i < sels.length; i++) {
      document.querySelectorAll(sels[i]).forEach(function (el) {
        el.style.setProperty("display", "none", "important");
        el.style.setProperty("pointer-events", "none", "important");
        el.setAttribute("data-checkapp-hide-sidebar-search", "1");
        const shell = el.closest && (el.closest(".vfm") || el.closest("[class*='vfm']"));
        if (shell && shell !== el) {
          shell.style.setProperty("display", "none", "important");
          shell.style.setProperty("pointer-events", "none", "important");
          shell.setAttribute("data-checkapp-hide-sidebar-search", "1");
        }
      });
    }
  }
  window.addEventListener("keydown", function (e) {
    const k = String(e.key || "").toLowerCase();
    if ((e.ctrlKey || e.metaKey) && (k === "f" || k === "а")) {
      e.stopImmediatePropagation();
      hideSidebarSearchUi();
    }
  }, true);
  function bootPanelHome() {
    if (RC_CLASSIC) return;
    let link = document.getElementById("rc-panel-home-css");
    if (!link) {
      link = document.createElement("link");
      link.id = "rc-panel-home-css";
      link.rel = "stylesheet";
      (document.head || document.documentElement).appendChild(link);
    }
    if (link.getAttribute("href") !== "/rc-panel-home.css?v=11") link.href = "/rc-panel-home.css?v=11";
    function run() {
      try { if (window.injectPanelHomeNav) window.injectPanelHomeNav(); } catch (_) {}
      try { if (window.mountPanelHome) window.mountPanelHome(); } catch (_) {}
    }
    const src = "/rc-panel-home.js?v=11";
    let s = document.getElementById("rc-panel-home-js");
    if (!s || s.getAttribute("src") !== src) {
      if (s) s.remove();
      window.__rcPanelHomeVer = 0;
      s = document.createElement("script");
      s.id = "rc-panel-home-js";
      s.src = src;
      s.onload = run;
      (document.head || document.documentElement).appendChild(s);
    } else {
      run();
    }
  }
  function bootUiPolish() {
    if (RC_CLASSIC) return;
    if (!document.getElementById("rc-ui-polish-critical")) {
      const crit = document.createElement("style");
      crit.id = "rc-ui-polish-critical";
      crit.textContent =
        ".payments-tab-general .usage,.payments-tab-general .usage-container," +
        ".content .usage:has(.usage-container),.content .usage:has(.text-head)," +
        '[data-rc-hide-billing-limits="1"],.rc-hide-billing-limits{display:none!important;height:0!important;overflow:hidden!important;opacity:0!important;visibility:hidden!important;}' +
        '.signage-card .buttons > .ra-button.preset.default,.signage-card .buttons > .ra-button.preset.liked,' +
        '.signage-card .buttons > button.preset.default,.signage-card .buttons > button.preset.liked,' +
        '.signage-card .flex-shrink-0,.signage-card [class*="flex-shrink-0"],.rc-hide-like{display:none!important;width:0!important;min-width:0!important;padding:0!important;margin:0!important;opacity:0!important;pointer-events:none!important;}';
      (document.head || document.documentElement).appendChild(crit);
    }
    let link = document.getElementById("rc-ui-polish-css");
    if (!link) {
      link = document.createElement("link");
      link.id = "rc-ui-polish-css";
      link.rel = "stylesheet";
      (document.head || document.documentElement).appendChild(link);
    }
    if (link.getAttribute("href") !== "/rc-ui-polish.css?v=10") link.href = "/rc-ui-polish.css?v=10";
    const src = "/rc-ui-polish.js?v=9";
    let s = document.getElementById("rc-ui-polish-js");
    if (!s || s.getAttribute("src") !== src) {
      if (s) s.remove();
      window.__rcUiPolishVer = 0;
      s = document.createElement("script");
      s.id = "rc-ui-polish-js";
      s.src = src;
      (document.head || document.documentElement).appendChild(s);
    }
  }
  function isRcAppBgPath() {
    const path = location.pathname || "/";
    if (path === "/" || path === "/index.html" || /^\/client\/auth/.test(path)) return false;
    return true;
  }
  function bootAppBg() {
    if (RC_CLASSIC) return;
    let link = document.getElementById("rc-app-bg-css");
    if (!link) {
      link = document.createElement("link");
      link.id = "rc-app-bg-css";
      link.rel = "stylesheet";
      (document.head || document.documentElement).appendChild(link);
    }
    if (link.getAttribute("href") !== "/rc-app-bg.css?v=13") link.href = "/rc-app-bg.css?v=13";
    const on = isRcAppBgPath();
    document.documentElement.classList.toggle("rc-app-bg", on);
    let layer = document.getElementById("rc-app-bg");
    if (on) {
      if (!layer && document.body) {
        layer = document.createElement("div");
        layer.id = "rc-app-bg";
        document.body.insertBefore(layer, document.body.firstChild);
      }
      if (layer && !layer.querySelector(".orb")) {
        layer.innerHTML = '<div class="bg"></div><div class="orb"></div><div class="ring"></div><div class="vignette"></div><div class="noise"></div>';
      }
    } else if (layer) {
      layer.remove();
    }
  }
  function hideSettingsApiTab() {
    if (window.__rcApiTabCssDone) return;
    window.__rcApiTabCssDone = 1;
    var st = document.createElement("style");
    st.textContent = "[data-rc-hide-api='1']{display:none!important;width:0!important;max-width:0!important;min-width:0!important;height:0!important;padding:0!important;margin:0!important;overflow:hidden!important;opacity:0!important;pointer-events:none!important;}";
    (document.head || document.documentElement).appendChild(st);
    function markApiNodes(root) {
      if (!root || !root.querySelectorAll) return;
      var nodes = root.querySelectorAll("a, button, span, div, [role='tab']");
      for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        if (el.getAttribute && el.getAttribute("data-rc-hide-api")) continue;
        if (el.closest && el.closest(".navigation, .landing-page, #rc-dash")) continue;
        var t = String(el.textContent || "").replace(/\s+/g, " ").trim();
        if (!/^API$/i.test(t)) continue;
        if (el.children.length > 3) continue;
        var r = el.getBoundingClientRect();
        if (r.width > 140 || r.height > 64) continue;
        el.setAttribute("data-rc-hide-api", "1");
      }
    }
    function markApiPanes(root) {
      if (!root || !root.querySelectorAll) return;
      root.querySelectorAll(".content div, .n-tab-pane, [role='tabpanel']").forEach(function (pane) {
        if (pane.getAttribute && pane.getAttribute("data-rc-hide-api")) return;
        var txt = String(pane.textContent || "");
        if (!(/Включить API/.test(txt) && /(Private key|Public key)/.test(txt))) return;
        if (pane.querySelector(".navigation")) return;
        if (pane.children.length > 30) return;
        pane.setAttribute("data-rc-hide-api", "1");
      });
    }
    markApiNodes(document);
    markApiPanes(document);
    var obs = new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        var nodes = muts[i].addedNodes;
        for (var j = 0; j < nodes.length; j++) {
          var n = nodes[j];
          if (n && n.nodeType === 1) { markApiNodes(n); markApiPanes(n); }
        }
      }
    });
    obs.observe(document.documentElement, { childList: true, subtree: true });
  }
  function bootRcTabAnim() {
    if (window.__rcTabAnimBound) return;
    window.__rcTabAnimBound = 1;
    function isTabClick(el) {
      if (!el || el.closest && el.closest(".navigation, .landing-page, #rc-dash, #rc-home, .vfm, .n-modal, .n-modal-container, .player-modal, .modal-border, .client-edit-modal, [class*='mute-view'], [class*='ban-view'], .ip-details-modal, .permissions-modal")) return false;
      var p = el.parentElement;
      if (!p) return false;
      if (p.closest && p.closest(".vfm, .n-modal, .player-modal, .modal-border")) return false;
      var kids = Array.from(p.children);
      if (kids.length < 3 || kids.length > 18) return false;
      var short = 0;
      kids.forEach(function (c) {
        var t = String(c.textContent || "").replace(/\s+/g, " ").trim();
        if (t && t.length < 24) short += 1;
      });
      return short >= 3;
    }
    function paneHost(tabEl) {
      if (tabEl.closest && tabEl.closest(".vfm, .n-modal, .player-modal, .modal-border")) return null;
      var tabs = tabEl.closest && tabEl.closest(".n-tabs, [class*='tabs']");
      if (tabs) {
        if (tabs.closest && tabs.closest(".vfm, .n-modal, .player-modal")) return null;
        var pane = tabs.parentElement && Array.from(tabs.parentElement.children).find(function (n) {
          return n !== tabs && n.offsetHeight > 40;
        });
        if (pane && !(pane.closest && pane.closest(".vfm, .n-modal, .player-modal"))) return pane;
        var inner = tabs.querySelector(".n-tab-pane, [role='tabpanel']");
        if (inner && !(inner.closest && inner.closest(".vfm, .n-modal, .player-modal"))) return inner;
      }
      var bar = tabEl.parentElement;
      var node = bar && bar.nextElementSibling;
      while (node && node.offsetHeight < 36) node = node.nextElementSibling;
      if (node && node.closest && node.closest(".vfm, .n-modal, .player-modal")) return null;
      if (document.querySelector(".vfm:not([style*='display: none']), .n-modal-container .n-modal")) return null;
      return node || null;
    }
    function play(host) {
      if (!host || host.getAttribute("data-rc-tab-lock") === "1") return;
      if (host.closest && host.closest(".vfm, .n-modal, .player-modal")) return;
      if (document.querySelector(".vfm .player-modal, .vfm:has(.player-modal), .n-modal-container:has(.player-modal)")) return;
      host.classList.remove("rc-tab-enter");
      try { void host.offsetWidth; } catch (_) {}
      host.classList.add("rc-tab-enter");
    }
    document.addEventListener("click", function (e) {
      var el = e.target && e.target.closest && e.target.closest("div, button, a, span, [role='tab']");
      if (!el || !isTabClick(el)) return;
      var host = paneHost(el);
      if (!host) return;
      window.setTimeout(function () { play(host); }, 16);
    }, true);
  }
  setInterval(hideMapUi, 2000);
  setInterval(hideSidebarSearchUi, 2000);
  setInterval(bootPanelHome, 2000);
  setInterval(bootAppBg, 2000);
  setInterval(bootUiPolish, 2000);
  setInterval(bootRcTabAnim, 800);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", hideMapUi);
    document.addEventListener("DOMContentLoaded", hideSidebarSearchUi);
    document.addEventListener("DOMContentLoaded", bootPanelHome);
    document.addEventListener("DOMContentLoaded", bootAppBg);
    document.addEventListener("DOMContentLoaded", bootUiPolish);
    document.addEventListener("DOMContentLoaded", hideSettingsApiTab);
    document.addEventListener("DOMContentLoaded", bootRcTabAnim);
  } else {
    hideMapUi();
    hideSidebarSearchUi();
    bootPanelHome();
    bootAppBg();
    bootUiPolish();
    hideSettingsApiTab();
    bootRcTabAnim();
  }

  (function killCriticalNotifications() {
    function isBadToast(el) {
      if (!el || el.nodeType !== 1) return false;
      const t = (el.textContent || "").replace(/\s+/g, " ").trim();
      if (!t) return false;
      return /unhandled-exception|Ошибка подключения к серверу авторизации|переподключаемся|Нет соединения с сервисом|No connection to the service|network-error|Мы уже получили сигнал|уже получили сигнал о проблеме|Не удалось подключиться к серверу событий|Failed to connect to the event server/i.test(t);
    }
    function dismissSituation() {
      try {
        const pinia = piniaRoot();
        const sit = pinia && pinia._s && pinia._s.get("situation");
        if (!sit || typeof sit.close !== "function") return;
        let row = sit.current;
        if (row && typeof row === "object" && "value" in row) row = row.value;
        if (row && typeof row === "object" && "value" in row && row.value && (row.value.name || row.value.text_ru)) row = row.value;
        const blob = String((row && (row.name || "")) + " " + (row && (row.text_ru || row.text_en || row.text || "")));
        if (/error-centrifugo|серверу событий|event server/i.test(blob)) sit.close();
      } catch (_) {}
    }
    function sweep(root) {
      dismissSituation();
      const scope = root && root.querySelectorAll ? root : document;
      scope.querySelectorAll(".notification,[class*='notification'],[class*='n-message'],[class*='n-notification'],[class*='n-dialog'],[class*='toast'],[class*='situation'],[class*='runtime']").forEach(function (el) {
        if (!isBadToast(el)) return;
        const box = el.closest(".notification,[class*='notification'],[class*='runtime'],[class*='toast'],[class*='situation']") || el;
        try { box.remove(); } catch (_) { box.style.display = "none"; }
      });
    }
    if (document.documentElement) {
      let _sweepPending = false;
      new MutationObserver(function () {
        if (_sweepPending) return;
        _sweepPending = true;
        setTimeout(function () { _sweepPending = false; sweep(document); }, 500);
      }).observe(document.documentElement, { childList: true, subtree: true });
    }
    setInterval(function () { sweep(document); }, 2000);
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) sweep(document);
    });
  })();

  // The bundled performance reporter occasionally receives an empty metric.
  // Patch the observer list itself so reportAllChanges never reads startTime
  // on undefined entries (photo uploads trigger INP/CLS).
  window.addEventListener("error", function (ev) {
    const msg = String((ev && (ev.message || (ev.error && ev.error.message))) || "");
    if (!/reading ['\"]startTime['\"]|reportAllChanges/i.test(msg)) return;
    try { ev.preventDefault(); ev.stopImmediatePropagation(); } catch (_) {}
  }, true);
  window.addEventListener("unhandledrejection", function (ev) {
    const msg = String((ev && ev.reason && ev.reason.message) || (ev && ev.reason) || "");
    if (!/reading ['\"]startTime['\"]|reportAllChanges/i.test(msg)) return;
    try { ev.preventDefault(); } catch (_) {}
  }, true);
  (function patchStartTime() {
    if (window.__checkappStartTimeFix) return;
    window.__checkappStartTimeFix = 1;
    function keep(arr) {
      const out = [];
      try {
        arr = arr || [];
        for (let i = 0; i < arr.length; i++) {
          if (arr[i] && typeof arr[i].startTime === "number") out.push(arr[i]);
        }
      } catch (_) {}
      return out;
    }
    function wrap(proto, name) {
      if (!proto || typeof proto[name] !== "function" || proto[name].__checkappPatched) return;
      const orig = proto[name];
      proto[name] = function () { return keep(orig.apply(this, arguments)); };
      proto[name].__checkappPatched = true;
    }
    try {
      const list = window.PerformanceObserverEntryList && PerformanceObserverEntryList.prototype;
      wrap(list, "getEntries");
      wrap(list, "getEntriesByType");
      wrap(list, "getEntriesByName");
      wrap(Performance.prototype, "getEntries");
      wrap(Performance.prototype, "getEntriesByType");
      wrap(Performance.prototype, "getEntriesByName");
    } catch (_) {}
    try {
      const pop = PerformanceObserver.prototype;
      if (pop.takeRecords && !pop.takeRecords.__checkappPatched) {
        const tr = pop.takeRecords;
        pop.takeRecords = function () { return keep(tr.call(this)); };
        pop.takeRecords.__checkappPatched = true;
      }
    } catch (_) {}
    try {
      const ce = console.error.bind(console);
      console.error = function () {
        try {
          for (let i = 0; i < arguments.length; i++) {
            const a = arguments[i];
            if (/reading ['\"]startTime['\"]|reportAllChanges/i.test(String((a && a.message) || a || ""))) return;
          }
        } catch (_) {}
        return ce.apply(console, arguments);
      };
    } catch (_) {}
  })();
  try {
    const NativePO = window.PerformanceObserver;
    if (NativePO && !window.__checkappPoPatched) {
      window.__checkappPoPatched = true;
      window.PerformanceObserver = function (cb) {
        const wrapped = function (list, obs) {
          try {
            const entries = list && list.getEntries ? list.getEntries() : [];
            const ok = (entries || []).filter(function (e) { return e && typeof e.startTime === "number"; });
            if (!ok.length) return;
            const view = {
              getEntries: function () { return ok; },
              getEntriesByType: function (type) { return ok.filter(function (e) { return e.entryType === type; }); },
              getEntriesByName: function (name) { return ok.filter(function (e) { return e.name === name; }); }
            };
            return cb(view, obs);
          } catch (_) {}
        };
        const po = new NativePO(typeof cb === "function" ? wrapped : cb);
        return po;
      };
      window.PerformanceObserver.prototype = NativePO.prototype;
      if (NativePO.supportedEntryTypes) {
        window.PerformanceObserver.supportedEntryTypes = NativePO.supportedEntryTypes;
      }
    }
  } catch (_) {}

  const ADMIN_LOGINS = new Set(["admin", "admin@checkapp.local", "admin@gmail.com"]);
  const ADMIN_PASSWORD = "admin123";
  const PLACEHOLDER = location.origin + "/local/image-1024.jpg?v=6";
  const ACCOUNT_AVATAR = location.origin + "/local/image-1024.jpg?v=6";
  const BRAND_LOGO = location.origin + "/local/image-1024.jpg?v=6";
  const LANDING_FILES = {
    "players.webp": 1, "chat.webp": 1, "check.webp": 1,
    "drawings.webp": 1, "bans.webp": 1, "stats-players.webp": 1,
    "map-preview.png": 1, "landing-mt-bg-2.png": 1, "landing-map.webm": 1,
    "landing_stats_01.webp": 1, "landing_stats_02.webp": 1, "landing_stats_03.webp": 1,
    "landing_stats_05.webp": 1, "stats-4.jpg": 1
  };
  const ASSET_FILES = {
    "1704281217881-3ecd831bb95e4bef780a4846.jpeg": "/local/image-1024.jpg",
    "1780921773745-3a0f9c1a159566cf7e0a3d0f.png": "/local/image-1024.jpg",
    "default-avatar.jpeg": "/local/image-1024.jpg",
    "default-banner.png": "/local/image-1024.jpg",
    "rustlogo_dark.jpg": "/local/image-1024.jpg",
    "rustlogo_dark-C4adiJ9u.jpg": "/local/image-1024.jpg",
    "logo.png": "/local/image-1024.jpg",
    "logo-avatar.png": "/local/image-1024.jpg",
    "image-1024.jpg": "/local/image-1024.jpg",
    "logo-mark.svg": "/local/image-1024.jpg",
    "moder.png": "/local/moder.png",
    "apple.spoiled-c6rqghtE.png": "/local/image-1024.jpg",
    "lock.key-CUFqW1so.png": "/local/image-1024.jpg",
    "photo-DeF6ukkU.png": "/local/image-1024.jpg",
    "electric.rf.receiver-B2MrTi8k.png": "/local/image-1024.jpg"
  };

  const PERMISSIONS = [
    "Core_ClientsEdit",
    "Court_AlertRead", "Court_AuditRead", "Court_ChatReadDirect", "Court_ChatReadPublic",
    "Court_ChatWriteGlobal", "Court_ChatWriteReply", "Court_CheckProcess", "Court_CheckRead",
    "Court_CheckStartIgnoreAfk", "Court_CheckStartIgnoreRaidBlock", "Court_CheckStartIgnoreReports",
    "Court_CustomActionsGreen", "Court_CustomActionsRed", "Court_CustomActionsYellow",
    "Court_MapRead", "Court_PlayerBan", "Court_PlayerBanDestroyBuildings", "Court_PlayerBanEditFull",
    "Court_PlayerBanEditGeneral", "Court_PlayerBanIgnoreLimit", "Court_PlayerBanIpActive",
    "Court_PlayerBanRead", "Court_PlayerBanUnban", "Court_PlayerEditComment",
    "Court_PlayerEditIgnoreReportsTime", "Court_PlayerHistoryRead", "Court_PlayerKick",
    "Court_PlayerMuteCreate", "Court_PlayerMuteDelete", "Court_PlayerMuteRead",
    "Court_PlayerReadDetails", "Court_PlayerSettingsAutoKickEdit", "Court_PlayerStatsRead",
    "Court_PlayerViewGameInfo", "Court_ReportDelete", "Court_ReportDeleteGlobal",
    "Court_ReportRead", "Court_ServerManage", "Court_ServerRead", "Court_SignageControl",
    "Court_SleepingBagRead"
  ];

  function staffAdminAliases() {
    return ["admin", "owner", "*", "administrator", "court_admin", "permissions-admin", "permissions_admin", "is_admin", "full", "full-control", "full_control", "administrator-rights"];
  }
  function truthyStaffFlag(v) {
    return v === true || v === 1 || v === "1" || v === "true" || v === "True";
  }
  function permsWantAdmin(raw, extra) {
    extra = extra || {};
    if (truthyStaffFlag(extra.is_immutable) || truthyStaffFlag(extra.is_admin) || truthyStaffFlag(extra.admin)) return true;
    if (Array.isArray(raw)) {
      return raw.some(function (p) {
        var key = String(p || "").trim().toLowerCase().replace(/\s+/g, "-").replace(/_/g, "-");
        return staffAdminAliases().indexOf(key) >= 0 || key.indexOf("permissions-admin") === 0;
      });
    }
    if (raw && typeof raw === "object") {
      return Object.keys(raw).some(function (k) {
        var v = raw[k];
        if (v === false || v === 0 || v === "0" || v === "false" || v == null || v === "") return false;
        var key = String(k || "").trim().toLowerCase().replace(/\s+/g, "-").replace(/_/g, "-");
        return staffAdminAliases().indexOf(key) >= 0 || key === "is-immutable" || key.indexOf("permissions-admin") === 0;
      });
    }
    return false;
  }
  function expandStaffAdminBody(url, method, body) {
    if (!/\/clients(?:-v2)?(?:\/|\?|$)/i.test(String(url || ""))) return body;
    if (!/^(POST|PUT|PATCH)$/i.test(String(method || "GET"))) return body;
    var parsed = body;
    var asString = typeof body === "string";
    if (asString) {
      try { parsed = JSON.parse(body || "{}"); } catch (_) { return body; }
    }
    if (!parsed || typeof parsed !== "object") return body;
    var nested = parsed.client && typeof parsed.client === "object" ? parsed.client : {};
    var rawPerms = parsed.permissions != null ? parsed.permissions : nested.permissions;
    if (!permsWantAdmin(rawPerms, parsed) && !permsWantAdmin(rawPerms, nested)) return body;
    parsed.permissions = PERMISSIONS.slice();
    parsed.is_immutable = true;
    parsed.is_admin = true;
    if (parsed.client && typeof parsed.client === "object") {
      parsed.client.permissions = PERMISSIONS.slice();
      parsed.client.is_immutable = true;
    }
    return asString ? JSON.stringify(parsed) : parsed;
  }

  function cleanToken(value) {
    let raw = String(value || "").trim();
    if (/^bearer\s+/i.test(raw)) raw = raw.replace(/^bearer\s+/i, "").trim();
    while (
      (raw.startsWith('"') && raw.endsWith('"')) ||
      (raw.startsWith("'") && raw.endsWith("'"))
    ) {
      raw = raw.slice(1, -1).trim();
    }
    return raw;
  }

  function purgePoisonedStorage() {
    try {
      ["setItem", "getItem", "removeItem", "clear", "key", "length"].forEach(function (k) {
        try { localStorage.removeItem(k); sessionStorage.removeItem(k); } catch (_) {}
      });
      Object.keys(localStorage).forEach(function (k) {
        if (/^setItem$|^getItem$|^removeItem$/i.test(k)) {
          try { localStorage.removeItem(k); } catch (_) {}
        }
      });
    } catch (_) {}
  }

  purgePoisonedStorage();

  try {
    let cleaned = cleanToken(localStorage.getItem("access_token") || localStorage.getItem("token") || "");
    if (cleaned) {
      localStorage.setItem("access_token", cleaned);
      localStorage.setItem("token", cleaned);
    }
    const existing = JSON.parse(localStorage.getItem("onboarding") || "{}");
    const alreadyDone = !!(existing && existing.finished);
    if (alreadyDone) {
      const onboardingDone = {
        invite_finished: true,
        context_finished: true,
        search_finished: true,
        settings_finished: true,
        ban_sync_finished: true,
        custom_actions_finished: true,
        onboarding_finished: true
      };
      localStorage.setItem("onboarding", JSON.stringify(onboardingDone));
      localStorage.setItem("onboarding-skips", JSON.stringify({ skips: onboardingDone }));
      try {
        localStorage.setItem("onboarding_finished", "1");
        localStorage.setItem("checkapp_onboarding_done", "1");
        Object.keys(localStorage).forEach(function (k) {
          if (/onboard/i.test(k) && k !== "onboarding" && k !== "onboarding-skips") {
            try { localStorage.setItem(k, "1"); } catch (_) {}
          }
        });
      } catch (_) {}
    }
  } catch (_) {}

  (function killOnboardingUi() {
    function forceDone() {
      try {
        const done = {
          invite_finished: true,
          context_finished: true,
          search_finished: true,
          settings_finished: true,
          ban_sync_finished: true,
          custom_actions_finished: true,
          onboarding_finished: true,
          server_pair_finished: true,
          finished: true
        };
        localStorage.setItem("onboarding", JSON.stringify(done));
        localStorage.setItem("onboarding-skips", JSON.stringify({ skips: done }));
      } catch (_) {}
    }
    function hideOnboarding() {
      const curPath = String(location.pathname || "");
      const isOnboardingPath = /\/onboarding(?:\/|$|\?|#)/i.test(curPath);
      if (isOnboardingPath) {
        if (/\/onboarding\/(?:username|nickname|profile|setup|start|welcome)/i.test(curPath)) return;
        try { history.replaceState(null, "", projectPlayersPath()); } catch (_) {}
        location.replace(projectPlayersPath());
        return;
      }
      try {
        const existing = JSON.parse(localStorage.getItem("onboarding") || "{}");
        if (existing && existing.finished) forceDone();
      } catch (_) {}
      document.querySelectorAll(
        "[class*='onboarding'],[class*='Onboarding'],[data-testid*='onboarding']," +
        ".router-onboarding,[href*='/onboarding']"
      ).forEach(function (el) {
        const txt = String(el.textContent || "");
        const isNav = el.closest && el.closest("nav,aside,.sidebar,.menu");
        if (isNav && /onboarding|начало работы/i.test(txt) && el.tagName === "A") {
          el.style.display = "none";
          return;
        }
        if (el.matches && el.matches("[class*='onboarding'],[class*='Onboarding']")) {
          const big = el.closest(".vfm,.modal,[class*='modal']") || el;
          if (big !== document.body && big !== document.documentElement &&
              /Пригласите команду|Connect your server|Начало работы|Invite the team|Используйте контекст|Подключите сервер|Complete onboarding|Завершите онбординг/i.test(String(big.textContent || ""))) {
            try { big.remove(); } catch (_) { big.style.display = "none"; }
          }
        }
      });
    }
    const _push = history.pushState;
    const _replace = history.replaceState;
    function rewriteOnboardingUrl(url) {
      if (!url || !/onboarding/i.test(String(url))) return url;
      forceDone();
      return String(url).replace(/\/onboarding(?:\/)?(?=[?#]|$)/i, "/players");
    }
    function rewritePublicUrl(url) {
      if (!url) return url;
      let next = rewriteOnboardingUrl(url);
      const s = String(next);
      if (/^\/profile(?:\/|$|\?|#)/i.test(s)) {
        if (window.__caLastCheckId && Date.now() < (window.__caForceCheckUntil || 0)) {
          const dest = checkDestForId(window.__caLastCheckId);
          if (dest) return dest;
        }
        next = s.replace(/^\/profile(?=\/|$|\?|#)/i, "/client/profile");
      }
      return next;
    }
    history.pushState = function (state, title, url) {
      const out = _push.call(this, state, title, rewritePublicUrl(url));
      try { setTimeout(mountRcHome, 0); setTimeout(mountRcProfile, 0); setTimeout(bootPanelHome, 0); setTimeout(bootAppBg, 0); } catch (_) {}
      return out;
    };
    history.replaceState = function (state, title, url) {
      const out = _replace.call(this, state, title, rewritePublicUrl(url));
      try { setTimeout(mountRcHome, 0); setTimeout(mountRcProfile, 0); setTimeout(bootPanelHome, 0); setTimeout(bootAppBg, 0); } catch (_) {}
      return out;
    };
    if (document.documentElement) {
      new MutationObserver(function () { hideOnboarding(); }).observe(document.documentElement, { childList: true, subtree: true });
    }
    setInterval(hideOnboarding, 3000);
    hideOnboarding();
  })();

  function b64url(obj) {
    return btoa(unescape(encodeURIComponent(JSON.stringify(obj))))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  }

  try {
    const origSetAttr = HTMLAnchorElement.prototype.setAttribute;
    HTMLAnchorElement.prototype.setAttribute = function (name, value) {
      if (String(name).toLowerCase() === "download" && /(checkapp|rustapp|rustcheck)\.cs/i.test(String(value || ""))) {
        value = "RustApp.cs";
      }
      return origSetAttr.call(this, name, value);
    };
    const desc = Object.getOwnPropertyDescriptor(HTMLAnchorElement.prototype, "download");
    if (desc && desc.set) {
      Object.defineProperty(HTMLAnchorElement.prototype, "download", {
        configurable: true,
        enumerable: desc.enumerable,
        get: desc.get,
        set: function (value) {
          if (/(checkapp|rustapp|rustcheck)\.cs/i.test(String(value || ""))) value = "RustApp.cs";
          return desc.set.call(this, value);
        }
      });
    }
  } catch (_) {}

  function issueToken(email, userId) {
    const mail = String(email || "").toLowerCase();
    const uid = Number(userId || 0) || 0;
    return (
      b64url({ alg: "none", typ: "JWT" }) +
      "." +
      b64url({
        sub: String(uid || ""),
        id: uid,
        serial: "checkapp-local",
        email: mail,
        name: mail.split("@")[0] || "user",
        exp: Math.floor(Date.now() / 1000) + 86400 * 365
      }) +
      ".local"
    );
  }

  function storeAuthToken(token) {
    const value = cleanToken(token);
    if (!value) return "";
    try {
      localStorage.setItem("access_token", value);
      localStorage.setItem("token", value);
    } catch (_) {}
    return value;
  }

  function readAuthToken() {
    try {
      return cleanToken(localStorage.getItem("access_token") || localStorage.getItem("token") || "");
    } catch (_) {
      return "";
    }
  }

  function authHeaderValue() {
    const token = readAuthToken();
    if (!token) return "";
    return "Bearer " + token;
  }

  window.__checkappSignIn = function (email, password) {
    const post = (typeof window.__checkappOrigFetch === "function")
      ? window.__checkappOrigFetch
      : fetch.bind(window);
    return post("/auth/classic/sign-in", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ email, password, login: email })
    }).then((res) => res.json().catch(() => ({})).then((data) => ({ res, data }))).then(({ res, data }) => {
      let token = "";
      if (typeof data === "string" && data.split(".").length === 3) {
        token = data;
      } else if (data && typeof data === "object") {
        token = data.token || data.access_token || "";
      }
      if (!token) {
        const mapped = humanizeApiError(data, res.status);
        return Promise.reject({ message: mapped.message || "Проверьте email и пароль и попробуйте снова.", title: mapped.title });
      }
      storeAuthToken(token);
      return token;
    });
  };
  window.__checkappExchange = function () { return 90; };

  function openOAuthPopup(fetchLink) {
    return new Promise(function (resolve, reject) {
      const popup = window.open("about:blank", "auth-window", "menubar=0,resizable=0,width=1200,height=745");
      if (!popup) {
        reject({ message: "popup.blocked" });
        return;
      }
      fetch(fetchLink, { credentials: "include", cache: "no-store" })
        .then(function (res) { return res.json(); })
        .then(function (url) {
          if (url && typeof url === "object") {
            if (/not\.configured/i.test(String(url.message || ""))) {
              try { popup.close(); } catch (_) {}
              reject({ message: url.message || "oauth.link.invalid", title: "Интеграция недоступна" });
              return;
            }
            url = url.url || url.link || url.authorize_url || url.redirect || url.href || "";
          }
          if (!url || typeof url !== "string") {
            try { popup.close(); } catch (_) {}
            reject({ message: "oauth.link.invalid" });
            return;
          }
          try { popup.location.replace(url); } catch (_) {
            try { popup.location = url; } catch (e2) {
              try { popup.close(); } catch (_) {}
              reject({ message: "popup.blocked" });
              return;
            }
          }
          function onMessage(ev) {
            try {
              if (ev.origin && ev.origin !== location.origin) return;
              const data = typeof ev.data === "string" ? JSON.parse(ev.data) : ev.data;
              if (data && data.query) {
                window.removeEventListener("message", onMessage);
                clearInterval(timer);
                try { popup.close(); } catch (_) {}
                resolve(String(data.query));
              }
            } catch (_) {}
          }
          window.addEventListener("message", onMessage);
          const timer = setInterval(function () {
            if (popup.closed) {
              clearInterval(timer);
              window.removeEventListener("message", onMessage);
              reject({ message: "Subwindow closed" });
            }
          }, 500);
        })
        .catch(function (err) {
          try { popup.close(); } catch (_) {}
          reject(err);
        });
    });
  }

  window.__checkappDiscordConnect = function () {
    const stay = location.pathname + location.search + location.hash;
    try { sessionStorage.setItem("ca_discord_stay", stay); } catch (_) {}
    const returnUrl = location.href.split("?")[0] + "?integrations-connect-discord=show";
    return openOAuthPopup("/auth/discord-connect?return_url=" + encodeURIComponent(returnUrl));
  };
  window.__checkappSteamConnect = function () {
    const returnUrl = location.href.split("?")[0] + "?integrations-connect-steam=show";
    return openOAuthPopup("/auth/steam-connect?return_url=" + encodeURIComponent(returnUrl));
  };
  window.__checkappGoogleConnect = function () {
    const returnUrl = location.href.split("?")[0] + "?integrations-connect-google=show";
    return openOAuthPopup("/auth/google-connect?return_url=" + encodeURIComponent(returnUrl));
  };

  function completeIntegrationConnect(kind, query) {
    const tok = readAuthToken();
    const headers = { "Content-Type": "application/json", Accept: "application/json" };
    if (tok) headers.Authorization = "Bearer " + tok;
    try {
      const slug = currentProjectSlug();
      if (slug) headers["X-Checkapp-Project"] = slug;
    } catch (_) {}
    return fetch("/auth/" + kind + "-connect?query=" + encodeURIComponent(query), {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers: headers,
      body: JSON.stringify({ query: query, token: tok, access_token: tok })
    }).then(function (res) {
      return res.json().then(function (body) {
        if (!res.ok) {
          return Promise.reject({ message: (body && body.message) || (kind + ".connect.failed"), status: res.status });
        }
        const did = body && (body.discord_id || (body.discord && body.discord.discord_id) || (body.integrations && body.integrations.discord && body.integrations.discord.connected));
        const sid = body && (body.steam_id || (body.steam && body.steam.steam_id) || (body.integrations && body.integrations.steam && body.integrations.steam.connected));
        const gid = body && (body.google_id || (body.google && body.google.google_id));
        if (kind === "discord" && !did) {
          return Promise.reject({ message: "Discord не привязан", status: 400 });
        }
        if (kind === "steam" && !sid) {
          return Promise.reject({ message: "Steam не привязан", status: 400 });
        }
        if (kind === "google" && !gid) {
          return Promise.reject({ message: "Google не привязан", status: 400 });
        }
        if (kind === "discord") rememberDiscordProfile(body);
        return body;
      });
    }).then(function (body) {
      if (kind === "discord") rememberDiscordProfile(body);
      return body;
    });
  }

  function wireIntegrationConnect() {
    document.addEventListener("click", function (ev) {
      const integration = ev.target.closest(".integration, [class*='integration']");
      if (!integration) return;
      const titleEl = integration.querySelector(".title, p.title, [class*='title']");
      const label = titleEl ? String(titleEl.textContent || "") : String(integration.textContent || "");
      let kind = "";
      if (/discord/i.test(label)) kind = "discord";
      else if (/steam/i.test(label)) kind = "steam";
      else if (/google/i.test(label)) kind = "google";
      else if (/telegram/i.test(label)) {
        ev.stopImmediatePropagation();
        ev.preventDefault();
        return;
      }
      if (!kind) return;
      const btn = ev.target.closest("button, .button-truncated, [class*='button']");
      if (!btn) return;
      const btnText = String(btn.textContent || "");
      if (/отвяз|disconnect|unlink/i.test(btnText)) return;
      if (!/connect|подключ|привяз/i.test(btnText)) return;
      ev.stopImmediatePropagation();
      ev.preventDefault();
      window.__caIgnoreDiscordError = Date.now() + 12000;
      const opener = kind === "steam" ? window.__checkappSteamConnect
        : (kind === "google" ? window.__checkappGoogleConnect : window.__checkappDiscordConnect);
      opener()
        .then(function (query) { return completeIntegrationConnect(kind, query); })
        .then(function (body) {
          // Do not send a successful OAuth result through the error mapper:
          // it always renders the title “Не удалось выполнить действие”.
          if (window.__checkappToast) {
            window.__checkappToast("success", kind.charAt(0).toUpperCase() + kind.slice(1) + " успешно привязан", { title: "Готово", force: true });
          }
          let stay = "";
          try { stay = sessionStorage.getItem("ca_discord_stay") || ""; sessionStorage.removeItem("ca_discord_stay"); } catch (_) {}
          const here = location.pathname + location.search + location.hash;
          const next = stay || here;
          setTimeout(function () {
            if (next && next !== here) location.replace(next);
            else location.reload();
          }, 400);
        })
        .catch(function (err) {
          if ((err && err.message) === "Subwindow closed") return;
          if (window.__checkappShowHumanError) {
            window.__checkappShowHumanError(err || { message: kind + " connect failed" }, (err && err.status) || 400, { toast: true });
          }
        });
    }, true);
  }

  try {
    document.addEventListener("DOMContentLoaded", wireIntegrationConnect);
  } catch (_) {}

  // Profile integrations: paint only inside .client-edit-modal, never scan the whole page.
  (function syncProfileIntegrations() {
    let loading = false;
    let lastFetch = 0;
    let linked = false;
    let discordName = "";
    let discordAvatar = "";
    let steamPersona = "";
    let steamPic = "";
    let steamRetry = 0;
    function profileModal() {
      return document.querySelector(".client-edit-modal");
    }
    function integrationsRoot() {
      const m = profileModal();
      if (!m) return null;
      return m.querySelector(".integrations") || null;
    }
    function authHeaders() {
      const headers = { Accept: "application/json" };
      try {
        const token = readAuthToken();
        if (token) headers.Authorization = "Bearer " + token;
        const slug = currentProjectSlug();
        if (slug) headers["X-Checkapp-Project"] = slug;
      } catch (_) {}
      return headers;
    }
    function writePiniaSteam(name, avatar) {
      try {
        const root = document.querySelector("#app");
        const pinia = root && root.__vue_app__ && root.__vue_app__.config && root.__vue_app__.config.globalProperties && root.__vue_app__.config.globalProperties.$pinia;
        if (!pinia || !pinia._s) return;
        pinia._s.forEach(function (store) {
          const c = store && (store.client || (store.$state && store.$state.client));
          if (!c || typeof c !== "object") return;
          if (c.steam && typeof c.steam === "object") {
            if (avatar) {
              c.steam.steam_avatar = avatar;
              c.steam.avatar = avatar;
              c.steam.avatarfull = avatar;
            }
            if (name) {
              c.steam.steam_name = name;
              c.steam.personaname = name;
              c.steam.name = name;
            }
          }
        });
      } catch (_) {}
    }
    function steamAvatarPx(root) {
      if (!root) return 34;
      const rows = Array.from(root.children || []);
      for (let i = 0; i < rows.length; i++) {
        const t = rows[i].querySelector(".title, p.title");
        if (!t || !/^steam$/i.test(String(t.textContent || "").trim())) continue;
        const box = rows[i].querySelector(".n-avatar, .n-avatar-container, img.ca-int-ava, .skeleton, img");
        if (!box) continue;
        const w = Math.round(box.getBoundingClientRect().width);
        if (w >= 28 && w <= 56) return w;
      }
      return 34;
    }
    function isIntegrationTextHost(el) {
      if (!el) return false;
      if (el.querySelector(".title, .message, p.title, p.message, button")) return true;
      const t = String(el.textContent || "").replace(/\s+/g, " ").trim();
      return /steam|discord|telegram|google/i.test(t) && t.length > 12;
    }
    function fillAvatarSlot(row, url, label) {
      if (!row || !url) return;
      row.style.display = "flex";
      row.style.justifyContent = "space-between";
      row.style.alignItems = "center";
      row.style.width = "100%";
      const size = steamAvatarPx(row.parentElement);
      const svg = row.querySelector("svg");
      const sk = row.querySelector(".skeleton");
      let host = row.querySelector(".n-avatar, .n-avatar-container, .ca-int-ava-host");
      if (!host && svg && svg.parentElement && svg.parentElement !== row) host = svg.parentElement;
      if (!host && sk && sk.parentElement && sk.parentElement !== row) host = sk.parentElement;
      const native = row.querySelector("img:not(.ca-int-ava)");
      if (!host && native && native.parentElement && native.parentElement !== row) host = native.parentElement;
      if (!host) {
        const item = row.querySelector(".item, .modal-menu-list-item, [class*='list-item']") || row.firstElementChild || row;
        host = item.firstElementChild || item;
      }
      if (isIntegrationTextHost(host)) {
        let icon = host.firstElementChild;
        while (icon && isIntegrationTextHost(icon) && icon.firstElementChild) icon = icon.firstElementChild;
        if (icon && !isIntegrationTextHost(icon)) host = icon;
        else {
          const box = document.createElement("div");
          box.className = "ca-int-ava-host";
          host.insertBefore(box, host.firstChild);
          host = box;
        }
      }
      if (!host) return;
      host.classList.add("ca-int-ava-host");
      const px = size + "px";
      host.style.setProperty("width", px, "important");
      host.style.setProperty("height", px, "important");
      host.style.setProperty("min-width", px, "important");
      host.style.setProperty("min-height", px, "important");
      host.style.setProperty("max-width", px, "important");
      host.style.setProperty("max-height", px, "important");
      host.style.setProperty("border-radius", "50%", "important");
      host.style.setProperty("overflow", "hidden", "important");
      host.style.setProperty("flex", "0 0 " + px, "important");
      host.style.setProperty("display", "flex", "important");
      host.style.setProperty("align-items", "center", "important");
      host.style.setProperty("justify-content", "center", "important");
      host.style.setProperty("background", "#2a2a2a", "important");
      Array.from(host.querySelectorAll("svg, .skeleton, .n-icon, .n-base-icon")).forEach(function (el) {
        el.style.setProperty("display", "none", "important");
        el.style.setProperty("visibility", "hidden", "important");
        el.style.setProperty("width", "0", "important");
        el.style.setProperty("height", "0", "important");
      });
      if (svg) {
        svg.style.setProperty("display", "none", "important");
        svg.style.setProperty("visibility", "hidden", "important");
      }
      if (sk) sk.style.setProperty("display", "none", "important");
      let img = host.querySelector("img.ca-int-ava");
      if (!img) {
        img = document.createElement("img");
        img.className = "ca-int-ava";
        host.insertBefore(img, host.firstChild);
      }
      Array.from(row.querySelectorAll("img.ca-int-ava")).forEach(function (el) {
        if (el !== img) el.remove();
      });
      img.onload = function () {
        if (sk) sk.style.setProperty("display", "none", "important");
      };
      img.onerror = function () {
        if (img.parentElement) img.remove();
        if (sk) sk.style.removeProperty("display");
      };
      img.src = url;
      img.alt = label || "";
      img.style.setProperty("width", px, "important");
      img.style.setProperty("height", px, "important");
      img.style.setProperty("min-width", px, "important");
      img.style.setProperty("min-height", px, "important");
      img.style.setProperty("max-width", px, "important");
      img.style.setProperty("max-height", px, "important");
      img.style.setProperty("border-radius", "50%", "important");
      img.style.setProperty("object-fit", "cover", "important");
      img.style.setProperty("display", "block", "important");
      img.style.setProperty("flex-shrink", "0", "important");
      const msg = row.querySelector("p.message, .message");
      if (msg && label) msg.textContent = label;
    }
    function paint() {
      const root = integrationsRoot();
      if (!root) return;
      Array.from(root.children).forEach(function (row) {
        if (!row || row.nodeType !== 1) return;
        const titleEl = row.querySelector(".title, p.title");
        const title = titleEl ? String(titleEl.textContent || "").replace(/\s+/g, " ").trim() : "";
        if (/^steam$/i.test(title) && isSteamCdnAvatar(steamPic)) fillAvatarSlot(row, steamPic, steamPersona);
        if (!/^discord$/i.test(title)) return;
        if (!linked) return;
        fillAvatarSlot(row, discordAvatar, discordName);
        const steamBtn = (function () {
          const kids = Array.from(root.children || []);
          for (let i = 0; i < kids.length; i++) {
            const te = kids[i].querySelector(".title, p.title");
            if (te && /^steam$/i.test(String(te.textContent || "").trim())) {
              return kids[i].querySelector("button, .n-button, .button-truncated");
            }
          }
          return null;
        })();
        row.querySelectorAll("button, .button-truncated, .n-button").forEach(function (button) {
          button.textContent = "Отвязать";
          button.disabled = false;
          button.removeAttribute("disabled");
          button.style.cursor = "pointer";
          if (steamBtn && steamBtn !== button) {
            const cs = window.getComputedStyle(steamBtn);
            const bg = cs.backgroundColor || "";
            const transparent = !bg || bg === "transparent" || /rgba\(\s*0,\s*0,\s*0,\s*0/.test(bg);
            button.style.setProperty("background", transparent ? "#d03050" : bg, "important");
            button.style.setProperty("background-color", transparent ? "#d03050" : bg, "important");
            button.style.setProperty("color", transparent ? "#fff" : (cs.color || "#fff"), "important");
            button.style.setProperty("border-color", transparent ? "#d03050" : (cs.borderColor || "transparent"), "important");
            button.style.setProperty("box-shadow", "none", "important");
            steamBtn.classList.forEach(function (c) {
              if (/n-button|error|warning|primary/.test(c) && !button.classList.contains(c)) button.classList.add(c);
            });
          } else {
            button.style.setProperty("background", "#d03050", "important");
            button.style.setProperty("background-color", "#d03050", "important");
            button.style.setProperty("color", "#fff", "important");
            button.style.setProperty("border", "none", "important");
          }
          if (button.dataset.caDiscordUnlink === "1") return;
          button.dataset.caDiscordUnlink = "1";
          button.addEventListener("click", function (ev) {
            ev.preventDefault();
            ev.stopImmediatePropagation();
            fetch("/auth/discord-connect", { method: "DELETE", credentials: "include", cache: "no-store", headers: authHeaders() })
              .finally(function () { clearDiscordProfile(); location.reload(); });
          }, true);
        });
      });
    }
    function sync() {
      if (!integrationsRoot() || loading) return;
      const cached = readJsonStore(DISCORD_CACHE_KEY, null);
      if (cached && cached.discord_id) {
        linked = true;
        discordName = discordName || cached.discord_name || "";
        discordAvatar = discordAvatar || cached.discord_avatar || discordDefaultAvatar(cached.discord_id);
      }
      paint();
      if (Date.now() - lastFetch < 5000) return;
      loading = true;
      lastFetch = Date.now();
      fetch("/client", { credentials: "include", cache: "no-store", headers: authHeaders() })
        .then(function (res) { return res.ok ? res.json() : null; })
        .then(function (profile) {
          if (profile) {
            applyCachedDiscord(profile);
            rememberDiscordProfile(profile);
          }
          const discord = profile && profile.discord;
          linked = !!(profile && (profile.discord_id || (discord && (discord.discord_id || discord.id)) || (profile.integrations && profile.integrations.discord && profile.integrations.discord.connected)));
          const steamName = String((profile && (profile.steam_name || (profile.steam && profile.steam.steam_name))) || "").trim();
          const accountName = String((profile && profile.name) || "").trim();
          let gotName = String((discord && (discord.discord_name || discord.global_name || discord.username)) || (profile && profile.discord_name) || "").trim();
          if (!gotName || gotName === steamName || gotName === accountName || gotName === String((profile && profile.discord_id) || "")) {
            gotName = String((discord && (discord.username || discord.discord_username)) || "").trim();
          }
          if (gotName === steamName || gotName === accountName) gotName = "";
          discordName = gotName || discordName;
          let gotAv = String((discord && (discord.discord_avatar || discord.avatar)) || (profile && profile.discord_avatar) || "").trim();
          if (!/cdn\.discordapp\.com/i.test(gotAv)) {
            gotAv = discordDefaultAvatar(String((profile && profile.discord_id) || (discord && discord.discord_id) || (cached && cached.discord_id) || ""));
          }
          discordAvatar = gotAv || discordAvatar;
          const sid = String((profile && ((profile.steam && profile.steam.steam_id) || profile.steam_id)) || "");
          steamPersona = cleanSteamName((profile && profile.steam && (profile.steam.personaname || profile.steam.steam_name || profile.steam.name)) || (profile && profile.steam_name) || "", sid) || steamPersona;
          steamPic = steamHttpsAvatar((profile && profile.steam && (profile.steam.avatarfull || profile.steam.steam_avatar || profile.steam.avatar)) || (profile && profile.steam_avatar) || "");
          if (!steamPic && sid) steamPic = location.origin + "/uploads/steam-" + sid + ".jpg";
          if (!isSteamCdnAvatar(steamPic)) steamPic = "";
          if (!steamPersona) steamPersona = "Steam";
          if (steamPic) writePiniaSteam(steamPersona, steamPic);
          paint();
          if (sid && !steamPic && steamRetry < 4) {
            steamRetry += 1;
            setTimeout(function () { lastFetch = 0; if (profileModal()) sync(); }, 1600);
          }
        })
        .catch(function () { paint(); })
        .finally(function () { loading = false; });
    }
    setInterval(function () {
      if (!profileModal()) return;
      sync();
    }, 400);
  })();

  (function paintStaffClientIntegrations() {
    function authHeaders() {
      const headers = { Accept: "application/json" };
      try {
        const token = readAuthToken();
        if (token) headers.Authorization = "Bearer " + token;
        const slug = currentProjectSlug();
        if (slug) headers["X-Checkapp-Project"] = slug;
      } catch (_) {}
      return headers;
    }
    function findStaffModal() {
      const nodes = Array.from(document.querySelectorAll(".vfm__content, [role='dialog'], .n-modal-body, .modal")).filter(function (el) {
        if (!el || el.id === "app") return false;
        if (el.closest(".client-edit-modal")) return false;
        const t = String(el.innerText || "");
        if (t.indexOf("Интеграции") < 0) return false;
        if (t.indexOf("Имя пользователя") < 0 && t.indexOf("@") < 0) return false;
        if (t.indexOf("Профиль") >= 0 && t.indexOf("Безопасность") >= 0 && t.indexOf("Проекты") >= 0) return false;
        const r = el.getBoundingClientRect();
        return r.width > 180 && r.width < 720 && r.height > 140;
      });
      nodes.sort(function (a, b) { return a.getBoundingClientRect().width - b.getBoundingClientRect().width; });
      return nodes[0] || null;
    }
    function clientIdFromModal(modal) {
      if (!modal) return 0;
      const seen = [];
      function walk(el, depth) {
        if (!el || depth > 14 || seen.indexOf(el) >= 0) return 0;
        seen.push(el);
        const inst = el.__vueParentComponent || el.__vue__;
        const props = inst && inst.props;
        const setup = inst && inst.setupState;
        const cands = [
          props && props.client,
          setup && setup.a,
          setup && setup.client,
          inst && inst.ctx && inst.ctx.client
        ];
        for (let i = 0; i < cands.length; i++) {
          let obj = cands[i];
          if (obj && obj.value) obj = obj.value;
          const id = Number((obj && obj.id) || 0);
          if (id > 0) return id;
        }
        const kids = el.children || [];
        for (let k = 0; k < kids.length; k++) {
          const got = walk(kids[k], depth + 1);
          if (got) return got;
        }
        return 0;
      }
      const fromTree = walk(modal, 0);
      if (fromTree) return fromTree;
      let n = modal;
      for (let i = 0; i < 10 && n; i++) {
        const got = walk(n, 0);
        if (got) return got;
        n = n.parentElement;
      }
      return 0;
    }
    function steamItem(modal) {
      return Array.from(modal.querySelectorAll(".item, [class*='item']")).find(function (el) {
        if (el.classList && (el.classList.contains("ca-staff-discord") || el.classList.contains("ca-staff-google"))) return false;
        return /^steam$/i.test(String((el.querySelector(".title, p.title") || {}).textContent || "").trim())
          || (/steam/i.test(String(el.textContent || "")) && !/discord|google|telegram/i.test(String((el.querySelector(".title, p.title") || {}).textContent || "")));
      }) || null;
    }
    function fillStaffRow(item, title, name, avatar, href) {
      if (!item) return;
      const titleEl = item.querySelector(".title, p.title");
      if (titleEl) titleEl.textContent = title;
      const msg = item.querySelector(".message, p.message, [class*='message']");
      if (msg) msg.textContent = name || title;
      let img = item.querySelector("img");
      if (!img && avatar) {
        img = document.createElement("img");
        const host = item.querySelector(".n-avatar, .skeleton, .ca-int-ava-host") || item.firstElementChild;
        if (host) {
          host.querySelectorAll(".skeleton, svg").forEach(function (el) {
            el.style.setProperty("display", "none", "important");
          });
          host.insertBefore(img, host.firstChild);
        } else {
          item.insertBefore(img, item.firstChild);
        }
      }
      if (img && avatar) {
        img.onload = function () {
          item.querySelectorAll(".skeleton").forEach(function (sk) { sk.style.display = "none"; });
        };
        img.onerror = function () { if (img.parentElement) img.style.display = "none"; };
        img.src = avatar;
        img.alt = name || title;
        img.style.cssText = "width:36px;height:36px;min-width:36px;min-height:36px;border-radius:50%;object-fit:cover;display:block;flex-shrink:0";
      }
      if (href) {
        item.style.cursor = "pointer";
        item.onclick = function (ev) {
          if (ev.target.closest("button, a")) return;
          window.open(href, "_blank", "noopener");
        };
      }
    }
    function cloneSteamCard(modal, kind) {
      const steam = steamItem(modal);
      const row = (steam && steam.parentElement) || modal.querySelector(".items-row");
      if (!row || !steam) return null;
      let card = row.querySelector(".ca-staff-" + kind);
      if (!card) {
        card = steam.cloneNode(true);
        card.classList.add("ca-staff-" + kind);
        card.querySelectorAll("[data-ca-discord-unlink]").forEach(function (el) { el.removeAttribute("data-ca-discord-unlink"); });
        row.appendChild(card);
      }
      return card;
    }
    function applyProfile(modal, profile) {
      if (!modal || !profile) return;
      const steam = profile.steam && typeof profile.steam === "object" ? profile.steam : null;
      const sid = String((steam && (steam.steam_id || steam.steamid)) || profile.steam_id || "").trim();
      let steamAv = steamHttpsAvatar((steam && (steam.avatarfull || steam.steam_avatar || steam.avatar)) || profile.steam_avatar || "");
      if (!steamAv && sid) steamAv = location.origin + "/uploads/steam-" + sid + ".jpg";
      const steamName = cleanSteamName((steam && (steam.personaname || steam.steam_name || steam.name)) || profile.steam_name || "", sid) || "Steam";
      const steamUrl = (steam && (steam.profileurl || steam.profile_url || steam.url)) || (sid ? "https://steamcommunity.com/profiles/" + sid : "");
      if (sid || steam) fillStaffRow(steamItem(modal), "Steam", steamName, steamAv, steamUrl);

      const disc = profile.discord && typeof profile.discord === "object" ? profile.discord : null;
      const did = String((disc && (disc.discord_id || disc.id)) || profile.discord_id || "").trim();
      const discordCard = modal.querySelector(".ca-staff-discord");
      if (did) {
        const dname = String((disc && (disc.discord_name || disc.global_name || disc.username || disc.name)) || profile.discord_name || "").trim() || "Discord";
        const dav = String((disc && (disc.discord_avatar || disc.avatar)) || profile.discord_avatar || "").trim() || discordDefaultAvatar(did);
        fillStaffRow(cloneSteamCard(modal, "discord"), "Discord", dname, dav, "https://discord.com/users/" + did);
      } else if (discordCard) {
        discordCard.remove();
      }

      const goog = profile.google && typeof profile.google === "object" ? profile.google : null;
      const gid = String((goog && (goog.google_id || goog.id)) || profile.google_id || "").trim();
      const googleCard = modal.querySelector(".ca-staff-google");
      if (gid) {
        const gname = String((goog && (goog.google_name || goog.name || goog.email)) || profile.google_name || "").trim() || "Google";
        const gav = String((goog && (goog.google_avatar || goog.avatar)) || profile.google_avatar || "").trim();
        fillStaffRow(cloneSteamCard(modal, "google"), "Google", gname, gav, "");
      } else if (googleCard) {
        googleCard.remove();
      }
    }
    var loading = {};
    var painted = {};
    function sync() {
      const modal = findStaffModal();
      if (!modal) return;
      let id = clientIdFromModal(modal);
      if (!id) {
        const tagm = String(modal.innerText || "").match(/@([A-Za-z0-9._-]{2,32})/);
        const tag = tagm ? tagm[1] : "";
        if (!tag) return;
        const known = window.__caClients
          ? Object.values(window.__caClients).find(function (c) { return c && String(c.tag || "").replace(/^@/, "") === tag; })
          : null;
        if (known) applyProfile(modal, known);
        if (loading["tag:" + tag]) return;
        loading["tag:" + tag] = true;
        fetch("/utils/client-by-tag?tag=" + encodeURIComponent(tag), { credentials: "include", cache: "no-store", headers: authHeaders() })
          .then(function (res) { return res.ok ? res.json() : null; })
          .then(function (profile) {
            if (profile && profile.id) {
              try { rememberStaffClient(profile); } catch (_) {}
              painted["tag:" + tag] = true;
              applyProfile(findStaffModal() || modal, profile);
            }
          })
          .catch(function () {})
          .finally(function () { loading["tag:" + tag] = false; });
        return;
      }
      const cached = window.__caClients ? window.__caClients[String(id)] : null;
      if (cached) applyProfile(modal, cached);
      if (loading[id] || painted[id]) return;
      loading[id] = true;
      fetch("/client/" + id, { credentials: "include", cache: "no-store", headers: authHeaders() })
        .then(function (res) { return res.ok ? res.json() : null; })
        .then(function (profile) {
          if (profile && profile.id) {
            try { rememberStaffClient(profile); } catch (_) {}
            painted[id] = true;
            applyProfile(findStaffModal() || modal, profile);
          }
        })
        .catch(function () {})
        .finally(function () { loading[id] = false; });
    }
    document.addEventListener("click", function () {
      requestAnimationFrame(sync);
    }, true);
    setInterval(sync, 400);
  })();

  (function watchAvatarSave() {
    function authHeaders() {
      const headers = { Accept: "application/json", "Content-Type": "application/json" };
      try {
        const token = readAuthToken();
        if (token) headers.Authorization = "Bearer " + token;
        const slug = currentProjectSlug();
        if (slug) headers["X-Checkapp-Project"] = slug;
      } catch (_) {}
      return headers;
    }
    function enableButton(el) {
      if (!el) return;
      el.removeAttribute("disabled");
      el.disabled = false;
      el.classList.remove("disabled", "-hidden");
      el.style.pointerEvents = "auto";
      el.style.opacity = "1";
      el.style.display = "";
    }
    function finishSignupFromForm(btn) {
      const root = (btn && btn.closest && (btn.closest("form") || btn.closest(".vfm") || btn.closest("main"))) || document;
      const inputs = root.querySelectorAll("input:not([type='hidden']):not([type='file']):not([type='checkbox']):not([type='radio'])");
      const name = String((inputs[0] && inputs[0].value) || "").trim();
      let tag = String((inputs[1] && inputs[1].value) || "").trim().replace(/^@/, "");
      if (!name || !tag) return false;
      fetch("/client", {
        method: "PUT",
        credentials: "include",
        headers: authHeaders(),
        body: JSON.stringify({ name: name, tag: tag, username: tag, nickname: name })
      }).then(function (res) { return res.ok ? res.json() : null; })
        .then(function (profile) {
          if (profile && profile.id) {
            try { window.__caMeId = profile.id; } catch (_) {}
            location.assign("/client/auth");
            setTimeout(function () { location.reload(); }, 200);
          }
        }).catch(function () {});
      return true;
    }
    function unlockSignupButton() {
      document.querySelectorAll("button, [role='button'], .n-button").forEach(function (btn) {
        const t = String(btn.textContent || "").replace(/\s+/g, " ").trim();
        if (!/Завершить регистрацию|Complete registration|Finish registration|Завершити реєстрацію/i.test(t)) return;
        enableButton(btn);
        if (btn.dataset.caSignupFix === "1") return;
        btn.dataset.caSignupFix = "1";
        btn.addEventListener("click", function (ev) {
          enableButton(btn);
          /* PUT /client only works with an existing session: this path is for
             "complete profile" flows (OAuth sign-in already stored a token).
             During classic / OAuth sign-UP there is no token yet — the SPA's
             own handler must run and create the account (POST .../sign-up).
             Hijacking it here silently broke account creation. */
          var hasToken = false;
          try { hasToken = !!readAuthToken(); } catch (_) {}
          if (!hasToken) return;
          if (finishSignupFromForm(btn)) {
            ev.preventDefault();
            ev.stopImmediatePropagation();
          }
        }, true);
      });
    }
    setInterval(unlockSignupButton, 600);
    unlockSignupButton();
    function revealProfileSave() {
      const tab = document.querySelector(".modal-menu-tab:has(.avatar-changer)");
      if (!tab) return;
      const pending = window.__caPendingProfileAvatar;
      const blob = tab.querySelector("img[src^='blob:'], img[src*='/uploads/']");
      if (!pending && !blob) return;
      const footer = tab.querySelector(".footer");
      if (!footer) return;
      footer.classList.remove("-hidden");
      footer.style.display = "flex";
      footer.style.visibility = "visible";
      const save = footer.querySelector("button, [class*='button']");
      enableButton(save);
      if (!save || save.dataset.caAvatarSave === "1") return;
      save.dataset.caAvatarSave = "1";
      save.addEventListener("click", function (ev) {
        const avatar = window.__caPendingProfileAvatar;
        if (!avatar) return;
        ev.preventDefault();
        ev.stopImmediatePropagation();
        const fields = tab.querySelectorAll("input:not([type='file']), textarea");
        const payload = { avatar: avatar };
        if (fields[0]) payload.name = fields[0].value;
        if (fields[1]) payload.tag = fields[1].value;
        if (fields[2]) payload.bio = fields[2].value;
        fetch("/client/profile", { method: "PUT", credentials: "include", headers: authHeaders(), body: JSON.stringify(payload) })
          .then(function (res) { return res.ok ? res.json() : null; })
          .then(function () { window.__caPendingProfileAvatar = ""; location.reload(); });
      }, true);
    }
    function revealProjectSave() {
      const pending = window.__caPendingProjectAvatar;
      if (!pending) return;
      const page = document.querySelector(".logo-avatar");
      if (!page) return;
      let row = document.getElementById("checkapp-avatar-save-row");
      const host = page.closest("div") && page.closest("div").parentElement;
      const existing = document.querySelector("button, [class*='button']");
      document.querySelectorAll("button, [class*='button']").forEach(function (btn) {
        if (!/save|сохран/i.test(String(btn.textContent || ""))) return;
        enableButton(btn);
      });
      if (row) return;
      row = document.createElement("div");
      row.id = "checkapp-avatar-save-row";
      row.style.cssText = "display:flex;gap:8px;margin-top:12px;";
      const save = document.createElement("button");
      save.type = "button";
      save.textContent = "Сохранить";
      save.style.cssText = "padding:8px 14px;border-radius:8px;background:#3b82f6;color:#fff;border:0;cursor:pointer;font-size:14px;";
      save.addEventListener("click", function () {
        let project = null;
        try {
          const pinia = piniaRoot();
          if (pinia && pinia._s) {
            pinia._s.forEach(function (store) {
              const st = store && (store.$state || store);
              if (st && st.project && st.project.id) project = st.project;
            });
          }
        } catch (_) {}
        if (!project || !project.id) return;
        fetch("/project/" + project.id + "/general", {
          method: "PUT",
          credentials: "include",
          headers: authHeaders(),
          body: JSON.stringify({
            name: project.name,
            domain: project.domain,
            avatar: pending,
            contact_url: project.contact_url || ""
          })
        }).then(function (res) { return res.ok ? res.json() : null; })
          .then(function () { window.__caPendingProjectAvatar = ""; location.reload(); });
      });
      const wrap = page.closest("[class*='settings']") || page.parentElement;
      if (wrap) wrap.appendChild(row);
      row.appendChild(save);
    }
    document.addEventListener("change", function (ev) {
      const input = ev.target;
      if (!input || input.type !== "file" || !input.files || !input.files[0]) return;
      const file = input.files[0];
      const inProfile = !!(input.closest(".modal-menu-tab") && document.querySelector(".avatar-changer"));
      const inProject = !!document.querySelector(".logo-avatar") && !inProfile;
      if (!inProfile && !inProject) return;
      const fd = new FormData();
      fd.append("file", file, file.name);
      fetch("/utils/upload?type=" + (inProject ? "avatar-project" : "avatar-user"), {
        method: "POST",
        credentials: "include",
        body: fd
      }).then(function (res) { return res.json(); }).then(function (url) {
        if (typeof url !== "string") url = (url && (url.url || url.s3_id)) || "";
        url = String(url || "").trim();
        if (!url) return;
        if (inProject) window.__caPendingProjectAvatar = url;
        else window.__caPendingProfileAvatar = url;
        revealProfileSave();
        revealProjectSave();
      }).catch(function () {});
    }, true);
    setInterval(function () {
      revealProfileSave();
      revealProjectSave();
    }, 800);
  })();

  function piniaRoot() {
    try {
      const root = document.querySelector("#app");
      const app = root && root.__vue_app__;
      return app && app.config && app.config.globalProperties && app.config.globalProperties.$pinia;
    } catch (_) {
      return null;
    }
  }

  function selectedStatsClientId() {
    try {
      const u = new URL(location.href);
      const q = Number(u.searchParams.get("client_id") || u.searchParams.get("clientId") || u.searchParams.get("ids") || 0);
      if (q) return q;
    } catch (_) {}
    try {
      const pinia = piniaRoot();
      if (!pinia || !pinia._s) return Number(window.__caStatsClientId || 0) || 0;
      let found = 0;
      pinia._s.forEach(function (store) {
        const st = store && (store.$state || store);
        if (!st || typeof st !== "object") return;
        const cid = Number(
          st.client_id || st.clientId
          || (st.client && st.client.id)
          || st.selectedClientId
          || (st.selectedClient && st.selectedClient.id)
          || st.selected_client_id
          || (st.filter && (st.filter.client_id || st.filter.clientId))
          || 0
        ) || 0;
        if (cid) found = cid;
      });
      return found || Number(window.__caStatsClientId || 0) || 0;
    } catch (_) {
      return Number(window.__caStatsClientId || 0) || 0;
    }
  }

  function rememberActiveCheck(steamId, checkId, finished) {
    try {
      window.__caActiveChecks = window.__caActiveChecks || {};
      const sid = String(steamId || "");
      const cid = Number(checkId || 0) || 0;
      if (!sid || sid === "0") return;
      if (finished || !cid) delete window.__caActiveChecks[sid];
      else window.__caActiveChecks[sid] = cid;
    } catch (_) {}
  }

  function activeCheckIdFor(steamId) {
    try {
      const sid = String(steamId || "");
      const n = Number((window.__caActiveChecks && window.__caActiveChecks[sid]) || 0) || 0;
      return n;
    } catch (_) {
      return 0;
    }
  }

  function piniaCurrentProjectId() {
    try {
      const pinia = piniaRoot();
      if (!pinia || !pinia._s) return Number(window.__caProjectId || 0) || 0;
      let found = 0;
      pinia._s.forEach(function (store) {
        if (found) return;
        const p = store.project || (store.$state && store.$state.project);
        if (p && p.id) found = Number(p.id) || 0;
      });
      if (found) window.__caProjectId = found;
      return found || Number(window.__caProjectId || 0) || 0;
    } catch (_) {
      return Number(window.__caProjectId || 0) || 0;
    }
  }

  function piniaCourtServers() {
    try {
      const pinia = piniaRoot();
      const court = pinia && pinia._s && (pinia._s.get("court") || pinia._s.get("Court"));
      const raw = court && (court.servers || (court.$state && court.$state.servers));
      const list = raw && raw.value ? raw.value : raw;
      return Array.isArray(list) ? list : [];
    } catch (_) {
      return [];
    }
  }

  function settleSiteChatMessages(chat) {
    try {
      if (!chat) return;
      const ref = chat.messages;
      const arr = ref && Array.isArray(ref.value) ? ref.value : (Array.isArray(chat.messages) ? chat.messages : null);
      if (!arr || arr.length < 2) return;
      let bad = false;
      for (let i = 1; i < arr.length; i++) {
        const prev = Number((arr[i - 1] && arr[i - 1].created_at) || 0);
        const next = Number((arr[i] && arr[i].created_at) || 0);
        if (next < prev) { bad = true; break; }
      }
      if (!bad) return;
      arr.sort(function (a, b) {
        const ta = Number((a && a.created_at) || 0);
        const tb = Number((b && b.created_at) || 0);
        if (ta !== tb) return ta - tb;
        const ia = Number((a && (a.id || a.M_ID)) || 0);
        const ib = Number((b && (b.id || b.M_ID)) || 0);
        return ia - ib;
      });
      if (ref && typeof ref === "object" && "value" in ref) ref.value = arr.slice();
    } catch (_) {}
  }

  function patchSpaChatAndTeam() {
    try {
      const pinia = piniaRoot();
      if (!pinia || !pinia._s) return;
      const chat = pinia._s.get("player-message-page-data");
      if (chat && typeof chat.appendMessages === "function" && !chat.__caPatchedAppend) {
        const orig = chat.appendMessages.bind(chat);
        chat.__caPatchedAppend = true;
        chat.appendMessages = function (rows, dir) {
          const list = Array.isArray(rows) ? rows : (rows ? [rows] : []);
          return orig(list, dir);
        };
      }
      if (chat) settleSiteChatMessages(chat);
      const court = pinia._s.get("court") || pinia._s.get("Court");
      if (court && typeof court.serverNameById === "function" && !court.__caPatchedServerName) {
        const origName = court.serverNameById.bind(court);
        court.__caPatchedServerName = true;
        court.serverNameById = function (id) {
          const servers = piniaCourtServers();
          const nid = Number(id || 0) || 0;
          const sid = String(id == null ? "" : id);
          function cleanName(row) {
            if (!row) return "";
            let name = String(row.name || row.hostname || row.server_name || "").trim();
            if (/^#\d+$/.test(name)) name = String(row.hostname || row.server_name || "").trim();
            if (/^#\d+$/.test(name)) return "";
            return name;
          }
          let row = servers.find(function (s) {
            return Number(s && s.id) === nid || String(s && s.id) === sid;
          });
          if (!row && servers.length === 1) row = servers[0];
          let name = cleanName(row);
          if (name) return name;
          const fallback = origName(id);
          if (fallback && !/^#\d+$/.test(String(fallback))) return String(fallback);
          for (let i = 0; i < servers.length; i++) {
            name = cleanName(servers[i]);
            if (name) return name;
          }
          return name || window.__checkappLastServerName || "Rust";
        };
      }
    } catch (_) {}
  }

  try {
    document.addEventListener("DOMContentLoaded", function () {
      patchSpaChatAndTeam();
      setInterval(patchSpaChatAndTeam, 1500);
    });
  } catch (_) {}

  function finishOAuthLogin(pathValidate, pathSignIn, pathSignUp, query, profileKeys) {
    const post = window.__checkappOrigFetch || window.fetch.bind(window);
    return post(pathValidate + "?query=" + encodeURIComponent(query), { credentials: "include", cache: "no-store" })
      .then(function (res) { return res.json().then(function (body) { return { res: res, body: body }; }); })
      .then(function (pack) {
        const info = pack.body || {};
        if (!pack.res.ok) {
          return Promise.reject({ message: (info && info.message) || "oauth.validate.failed" });
        }
        const signPath = info.exists ? pathSignIn : pathSignUp;
        const payload = info.exists ? { query: query } : {
          query: query,
          name: info[profileKeys.name] || "user",
          tag: info[profileKeys.name] || "user",
          avatar: info[profileKeys.avatar] || ""
        };
        return post(signPath, {
          method: "POST",
          credentials: "include",
          cache: "no-store",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        }).then(function (res) {
          return res.text().then(function (text) {
            let token = "";
            try {
              const parsed = JSON.parse(text);
              if (typeof parsed === "string") token = parsed;
              else if (parsed && typeof parsed === "object") token = parsed.token || parsed.access_token || "";
            } catch (_) {
              token = String(text || "").trim();
            }
            if (!res.ok || !token || token.split(".").length !== 3) {
              let msg = "oauth.signin.failed";
              try { msg = JSON.parse(text).message || msg; } catch (_) {}
              return Promise.reject({ message: msg });
            }
            storeAuthToken(token);
            if (!info.exists) sessionStorage.setItem("rc-complete-registration", "1");
            location.assign("/client/auth");
            return token;
          });
        });
      });
  }

  // IMPORTANT: do NOT define window.__checkappHandshake / __checkappProjects.
  // If they exist, SPA warmup skips real /auth/handshake and /project and stays stuck on auth.
  try {
    delete window.__checkappHandshake;
    delete window.__checkappProjects;
    window.__checkappClientCache = null;
    window.__checkappProjectsCache = [];
  } catch (_) {}

  function localMedia(pathname) {
    const path = String(pathname || "").split("?")[0];
    const name = path.split("/").pop();
    if ((path.includes("/landing/") || LANDING_FILES[name]) && name && LANDING_FILES[name]) {
      return location.origin + "/local/landing/" + name;
    }
    if (path.includes("/uploads/") && name) {
      return location.origin + "/uploads/" + name + "?https=1";
    }
    if (ASSET_FILES[name]) return location.origin + ASSET_FILES[name] + "?https=1";
    if (/rustlogo_dark/i.test(name || "")) return location.origin + "/local/image-1024.jpg";
    if (/1695419722879-43ad94311081cd8185649d49/.test(path)) return PLACEHOLDER;
    if (path.includes("plugin-sign")) return location.origin + "/local/landing/drawings.webp";
    return PLACEHOLDER;
  }

  function landingFileName(value) {
    const src = String(value || "").split("?")[0];
    const name = src.split("/").pop();
    return name && LANDING_FILES[name] ? name : "";
  }

  function isDeadMedia(src) {
    const href = String(src || "");
    if (!href || href.startsWith("data:") || href.startsWith("blob:")) return false;
    if (href.includes("/local/") || href.includes(location.origin + "/uploads/")) return false;
    if (/steamstatic|steamcdn|akamaihd\.net|avatars\.steam|cdn\.discordapp|discordapp\.com/i.test(href) && !/(?:s3|r2)\./i.test(href)) return false;
    return (
      /(?:^|\/\/)(?:s3|r2)\./i.test(href) ||
      href.includes("s3.checkapp") ||
      href.includes("r2.checkapp") ||
      href.includes("s3.rustapp") ||
      href.includes("r2.rustapp") ||
      href.includes("s3.rustcheck") ||
      href.includes("r2.rustcheck") ||
      /\/\/s3\.(?:127\.0\.0\.1|localhost)/i.test(href) ||
      (href.includes("rustapp.io") && !href.includes("docs.rustapp") && !href.includes("steam"))
    );
  }

  function localImages(value) {
    if (value == null || value === "") return PLACEHOLDER;
    if (typeof value === "object") value = value.url || value.s3_id || value.avatar || value.src || "";
    let src = String(value).trim();
    if (!src || src === "[object Object]" || src === "undefined" || src === "null") return PLACEHOLDER;
    if (src.startsWith("data:") || src.startsWith("blob:")) return src;
    if (src.startsWith("/local/") || src.startsWith("/uploads/")) {
      if (/logo-mark\.svg/i.test(src)) return BRAND_LOGO;
      return location.origin + src.split("?")[0].split("#")[0];
    }
    if (src.startsWith(location.origin + "/local/") || src.startsWith(location.origin + "/uploads/")) {
      if (/logo-mark\.svg/i.test(src)) return BRAND_LOGO;
      return src.split("?")[0].split("#")[0];
    }
    if (src.startsWith("http://") || src.startsWith("https://")) return imageSrc(src);
    if (src.startsWith("/")) {
      const name = src.split("?")[0].split("/").pop();
      if (ASSET_FILES[name] || /rustlogo_dark/i.test(name || "") || /1695419722879-43ad94311081cd8185649d49/.test(src)) {
        return localMedia(src);
      }
      return location.origin + src.split("?")[0].split("#")[0];
    }
    return imageSrc(src);
  }

  function rewriteBrokenImage(img) {
    if (!img || img.nodeType !== 1) return;
    const raw = String(img.getAttribute("src") || img.src || "");
    if (!raw || raw.startsWith("data:") || raw.startsWith("blob:")) return;
    if (/steamstatic|steamcdn|akamaihd\.net|cloudflare|avatars\.steam/i.test(raw) && !/s3\.|r2\.|checkapp|rustapp/i.test(raw)) return;
    if (raw.indexOf(location.origin + "/local/") === 0 || raw.indexOf(location.origin + "/uploads/") === 0) return;
    if (raw.indexOf("/local/") === 0 || raw.indexOf("/uploads/") === 0) return;
    if (isDeadMedia(raw) || /(?:^|\/\/)(?:s3|r2)\./i.test(raw) || /checkapp|rustapp\.io/i.test(raw)) {
      const next = localImages(raw);
      if (next && next !== raw) img.src = next;
    }
  }

  (function watchLocalImages() {
    function sweep(root) {
      const scope = root && root.querySelectorAll ? root : document;
      try {
        scope.querySelectorAll("img").forEach(rewriteBrokenImage);
      } catch (_) {}
    }
    if (document.documentElement) {
      new MutationObserver(function (records) {
        records.forEach(function (rec) {
          rec.addedNodes && rec.addedNodes.forEach(function (node) {
            if (!node || node.nodeType !== 1) return;
            if (node.tagName === "IMG") rewriteBrokenImage(node);
            else sweep(node);
          });
        });
      }).observe(document.documentElement, { childList: true, subtree: true });
    }
    setInterval(function () { sweep(document); }, 1500);
  })();

  function imageSrc(value) {
    if (value == null || value === "") return PLACEHOLDER;
    if (typeof value === "object") value = value.url || value.s3_id || value.avatar || value.src || "";
    let src = String(value).trim();
    if (!src || src === "[object Object]" || src === "undefined" || src === "null") return PLACEHOLDER;
    if (/logo-mark\.svg/i.test(src)) return BRAND_LOGO;
    if (/1695419722879-43ad94311081cd8185649d49/.test(src) || /avatar-project\/1695419722879/.test(src)) return PLACEHOLDER;
    if (/rustlogo_dark/i.test(src)) return location.origin + "/local/image-1024.jpg";
    if (src.includes("data:image")) {
      const idx = src.indexOf("data:image");
      return src.slice(idx).split(/[\s"'<>]/)[0];
    }
    if (src.startsWith("data:") || src.startsWith("blob:")) return src;
    if (/s3\.rustcheck\.cc\/sound\//i.test(src) || /\/sound\/(?:ping|ding-dong)\.mp3/i.test(src)) {
      return "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=";
    }
    if (/\/assets\/(?:apple\.spoiled|lock\.key|photo-|electric\.rf\.receiver)/i.test(src)) return PLACEHOLDER;
    // API used to emit http://127.0.0.1:8081/... — rewrite to current host
    src = src.replace(/^https?:\/\/127\.0\.0\.1(?::\d+)?/i, location.origin);
    src = src.replace(/^https?:\/\/localhost(?::\d+)?/i, location.origin);
    if (src.startsWith("/local/") || src.startsWith("/uploads/")) {
      if (/logo-mark\.svg/i.test(src)) return BRAND_LOGO;
      return location.origin + src.split("#")[0];
    }
    if (src.startsWith(location.origin + "/local/") || src.startsWith(location.origin + "/uploads/")) {
      if (/logo-mark\.svg/i.test(src)) return BRAND_LOGO;
      return src;
    }
    if (/(?:^|\/\/)(?:s3|r2)\./i.test(src)) {
      const upload = src.match(/(\/uploads\/[^\s"'?#]+)/i);
      if (upload) return location.origin + upload[1];
    }
    const landingName = landingFileName(src);
    if (landingName) return location.origin + "/local/landing/" + landingName;
    const brokenS3 = src.match(/(?:https?:)?\/\/s3\.[^/]+(\/[^?\s#'"]*)/i);
    if (brokenS3) return localMedia(brokenS3[1]);
    const dead = src.match(/(?:https?:)?\/\/(?:s3|r2)\.(?:checkapp|rustapp\.io)(\/[^?\s#'"]*)/i)
      || src.match(/(?:https?:)?\/\/[^/\s"']*rustapp\.io(\/[^?\s#'"]*)/i);
    if (dead) return localMedia(dead[1]);
    if (isDeadMedia(src)) return localMedia(src);
    if ((src.includes("amazonaws.com")) && !src.includes("steam")) return PLACEHOLDER;
    if (/steamstatic|steamcdn|akamaihd\.net\/steam/i.test(src)) {
      src = src.replace(/^http:\/\//i, "https://");
    }
    return src;
  }

  function fixSignageRow(row, i) {
    if (!row || typeof row !== "object") return null;
    row.net_id = row.net_id != null ? String(row.net_id) : "";
    if (row.server_id == null) row.server_id = 1;
    if (row.project_id == null) row.project_id = 1;
    const imgPath = row.url || row.image || row.src || "";
    if (!Array.isArray(row.variants)) {
      const img = localImages(imgPath);
      row.variants = [{
        id: row.id || i + 1,
        net_id: row.net_id,
        steam_id: row.steam_id,
        type: row.type || "sign",
        image: imgPath.startsWith("/") ? imgPath : img,
        url: imgPath.startsWith("/") ? imgPath : (imgPath.startsWith("data:") ? imgPath : img),
        src: imgPath.startsWith("/") ? imgPath : img,
        s3_id: imgPath.startsWith("/") ? imgPath : "",
        created_at: row.created_at || Date.now(),
        player: row.player || { steam_id: row.steam_id, steam_name: row.steam_name || row.steam_id }
      }];
    } else {
      row.variants.forEach((variant) => {
        if (!variant || typeof variant !== "object") return;
        variant.net_id = variant.net_id != null ? String(variant.net_id) : row.net_id;
        const raw = variant.url || variant.image || variant.src || imgPath || "";
        if (raw.startsWith("/")) {
          variant.url = raw;
          variant.image = raw;
          variant.src = raw;
          variant.s3_id = variant.s3_id || raw;
        } else if (raw.startsWith("data:")) {
          variant.url = raw;
          variant.image = raw;
          variant.src = raw;
        } else {
          const img = localImages(raw);
          variant.url = img;
          variant.image = img;
          variant.src = img;
        }
      });
    }
    const top = row.variants[0] || {};
    row.url = top.url || row.url || "";
    row.image = top.image || row.image || row.url || "";
    if (top.player && typeof top.player === "object") {
      row.player = top.player;
      if (top.player.steam_name) {
        row.steam_name = top.player.steam_name;
        row.name = top.player.steam_name;
      }
    } else if (!row.player || typeof row.player !== "object") {
      row.player = {
        steam_id: row.steam_id,
        steam_name: row.steam_name || row.name || row.steam_id,
        name: row.steam_name || row.name || row.steam_id
      };
    }
    // Keep position stringy for SPA parsers that call .match
    if (row.position && typeof row.position === "object") {
      const p = row.position;
      row.position = [p.x, p.y, p.z].filter(function (v) { return v != null; }).join(", ") || JSON.stringify(p);
    }
    return row;
  }

  function dedupeSignages(list) {
    const seen = new Set();
    const out = [];
    (Array.isArray(list) ? list : []).forEach((row) => {
      if (!row || typeof row !== "object") return;
      const key = String(row.net_id || "").trim();
      if (!key) return;
      if (seen.has(key)) return;
      seen.add(key);
      out.push(row);
    });
    return out;
  }

  function signageBrowseKey(href) {
    try {
      const u = new URL(String(href || ""), location.origin);
      return [
        currentProjectSlug(),
        u.searchParams.get("page") || "0",
        u.searchParams.get("server_id") || "",
        u.searchParams.get("search") || "",
        u.searchParams.get("only_liked") || "",
        u.searchParams.get("steam_id") || "",
        u.searchParams.get("hide_destroyed") || "",
        u.searchParams.get("hide_actual") || ""
      ].join("|");
    } catch (_) {
      return String(href || "");
    }
  }

  function parseSignageDeleteBody(body) {
    if (!body) return {};
    if (typeof body === "string") {
      try { return JSON.parse(body) || {}; } catch (_) { return {}; }
    }
    if (typeof body === "object") return body;
    return {};
  }

  function asVec(value) {
    if (typeof value === "string" && value.trim()) {
      const parts = value.replace(/[()]/g, "").split(",");
      if (parts.length >= 3) {
        const x = Number(parts[0]);
        const y = Number(parts[1]);
        const z = Number(parts[2]);
        if (!Number.isNaN(x) && !Number.isNaN(y) && !Number.isNaN(z)) {
          return { x: x, y: y, z: z, time: Date.now() };
        }
      }
    }
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return {
        x: Number(value.x ?? 0),
        y: Number(value.y ?? 0),
        z: Number(value.z ?? 0),
        time: Number(value.time ?? 0)
      };
    }
    return { x: 0, y: 0, z: 0, time: 0 };
  }

  function asCoords(value) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const text = String(value.value || value.grid || value.square || value.coords || "");
      return { value: text, grid: text, square: text };
    }
    const text = String(value || "").trim();
    return { value: text, grid: text, square: text };
  }

  function asHome(value) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return { time: Number(value.time || 0), value: !!value.value };
    }
    return { time: 0, value: false };
  }

  function bagPosText(row) {
    if (!row || typeof row !== "object") return "0.00, 0.00, 0.00";
    const raw = row.position;
    if (typeof raw === "string" && raw.trim() && raw.trim()[0] !== "{") {
      const n = raw.match(/-?\d+(?:\.\d+)?/g);
      if (n && n.length >= 3) {
        return Number(n[0]).toFixed(2) + ", " + Number(n[1]).toFixed(2) + ", " + Number(n[2]).toFixed(2);
      }
      return raw.trim();
    }
    const x = Number((raw && raw.x) ?? row.x ?? 0);
    const y = Number((raw && raw.y) ?? row.y ?? 0);
    const z = Number((raw && raw.z) ?? row.z ?? 0);
    return x.toFixed(2) + ", " + y.toFixed(2) + ", " + z.toFixed(2);
  }

  function walkFix(node, depth, seen) {
    if (!node || typeof node !== "object" || depth > 8) return;
    if (!seen) seen = new Set();
    if (seen.has(node)) return;
    seen.add(node);
    if (Array.isArray(node)) {
      for (let i = 0; i < node.length; i++) walkFix(node[i], depth + 1, seen);
      return;
    }
    const isBag = ("net_id" in node) || (node.initiator_steam_id != null && node.target_steam_id != null && node.seconds_connected == null);
    if (isBag) {
      const grid = String(node.grid || node.square || (node.coords && node.coords.value) || "").trim();
      if (grid) {
        node.position = grid;
        node.coordinates = grid;
        node.coordinate = grid;
        node.position_text = grid;
        node.grid = grid;
        node.square = grid;
      } else {
        node.position = bagPosText(node);
        node.coordinates = node.position;
        node.coordinate = node.position;
        node.position_text = node.position;
      }
    } else if (typeof node.position === "string" && /^-?\d+(?:\.\d+)?\s*,/.test(node.position.trim()) && (node.initiator_steam_id || node.from_steam_id)) {
      node.position = bagPosText(node);
      node.coordinates = node.position;
      node.coordinate = node.position;
      node.position_text = node.position;
    } else if (node.steam_name || (node.position && typeof node.position === "object")) {
      node.position = asVec(node.position);
      if ("rotation" in node) node.rotation = asVec(node.rotation);
      if ("home" in node) node.home = asHome(node.home);
      if (node.id == null && node.steam_id) node.id = node.steam_id;
    }
    if (node.id != null && node.M_ID == null) node.M_ID = node.id;
    if (node.type != null && node.M_ID == null) node.M_ID = node.id || node.type;
    ["team", "players", "members", "commands", "teammates", "results", "data", "items", "bans", "servers", "variants", "friends", "checks", "comments"].forEach(function (key) {
      if (key in node && node[key] == null) node[key] = [];
    });
    if (node.client && typeof node.client === "object") {
      if (!node.client.avatar) node.client.avatar = PLACEHOLDER;
      if (node.client.bio == null) node.client.bio = "";
      ensureClientIntegrations(node.client);
    }
    if ((node.email != null || node.tag != null) && node.steam_id == null) {
      ensureClientIntegrations(node);
    }
    if (node.project_original && typeof node.project_original === "object" && !node.project_original.avatar) {
      node.project_original.avatar = PLACEHOLDER;
    }
    if (node.avatar === undefined && (node.tag != null || node.email != null) && node.steam_id == null) {
      node.avatar = PLACEHOLDER;
    }
    if (node.bio == null && (node.tag != null || node.email != null) && node.steam_id == null) node.bio = "";
    if (node.project_id_original != null && (!node.project_original || typeof node.project_original !== "object")) {
      node.project_original = { id: node.project_id_original, name: node.name || "", avatar: PLACEHOLDER };
    }
    if (node.id != null) {
      try { Object.defineProperty(node, "toString", { configurable: true, value: function () { return String(this.id); } }); } catch (_) {}
    }
    if (node.options && typeof node.options === "object") {
      if (node.options.ignore_reports_after_days == null) node.options.ignore_reports_after_days = 7;
      if (node.options.ignore_reports_after_check == null) node.options.ignore_reports_after_check = 0;
      node.options.ignore_reports_after_days = Number(node.options.ignore_reports_after_days);
      node.options.ignore_reports_after_check = Number(node.options.ignore_reports_after_check);
    }
    for (const key in node) {
      if (!Object.prototype.hasOwnProperty.call(node, key)) continue;
      if (key === "position" || key === "rotation" || key === "home") continue;
      // Skip nested player copies that create cycles (alerts meta.bans[].player)
      if (key === "player" && depth > 1) continue;
      if (key === "meta" && node.meta && node.meta.player === node) continue;
      const child = node[key];
      if (child && typeof child === "object") walkFix(child, depth + 1, seen);
    }
  }

  function playerIsLive(status) {
    return /^(online|active|afk|joining|queued|unstable)$/i.test(String(status || ""));
  }

  function sanitizeLastOnline(player) {
    if (!player || typeof player !== "object") return;
    const now = Date.now();
    let last = Number(player.last_online_at);
    if (!isFinite(last)) last = 0;
    if (last > 0 && last < 1e12) last *= 1000;
    if (last <= 0 || last > now + 60000) {
      player.last_online_at = 0;
      return;
    }
    player.last_online_at = last;
  }

  function sanitizeSessionTimes(player, entity) {
    if (!player || typeof player !== "object") return entity || {};
    entity = entity && typeof entity === "object" ? entity : (player.entity || {});
    const now = Date.now();
    let seconds = Number(entity.seconds_connected != null ? entity.seconds_connected : player.seconds_connected) || 0;
    let connected = Number(entity.connected_at != null ? entity.connected_at : player.connected_at) || 0;
    if (seconds >= 1e12) seconds = Math.max(0, Math.floor((now - seconds) / 1000));
    else if (seconds >= 1e9) seconds = Math.max(0, Math.floor(now / 1000) - seconds);
    if (seconds < 0 || seconds > 14 * 86400) seconds = 0;
    if (connected > 0 && connected < 1e12) connected *= 1000;
    const online = /^(online|active|afk|unstable|joining|queued)$/i.test(String(player.status || ""));
    if (!online) {
      seconds = 0;
      connected = now;
    } else {
      if (seconds <= 0 && connected) seconds = Math.max(1, Math.floor((now - connected) / 1000));
      if (seconds <= 0) seconds = 1;
      if (!connected) connected = now - seconds * 1000;
      if (connected < now - 14 * 86400 * 1000 || connected > now + 60000) connected = now - seconds * 1000;
    }
    entity.seconds_connected = seconds;
    entity.connected_at = connected;
    player.seconds_connected = seconds;
    player.connected_at = connected;
    return entity;
  }

  function fixPlayerDetails(obj, href) {
    if (Array.isArray(obj)) obj = null;
    if (!obj || typeof obj !== "object") obj = {};
    let player = obj.player && typeof obj.player === "object" && obj.player.steam_id
      ? obj.player
      : (obj.steam_id ? obj : null);
    if (!player) {
      let sid = "";
      const src = String(href || "");
      const m = src.match(/\/players\/([^/?#]+)\/details/);
      try { sid = decodeURIComponent((m && m[1]) || ""); } catch (_) { sid = (m && m[1]) || ""; }
      if (!sid) sid = String(window.__caCheckSteam || "");
      player = {
        steam_id: sid,
        id: sid,
        steam_name: String(window.__caCheckName || sid || ""),
        name: String(window.__caCheckName || sid || ""),
        team: [],
        status: "offline",
        steam: true
      };
      obj = { player: player, entity: {}, team: [] };
    }
    if (!player.status) player.status = "offline";
    if (player.status === "active") player.status = "online";
    // Server offline → player must be offline (never AFK / «нет на месте»)
    // Keep joining/queued so UI can show «Подключается»
    const srv = player.server && typeof player.server === "object" ? player.server : null;
    if (
      player.status !== "joining"
      && player.status !== "queued"
      && srv
      && (srv.offline === true || srv.connected === false || srv.connected === 0 || srv.status === "offline"
        || (srv.state && srv.state.isStable === false))
    ) {
      player.status = "offline";
    }
    if (player.steam == null) player.steam = true;
    player.steam = true;
    if (!player.steam_data || typeof player.steam_data !== "object") {
      player.steam_data = {
        visible: true,
        profile_filled: true,
        avatar: player.steam_avatar || PLACEHOLDER,
        personaname: player.steam_name || player.steam_id,
        rust_hours_total: 0,
        rust_hours_2week: 0,
        spacewar_hours_total: 0,
        spacewar_hours_2week: 0,
        hours_closed_at: null,
        signed_at: 0,
        complete: false,
        unavailable: false,
        updated_at: Date.now(),
        ban_data: {
          days_since_last_ban: 0,
          game_ban: { count: 0 },
          vac_ban: { count: 0 }
        }
      };
    }
    if (player.steam_data.ban_data == null || typeof player.steam_data.ban_data !== "object") {
      player.steam_data.ban_data = {
        days_since_last_ban: 0,
        game_ban: { count: 0 },
        vac_ban: { count: 0 }
      };
    }
    if (player.steam_data.unavailable) player.steam_data.unavailable = false;
    if (player.steam_data.profile_filled == null) player.steam_data.profile_filled = true;
    if (player.steam_data.rust_hours_total == null) player.steam_data.rust_hours_total = 0;
    if (player.steam_data.rust_hours_2week == null) player.steam_data.rust_hours_2week = 0;
    player.steam_data.ban_data.game_ban = Object.assign({ count: 0 }, player.steam_data.ban_data.game_ban || {});
    player.steam_data.ban_data.vac_ban = Object.assign({ count: 0 }, player.steam_data.ban_data.vac_ban || {});
    if (player.steam_data.ban_data.game_ban.count == null) player.steam_data.ban_data.game_ban.count = 0;
    if (player.steam_data.ban_data.vac_ban.count == null) player.steam_data.ban_data.vac_ban.count = 0;
    if (player.steam_data.avatar == null) player.steam_data.avatar = player.steam_avatar || PLACEHOLDER;
    if (player.steam_data.personaname == null) player.steam_data.personaname = player.steam_name || player.steam_id;
    if (player.steam_data.updated_at == null) player.steam_data.updated_at = Date.now();
    if (player.steam_data.signed_at == null) player.steam_data.signed_at = 0;
    if (player.id == null) player.id = player.steam_id;
    if (player.created_at == null) player.created_at = Number(player.first_seen || 0) || 0;
    sanitizeLastOnline(player);
    let entity = obj.entity && typeof obj.entity === "object" ? obj.entity : (player.entity || {});
    const rawPos = player.position || entity.position;
    const rawRot = player.rotation || entity.rotation;
    entity.position = asVec(entity.position || rawPos);
    player.position = asVec(player.position || entity.position);
    entity.rotation = asVec(entity.rotation || rawRot);
    player.rotation = asVec(player.rotation || entity.rotation);
    entity.home = asHome(entity.home || player.home);
    player.home = asHome(player.home || entity.home);
    // Do NOT force home from can_build — CanBuild()!=TC auth; trust home.value from plugin
    const coords = asCoords(entity.coords || player.coords || entity.grid || player.grid || entity.square || player.square);
    player.coords = coords;
    entity.coords = coords;
    entity.grid = coords.value;
    entity.square = coords.value;
    player.grid = coords.value;
    player.square = coords.value;
    let moved = asElapsed(entity.last_moved_seconds || player.last_moved_seconds || 0);
    if (!moved) moved = asElapsed((entity.position && entity.position.time) || (player.position && player.position.time) || 0);
    if (!moved && (player.status === "online" || player.status === "active")) moved = 250;
    entity.last_moved_seconds = moved;
    // Never rewrite joining/queued → AFK («нет на месте»); UI shows «подключается» / «в очереди»
    if (player.status === "joining" || player.status === "queued") {
      // keep as-is
    } else if (player.status === "offline") {
      // Keep offline — SPA hides «Состояние» when status === offline
    } else if (moved >= 60000 && (player.status === "online" || player.status === "active" || player.status === "afk")) {
      player.status = "afk";
    } else if (moved < 60000 && player.status === "afk") {
      player.status = "online";
    }
    if (player.id == null) player.id = player.steam_id;
    if (!entity.raid || typeof entity.raid !== "object") entity.raid = { value: !!player.is_raiding };
    if (!entity.meta || typeof entity.meta !== "object") entity.meta = { tags: {}, fields: {} };
    if (Array.isArray(entity.meta.tags)) {
      const tags = {};
      entity.meta.tags.forEach((tag, i) => {
        tags[String(i)] = typeof tag === "object" && tag ? tag : { value: String(tag || "") };
      });
      entity.meta.tags = tags;
    } else if (!entity.meta.tags || typeof entity.meta.tags !== "object") {
      entity.meta.tags = {};
    }
    if (!entity.meta.fields || typeof entity.meta.fields !== "object") entity.meta.fields = {};
    if (entity.last_moved_seconds == null) entity.last_moved_seconds = 0;
    if (!player.ip_details || typeof player.ip_details !== "object") player.ip_details = {};
    if (!player.ip_details.ip) player.ip_details.ip = player.ip || "";
    const pip = String(player.ip_details.ip || player.ip || "");
    const privateIp = !pip || /^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|::1|localhost|0\.0\.0\.0)/i.test(pip);
    if (!player.ip_details.country_name) {
      player.ip_details.country_name = player.ip_details.country || player.country || (privateIp ? "Локальная сеть" : "");
    }
    if (!player.ip_details.city) player.ip_details.city = player.city || (privateIp ? "LAN" : "");
    if (!player.ip_details.provider) player.ip_details.provider = player.ip_details.isp || player.isp || (privateIp ? "Private network" : "");
    if (!player.ip_details.isp) player.ip_details.isp = player.ip_details.provider;
    if (!player.ip_details.country_code || player.ip_details.country_code === "un") {
      player.ip_details.country_code = privateIp ? "" : (player.ip_details.country_code || "");
    }
    if (player.client_id == null && player.checker_id != null) player.client_id = player.checker_id;
    let team = Array.isArray(obj.team) ? obj.team : (Array.isArray(player.team) ? player.team : []);
    team = team.map((row) => {
      if (row && typeof row === "object") return row;
      return { steam_id: String(row || ""), steam_name: String(row || ""), status: "offline", steam_avatar: PLACEHOLDER };
    });
    player.team = team;
    player.entity = entity;
    if (!player.server || typeof player.server !== "object") {
      player.server = { id: Number(player.server_id || 0) || 0, name: player.server_name || player.hostname || "" };
    }
    if (player.server.id == null) player.server.id = Number(player.server_id || 0) || Number(player.server.id || 0) || 0;
    if (!player.server.name || /^#\d+$/.test(String(player.server.name).trim())) {
      player.server.name = player.server_name || player.server.hostname || "";
    }
    if (player.server_id == null) player.server_id = player.server.id;
    if (
      player.status !== "joining"
      && player.status !== "queued"
      && (
        player.server.offline === true
        || player.server.connected === false
        || player.server.connected === 0
        || player.server.status === "offline"
        || (player.server.state && player.server.state.isStable === false)
      )
    ) {
      player.status = "offline";
    }
    try { Object.defineProperty(player, "toString", { configurable: true, value: function () { return String(this.id || this.steam_id || ""); } }); } catch (_) {}
    try { Object.defineProperty(player.server, "toString", { configurable: true, value: function () { return String(this.id); } }); } catch (_) {}
    const knownCheck = activeCheckIdFor(player.steam_id || player.id);
    let activeId = Number(player.active_check_id || player.activeCheckId || 0) || 0;
    if (!activeId && knownCheck) activeId = knownCheck;
    player.active_check_id = activeId;
    player.activeCheckId = activeId;
    player.is_checking = !!activeId;
    player.checking = !!activeId;
    if (activeId) rememberActiveCheck(player.steam_id || player.id, activeId, false);
    entity = sanitizeSessionTimes(player, entity);
    player.entity = entity;
    return { player: player, entity: entity, team: team };
  }

  function fixServer(obj) {
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) return obj;
    let last = Number(obj.last_seen || 0);
    if (last > 1e12) last = Math.floor(last / 1000);
    const nowSec = Math.floor(Date.now() / 1000);
    // Prefer explicit flags from API; never force online when last heartbeat is stale
    let connected = obj.connected === true || obj.connected === 1 || obj.connected === "1";
    if (obj.offline === true || obj.status === "offline") connected = false;
    if (obj.state && obj.state.isStable === false) connected = false;
    if (obj.paired && last > 0 && last <= nowSec - 90) connected = false;
    if (obj.paired && last > 0 && last > nowSec - 90 && obj.connected !== false && obj.offline !== true) {
      connected = true;
    }
    const online = connected ? Number((obj.state && obj.state.online) || obj.online || 0) : 0;
    const slots = Number((obj.state && obj.state.max_online) || obj.slots || 100) || 100;
    const level = obj.level || (obj.state && obj.state.level) || "Procedural Map";
    obj.connected = !!connected;
    obj.offline = !connected;
    obj.status = connected ? "online" : "offline";
    obj.id = Number(obj.id || obj.server_id || 0) || obj.id;
    obj.last_seen = last || obj.last_seen || 0;
    obj.state = {
      isStable: !!connected,
      online: online,
      max_online: slots,
      active_amount: online,
      joining_amount: 0,
      queue_amount: 0,
      reserved: connected ? Number(obj.reserved || 0) : 0,
      license_amount: online,
      pirate_amount: 0,
      level: level
    };
    if (!obj.name) obj.name = obj.hostname || "Rust";
    if (/^#\d+$/.test(String(obj.name || "").trim())) obj.name = obj.hostname || "";
    if (!obj.name || /^#\d+$/.test(String(obj.name).trim())) obj.name = obj.hostname || obj.server_name || "Rust";
    if (/^#\d+$/.test(String(obj.name || "").trim())) obj.name = "Rust";
    if (!obj.hostname) obj.hostname = obj.name;
    if (!obj.level) obj.level = level;
    if (!obj.avatar_url) obj.avatar_url = location.origin + "/local/rustlogo_dark.jpg?https=1";
    if (!obj.avatar_big) obj.avatar_big = obj.avatar_url;
    if (!obj.banner_url) obj.banner_url = location.origin + "/local/default-banner.png?https=1";
    if (!obj.version) obj.version = "2.1.6";
    if (!obj.protocol) obj.protocol = "2600";
    if (obj.full_updated == null) obj.full_updated = true;
    if (obj.updated == null) obj.updated = true;
    if (obj.deleted == null) obj.deleted = false;
    if (obj.order == null) obj.order = 0;
    if (obj.id == null) obj.id = 1;
    if (obj.M_ID == null) obj.M_ID = obj.id;
    try {
      Object.defineProperty(obj, "toString", { configurable: true, value: function () { return String(this.id != null ? this.id : (this.M_ID != null ? this.M_ID : "")); } });
    } catch (_) {}
    return obj;
  }

  function ensureIdToString(obj, fallbackId) {
    if (!obj || typeof obj !== "object") return obj;
    if (obj.id == null && fallbackId != null) obj.id = fallbackId;
    if (obj.id != null) {
      try {
        Object.defineProperty(obj, "toString", { configurable: true, value: function () { return String(this.id); } });
      } catch (_) {}
    }
    return obj;
  }

  // SPA chat: $.message.initiator_id.trim() — MUST be a string. Numbers crash the page.
  function asInitiatorId(value, steamFallback) {
    if (value != null && value !== "" && value !== 0 && value !== "0") return String(value);
    if (steamFallback != null && steamFallback !== "") return String(steamFallback);
    return "";
  }

  function stableClientId(uid, name) {
    let n = 0;
    try { n = Number(uid) || 0; } catch (_) { n = 0; }
    if (n) return n;
    const s = String(name || "staff");
    let h = 0;
    for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    return 100000 + (Math.abs(h) % 800000);
  }

  function unlinkedSteam(av) {
    const pic = (typeof imageSrc === "function") ? imageSrc(av || PLACEHOLDER) : (av || PLACEHOLDER);
    return {
      steam_id: "",
      steamid: "",
      steam_name: "",
      name: "",
      personaname: "",
      avatar: pic,
      steam_avatar: pic,
      avatarfull: pic,
      connected: false,
      profileurl: ""
    };
  }

  function cleanSteamName(name, sid) {
    const t = String(name || "").trim();
    const id = String(sid || "").trim();
    if (!t || t === "." || t === "-" || t === "—") return "";
    if (id && t === id) return "";
    if (/^\d{16,}$/.test(t)) return "";
    return t;
  }

  function isSteamCdnAvatar(url) {
    const src = String(url || "");
    if (!src || /image-1024|logo-avatar|placeholder/i.test(src)) return false;
    return /steamstatic|steamcdn|akamaihd\.net\/steam|\/uploads\/steam-\d+/i.test(src);
  }
  function steamHttpsAvatar(url) {
    let src = String(url || "").trim();
    if (!src) return "";
    if (typeof url === "object") src = String((url && (url.url || url.avatar || url.src)) || "").trim();
    src = src.replace(/^http:\/\//i, "https://");
    src = src.replace("cdn.akamai.steamstatic.com", "avatars.steamstatic.com");
    src = src.replace("steamcdn-a.akamaihd.net", "avatars.steamstatic.com");
    if (!isSteamCdnAvatar(src)) return "";
    return src;
  }

  var PLAYER_AUTOKICK_KEYS = [
    "steam_empty_disabled", "steam_closed_disabled", "steam_signed_days_disabled",
    "steam_hours_disabled", "steam_vac_disabled", "steam_gameban_disabled",
    "ip_vpn_disabled", "ip_country_disabled", "ip_bad_provider_disabled",
    "name_contains_disabled", "game_language_disabled", "afk_disabled"
  ];
  var PLAYER_AUTOKICK_ALIAS_MAP = {
    steam_closed: "steam_closed_disabled",
    steam_empty_profile: "steam_empty_disabled",
    steam_signed_days: "steam_signed_days_disabled",
    steam_hours: "steam_hours_disabled",
    steam_vac: "steam_vac_disabled",
    steam_gameban: "steam_gameban_disabled",
    ip_vpn: "ip_vpn_disabled",
    ip_country: "ip_country_disabled",
    ip_bad_provider: "ip_bad_provider_disabled",
    name_contains: "name_contains_disabled",
    game_language: "game_language_disabled",
    afk: "afk_disabled"
  };
  function mapPlayerAutokickAliases(obj) {
    if (!obj || typeof obj !== "object") return obj;
    Object.keys(PLAYER_AUTOKICK_ALIAS_MAP).forEach(function (short) {
      var full = PLAYER_AUTOKICK_ALIAS_MAP[short];
      if (obj[short] != null && (obj[full] == null || obj[short])) obj[full] = !!obj[short] || !!obj[full];
      try { delete obj[short]; } catch (_) {}
    });
    return obj;
  }
  function playerAutokickSid(url) {
    var m = String(url || "").match(/\/players\/([^/?#]+)\/settings-auto-kick/i);
    try { return m ? decodeURIComponent(m[1]) : ""; } catch (_) { return m ? m[1] : ""; }
  }
  function playerAutokickOnlyKeys(obj) {
    var out = {};
    PLAYER_AUTOKICK_KEYS.forEach(function (k) { out[k] = !!(obj && obj[k]); });
    return out;
  }
  function readPlayerAutokickCache(sid) {
    if (!sid) return null;
    try {
      var raw = readJsonStore("ca_player_autokick_" + currentProjectSlug() + "_" + sid, null);
      if (!raw || typeof raw !== "object") return null;
      return playerAutokickOnlyKeys(raw);
    } catch (_) { return null; }
  }
  function writePlayerAutokickCache(sid, obj) {
    if (!sid || !obj || typeof obj !== "object") return;
    var clean = playerAutokickOnlyKeys(obj);
    try { writeJsonStore("ca_player_autokick_" + currentProjectSlug() + "_" + sid, clean); } catch (_) {}
    if (playerAutokickAnyTrue(clean)) {
      try { window.__caKickTrueAt = window.__caKickTrueAt || {}; window.__caKickTrueAt[sid] = Date.now(); } catch (_) {}
    }
  }
  function playerAutokickAnyTrue(obj) {
    if (!obj || typeof obj !== "object") return false;
    return PLAYER_AUTOKICK_KEYS.some(function (k) { return !!obj[k]; });
  }
  function playerAutokickAllFalse(obj) {
    if (!obj || typeof obj !== "object") return true;
    return PLAYER_AUTOKICK_KEYS.every(function (k) { return !obj[k]; });
  }
  function mergePlayerAutokick(url, obj, method) {
    var sid = playerAutokickSid(url);
    if (!sid || sid === "undefined" || sid === "null") return obj;
    var verb = String(method || "GET").toUpperCase();
    var data = obj && typeof obj === "object" && !Array.isArray(obj) ? obj : {};
    if (data.data && typeof data.data === "object" && !playerAutokickAnyTrue(data) && playerAutokickAnyTrue(data.data)) {
      data = data.data;
    }
    mapPlayerAutokickAliases(data);
    PLAYER_AUTOKICK_KEYS.forEach(function (k) { data[k] = !!data[k]; });
    writePlayerAutokickCache(sid, data);
    return playerAutokickOnlyKeys(data);
  }
  function sanitizePlayerAutokickBody(url, method, body) {
    if (!/\/players\/[^/]+\/settings-auto-kick/i.test(String(url || ""))) return body;
    if (!/^(PUT|POST|PATCH)$/i.test(String(method || ""))) return body;
    var sid = playerAutokickSid(url);
    if (!sid || sid === "undefined" || sid === "null") return body;
    var parsed = body;
    try {
      if (typeof body === "string") parsed = JSON.parse(body || "{}");
    } catch (_) { parsed = body; }
    if (!parsed || typeof parsed !== "object") return body;
    var incoming = parsed.data && typeof parsed.data === "object" && !playerAutokickAnyTrue(parsed)
      ? parsed.data : parsed;
    mapPlayerAutokickAliases(incoming);
    var clean = playerAutokickOnlyKeys(incoming);
    return JSON.stringify(clean);
  }
  function currentPlayerSteamId() {
    try {
      const path = String(location.pathname || "");
      let m = path.match(/\/players\/(7656119\d{10})/);
      if (m) return m[1];
      const u = new URL(location.href);
      const q = String(u.searchParams.get("player") || u.searchParams.get("steam_id") || u.searchParams.get("steamId") || "");
      if (/7656119\d{10}/.test(q)) return q;
    } catch (_) {}
    const blob = String((document.body && document.body.innerText) || "");
    const m2 = blob.match(/7656119\d{10}/);
    return m2 ? m2[0] : "";
  }
  function permissionKeyFromText(text) {
    const t = String(text || "").toLowerCase();
    if (/vpn/.test(t)) return "ip_vpn_disabled";
    if (/стран|country/.test(t)) return "ip_country_disabled";
    if (/провайд|provider/.test(t)) return "ip_bad_provider_disabled";
    if (/ненастроен|unconfigured|empty/.test(t)) return "steam_empty_disabled";
    if (/закрыт|private|closed/.test(t)) return "steam_closed_disabled";
    if (/новым аккаунт|new account|creation/.test(t)) return "steam_signed_days_disabled";
    if (/часов|hours/.test(t)) return "steam_hours_disabled";
    if (/\bvac\b/.test(t)) return "steam_vac_disabled";
    if (/игровой блок|game ban/.test(t)) return "steam_gameban_disabled";
    if (/ник|nick/.test(t)) return "name_contains_disabled";
    if (/язык|language/.test(t)) return "game_language_disabled";
    if (/afk|неактив/.test(t)) return "afk_disabled";
    return "";
  }
  function findAutokickState(el) {
    let n = el;
    for (let i = 0; i < 24 && n; i++) {
      const inst = n.__vueParentComponent || n.__vue__;
      const setup = inst && inst.setupState;
      const cand = setup && (setup.i || setup.state);
      const obj = cand && typeof cand === "object" && "value" in cand ? cand.value : cand;
      if (obj && typeof obj === "object" && ("ip_vpn_disabled" in obj || "steam_empty_disabled" in obj)) return cand && "value" in cand ? cand : { value: obj };
      n = n.parentElement;
    }
    return null;
  }
  function persistPlayerPermission(sid, key, on, fromVue) {
    const current = playerAutokickOnlyKeys(Object.assign({}, readPlayerAutokickCache(sid) || {}, fromVue || {}));
    current[key] = !!on;
    writePlayerAutokickCache(sid, current);
    const headers = {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Checkapp-Player-Perm": "1"
    };
    try {
      const token = readAuthToken();
      if (token) headers.Authorization = "Bearer " + token;
      const slug = currentProjectSlug();
      if (slug) headers["X-Checkapp-Project"] = slug;
    } catch (_) {}
    fetch("/players/" + encodeURIComponent(sid) + "/settings-auto-kick", {
      method: "PUT",
      credentials: "include",
      cache: "no-store",
      headers: headers,
      body: JSON.stringify(current)
    }).catch(function () {});
  }
  document.addEventListener("click", function (ev) {
    const t = ev.target;
    if (!t || !t.closest) return;
    const page = String((document.body && document.body.innerText) || "");
    if (page.indexOf("Разрешения") < 0) return;
    if (!/Пускать с VPN|Allow with VPN|Пускать с ненастроенным|Пускать с закрытым/i.test(page)) return;
    const sw = t.closest(".n-switch, [role='switch']");
    if (!sw) return;
    let row = sw.parentElement;
    let key = "";
    for (let i = 0; i < 6 && row; i++) {
      key = permissionKeyFromText(row.textContent);
      if (key) break;
      row = row.parentElement;
    }
    if (!key) return;
    const sid = currentPlayerSteamId();
    if (!sid) return;
    ev.preventDefault();
    ev.stopImmediatePropagation();
    const wasOn = sw.getAttribute("aria-checked") === "true" || sw.classList.contains("n-switch--active");
    const next = !wasOn;
    window.__caKickGestureWasOn = wasOn;
    window.__caKickGestureAt = Date.now();
    const st = findAutokickState(sw);
    if (st && st.value && typeof st.value === "object") {
      mapPlayerAutokickAliases(st.value);
      st.value[key] = next;
    }
    if (next) {
      sw.classList.add("n-switch--active");
      sw.setAttribute("aria-checked", "true");
    } else {
      sw.classList.remove("n-switch--active");
      sw.setAttribute("aria-checked", "false");
    }
    persistPlayerPermission(sid, key, next, st && st.value);
  }, true);

  function projectLabelSet() {
    const out = {};
    function add(val) {
      const t = String(val || "").trim().toLowerCase().replace(/^@/, "").replace(/[\s-]+/g, "");
      if (t) out[t] = true;
    }
    try { add(typeof currentProjectSlug === "function" ? currentProjectSlug() : ""); } catch (_) {}
    const list = Array.isArray(window.__checkappProjectsCache) ? window.__checkappProjectsCache : [];
    list.forEach(function (p) {
      if (!p || typeof p !== "object") return;
      add(p.name); add(p.title); add(p.domain); add(p.tag); add(p.url);
    });
    return out;
  }

  function isProjectLabel(text) {
    const t = String(text || "").trim().toLowerCase().replace(/^@/, "").replace(/[\s-]+/g, "");
    if (!t) return false;
    return !!projectLabelSet()[t];
  }

  function isGenericStaffLabel(text) {
    const t = String(text || "").trim().toLowerCase().replace(/^@/, "").replace(/[\s-]+/g, "");
    if (!t) return true;
    if (/^(admin|staff|moderator|system|plugin|user|сотрудник|owner|rustcheck|checkapp|rustapp|rystcheck)$/i.test(t)) return true;
    return isProjectLabel(t);
  }

  function personalStaffTag(client) {
    if (!client || typeof client !== "object") return "";
    const mail = String(client.email || "");
    const parts = mail.split("@");
    const local = String(parts[0] || "");
    const domain = String(parts[1] || "").toLowerCase();
    const fakeDomain = /^(steam|discord|google)\.rustcheck\.local$|^(rustcheck|checkapp)\.local$/.test(domain);
    if (!fakeDomain && local && !isGenericStaffLabel(local) && !/^\d{16,}$/.test(local)) return local;
    const name = String(client.name || "").trim().replace(/^@/, "");
    const slug = name.replace(/[^a-zA-Z0-9_]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 24);
    if (slug && !isGenericStaffLabel(slug) && !/^\d{16,}$/.test(slug)) return slug;
    const id = Number(client.id || 0) || 0;
    if (id) return "user" + id;
    return "";
  }

  function betterStaffField(current, incoming) {
    const cur = String(current || "").trim();
    const next = String(incoming || "").trim();
    if (isGenericStaffLabel(cur) && !isGenericStaffLabel(next)) return next;
    if (!cur && next) return next;
    return cur || next;
  }

  function ensureClientShape(client, fallbackName, fallbackId) {
    if (client && client.is_project) { ensureIdToString(client, client.id); return client; }
    let me = null;
    try { me = staffProfile(); } catch (_) { me = null; }
    let name = String(fallbackName || (client && client.name) || "").trim();
    let id = 0;
    try { id = Number((client && client.id) || fallbackId || 0) || 0; } catch (_) { id = 0; }
    const meId = Number((me && me.id) || 0) || 0;
    if (!id) id = stableClientId(0, name || "staff");
    if (!client || typeof client !== "object") {
      client = { id: id, name: name, tag: "", status: "online", avatar: PLACEHOLDER };
    }
    if (client.id == null || client.id === "" || client.id === 0 || client.id === "0") {
      client.id = id;
    }
      const nid = Number(client.id);
    if (nid) {
      client.id = nid;
      client.M_ID = nid;
    }
    const isMe = !!(meId && nid && meId === nid);
    let known = null;
    try { known = window.__caClients && nid ? window.__caClients[String(nid)] : null; } catch (_) { known = null; }
    if (isGenericStaffLabel(name) && known && !isGenericStaffLabel(known.name)) name = known.name;
    if (isGenericStaffLabel(name) && isMe && me && me.name && !isGenericStaffLabel(me.name)) name = me.name;
    if (!client.name || isGenericStaffLabel(client.name)) {
      client.name = (!isGenericStaffLabel(name) && name) || (known && known.name) || (isMe && me && me.name) || client.name || "";
    }
    const genericTag = !client.tag || isGenericStaffLabel(client.tag);
    if (genericTag && known && known.tag && !isGenericStaffLabel(known.tag)) {
      client.tag = known.tag;
    } else if (genericTag && isMe && me && me.tag && !isGenericStaffLabel(me.tag)) {
      client.tag = me.tag;
    } else if (genericTag) {
      client.tag = personalStaffTag(client) || personalStaffTag(known) || (isMe ? personalStaffTag(me) : "") || (nid ? ("user" + nid) : "");
    }
    if (isGenericStaffLabel(client.tag)) {
      client.tag = personalStaffTag(client) || (nid ? ("user" + nid) : "");
    }
    const av = String(client.avatar || "");
    if (!av || /logo-avatar|image-1024/i.test(av)) {
      if (isMe && me && me.avatar) client.avatar = me.avatar;
      else if (known && known.avatar) client.avatar = known.avatar;
      else if (!client.avatar) client.avatar = PLACEHOLDER;
    } else {
      client.avatar = imageSrc(client.avatar);
    }
    if (client.bio == null) client.bio = "";
    if (client.M_ID == null) client.M_ID = client.id;
    client.status = client.status || "online";
    client.online = true;
    client.is_online = true;
    return ensureClientIntegrations(client);
  }

  function isRealSteamId(sid) {
    const t = String(sid || "").trim();
    return t.length === 17 && /^\d+$/.test(t) && t.indexOf("7656119") === 0
      && t !== "76561198000000000" && t !== "76561198000000001";
  }

  function killAmmoForWeapon(weapon) {
    const w = String(weapon || "").toLowerCase();
    if (/glock|python|revolver|pistol|semiauto\.pistol|\bsap\b|m92|nailgun|smg|mp5|thompson|customsmg|custom\.smg/.test(w)) {
      return "pistolbullet";
    }
    if (/shotgun|spas|pump|waterpipe|double/.test(w)) return "handmade.shell";
    if (/bow|crossbow/.test(w)) return "arrow";
    return "riflebullet";
  }

  function killPartyDisplayName(party, fallbackSid) {
    const p = party && typeof party === "object" ? party : {};
    const sid = String(fallbackSid || p.steam_id || p.id || "").trim();
    const raw = String(p.steam_name || p.name || p.display_name || p.personaname || "").trim();
    if (raw && raw !== sid && !/^\d+$/.test(raw) && !isRealSteamId(raw)) return raw;
    return "Игрок";
  }

  function shapeKillFeedPlayer(party, fallbackSid) {
    const src = party && typeof party === "object" ? party : {};
    const sid = String(fallbackSid || src.steam_id || src.id || "").trim();
    const pretty = killPartyDisplayName(src, sid);
    const avatar = src.steam_avatar || src.avatar || PLACEHOLDER;
    return Object.assign({}, src, {
      id: sid || src.id || "0",
      steam_id: sid || "0",
      steamid: sid || "0",
      steam_name: pretty,
      name: pretty,
      personaname: pretty,
      display_name: pretty,
      steam_avatar: avatar,
      avatar: avatar,
      status: src.status || "offline",
      online: false,
      is_online: false,
      team: Array.isArray(src.team) ? src.team : []
    });
  }

  function ensureClientIntegrations(obj) {
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) return obj;
    const av = obj.avatar || PLACEHOLDER;
    const linkedSid = String((obj.steam && obj.steam.steam_id) || obj.steam_id || "").trim();
    if (isRealSteamId(linkedSid)) {
      if (!obj.steam || typeof obj.steam !== "object") {
        obj.steam = {
          steam_id: linkedSid,
          steam_name: obj.steam_name || "",
          name: obj.steam_name || "",
          personaname: obj.steam_name || "",
          avatar: obj.steam_avatar || av,
          steam_avatar: obj.steam_avatar || av,
          avatarfull: obj.steam_avatar || av
        };
      }
      const steamAv = steamHttpsAvatar(obj.steam.avatarfull || obj.steam.steam_avatar || obj.steam.avatar || obj.steam_avatar || "");
      if (steamAv) {
        obj.steam.avatar = steamAv;
        obj.steam.steam_avatar = steamAv;
        obj.steam.avatarfull = steamAv;
        obj.steam_avatar = steamAv;
      } else {
        const localAv = location.origin + "/uploads/steam-" + linkedSid + ".jpg";
        obj.steam.avatar = obj.steam.avatar && isSteamCdnAvatar(obj.steam.avatar) ? obj.steam.avatar : localAv;
        obj.steam.steam_avatar = obj.steam.avatar;
        obj.steam.avatarfull = obj.steam.avatar;
        obj.steam_avatar = obj.steam.avatar;
      }
      const steamNm = cleanSteamName(obj.steam.personaname || obj.steam.steam_name || obj.steam.name || obj.steam_name || "", linkedSid);
      obj.steam.steam_name = steamNm || "Steam";
      obj.steam.personaname = obj.steam.steam_name;
      obj.steam.name = obj.steam.steam_name;
      obj.steam_name = obj.steam.steam_name;
    } else {
      obj.steam = null;
      if (!isRealSteamId(obj.steam_id)) obj.steam_id = "";
    }
    if (!obj.discord || typeof obj.discord !== "object") {
      obj.discord = {
        discord_id: String(obj.discord_id || ""),
        discord_name: obj.discord_name || "",
        name: obj.discord_name || "",
        avatar: obj.discord_avatar || "",
        discord_avatar: obj.discord_avatar || ""
      };
    }
    if (obj.discord.avatar == null || !/cdn\.discordapp\.com/i.test(String(obj.discord.avatar || ""))) {
      const did = String((obj.discord && obj.discord.discord_id) || obj.discord_id || "").trim();
      obj.discord.avatar = obj.discord.discord_avatar && /cdn\.discordapp\.com/i.test(String(obj.discord.discord_avatar)) ? obj.discord.discord_avatar : (did ? discordDefaultAvatar(did) : "");
    }
    const linkedDiscordId = String((obj.discord && obj.discord.discord_id) || obj.discord_id || "").trim();
    obj.discord_id = linkedDiscordId;
    obj.discord.id = obj.discord.id || linkedDiscordId;
    obj.discord.user_id = obj.discord.user_id || linkedDiscordId;
    obj.discord.account_id = obj.discord.account_id || linkedDiscordId;
    obj.discord.discord_name = obj.discord.discord_name || obj.discord.global_name || obj.discord.username || obj.discord_name || "";
    obj.discord.name = obj.discord.discord_name || obj.discord.name;
    obj.discord.username = obj.discord.username || obj.discord.discord_name;
    obj.discord.personaname = obj.discord.discord_name || obj.discord.personaname;
    obj.discord.discord_avatar = obj.discord.discord_avatar || obj.discord.avatar;
    obj.discord.connected = !!linkedDiscordId;
    obj.discord.is_connected = !!linkedDiscordId;
    obj.discord.available = true;
    obj.discord.status = linkedDiscordId ? "connected" : "disconnected";
    if (!obj.google || typeof obj.google !== "object") {
      obj.google = {
        google_id: String(obj.google_id || ""),
        google_name: obj.google_name || "",
        name: obj.google_name || "",
        avatar: obj.google_avatar || av,
        google_avatar: obj.google_avatar || av
      };
    }
    if (obj.google.avatar == null) obj.google.avatar = obj.google.google_avatar || av;
    if (!obj.telegram || typeof obj.telegram !== "object") {
      obj.telegram = {
        telegram_id: "",
        name: "",
        avatar: "",
        connected: false,
        available: false,
        disabled: true,
        status: "unavailable"
      };
    }
    obj.telegram.connected = false;
    obj.telegram.available = false;
    obj.telegram.disabled = true;
    obj.telegram.status = "unavailable";
    if (!obj.integrations || typeof obj.integrations !== "object") obj.integrations = {};
    ["steam", "discord", "google", "telegram"].forEach(function (k) {
      if (!obj.integrations[k] || typeof obj.integrations[k] !== "object") obj.integrations[k] = {};
      if (obj.integrations[k].avatar == null) obj.integrations[k].avatar = (obj[k] && obj[k].avatar) || av;
      if (k === "steam") {
        obj.integrations.steam.connected = isRealSteamId(linkedSid);
        obj.integrations.steam.status = isRealSteamId(linkedSid) ? "connected" : "disconnected";
      }
      if (k === "discord") {
        obj.integrations.discord.connected = !!linkedDiscordId;
        obj.integrations.discord.is_connected = !!linkedDiscordId;
        obj.integrations.discord.id = linkedDiscordId;
        obj.integrations.discord.discord_id = linkedDiscordId;
        obj.integrations.discord.name = (obj.discord && (obj.discord.discord_name || obj.discord.name || obj.discord.username)) || obj.discord_name || "";
        obj.integrations.discord.username = obj.integrations.discord.name;
        obj.integrations.discord.personaname = obj.integrations.discord.name;
        obj.integrations.discord.avatar = (obj.discord && (obj.discord.discord_avatar || obj.discord.avatar)) || obj.discord_avatar || "";
        obj.integrations.discord.discord_avatar = obj.integrations.discord.avatar;
        obj.integrations.discord.available = true;
        obj.integrations.discord.status = linkedDiscordId ? "connected" : "disconnected";
      }
      if (k === "telegram") {
        obj.integrations.telegram.connected = false;
        obj.integrations.telegram.available = false;
        obj.integrations.telegram.disabled = true;
        obj.integrations.telegram.can_connect = false;
        obj.integrations.telegram.status = "unavailable";
      }
    });
    return obj;
  }

  function packedResults(list, extra) {
    const rows = Array.isArray(list) ? list : [];
    const src = (extra && typeof extra === "object" && !Array.isArray(extra)) ? extra : {};
    const out = src;
    out.data = rows;
    out.results = rows;
    out.items = rows;
    const keepTotal = src.total != null ? Number(src.total) : rows.length;
    const keepLimit = src.limit != null ? Number(src.limit) : (rows.length + 1);
    out.total = keepTotal;
    out.limit = keepLimit > 0 ? keepLimit : 20;
    if (out.page == null) out.page = 1;
    const more = src.has_more === true || src.hasMore === true;
    out.has_more = more;
    out.hasMore = more;
    out.done = !more;
    out.finished = !more;
    if (!more) {
      out.next_cursor = null;
      out.next_page = null;
    }
    return out;
  }

  function deletedStaffStub(id, name) {
    const nid = Number(id) || 0;
    const cached = (typeof window !== "undefined" && window.__caClients && nid) ? window.__caClients[String(nid)] : null;
    const nm = String((cached && cached.name) || name || "Удалённый сотрудник");
    return ensureClientShape(cached || {
      id: nid || 1,
      name: nm,
      tag: (cached && cached.tag && !isGenericStaffLabel(cached.tag)) ? cached.tag : "",
      status: "offline",
      avatar: PLACEHOLDER,
      former_member: true,
      deleted: true
    }, nm, nid);
  }

  function rememberStaffClient(client) {
    if (client && client.is_project) return client;
    if (!client || typeof client !== "object") return client;
    const idNum = Number(client.id);
    if (!idNum || !isFinite(idNum)) return client;
    client.id = idNum;
    try {
      window.__caClients = window.__caClients || {};
      const prev = window.__caClients[String(idNum)];
      if (prev && typeof prev === "object") {
        const merged = Object.assign({}, prev, client, { id: idNum });
        merged.name = betterStaffField(client.name, prev.name);
        merged.tag = betterStaffField(client.tag, prev.tag);
        if (isGenericStaffLabel(merged.tag)) merged.tag = personalStaffTag(merged) || personalStaffTag(prev) || "";
        if (isGenericStaffLabel(merged.name) && !isGenericStaffLabel(prev.name)) merged.name = prev.name;
        if (isGenericStaffLabel(merged.tag) && !isGenericStaffLabel(prev.tag)) merged.tag = prev.tag;
        window.__caClients[String(idNum)] = merged;
        client.name = merged.name;
        client.tag = merged.tag;
      } else if (!isGenericStaffLabel(client.name) || !isGenericStaffLabel(client.tag)) {
        window.__caClients[String(idNum)] = client;
      } else {
        window.__caClients[String(idNum)] = client;
      }
    } catch (_) {}
    // This cache is used to enrich authors in logs.  It must never add an
    // author as a project employee: that previously manufactured the
    // @undefined card in the staff page.
    return client;
  }

  function tierServerLimit(tier) {
    const slug = String(tier || "base").toLowerCase();
    if (slug === "plus" || slug === "enterprise" || slug === "custom" || slug === "pro" || slug === "premium") return 5;
    return 2;
  }

  function tierPlayerLimit(tier) {
    const slug = String(tier || "base").toLowerCase();
    if (slug === "plus" || slug === "enterprise" || slug === "custom" || slug === "pro" || slug === "premium") return 500000;
    return 100000;
  }

  function countPairedServers(list) {
    if (!Array.isArray(list)) return 0;
    return list.filter(function (s) { return s && (s.paired === true || s.paired === 1 || s.paired === "1"); }).length;
  }

  function isProjectLimitResponse(obj) {
    if (!obj || typeof obj !== "object") return false;
    const msg = String(obj.message || obj.detail || obj.error || "");
    return /project limit exceeded|project-limit-exceeded|достигнул лимит|не можете создавать проект/i.test(msg);
  }

  function showProjectLimitNativeToast() {
    showCheckappToast("warn", "Вы больше не можете создавать проекты, достигнул лимит!");
  }

  function showCheckappToast(type, message, opts) {
    opts = opts || {};
    const now = Date.now();
    const text = String(message || "").trim();
    if (!text) return;
    const dedupeKey = String(type || "info") + "|" + text + "|" + String(opts.title || "");
    window.__checkappToastLast = window.__checkappToastLast || {};
    if (!opts.force && window.__checkappToastLast[dedupeKey] && now - window.__checkappToastLast[dedupeKey] < 700) return;
    window.__checkappToastLast[dedupeKey] = now;

    // Unified black RustApp toast — same look for error/warn/success/info
    const icons = { error: "!", warn: "!", success: "✓", info: "i" };
    const kind = String(type || "info").toLowerCase();
    const icon = icons[kind] || icons.info;
    const title = String(opts.title || "").trim();

    let wrap = document.querySelector(".runtime-notification-wrapper");
    if (!wrap) {
      wrap = document.getElementById("checkapp-native-toast-wrap");
      if (!wrap) {
        wrap = document.createElement("div");
        wrap.id = "checkapp-native-toast-wrap";
        wrap.className = "runtime-notification-wrapper";
        wrap.style.cssText = "position:fixed;z-index:1000003;display:flex;flex-direction:column-reverse;gap:12px;padding:0 16px 16px;width:min(380px,calc(100vw - 24px));bottom:0;right:0;pointer-events:none;";
        document.body.appendChild(wrap);
      }
    }

    const note = document.createElement("div");
    note.className = "notification pointer-events-auto cursor-pointer checkapp-toast";
    note.dataset.checkappToastKeep = "1";
    note.style.cssText = [
      "display:flex", "align-items:flex-start", "gap:12px", "padding:14px 16px",
      "border-radius:12px", "background:#141414", "border:1px solid #2a2a2a",
      "color:#fff", "box-shadow:0 16px 40px rgba(0,0,0,.55)",
      "pointer-events:auto", "max-width:380px", "opacity:0", "transform:translateY(12px)",
      "transition:opacity .22s ease, transform .22s ease"
    ].join(";");
    note.innerHTML =
      '<div style="flex-shrink:0;width:28px;height:28px;border-radius:8px;background:#1e1e1e;border:1px solid #333;display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:700;color:#fff">' + icon + "</div>" +
      '<div style="min-width:0">' +
      (title ? ('<div style="font-size:14px;line-height:1.35;font-weight:700;margin-bottom:4px;color:#fff">' + title + "</div>") : "") +
      '<div style="font-size:13px;line-height:1.45;font-weight:500;color:#cfcfcf">' + text + "</div>" +
      "</div>";
    note.addEventListener("click", function () {
      note.style.opacity = "0";
      note.style.transform = "translateY(8px)";
      setTimeout(function () { try { note.remove(); } catch (_) {} }, 180);
    });
    wrap.prepend(note);
    requestAnimationFrame(function () {
      note.style.opacity = "1";
      note.style.transform = "translateY(0)";
    });
    setTimeout(function () {
      if (!note.isConnected) return;
      note.style.opacity = "0";
      note.style.transform = "translateY(8px)";
      setTimeout(function () { try { note.remove(); } catch (_) {} }, 220);
    }, Number(opts.duration || 4800));
  }

  function showBaseTariffToast(message) {
    showCheckappToast("warn", message || "Он выдаётся автоматически при создании проекта.", {
      title: "Базовый тариф нельзя выбрать"
    });
  }

  function showPlanLockedToast(message) {
    showCheckappToast("warn", message || "Enterprise/Custom нельзя сменить на Base или Plus.", {
      title: "Нельзя изменить текущий тариф."
    });
  }

  function injectCheckappNoticeStyles() {
    if (document.getElementById("checkapp-notice-css")) return;
    const st = document.createElement("style");
    st.id = "checkapp-notice-css";
    st.textContent = [
      "#checkapp-notice-root{position:fixed;inset:0;z-index:1000002;display:flex;align-items:center;justify-content:center;padding:16px;box-sizing:border-box;}",
      "#checkapp-notice-root .ck-notice-overlay{position:absolute;inset:0;background:rgba(0,0,0,.5);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);}",
      "#checkapp-notice-root .ck-notice-box{position:relative;z-index:2;background:#1e1e1e;color:#fff;border-radius:14px;padding:28px 24px;max-width:420px;width:min(92vw,420px);text-align:center;border:1px solid #2a2a2a;box-shadow:0 24px 80px rgba(0,0,0,.75);}",
      "#checkapp-notice-root .ck-notice-icon{font-size:42px;line-height:1;margin-bottom:14px;}",
      "#checkapp-notice-root .ck-notice-title{font-size:18px;font-weight:700;margin-bottom:10px;}",
      "#checkapp-notice-root .ck-notice-text{font-size:14px;color:#aaa;line-height:1.55;margin-bottom:20px;}",
      "#checkapp-notice-root .ck-notice-actions{display:flex;flex-direction:column;gap:10px;}",
      "#checkapp-notice-root .ck-notice-btn{width:100%;border:none;border-radius:10px;padding:11px;background:#2a2a2a;color:#fff;font-weight:600;cursor:pointer;}",
      "#checkapp-notice-root .ck-notice-btn.primary{background:#1a3d2a;color:#7dffa3;}",
      "#checkapp-notice-root .ck-notice-btn.danger{background:#3a1a1a;color:#ffb4b4;}",
      "#checkapp-billing-blocked{margin:0 0 16px;padding:16px 18px;border-radius:12px;border:1px solid #5a3030;background:#241616;color:#ffb4b4;display:flex;gap:12px;align-items:flex-start;}",
      "#checkapp-billing-blocked .ck-bb-icon{font-size:24px;line-height:1;flex:0 0 auto;}",
      "#checkapp-billing-blocked .ck-bb-title{font-size:15px;font-weight:700;color:#fff;margin-bottom:4px;}",
      "#checkapp-billing-blocked .ck-bb-text{font-size:13px;line-height:1.5;color:#d4aaaa;}"
    ].join("");
    (document.head || document.documentElement).appendChild(st);
  }

  function showCheckappNotice(opts) {
    opts = opts || {};
    injectCheckappNoticeStyles();
    const existing = document.getElementById("checkapp-notice-root");
    if (existing) existing.remove();
    const root = document.createElement("div");
    root.id = "checkapp-notice-root";
    const icon = String(opts.icon || "⚠️");
    const title = String(opts.title || "Не удалось выполнить действие");
    const message = String(opts.message || "Попробуйте ещё раз через несколько секунд.");
    const actionLabel = String(opts.actionLabel || "Понятно");
    const actionClass = opts.primary ? " ck-notice-btn primary" : (opts.danger ? " ck-notice-btn danger" : " ck-notice-btn");
    root.innerHTML =
      '<div class="ck-notice-overlay"></div>' +
      '<div class="ck-notice-box" role="alertdialog" aria-modal="true">' +
      '<div class="ck-notice-icon">' + icon + "</div>" +
      '<div class="ck-notice-title">' + title + "</div>" +
      '<div class="ck-notice-text">' + message + "</div>" +
      '<div class="ck-notice-actions"><button type="button" class="' + actionClass.trim() + '">' + actionLabel + "</button></div>" +
      "</div>";
    function closeNotice() {
      try { root.remove(); } catch (_) {}
    }
    root.addEventListener("click", function (e) {
      if (e.target.classList.contains("ck-notice-overlay") || e.target.classList.contains("ck-notice-btn")) {
        if (typeof opts.onAction === "function") opts.onAction();
        closeNotice();
      }
    });
    document.body.appendChild(root);
    return closeNotice;
  }

  function humanizeApiError(obj, status) {
    const code = String((obj && obj.error) || "").toLowerCase();
    const raw = String((obj && (obj.message || obj.detail)) || "").trim();
    const st = Number(status || 0);
    if (code === "project_blocked" || /project blocked|заблокирован администрац/i.test(raw)) {
      return {
        icon: "🔒",
        title: "Проект заблокирован",
        message: "Этот проект был заблокирован администрацией. Покупка подписки недоступна, пока блокировка не будет снята."
      };
    }
    if (st === 402 || code === "insufficient_balance" || /not enough balance|недостаточно средств|не хватает средств|payment required/i.test(raw)) {
      return {
        icon: "⚠️",
        title: "Недостаточно средств",
        message: "Пополните баланс проекта, чтобы продолжить."
      };
    }
    if (code === "base_not_purchasable") {
      return {
        icon: "⚠️",
        title: "Базовый тариф нельзя выбрать",
        message: "Он выдаётся автоматически при создании проекта."
      };
    }
    if (code === "plan_locked" || code === "cannot_change_plan" || /нельзя изменить текущий тариф/i.test(raw)) {
      return {
        icon: "⚠️",
        title: "Нельзя изменить текущий тариф.",
        message: "Enterprise/Custom нельзя сменить на Base или Plus."
      };
    }
    if (code === "project-limit-exceeded" || /project limit exceeded|достигнул лимит/i.test(raw)) {
      return {
        icon: "⚠️",
        title: "Лимит проектов",
        message: "Вы больше не можете создавать проекты — достигнут лимит."
      };
    }
    if (code === "already_staff" || /уже является сотрудником|already (a )?staff|already (a )?member/i.test(raw + " " + code)) {
      return {
        icon: "⚠️",
        title: "Уже в проекте",
        message: "Этот пользователь уже является сотрудником текущего проекта."
      };
    }
    if (code === "cannot_add_self" || /владелец проекта уже есть|cannot add (yourself|self)/i.test(raw + " " + code)) {
      return {
        icon: "⚠️",
        title: "Нельзя добавить",
        message: "Владелец проекта уже есть в списке сотрудников."
      };
    }
    if (code === "user_not_found" || /пользователь не найден|user not found/i.test(raw + " " + code)) {
      return {
        icon: "⚠️",
        title: "Пользователь не найден",
        message: "Проверьте ник: такой аккаунт не зарегистрирован."
      };
    }
    if (code === "server-limit-exceeded") {
      return {
        icon: "⚠️",
        title: "Лимит серверов",
        message: "На текущем тарифе достигнут лимит подключённых серверов."
      };
    }
    if (/password\.?miss|invalid credentials|неверный email|неверный пароль|wrong password/i.test(raw + " " + code)) {
      return {
        icon: "⚠️",
        title: "Не удалось войти",
        message: "Проверьте email и пароль и попробуйте снова."
      };
    }
    if (/email.*exists|already registered|уже зарегистр/i.test(raw)) {
      return {
        icon: "⚠️",
        title: "Email уже используется",
        message: "Попробуйте войти или укажите другой email."
      };
    }
    if (st === 401 || st === 403 || /forbidden|unauthorized|нет доступа|запрещено/i.test(raw)) {
      return {
        icon: "🔒",
        title: "Доступ запрещён",
        message: "У вас нет прав для выполнения этого действия."
      };
    }
    if (st === 404 || /not found|ничего не найдено/i.test(raw)) {
      return {
        icon: "⚠️",
        title: "Ничего не найдено",
        message: "Запрашиваемые данные не найдены или были удалены."
      };
    }
    if (st >= 500 || /internal server error|database error|prisma|axioserror|network error|failed to fetch/i.test(raw)) {
      return {
        icon: "🔴",
        title: "Произошла ошибка",
        message: "Не удалось выполнить операцию. Попробуйте ещё раз.",
        primary: false,
        actionLabel: "Повторить"
      };
    }
    if (/validation|required|invalid|некоррект|обязательн/i.test(raw)) {
      return {
        icon: "⚠️",
        title: "Проверьте данные",
        message: raw && raw.length < 180 ? raw : "Некоторые поля заполнены некорректно."
      };
    }
    if (raw && !/^(error|ok|false|true)$/i.test(raw) && raw.length < 180 && !/axios|prisma|internal server/i.test(raw)) {
      return { icon: "⚠️", title: "Не удалось выполнить действие", message: raw };
    }
    return {
      icon: "⚠️",
      title: "Не удалось выполнить действие",
      message: "Попробуйте ещё раз через несколько секунд.",
      actionLabel: "Попробовать снова"
    };
  }

  function showHumanApiError(obj, status, opts) {
    if (window.__caIgnoreDiscordError && Date.now() < window.__caIgnoreDiscordError) {
      const raw = String((obj && (obj.message || obj.detail)) || "") + String(status || "");
      if (/401|403|unauthorized|запрещ|не удалось/i.test(raw) || Number(status) === 401 || Number(status) === 403) return;
    }
    opts = opts || {};
    const st = Number(status || 0);
    const raw = String((obj && (obj.message || obj.detail || obj.error)) || "") + " " + String((opts && opts.message) || "");
    const recentSelect = window.__checkappLastTariffSelectAt && (Date.now() - window.__checkappLastTariffSelectAt < 8000);
    const billingPage = /billing/i.test(String(location.search || "") + String(location.pathname || ""));
    const genericCrash = /произошла ошибка|не удалось выполнить операцию|failed to fetch|axioserror|payment required/i.test(
      raw + " " + String((opts && opts.title) || "") + " " + String((opts && opts.message) || "")
    );
    if (
      st === 402 ||
      /insufficient_balance|payment required|not enough balance|недостаточно средств/i.test(raw) ||
      (genericCrash && (recentSelect || billingPage))
    ) {
      showTariffSelectUi("funds", obj || {});
      return;
    }
    const mapped = humanizeApiError(obj, status);
    if (opts.toast) {
      showCheckappToast("error", mapped.message, { title: mapped.title, force: true });
      return;
    }
    showCheckappNotice(Object.assign({}, mapped, opts));
  }

  function showProjectBlockedNotice() {
    showCheckappNotice({
      icon: "🔒",
      title: "Проект заблокирован",
      message: "Этот проект был заблокирован администрацией. Покупка подписки недоступна, пока блокировка не будет снята."
    });
  }

  function injectFundsModalStyles() {
    if (document.getElementById("checkapp-funds-css")) return;
    const st = document.createElement("style");
    st.id = "checkapp-funds-css";
    st.textContent = [
      "#checkapp-funds-modal{position:fixed;inset:0;z-index:1000003;display:flex;align-items:center;justify-content:center;padding:16px;box-sizing:border-box;font-family:ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif;}",
      "#checkapp-funds-modal .ck-funds-overlay{position:absolute;inset:0;background:rgba(0,0,0,.52);}",
      "#checkapp-funds-modal .ck-funds-box{position:relative;z-index:2;background:#1a1a1a;color:#fff;border-radius:12px;padding:30px 24px 20px;width:min(92vw,356px);text-align:center;box-shadow:0 24px 70px rgba(0,0,0,.7);}",
      "#checkapp-funds-modal .ck-funds-icon{position:relative;width:120px;height:88px;margin:0 auto 10px;}",
      "#checkapp-funds-modal .ck-funds-glow{position:absolute;left:50%;top:38px;width:86px;height:52px;margin-left:-43px;background:radial-gradient(ellipse at center,rgba(245,197,24,.5) 0%,rgba(245,197,24,0) 70%);filter:blur(6px);pointer-events:none;}",
      "#checkapp-funds-modal .ck-funds-tri{position:absolute;left:50%;top:6px;width:64px;height:60px;margin-left:-32px;overflow:visible;}",
      "#checkapp-funds-modal .ck-funds-tri.ghost{opacity:.38;}",
      "#checkapp-funds-modal .ck-funds-tri.left{transform:translate(-19px,11px) rotate(-21deg);}",
      "#checkapp-funds-modal .ck-funds-tri.right{transform:translate(19px,11px) rotate(19deg);}",
      "#checkapp-funds-modal .ck-funds-tri.main{z-index:2;filter:drop-shadow(0 7px 8px rgba(0,0,0,.38));}",
      "#checkapp-funds-modal .ck-funds-title{font-size:17px;font-weight:700;line-height:1.25;margin:0 0 8px;color:#fff;}",
      "#checkapp-funds-modal .ck-funds-text{font-size:13.5px;line-height:1.5;color:#a6a6a6;margin:0 4px 22px;}",
      "#checkapp-funds-modal .ck-funds-btn{display:block;width:100%;height:40px;border:none;border-radius:8px;background:#2b2b2b;color:#ececec;font-size:14px;font-weight:600;cursor:pointer;}",
      "#checkapp-funds-modal .ck-funds-btn:hover{background:#333;}"
    ].join("");
    (document.head || document.documentElement).appendChild(st);
  }

  function fundsWarningSvg(fill) {
    fill = fill || "#F5C518";
    return '<svg class="ck-funds-tri" viewBox="0 0 64 58" width="64" height="60" fill="none" aria-hidden="true">' +
      '<path fill="' + fill + '" d="M32 4.4c1.72 0 3.28.9 4.14 2.4L60.7 49.2c.88 1.52.86 3.38-.08 4.86C59.76 55.54 58.16 56.4 56.4 56.4H7.6c-1.76 0-3.36-.86-4.22-2.34-.94-1.48-.96-3.34-.08-4.86L27.86 6.8C28.72 5.3 30.28 4.4 32 4.4z"/>' +
      '<rect x="29.2" y="20.2" width="5.6" height="17.2" rx="2.8" fill="#1a1a1a"/>' +
      '<circle cx="32" cy="43.6" r="3.05" fill="#1a1a1a"/>' +
      "</svg>";
  }

  function renderFundsModal(need) {
    var n = Number(need || 0);
    if (n >= 10000) n = Math.round(n / 100);
    if (!n) n = 300;
    injectFundsModalStyles();
    var existing = document.getElementById("checkapp-funds-modal");
    if (existing) existing.remove();
    var root = document.createElement("div");
    root.id = "checkapp-funds-modal";
    var ghost = fundsWarningSvg("#C4A016");
    var main = fundsWarningSvg("#F5C518");
    root.innerHTML =
      '<div class="ck-funds-overlay"></div>' +
      '<div class="ck-funds-box" role="alertdialog" aria-modal="true">' +
      '<div class="ck-funds-icon">' +
      '<i class="ck-funds-glow"></i>' +
      ghost.replace('class="ck-funds-tri"', 'class="ck-funds-tri ghost left"') +
      ghost.replace('class="ck-funds-tri"', 'class="ck-funds-tri ghost right"') +
      main.replace('class="ck-funds-tri"', 'class="ck-funds-tri main"') +
      "</div>" +
      '<div class="ck-funds-title">Не хватает средств</div>' +
      '<div class="ck-funds-text">Для перехода на выбранный тарифный план вам нужно ещё ₽' +
      n.toLocaleString("ru-RU") + " на балансе.</div>" +
      '<button type="button" class="ck-funds-btn">Понятно</button></div>';
    root.addEventListener("click", function (e) {
      if (e.target.classList.contains("ck-funds-overlay") || e.target.classList.contains("ck-funds-btn")) {
        try { root.remove(); } catch (_) {}
      }
    });
    document.body.appendChild(root);
  }

  function showInsufficientFundsNotice(need) {
    renderFundsModal(need);
  }

  var lastTariffErrAt = 0;
  var lastTariffErrKind = "";
  function showTariffSelectUi(kind, payload) {
    var now = Date.now();
    if (kind === lastTariffErrKind && now - lastTariffErrAt < 1500) return;
    lastTariffErrKind = kind;
    lastTariffErrAt = now;
    payload = payload || {};
    if (kind === "funds") {
      var need = payload.needed_rub != null ? Number(payload.needed_rub) : Math.ceil(Number(payload.needed || 0) / 100);
      if (!need) need = 300;
      showInsufficientFundsNotice(need);
      try { hideTariffCrashDialogs(); } catch (_) {}
      setTimeout(function () { try { hideTariffCrashDialogs(); } catch (_) {} }, 50);
      setTimeout(function () { try { hideTariffCrashDialogs(); } catch (_) {} }, 250);
    } else if (kind === "base") {
      showBaseTariffToast(payload.message);
    } else if (kind === "blocked") {
      showProjectBlockedNotice();
    } else if (kind === "locked") {
      showPlanLockedToast(payload.message);
    }
  }

  function currentTariffSnapshot() {
    try {
      return JSON.parse(JSON.stringify(window.__checkappTariff || {}));
    } catch (_) {
      return (window.__checkappTariff && typeof window.__checkappTariff === "object")
        ? Object.assign({}, window.__checkappTariff)
        : {};
    }
  }

  function softenTariffSelect(url, status, obj) {
    var href = String(url || "");
    if (!/\/tariff/i.test(href) || /discard-trial/i.test(href)) return null;
    if (!/select|\/tariff\/?\d|\/tariff\/(?:base|plus|enterprise)/i.test(href) && String(status) !== "402") {
      if (!(obj && obj.ok === false && obj.error)) return null;
    }
    obj = obj && typeof obj === "object" ? obj : {};
    var st = Number(status || 0);
    var err = String(obj.error || "");
    var msg = String(obj.message || obj.detail || "");
    var failed = obj.ok === false || st === 402 || st === 403 ||
      err === "insufficient_balance" || err === "base_not_purchasable" ||
      err === "project_blocked" || err === "plan_locked" ||
      /not enough balance|недостаточно|payment required/i.test(msg);
    if (!failed) return null;
    if (st === 402 || err === "insufficient_balance" || /not enough balance|недостаточно|payment required/i.test(msg)) {
      showTariffSelectUi("funds", obj);
    } else if (err === "base_not_purchasable") {
      showTariffSelectUi("base", obj);
    } else if (st === 403 || err === "project_blocked") {
      showTariffSelectUi("blocked", obj);
    } else if (err === "plan_locked") {
      showTariffSelectUi("locked", obj);
    }
    var keep = currentTariffSnapshot();
    if (keep && typeof keep === "object") {
      delete keep.ok;
      delete keep.purchased;
      delete keep.error;
      delete keep.message;
    }
    if (!keep || !Object.keys(keep).length) {
      keep = { slug: "base", plan: "base", tariff: { slug: "base", tier: "base", is_current: true } };
    }
    return { status: 200, body: keep };
  }

  function readKnownBalanceKopecks() {
    try {
      var t = window.__checkappTariff || {};
      var v = t.balance;
      if (v == null && t.wallet) v = t.wallet.balance;
      if (v == null && t.wallet && t.wallet.amount != null) v = t.wallet.amount;
      if (v == null) return null;
      v = Number(v);
      if (!isFinite(v)) return null;
      return v;
    } catch (_) {
      return null;
    }
  }

  function isOwnPlanSelectHeaders(headers, xhr) {
    try {
      if (headers) {
        if (headers.get && headers.get("X-Checkapp-Plan-Select") === "1") return true;
        var hk = Object.keys(headers).find(function (k) { return String(k).toLowerCase() === "x-checkapp-plan-select"; });
        if (hk && String(headers[hk]) === "1") return true;
      }
    } catch (_) {}
    try {
      var map = xhr && xhr.__checkappReqHeaders;
      if (map && String(map["x-checkapp-plan-select"] || "") === "1") return true;
    } catch (_) {}
    return false;
  }

  function localTariffSelectReply(method, url, headers, xhr) {
    var href = String(url || "");
    var verb = String(method || "GET").toUpperCase();
    if (!/POST|PUT|PATCH/.test(verb) || !/\/tariff/i.test(href) || /discard-trial/i.test(href)) return null;
    var isSelect = /select|\/tariff\/(?:base|plus|enterprise|1|2)(?:\/|$)/i.test(href);
    if (!isSelect) return null;
    var isBase = /\/tariff\/(?:base|1)(?:\/|$)/i.test(href);
    var isEnt = /\/tariff\/enterprise/i.test(href);
    var own = isOwnPlanSelectHeaders(headers, xhr);
    window.__checkappLastTariffSelectAt = Date.now();
    if (isBase) {
      showTariffSelectUi("base");
      return {
        status: 200,
        body: own
          ? { ok: false, error: "base_not_purchasable", message: "Выбрать базовый тариф нельзя — он выдаётся при создании проекта" }
          : currentTariffSnapshot()
      };
    }
    if (isEnt) {
      return null;
    }
    var bal = readKnownBalanceKopecks();
    var price = 30000;
    if (bal == null || bal < price) {
      var need = Math.max(300, Math.round((price - Number(bal || 0)) / 100) || 300);
      showTariffSelectUi("funds", { needed_rub: need, needed: price - Number(bal || 0) });
      var snap = currentTariffSnapshot();
      if (snap && typeof snap === "object") {
        delete snap.ok;
        delete snap.purchased;
        delete snap.error;
        delete snap.message;
      }
      return {
        status: 200,
        body: own
          ? { ok: false, error: "insufficient_balance", message: "Not enough balance", needed_rub: need, needed: price - Number(bal || 0), balance: bal, price: price }
          : (snap && Object.keys(snap).length ? snap : { slug: "base", plan: "base" })
      };
    }
    return null;
  }

  window.__checkappToast = showCheckappToast;
  window.__checkappShowBaseTariffToast = showBaseTariffToast;
  window.__checkappShowNotice = showCheckappNotice;
  window.__checkappShowHumanError = showHumanApiError;
  window.__checkappShowProjectBlocked = showProjectBlockedNotice;
  window.__checkappOpenInsufficientFunds = showInsufficientFundsNotice;
  window.__checkappRenderFundsModal = renderFundsModal;
  window.__checkappRenderFundsModal = renderFundsModal;

  function maybeShowProjectLimitToast(url, method, status, obj) {
    if (String(method || "GET").toUpperCase() !== "POST") return;
    const href = String(url || "");
    if (!/\/project(?:\?|$)/.test(href) || /\/project\//.test(href)) return;
    if (Number(status) === 403 || isProjectLimitResponse(obj)) showProjectLimitNativeToast();
  }

  window.__checkappShowProjectLimitToast = showProjectLimitNativeToast;

  function rewriteCssUrls(css) {
    return String(css || "").replace(/url\(\s*(['"]?)(.*?)\1\s*\)/g, function (_, q, url) {
      return "url(" + q + imageSrc(url) + q + ")";
    });
  }

  function isAnalytics(rawUrl) {
    const href = String(rawUrl || "").toLowerCase();
    return /amplitude|sentry\.io|google-analytics|googletagmanager|gtag\/js|hotjar|fullstory|intercom|mixpanel|segment\.com|facebook\.net|doubleclick|scorecardresearch|newrelic|nr-data\.net|\/__checkapp-analytics|\/2\/httpapi|api2\.amplitude|cdn\.amplitude/.test(href);
  }

  function emptyJsonResponse() {
    return new Response("{\"code\":200,\"events_ingested\":0}", { status: 200, headers: { "Content-Type": "application/json" } });
  }

  function gatewayStub(url, method) {
    const href = String(url || "");
    const verb = String(method || "GET").toUpperCase();
    if (verb !== "GET") return null;
    if (/\/utils\/tariff|\/tariff\/?(\?|$)/.test(href) && verb === "GET") {
      const plans = (typeof defaultTariffs === "function") ? defaultTariffs() : [];
      return {
        tariffs: plans,
        plans: plans,
        data: plans,
        results: plans,
        items: plans,
        tariff: plans[0] || { tier: "base", month_price: 0, is_current: true },
        tier_features: {}
      };
    }
    if (/\/wallet(?:-operations)?(?:\?|$)/.test(href) && verb === "GET") {
      if (/wallet-operations/.test(href)) {
        return { results: [], data: [], items: [], total: 0, limit: 50, page: 1 };
      }
      return { balance: 0, amount: 0, value: 0 };
    }
    if (/\/players\/[^/]+\/details/.test(href) && verb === "GET") {
      const dm = href.match(/\/players\/([^/?#]+)\/details/);
      let sid = "";
      try { sid = decodeURIComponent((dm && dm[1]) || ""); } catch (_) { sid = (dm && dm[1]) || ""; }
      const name = String(window.__caCheckName || sid || "");
      const entity = {
        team: [],
        home: { time: 0, value: false },
        position: { x: 0, y: 0, z: 0, time: 0 },
        rotation: { x: 0, y: 0, z: 0, time: 0 },
        coords: { value: "", grid: "", square: "", time: 0 },
        meta: { tags: {}, fields: {} },
        raid: { value: false },
        last_moved_seconds: 0
      };
      const player = {
        id: sid,
        steam_id: sid,
        steam_name: name,
        name: name,
        team: [],
        status: "offline",
        steam: true,
        steam_avatar: PLACEHOLDER,
        entity: entity,
        steam_data: {
          personaname: name,
          avatar: PLACEHOLDER,
          signed_at: 0,
          updated_at: Date.now(),
          unavailable: false,
          complete: false,
          ban_data: { days_since_last_ban: null, game_ban: { count: 0 }, vac_ban: { count: 0 } }
        },
        server: { id: 0, name: "", connected: false, offline: true }
      };
      return { player: player, entity: entity, team: [] };
    }
    if (/\/check\/\d+\/activity/.test(href) && verb === "GET") {
      return currentCheckActivityRows((href.match(/\/check\/(\d+)\/activity/) || [])[1]);
      return [];
    }
    // Check activity is real data from the local API.  Do not short-circuit it
    // here: this fallback used to run before the successful API response was
    // normalized, so the RustApp check page always received an empty timeline.
    if (/\/check\/\d+(\?|$)/.test(href.replace(location.origin, "")) && verb === "GET") {
      // Only used on 500/parse-failure. Never return null/undefined — that
      // replaces a later successful GET and leaves both check panes loading.
      if (obj && typeof obj === "object" && !Array.isArray(obj) && (obj.id || obj.steam_id || obj.suspect || obj.player)) {
        const sid = String(obj.steam_id || (obj.suspect && obj.suspect.steam_id) || (obj.player && obj.player.steam_id) || "");
        if (sid && sid !== "0" && sid !== ".") return obj;
      }
      const m = href.match(/\/check\/(\d+)/);
      const id = Number((m && m[1]) || 0) || 0;
      const cached = (window.__caCheckStub && Number(window.__caCheckStub.id) === id) ? window.__caCheckStub : null;
      const steam = String((cached && (cached.steam_id || (cached.suspect && cached.suspect.steam_id))) || window.__caCheckSteam || "");
      if (cached && steam && steam !== "0" && steam !== ".") return cached;
      if (steam && steam !== "0" && steam !== ".") return buildCheckStub(id, steam, window.__caCheckName);
      if (cached) return cached;
      return buildCheckStub(id, steam, window.__caCheckName);
    }
    if (/browse-anonymous/.test(href)) return { checks: [], results: [], data: [], items: [], total: 0 };
    if (/team-history|session-history|\/checks(?:\?|$)/.test(href)) {
      return { results: [], data: [], items: [], total: 0, limit: 20, page: 1, has_more: false, done: true, finished: true };
    }
    if (verb === "GET") return { results: [], data: [], items: [], total: 0, limit: 20, page: 1 };
    return null;
  }

  function asCheckCreateId(raw) {
    let id = 0;
    if (typeof raw === "number" && raw > 0) id = raw;
    else if (typeof raw === "string" && /^\d+$/.test(String(raw).trim())) id = Number(raw.trim());
    else if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      id = Number(raw.id || raw.check_id || raw.checkId || 0) || 0;
    }
    if (!id) return raw;
    try { window.__caLastCheckId = id; } catch (_) {}
    // SPA: params:{id: N} after check.create() — must be a number, not {id:...}.
    return id;
  }

  function isRemoteApi(rawUrl) {
    const href = String(rawUrl || "").toLowerCase();
    if (!href || href.startsWith("/") || href.startsWith("data:") || href.startsWith("blob:")) return false;
    if (isAnalytics(href)) return true;
    if (href.includes(String(location.host || "").toLowerCase())) return false;
    return (
      href.includes("rustapp.io") ||
      href.includes("rustapp") ||
      href.includes("checkapp") ||
      href.includes("://core.") ||
      href.includes("://court.") ||
      href.includes("centrifugo") ||
      href.includes("s3.") ||
      href.includes("r2.") ||
      /https?:\/\/core\./i.test(href) ||
      /https?:\/\/court\./i.test(href)
    );
  }

  function asElapsed(moved) {
    moved = Number(moved || 0);
    const now = Date.now();
    if (moved > 1e12) return Math.max(100, now - moved);
    if (moved > 1e9) return Math.max(100, now - moved * 1000);
    return moved > 0 ? moved : 0;
  }

  function rewriteUrl(rawUrl, method) {
    const href = String(rawUrl || "");
    const verb = String(method || "GET").toUpperCase();
    if (!href) return href;
    if (verb === "GET" && /\/(check|ban|player-mute)\/stats/i.test(href)) {
      try {
        const u = new URL(href, location.origin);
        ["client_id", "clientId", "ids"].forEach(function (k) {
          const v = String(u.searchParams.get(k) || "");
          if (!v || /object Object|undefined|null/i.test(v)) u.searchParams.delete(k);
        });
        const has = u.searchParams.get("client_id") || u.searchParams.get("clientId") || u.searchParams.get("ids");
        const cid = Number(has || selectedStatsClientId() || window.__caStatsClientId || 0) || 0;
        if (cid) {
          window.__caStatsClientId = cid;
          u.searchParams.set("client_id", String(cid));
        }
        return u.origin === location.origin ? (u.pathname + u.search + u.hash) : u.toString();
      } catch (_) {}
    }
    if (verb === "GET" && /https?:\/\/((canary|ptb)\.)?discord(app)?\.com\/api\/webhooks\/\d+/i.test(href)) {
      return location.origin + "/local/discord-webhook-info";
    }
    if (/\.cs(\?|$)/i.test(href) && /github|githubusercontent|rust-app-io|\/plugin\//i.test(href)) {
      return location.origin + "/plugin/download";
    }
    if (verb === "GET" && /\/server\/pair/.test(href)) {
      try {
        const u = new URL(href, location.origin);
        const name = readConnectServerName();
        if (name && !u.searchParams.get("name")) u.searchParams.set("name", name);
        return u.origin === location.origin ? (u.pathname + u.search + u.hash) : (u.toString());
      } catch (_) {}
    }
    try {
      const u = new URL(href, location.origin);
      const broken = /\[object Object\]|object%20Object|%5Bobject/i.test(u.pathname);
      if (broken && u.pathname.includes("/check/")) {
        u.pathname = u.pathname.replace(/\/check\/[^/]+/, "/check/latest");
        return u.origin === location.origin ? (u.pathname + u.search + u.hash) : (location.origin + u.pathname + u.search);
      }
      if (u.origin === location.origin) {
        if (/\/project\/(?:undefined|null|NaN)\//i.test(u.pathname)) {
          const slug = currentProjectSlug();
          if (slug) u.pathname = u.pathname.replace(/\/project\/(?:undefined|null|NaN)\//i, "/project/" + encodeURIComponent(slug) + "/");
        }
        const drop = [];
        u.searchParams.forEach(function (v, k) {
          if (v == null || v === "undefined" || v === "null" || k === "undefined" || k === "null") drop.push(k);
        });
        drop.forEach(function (k) { u.searchParams.delete(k); });
        return href.startsWith("http") ? (u.pathname + u.search + u.hash) : (u.pathname + u.search + u.hash);
      }
      const host = String(u.hostname || "").toLowerCase();
      if (/\/sound\/(?:ping|ding-dong)\.mp3/i.test(u.pathname) || /s3\.rustcheck\.cc\/sound/i.test(host + u.pathname)) {
        return "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=";
      }
      if (
        isRemoteApi(href) ||
        host.includes("rustapp") ||
        host.includes("checkapp") ||
        host.startsWith("core") ||
        host.startsWith("court") ||
        host.includes("centrifugo") ||
        host.includes("s3.") ||
        host.includes("r2.")
      ) {
        return location.origin + u.pathname + u.search + u.hash;
      }
    } catch (_) {}
    // Absolute remote URL we failed to parse → force same-origin path guess
    if (/^https?:\/\//i.test(href) && isRemoteApi(href)) {
      try {
        const path = href.replace(/^https?:\/\/[^/]+/i, "");
        return location.origin + (path || "/");
      } catch (_) {}
    }
    return href;
  }

  function normalizeTariffPlan(plan) {
    if (!plan || typeof plan !== "object") return plan;
    const tier = String(plan.tier || plan.slug || plan.code || "").toLowerCase();
    // kopecks: Base=Free(0), Plus=30000 -> ₽300
    const prices = { base: 0, plus: 30000, enterprise: 1000000, basic: 0, starter: 0, custom: 1000000 };
    const price = prices[tier];
    if (price != null) {
      plan.month_price = price;
      plan.price_month = price;
      plan.monthly_price = price;
      plan.price = price;
      plan.cost = price;
    }
    if (!plan.tier) plan.tier = tier || "base";
    if (!plan.slug) plan.slug = plan.tier;
    if (!plan.name) plan.name = plan.tier.charAt(0).toUpperCase() + plan.tier.slice(1);
    if (!plan.title) plan.title = plan.name;
    plan.is_free = tier === "base" || Number(plan.month_price || 0) <= 0;
    plan.price_label = plan.is_free ? "Free" : null;
    if (tier === "base") plan.can_select = false;
    plan.servers_limit = tierServerLimit(tier);
    plan.players_limit = tierPlayerLimit(tier);
    plan.clients_limit = Number(plan.clients_limit || 999);
    if (!Array.isArray(plan.features) || !plan.features.length) {
      if (tier === "base") plan.features = ["Все функции", "Тест 7 дней при создании проекта", "Без оплаты — только пробный доступ"];
      else if (tier === "plus") plan.features = ["Все функции", "5 серверов", "Подписка на 30 дней"];
      else plan.features = ["Все функции", "От 5 серверов", "Приоритетная поддержка"];
    }
    return plan;
  }

  function ensureTierFeatures(obj) {
    if (!obj || typeof obj !== "object") return obj;
    const prev = obj.tier_features && typeof obj.tier_features === "object" ? obj.tier_features : {};
    const all = ["base", "plus", "enterprise", "custom"];
    const needAll = [
      "Player/Kills", "Player/Mutes", "Player/Signages", "Player/Team-History",
      "Player/Kills-Combat-Log", "Ban-Sync/General",
      "Integrations/API", "Integrations/Custom-Alert",
      "Checks/Anonymous-Data", "Map/General", "Stats/General", "Player/Auto-Kick"
    ];
    const tf = {};
    needAll.forEach(function (k) {
      const old = prev[k] && typeof prev[k] === "object" ? prev[k] : {};
      tf[k] = Object.assign({}, old, { tiers: all.slice(), plus: true, enterprise: true, base: true });
      if (old.name) tf[k].name = old.name;
    });
    obj.tier_features = tf;
    if (obj.frozen == null && obj.is_frozen != null) obj.frozen = obj.is_frozen;
    if (obj.is_frozen == null && obj.frozen != null) obj.is_frozen = obj.frozen;
    return obj;
  }

  function defaultTariffs() {
    return [
      normalizeTariffPlan({ id: 1, tier: "base", slug: "base", name: "Base", is_current: true }),
      normalizeTariffPlan({ id: 2, tier: "plus", slug: "plus", name: "Plus", is_current: false }),
      normalizeTariffPlan({ id: 3, tier: "enterprise", slug: "enterprise", name: "Enterprise", month_price: 1000000, is_current: false, contact: true })
    ];
  }

  function sanitizePaidUntilMs(value) {
    const now = Date.now();
    let n = Number(value || 0);
    if (!n) return 0;
    // Reject only absurd far-future (lifetime / year-2100) dates — keep normal 30-day subs.
    if (n >= 4102444800000 - 86400000 * 30) return 0;
    if (n > now + 86400000 * 400) return 0;
    return n;
  }

  const TRIAL_MS = 7 * 24 * 60 * 60 * 1000;

  function billingActiveUntilForUi(obj, paidMs) {
    const paid = Number(paidMs || 0);
    if (!paid || paid <= Date.now()) return paid;
    const tier = String((obj.tariff && (obj.tariff.tier || obj.tariff.slug)) || obj.slug || obj.plan || "base").toLowerCase();
    const monthPrice = Number((obj.tariff && obj.tariff.month_price) || obj.month_price || 0);
    if (monthPrice <= 0 || monthPrice >= 1000000) return paid;
    const bal = Number((obj.wallet && obj.wallet.balance) || obj.balance || 0);
    if (!bal) return paid;
    const daily = Math.max(1, monthPrice / 30);
    const extraMs = (bal / daily) * 86400000;
    // Do not clamp to now — SPA adds balance days via dayjs.add().
    return paid - extraMs;
  }

  function applyBillingDates(obj) {
    if (!obj || typeof obj !== "object") return obj;
    const now = Date.now();
    const isBlocked = !!(obj.blocked || obj.is_blocked);
    if (isBlocked) {
      obj.blocked = true;
      obj.is_blocked = true;
      obj.is_banned = true;
      obj.banned = true;
      obj.project_status = "blocked";
      obj.lifecycle = "blocked";
      obj.frozen = false;
      obj.is_frozen = false;
      obj.renew_failed = false;
      return obj;
    }
    let paid = sanitizePaidUntilMs(obj.paid_until);
    let trial = Number(obj.trial_ends_at || obj.trial_ends || 0);
    // Do NOT promote active_until/subscription_ends_at to "paid" — during trial
    // those fields equal trial_ends_at and were incorrectly wiping is_trial.
    const isPaid = paid > now;
    if (isPaid) {
      obj.is_paid = true;
      obj.is_trial = false;
      obj.frozen = false;
      obj.is_frozen = false;
      obj.renew_failed = false;
      obj.project_status = "active";
      obj.lifecycle = "active";
      obj.paid_until = paid;
      obj.trial_ends_at = 0;
      obj.trial_ends = 0;
      // SPA adds wallet/(month_price/30) days to active_until — always back-adjust so display = paid_until.
      obj.active_until = billingActiveUntilForUi(obj, paid);
      obj.subscription_ends_at = paid;
      obj.subscriptionExpiresAt = paid;
      obj.renew_at = paid;
      return obj;
    }
    const isTrial = trial > now;
    const trialActive = isTrial;
    obj.is_paid = false;
    obj.is_trial = trialActive;
    obj.trial_remaining_ms = trialActive ? Math.max(0, trial - now) : 0;
    obj.frozen = !trialActive;
    obj.is_frozen = !trialActive;
    obj.renew_failed = !trialActive;
    obj.project_status = trialActive ? "active" : "frozen";
    obj.lifecycle = obj.project_status;
    obj.paid_until = 0;
    if (trialActive) {
      obj.trial_ends_at = trial;
      obj.trial_ends = trial;
      obj.active_until = trial;
      obj.subscription_ends_at = trial;
    } else {
      obj.trial_ends_at = trial > 0 ? trial : 0;
      obj.trial_ends = obj.trial_ends_at;
      obj.active_until = 0;
      obj.subscription_ends_at = 0;
    }
    obj.renew_at = 0;
    return obj;
  }

  function zeroDailyBillingIfPrepaidPlus(obj) {
    if (!obj || typeof obj !== "object") return obj;
    const paid = Number(obj.paid_until || 0);
    if (!obj.is_paid || paid <= Date.now()) return obj;
    // Only stop daily billing charges — keep tariff.month_price for SPA date math.
    obj.daily_price = 0;
    return obj;
  }

  function normalizeTariffPayload(obj) {
    if (!obj || typeof obj !== "object") return obj;
    const panelFlags = readPanelProjectFlags && readPanelProjectFlags();
    if (panelFlags && panelFlags.blocked && obj.blocked == null && obj.is_blocked == null) {
      obj.blocked = true;
      obj.is_blocked = true;
    }
    ["tariffs", "plans", "data", "results", "items"].forEach(function (key) {
      if (Array.isArray(obj[key])) obj[key] = obj[key].map(normalizeTariffPlan);
    });
    if (obj.tariff && typeof obj.tariff === "object") normalizeTariffPlan(obj.tariff);
    if (!obj.tariff_project_usage || typeof obj.tariff_project_usage !== "object") {
      obj.tariff_project_usage = { servers_db: 0, players_db: 0, servers: 0, players: 0, clients_db: 0, clients: 0 };
    }
    const usage = obj.tariff_project_usage;
    if (typeof window.__checkappServersCount === "number") {
      usage.servers_db = window.__checkappServersCount;
      usage.servers = window.__checkappServersCount;
    }
    if (!Array.isArray(obj.tariffs) || !obj.tariffs.length) {
      obj.tariffs = defaultTariffs();
      obj.plans = obj.tariffs;
      obj.data = obj.tariffs;
      obj.results = obj.tariffs;
      obj.items = obj.tariffs;
    }
    if (!obj.tariff) obj.tariff = obj.tariffs.find(function (p) { return p && p.is_current; }) || obj.tariffs[0];
    applyBillingDates(obj);
    if (obj.tariff && typeof obj.tariff === "object") {
      const cur = String(obj.tariff.tier || obj.tariff.slug || "base").toLowerCase();
      obj.tariff.tier = cur;
      obj.tariff.slug = cur;
      obj.tariff.plan = cur;
      obj.tariff.servers_limit = tierServerLimit(cur);
      obj.tariff.players_limit = tierPlayerLimit(cur);
      obj.tariff.clients_limit = Number(obj.tariff.clients_limit || obj.clients_limit || 999);
      obj.servers_limit = obj.tariff.servers_limit;
      obj.players_limit = obj.tariff.players_limit;
      obj.clients_limit = obj.tariff.clients_limit;
    }
    zeroDailyBillingIfPrepaidPlus(obj);
    ensureTierFeatures(obj);
    return saveProjectTariffCache(obj);
  }

  function normalizeStatsPayload(obj) {
    if (!obj || typeof obj !== "object") return obj;
    // Keep landing project carousel — real projects from /utils/stats
    if (!Array.isArray(obj.reviews)) obj.reviews = [];
    (obj.reviews || []).forEach(function (row, i) {
      if (!row || typeof row !== "object") return;
      if (!row.project || typeof row.project !== "object") {
        row.project = {
          id: row.id || i + 1,
          name: row.name || row.title || "RustApp",
          domain: row.domain || row.tag || "",
          avatar: row.avatar || row.image || PLACEHOLDER
        };
      }
      const p = row.project;
      p.avatar = imageSrc(p.avatar || p.image || PLACEHOLDER);
      p.image = p.avatar;
      if (!p.name) p.name = p.domain || "RustApp";
      if (!p.domain) p.domain = p.tag || p.url || "";
      if (p.id == null) p.id = row.id || i + 1;
      if (row.id == null) row.id = p.id;
    });
    if (obj.reviews.length && obj.reviews.length < 8) {
      const base = obj.reviews.slice();
      while (obj.reviews.length < 14) obj.reviews = obj.reviews.concat(base);
      obj.reviews = obj.reviews.slice(0, 14);
    }
    if (!Array.isArray(obj.feed)) obj.feed = [];
    if (!Array.isArray(obj.orgs)) obj.orgs = [];
    if (!Array.isArray(obj.organizations)) obj.organizations = obj.orgs;
    if ((!obj.orgs || !obj.orgs.length) && obj.reviews.length) {
      obj.orgs = obj.reviews.map(function (r) { return r.project || r; });
      obj.organizations = obj.orgs;
      obj.projects = obj.orgs;
    }
    if (!obj.reviews.length && Array.isArray(obj.orgs) && obj.orgs.length) {
      obj.reviews = obj.orgs.map(function (row, i) {
        return {
          id: row.id != null ? row.id : i + 1,
          project: {
            id: row.id != null ? row.id : i + 1,
            name: row.name || row.title || row.domain || "RustApp",
            domain: row.domain || row.tag || "",
            avatar: imageSrc(row.avatar || row.image || PLACEHOLDER)
          }
        };
      });
    }
    if (obj.reviews.length && obj.reviews.length < 8) {
      const base = obj.reviews.slice();
      while (obj.reviews.length < 14) obj.reviews = obj.reviews.concat(base);
      obj.reviews = obj.reviews.slice(0, 14);
    }
    // Keep numeric counters — SPA shows N/A when values are null/undefined
    const counters = obj.counters && typeof obj.counters === "object" ? obj.counters : {};
    const stats = obj.stats && typeof obj.stats === "object" ? obj.stats : counters;
    const keys = [
      "players", "checks", "bans", "ban", "reports", "messages",
      "total_players", "total_checks", "total_bans", "total_reports", "total_messages",
      "online_servers", "online_players", "online_users"
    ];
    keys.forEach(function (key) {
      let val = obj[key];
      if (val == null) val = counters[key];
      if (val == null) val = stats[key];
      val = Number(val);
      if (!Number.isFinite(val)) val = 0;
      obj[key] = val;
      counters[key] = val;
      stats[key] = val;
    });
    obj.counters = counters;
    obj.stats = stats;
    obj.service = obj.service && typeof obj.service === "object" ? obj.service : counters;
    keys.forEach(function (key) {
      if (obj.service[key] == null) obj.service[key] = obj[key];
    });
    window.__checkappLandingStatsCache = obj;
    try { syncLandingStatsToPinia(obj); } catch (_) {}
    try { patchLandingAboutStatsRef(obj); } catch (_) {}
    return obj;
  }

  function patchLandingAboutStatsRef(obj) {
    if (!obj || typeof obj !== "object") return false;
    const scroll = document.querySelector(".landing-page .scroll-container");
    if (!scroll) return false;
    let el = scroll;
    for (let depth = 0; depth < 24 && el; depth++) {
      const vnode = el.__vueParentComponent;
      if (vnode && vnode.setupState && vnode.setupState.i && vnode.setupState.i.value) {
        const cur = vnode.setupState.i.value;
        if (cur && Array.isArray(cur.reviews) && cur.reviews.length && Array.isArray(obj.reviews) && obj.reviews.length) {
          return false;
        }
        const missing = !cur || !Array.isArray(cur.reviews) || !cur.reviews.length;
        if (missing && Array.isArray(obj.reviews) && obj.reviews.length) {
          vnode.setupState.i.value = Object.assign({}, cur || {}, obj);
          return true;
        }
        return false;
      }
      el = el.parentElement;
    }
    return false;
  }

  function fetchLandingFeedPayload() {
    const fetcher = window.__checkappOrigFetch || window.fetch.bind(window);
    return fetcher("/utils/landing-feed", {
      credentials: "include",
      cache: "no-store",
      headers: { Accept: "application/json" }
    }).then(function (res) {
      if (!res || !res.ok) return null;
      return res.json();
    }).catch(function () {
      return null;
    });
  }

  function mergeLandingFeedIntoStats(obj, feed) {
    if (!feed || typeof feed !== "object") return obj;
    if (!obj || typeof obj !== "object") obj = { counters: {}, stats: {}, service: {} };
    if (Array.isArray(feed.reviews) && feed.reviews.length) obj.reviews = feed.reviews.slice();
    if (Array.isArray(feed.orgs) && feed.orgs.length) obj.orgs = feed.orgs.slice();
    return normalizeStatsPayload(obj);
  }

  function fetchLandingStatsNormalized() {
    const fetcher = window.__checkappOrigFetch || window.fetch.bind(window);
    return fetcher("/utils/stats", {
      credentials: "include",
      cache: "no-store",
      headers: { Accept: "application/json" }
    }).then(function (res) {
      if (!res || !res.ok) return null;
      return res.json();
    }).then(function (obj) {
      if (!obj || typeof obj !== "object") return null;
      obj = normalizeStatsPayload(obj);
      if (obj.reviews && obj.reviews.length) return obj;
      return fetchLandingFeedPayload().then(function (feed) {
        return mergeLandingFeedIntoStats(obj, feed);
      });
    }).catch(function () {
      return fetchLandingFeedPayload().then(function (feed) {
        if (!feed) return null;
        return mergeLandingFeedIntoStats({ counters: {}, stats: {}, service: {} }, feed);
      });
    });
  }

  function loadLandingFeedItems() {
    let items = landingCarouselItemsFromCache();
    if (items.length) return Promise.resolve(items);
    return fetchLandingStatsNormalized().then(function () {
      items = landingCarouselItemsFromCache();
      if (items.length) return items;
      return fetchLandingFeedPayload().then(function (feed) {
        if (feed) mergeLandingFeedIntoStats(window.__checkappLandingStatsCache || { counters: {} }, feed);
        return landingCarouselItemsFromCache();
      });
    });
  }

  window.__checkappStats = function () {
    const cached = window.__checkappLandingStatsCache;
    if (cached && Array.isArray(cached.reviews) && cached.reviews.length) {
      return Promise.resolve(cached);
    }
    if (window.__checkappStatsPromise) return window.__checkappStatsPromise;
    window.__checkappStatsPromise = fetchLandingStatsNormalized().then(function (obj) {
      window.__checkappStatsPromise = null;
      if (obj && Array.isArray(obj.reviews) && obj.reviews.length) return obj;
      return loadLandingFeedItems().then(function () {
        const next = window.__checkappLandingStatsCache;
        return (next && next.reviews && next.reviews.length) ? next : (obj || cached || { counters: {}, reviews: [], orgs: [] });
      });
    });
    return window.__checkappStatsPromise;
  };

  function syncLandingStatsToPinia(obj) {
    if (!obj || !Array.isArray(obj.reviews) || !obj.reviews.length) return;
    if (window.__checkappLandingStable && landingCarouselHasNativeContent()) return;
    try {
      const root = document.querySelector("#app");
      const pinia = root && root.__vue_app__ && root.__vue_app__.config.globalProperties.$pinia;
      if (!pinia || !pinia._s) return;
      pinia._s.forEach(function (store) {
        if (!store || typeof store !== "object") return;
        if (Array.isArray(store.reviews)) store.reviews = obj.reviews.slice();
        if (store.value && typeof store.value === "object" && Array.isArray(store.value.reviews)) {
          store.value.reviews = obj.reviews.slice();
        }
        if (store.stats && typeof store.stats === "object") {
          store.stats.reviews = obj.reviews.slice();
        }
      });
    } catch (_) {}
  }

  function landingCarouselItemsFromCache() {
    const stats = window.__checkappLandingStatsCache;
    const reviews = stats && Array.isArray(stats.reviews) ? stats.reviews : [];
    const out = [];
    const seen = {};
    reviews.forEach(function (row, i) {
      const p = (row && row.project) || row || {};
      const name = String(p.name || p.title || row.name || row.title || "").trim();
      if (!name) return;
      const key = String(p.id != null ? p.id : name.toLowerCase());
      if (seen[key]) return;
      seen[key] = 1;
      out.push({
        id: row.id != null ? row.id : (p.id != null ? p.id : i + 1),
        name: name,
        domain: String(p.domain || p.tag || p.url || row.domain || row.tag || row.url || "").trim(),
        avatar: imageSrc(p.avatar || p.image || p.avatar_url || PLACEHOLDER)
      });
    });
    return out;
  }

  function landingCarouselHasNativeContent() {
    const scroll = document.querySelector(".landing-page .scroll-container");
    if (!scroll || scroll.closest("[data-checkapp-hide-trust='1']")) return false;
    const cards = scroll.querySelectorAll(".project:not(.skeleton)");
    if (cards.length >= 2) return true;
    return false;
  }

  function injectLandingStatsBgStyles() {
    let st = document.getElementById("checkapp-stats-bg-css");
    if (!st) {
      st = document.createElement("style");
      st.id = "checkapp-stats-bg-css";
      (document.head || document.documentElement).appendChild(st);
    }
    st.textContent = "html.checkapp-home .landing-page .stats-bg{background-size:cover!important;background-position:center!important;background-repeat:no-repeat!important;}";
  }

  function ribbonSlug(item) {
    const domain = String((item && (item.domain || item.tag || item.url)) || "").replace(/^@/, "").trim();
    if (domain) return domain.toLowerCase();
    const name = String((item && item.name) || "").trim();
    return name.toLowerCase().replace(/[^a-z0-9]+/g, "") || "project";
  }

  function landingRibbonFingerprint(items) {
    if (!items || !items.length) return "";
    return items.map(function (item) {
      return String(item.id != null ? item.id : "") + ":" + String(item.name || "").toLowerCase() + ":" + String(item.domain || "").toLowerCase();
    }).join("|");
  }

  function landingRibbonIsHealthy(host, items) {
    if (!host || !items || !items.length) return false;
    const track = host.querySelector(".checkapp-ribbon-track-a");
    if (!track || !track.querySelector(".checkapp-ribbon-item")) return false;
    return host.dataset.checkappRibbonFp === landingRibbonFingerprint(items);
  }

  function showLandingRibbonSection(section) {
    if (!section || section.dataset.checkappHideTrust === "1") return;
    section.dataset.checkappProjectsRibbon = "1";
    delete section.dataset.checkappHideFeed;
    ["display", "visibility", "height", "min-height", "max-height", "margin", "padding", "overflow", "opacity", "pointer-events"].forEach(function (key) {
      section.style.removeProperty(key);
    });
  }

  function injectLandingRibbonStyles() {
    const oldHide = document.getElementById("checkapp-landing-feed-hide");
    if (oldHide) {
      try { oldHide.remove(); } catch (_) {}
    }
    const old = document.getElementById("checkapp-landing-ribbon-style");
    if (old) {
      try { old.remove(); } catch (_) {}
    }
    const st = document.createElement("style");
    st.id = "checkapp-landing-ribbon-style";
    const css = [
      "html.checkapp-home .landing-page main>section:has(.scroll-container):not([data-checkapp-hide-trust='1']),html.checkapp-home #checkapp-projects-ribbon{display:block!important;visibility:visible!important;opacity:1!important;height:auto!important;min-height:56px!important;max-height:none!important;margin:0!important;padding:18px 0 24px!important;overflow:hidden!important;pointer-events:none!important;background:transparent!important;}",
      "html.checkapp-home .landing-page .scroll-container,html.checkapp-home .checkapp-ribbon-shell{display:block!important;visibility:visible!important;opacity:1!important;width:100%!important;max-width:1100px!important;margin:0 auto!important;overflow:hidden!important;-webkit-mask-image:linear-gradient(90deg,transparent,#000 4%,#000 96%,transparent)!important;mask-image:linear-gradient(90deg,transparent,#000 4%,#000 96%,transparent)!important;pointer-events:none!important;}",
      "html.checkapp-home .landing-page .scroll-container .scroll-content,html.checkapp-home .checkapp-ribbon-track{display:flex!important;flex-wrap:nowrap!important;align-items:center!important;width:max-content!important;}",
      "html.checkapp-home .landing-page .scroll-container>.scroll-content{animation:none!important;transform:none!important;will-change:auto!important;overflow:visible!important;}",
      "html.checkapp-home .checkapp-ribbon-track-a{will-change:transform!important;animation:checkapp-ribbon-marquee 48s linear infinite!important;}",
      "html.checkapp-home .landing-page .scroll-container .scroll-content+.scroll-content,html.checkapp-home .checkapp-ribbon-track-b{display:none!important;}",
      "@keyframes checkapp-ribbon-marquee{from{transform:translateX(0)}to{transform:translateX(-50%)}}",
      "html.checkapp-home .landing-page .scroll-container .project.checkapp-ribbon-item,html.checkapp-home .checkapp-ribbon-item{display:inline-flex!important;align-items:center!important;gap:12px!important;padding:6px 32px 6px 6px!important;margin:0!important;background:transparent!important;border:none!important;border-radius:0!important;box-shadow:none!important;outline:none!important;min-width:0!important;width:auto!important;max-width:none!important;flex:0 0 auto!important;white-space:nowrap!important;pointer-events:auto!important;filter:grayscale(1)!important;opacity:.72!important;transition:filter .25s ease,opacity .25s ease!important;transform:none!important;}",
      "html.checkapp-home .landing-page .scroll-container .project.checkapp-ribbon-item:hover,html.checkapp-home .checkapp-ribbon-item:hover{filter:grayscale(0)!important;opacity:1!important;}",
      "html.checkapp-home .checkapp-ribbon-avatar,html.checkapp-home .checkapp-ribbon-item img{display:block!important;visibility:visible!important;width:40px!important;height:40px!important;min-width:40px!important;min-height:40px!important;max-width:40px!important;max-height:40px!important;border-radius:50%!important;object-fit:cover!important;flex:0 0 40px!important;opacity:1!important;}",
      "html.checkapp-home .checkapp-ribbon-text{display:flex!important;flex-direction:column!important;gap:2px!important;min-width:0!important;flex:0 1 auto!important;}",
      "html.checkapp-home .checkapp-ribbon-title{font-size:15px!important;font-weight:600!important;line-height:1.2!important;color:#ececec!important;white-space:nowrap!important;display:block!important;text-transform:uppercase!important;}",
      "html.checkapp-home .checkapp-ribbon-slug{font-size:13px!important;font-weight:400!important;line-height:1.2!important;color:#7a7a7a!important;white-space:nowrap!important;text-transform:lowercase!important;display:block!important;}",
      "html.checkapp-home .landing-page .scroll-container .project.checkapp-ribbon-item>*:not(.checkapp-ribbon-avatar):not(.checkapp-ribbon-text),html.checkapp-home .checkapp-ribbon-item>*:not(.checkapp-ribbon-avatar):not(.checkapp-ribbon-text){display:none!important;}",
      "@media (max-width:768px){html.checkapp-home .checkapp-ribbon-item{padding-right:20px!important;gap:10px!important;}}"
    ].join("");
    /* Classic mode keeps the original rustapp.io design and therefore never
       adds html.checkapp-home (that class was only ever set together with
       rc-home-on — the custom skin we switched off). Strip the prefix there,
       otherwise the marquee renders as an unstyled vertical stack with
       title+slug glued side by side ("devrusthubdevrusthub"). */
    st.textContent = window.__RC_CLASSIC__ ? css.replace(/html\.checkapp-home\s+/g, "") : css;
    (document.head || document.documentElement).appendChild(st);
  }

  function ribbonLoopItems(items) {
    if (!items || !items.length) return [];
    let base = items.slice();
    while (base.length < 4) {
      base = base.concat(items);
    }
    return base.concat(base);
  }

  function buildLandingRibbonItemHtml(item) {
    const name = String(item.name || "Project").replace(/</g, "&lt;");
    const slug = String(ribbonSlug(item)).replace(/</g, "&lt;");
    const avatar = String(imageSrc(item.avatar || PLACEHOLDER)).replace(/"/g, "&quot;");
    const fb = String(PLACEHOLDER).replace(/"/g, "&quot;");
    return '<div class="project checkapp-ribbon-item" tabindex="0">' +
      '<img class="checkapp-ribbon-avatar" src="' + avatar + '" alt="' + name + '" width="40" height="40" loading="lazy" decoding="async" onerror="this.onerror=null;this.src=\'' + fb + '\';">' +
      '<div class="checkapp-ribbon-text">' +
      '<span class="checkapp-ribbon-title">' + name + "</span>" +
      '<span class="checkapp-ribbon-slug">' + slug + "</span>" +
      "</div></div>";
  }

  function buildLandingCarouselRowHtml(items) {
    if (!items || !items.length) return "";
    return items.map(buildLandingRibbonItemHtml).join("");
  }

  function ribbonTracksHtml(items) {
    const loop = ribbonLoopItems(items);
    const rowHtml = buildLandingCarouselRowHtml(loop);
    return '<div class="scroll-content">' +
      '<div class="checkapp-ribbon-track checkapp-ribbon-track-a">' + rowHtml + "</div>" +
      "</div>";
  }

  function renderRibbonIntoScroll(scroll, items) {
    if (!scroll || !items || !items.length) return false;
    const fp = landingRibbonFingerprint(items);
    if (landingRibbonIsHealthy(scroll, items)) return true;
    injectLandingRibbonStyles();
    scroll.innerHTML = ribbonTracksHtml(items);
    scroll.dataset.checkappRibbonFp = fp;
    scroll.dataset.checkappRibbonReady = "1";
    showLandingRibbonSection(scroll.closest("section"));
    scroll.style.removeProperty("display");
    scroll.style.removeProperty("visibility");
    scroll.style.removeProperty("opacity");
    return true;
  }

  function patchNativeRibbonCards() {
    const items = landingCarouselItemsFromCache();
    if (!items.length) return false;
    const scroll = document.querySelector(".landing-page .scroll-container");
    if (!scroll || scroll.closest("[data-checkapp-hide-trust='1']")) return false;
    return renderRibbonIntoScroll(scroll, items);
  }

  function renderForcedLandingRibbon(items) {
    if (!items || !items.length) return false;
    injectLandingRibbonStyles();
    const scroll = document.querySelector(".landing-page .scroll-container");
    if (scroll && !scroll.closest("[data-checkapp-hide-trust='1']")) {
      const forced = document.getElementById("checkapp-projects-ribbon");
      if (forced) {
        try { forced.remove(); } catch (_) {}
      }
      return renderRibbonIntoScroll(scroll, items);
    }
    const main = document.querySelector(".landing-page main");
    if (!main) return false;
    const rowHtml = buildLandingCarouselRowHtml(ribbonLoopItems(items));
    const shell = '<div class="checkapp-ribbon-shell">' +
      '<div class="checkapp-ribbon-track checkapp-ribbon-track-a">' + rowHtml + "</div>" +
      "</div>";
    let box = document.getElementById("checkapp-projects-ribbon");
    const fp = landingRibbonFingerprint(items);
    if (box && landingRibbonIsHealthy(box, items)) return true;
    if (!box) {
      box = document.createElement("section");
      box.id = "checkapp-projects-ribbon";
      box.dataset.checkappProjectsRibbon = "1";
      let insertBefore = null;
      main.querySelectorAll("section").forEach(function (sec) {
        if (!insertBefore && isLandingTrustReviewsSection(sec)) insertBefore = sec;
      });
      if (!insertBefore) {
        const sections = main.querySelectorAll("section");
        if (sections.length > 1) insertBefore = sections[1];
      }
      if (insertBefore && insertBefore.parentElement === main) main.insertBefore(box, insertBefore);
      else main.appendChild(box);
    }
    box.innerHTML = shell;
    box.dataset.checkappRibbonFp = fp;
    box.dataset.checkappRibbonReady = "1";
    window.__checkappLandingFeedReady = true;
    return true;
  }

  function renderForcedLandingFeed(items) {
    return renderForcedLandingRibbon(items);
  }

  function ensureForcedLandingFeed() {
    const path = location.pathname || "/";
    if (path !== "/" && path.replace(/\/+$/, "") !== "") return;
    const cachedItems = landingCarouselItemsFromCache();
    if (cachedItems.length) {
      renderForcedLandingRibbon(cachedItems);
      try { patchLandingAboutStatsRef(window.__checkappLandingStatsCache); } catch (_) {}
      return;
    }
    if (window.__checkappLandingFeedLoading) return;
    window.__checkappLandingFeedLoading = true;
    loadLandingFeedItems().then(function (items) {
      window.__checkappLandingFeedLoading = false;
      if (!items || !items.length) return;
      renderForcedLandingRibbon(items);
      try { patchLandingAboutStatsRef(window.__checkappLandingStatsCache); } catch (_) {}
    }).catch(function () {
      window.__checkappLandingFeedLoading = false;
    });
  }

  function injectLandingCarouselStyles() {
    injectLandingRibbonStyles();
  }

  function patchNativeProjectCards() {
    patchNativeRibbonCards();
  }

  function mountLandingProjectsCarousel() {
    const path = location.pathname || "/";
    if (path !== "/" && path.replace(/\/+$/, "") !== "") return;
    const oldForced = document.getElementById("checkapp-forced-landing-feed");
    if (oldForced) {
      try { oldForced.remove(); } catch (_) {}
    }
    const cachedItems = landingCarouselItemsFromCache();
    const scroll = document.querySelector(".landing-page .scroll-container");
    const forced = document.getElementById("checkapp-projects-ribbon");
    if (cachedItems.length && ((scroll && landingRibbonIsHealthy(scroll, cachedItems)) || (forced && landingRibbonIsHealthy(forced, cachedItems)))) {
      injectLandingRibbonStyles();
      return;
    }
    injectLandingRibbonStyles();
    if (cachedItems.length) {
      renderForcedLandingRibbon(cachedItems);
      return;
    }
    ensureForcedLandingFeed();
  }

  (function bootLandingRibbon() {
    const path = location.pathname || "/";
    if (path !== "/" && path.replace(/\/+$/, "") !== "") return;
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", mountLandingProjectsCarousel);
    } else {
      mountLandingProjectsCarousel();
    }
  })();

  function normalizeApi(url, obj, method) {
    const href = String(url || "");
    const verb = String(method || "GET").toUpperCase();
    if (/\/check\/\d+\/freeze-state/.test(href)) return obj;
    if (href.includes("/map") && !href.includes("/plugin/map") && !href.includes("map-preview")) {
      if (!obj || typeof obj !== "object" || Array.isArray(obj)) {
        obj = { servers: [], players: [], chunks: [], image: "" };
      }
      if (!Array.isArray(obj.servers)) obj.servers = [];
      if (!Array.isArray(obj.players)) obj.players = [];
      if (!Array.isArray(obj.chunks)) obj.chunks = [];
      if (!obj.image) obj.image = obj.image_url || obj.url || obj.map || "";
      if (!obj.image_url) obj.image_url = obj.image;
      if (!obj.url) obj.url = obj.image;
      if (!obj.world_size) obj.world_size = obj.size || 3000;
      if (!obj.size) obj.size = obj.world_size || 3000;
      function stringifyPos(node) {
        if (!node || typeof node !== "object") return;
        const pos = node.position;
        if (pos && typeof pos === "object" && !Array.isArray(pos)) {
          node.position = [pos.x || 0, pos.y || 0, pos.z || 0].map(Number).join(", ");
        }
        if (node.entity && typeof node.entity === "object") stringifyPos(node.entity);
      }
      obj.players.forEach(stringifyPos);
      obj.servers.forEach((srv) => {
        if (!srv || typeof srv !== "object") return;
        if (!Array.isArray(srv.players)) srv.players = obj.players || [];
        if (!srv.image) srv.image = srv.image_url || srv.url || obj.image;
        if (!srv.world_size) srv.world_size = srv.size || obj.world_size || 3000;
        (srv.players || []).forEach(stringifyPos);
      });
      return obj;
    }
    if (href.includes("/utils/upload")) {
      // SPA stores response directly into proof.s3_id — must be a non-empty string.
      // Urls.Images() only keeps a URL as-is if it contains "https", otherwise it
      // prefixes s3.{host} and the save button never sees a dirty avatar.
      let url = "";
      if (typeof obj === "string") url = obj;
      else if (obj && typeof obj === "object") url = String(obj.url || obj.s3_id || obj.path || "");
      url = String(url || "").trim();
      if (!url || url === "[object Object]" || url === "undefined") return "";
      try {
        const abs = new URL(url, location.origin);
        if (abs.origin === location.origin || /(?:s3|r2|core)\./i.test(abs.hostname)) {
          url = abs.pathname + abs.search;
        }
      } catch (_) {}
      if (url.indexOf("https") < 0) url += (url.indexOf("?") >= 0 ? "&" : "?") + "https=1";
      return url;
    }
    if (href.includes("clients-v2") || (href.includes("/clients") && !href.includes("clients-settings"))) {
      function fixStaffRow(row, idx) {
        if (!row || typeof row !== "object") return row;
        if (row.ok === false || row.error || row.unauthorized) return row;
        const memberId = Number((row.client && row.client.id) || row.client_id || row.id || 0) || 0;
        if (!memberId) return null;
        if (row.client && typeof row.client === "object") {
          row.client = ensureClientShape(row.client, row.client.name, memberId);
          row.client.id = memberId;
          ensureIdToString(row.client, memberId);
        } else {
          return null;
        }
        row.id = memberId;
        row.client_id = memberId;
        ensureIdToString(row, memberId);
        if (!Array.isArray(row.permissions)) row.permissions = [];
        if (!row.is_owner && (row.is_immutable || row.is_admin || permsWantAdmin(row.permissions, row))) {
          row.permissions = PERMISSIONS.slice();
          row.is_immutable = true;
          row.is_admin = true;
        }
        return row;
      }
      if (obj && typeof obj === "object" && (obj.ok === false || obj.error) && !obj.client && !obj.active) {
        return obj;
      }
      if (verb === "DELETE" && obj && typeof obj === "object" && !Array.isArray(obj.active)) {
        return obj;
      }
      if (Array.isArray(obj)) {
        const rows = obj.map(fixStaffRow).filter(Boolean);
        return { active: rows, all: rows };
      }
      if (obj && typeof obj === "object" && Array.isArray(obj.active)) {
        obj.active = obj.active.map(fixStaffRow).filter(Boolean);
        if (Array.isArray(obj.all)) obj.all = obj.all.map(fixStaffRow).filter(Boolean);
        return obj;
      }
      // POST /clients must stay a single membership row (SPA does row.id.toString / row.client.id.toString).
      if (obj && typeof obj === "object" && (verb === "POST" || verb === "PUT" || verb === "PATCH")) {
        return fixStaffRow(obj.client ? obj : { client: obj, permissions: Array.isArray(obj.permissions) ? obj.permissions : [], is_immutable: false }, 0);
      }
      if (obj && typeof obj === "object") {
        const row = fixStaffRow(obj.client ? obj : { client: obj, permissions: obj.permissions || PERMISSIONS.slice(), is_immutable: true }, 0);
        return { active: [row], all: [row] };
      }
    }
    if ((href.includes("/client") || href.includes("/auth/handshake")) && obj && typeof obj === "object" && !Array.isArray(obj) && !obj.unauthorized && Number(obj.id || 0) > 0 && (obj.email || obj.name)) {
      const selfPath = String(href || "").split("?")[0];
      const isSelfClient = /\/client$/.test(selfPath) || /\/client\/profile$/.test(selfPath) || /\/client\/auth$/.test(selfPath) || /\/auth\/handshake$/.test(selfPath);
      if (isSelfClient) {
        applyCachedDiscord(obj);
        if (obj.discord_id) rememberDiscordProfile(obj);
      }
      ensureClientIntegrations(obj);
      if (obj.M_ID == null) obj.M_ID = obj.id;
      obj.status = "online";
      obj.online = true;
      obj.is_online = true;
      obj.presence = "online";
      if (isSelfClient && obj.id) window.__caMeId = obj.id;
      if (isSelfClient && (!obj.avatar || String(obj.avatar).includes("placeholder.jpeg"))) {
        obj.avatar = ACCOUNT_AVATAR;
      } else if (!obj.avatar || String(obj.avatar).includes("placeholder.jpeg")) {
        obj.avatar = imageSrc(obj.avatar || PLACEHOLDER);
      } else {
        obj.avatar = imageSrc(obj.avatar);
      }
      const linkedSid = String((obj.steam && obj.steam.steam_id) || obj.steam_id || "").trim();
      if (isRealSteamId(linkedSid)) {
        if (!obj.steam || typeof obj.steam !== "object") {
          obj.steam = {
            steam_id: linkedSid,
            steam_name: obj.steam_name || "",
            steam_avatar: obj.steam_avatar || PLACEHOLDER,
            avatar: obj.steam_avatar || PLACEHOLDER,
            personaname: obj.steam_name || "",
            name: obj.steam_name || "",
            profileurl: "https://steamcommunity.com/profiles/" + linkedSid
          };
        }
        const steamName = cleanSteamName(obj.steam.personaname || obj.steam.steam_name || obj.steam.name || obj.steam_name || "", linkedSid) || "Steam";
        const av = steamHttpsAvatar(obj.steam.avatarfull || obj.steam.steam_avatar || obj.steam.avatar || obj.steam_avatar || "");
        obj.steam.steam_id = linkedSid;
        obj.steam.steamid = linkedSid;
        obj.steam.steam_name = steamName;
        obj.steam.personaname = steamName;
        obj.steam.name = steamName;
        obj.steam.avatar = av;
        obj.steam.steam_avatar = av;
        obj.steam.avatarfull = av;
        obj.steam.profileurl = obj.steam.profileurl || ("https://steamcommunity.com/profiles/" + linkedSid);
        obj.steam_id = linkedSid;
        obj.steam_name = steamName;
        obj.steam_avatar = av;
      } else {
        obj.steam = null;
        obj.steam_id = "";
        obj.steam_name = "";
        obj.steam_avatar = "";
      }
      if (obj.discord && typeof obj.discord !== "object") {
        obj.discord = null;
      }
      if (!obj.discord || typeof obj.discord !== "object") {
        obj.discord = {
          discord_id: String(obj.discord_id || ""),
          discord_name: obj.discord_name || "",
          discord_avatar: obj.discord_avatar || "",
          avatar: obj.discord_avatar || ""
        };
      } else if (!obj.discord.avatar || !/cdn\.discordapp\.com/i.test(String(obj.discord.avatar || ""))) {
        obj.discord.avatar = (/cdn\.discordapp\.com/i.test(String(obj.discord.discord_avatar || "")) ? obj.discord.discord_avatar : "") || obj.discord_avatar || "";
      }
      if (obj.discord_id && !obj.discord.discord_id) {
        obj.discord.discord_id = String(obj.discord_id);
      }
      const linkedDiscordId = String((obj.discord && obj.discord.discord_id) || obj.discord_id || "").trim();
      obj.discord_id = linkedDiscordId;
      obj.discord.id = obj.discord.id || linkedDiscordId;
      obj.discord.user_id = obj.discord.user_id || linkedDiscordId;
      obj.discord.account_id = obj.discord.account_id || linkedDiscordId;
      obj.discord.connected = !!linkedDiscordId;
      obj.discord.is_connected = !!linkedDiscordId;
      obj.discord.available = true;
      obj.discord.status = linkedDiscordId ? "connected" : "disconnected";
      if (!obj.integrations || typeof obj.integrations !== "object") obj.integrations = {};
      if (!obj.integrations.discord || typeof obj.integrations.discord !== "object") obj.integrations.discord = {};
      obj.integrations.discord.connected = !!linkedDiscordId;
      obj.integrations.discord.is_connected = !!linkedDiscordId;
      obj.integrations.discord.id = linkedDiscordId;
      obj.integrations.discord.discord_id = linkedDiscordId;
      obj.integrations.discord.name = (obj.discord && (obj.discord.discord_name || obj.discord.name || obj.discord.username)) || obj.discord_name || "";
      obj.integrations.discord.username = obj.integrations.discord.name;
      obj.integrations.discord.personaname = obj.integrations.discord.name;
      obj.integrations.discord.avatar = (obj.discord && (obj.discord.discord_avatar || obj.discord.avatar)) || obj.discord_avatar || "";
      obj.integrations.discord.discord_avatar = obj.integrations.discord.avatar;
      obj.integrations.discord.available = true;
      obj.integrations.discord.status = linkedDiscordId ? "connected" : "disconnected";
      if (!obj.google || typeof obj.google !== "object") {
        obj.google = {
          google_id: String(obj.google_id || ""),
          google_name: obj.google_name || "",
          google_avatar: obj.google_avatar || "",
          avatar: obj.google_avatar || obj.avatar || PLACEHOLDER
        };
      } else if (!obj.google.avatar) {
        obj.google.avatar = obj.google.google_avatar || obj.avatar || PLACEHOLDER;
      }
      if (isRealSteamId(obj.steam_id) || (obj.steam && isRealSteamId(obj.steam.steam_id))) {
        if (!obj.steam || typeof obj.steam !== "object") {
          obj.steam = {
            steam_id: String(obj.steam_id || obj.steam.steam_id),
            steam_name: obj.steam_name || "Steam",
            name: obj.steam_name || "Steam",
            personaname: obj.steam_name || "Steam",
            avatar: steamHttpsAvatar(obj.steam_avatar || ""),
            steam_avatar: steamHttpsAvatar(obj.steam_avatar || ""),
            avatarfull: steamHttpsAvatar(obj.steam_avatar || "")
          };
        }
      } else {
        obj.steam = null;
        obj.steam_id = "";
      }
      if (!Array.isArray(obj.permissions)) {
        obj.permissions = PERMISSIONS.slice();
      }
    }
    if (href.includes("/client/browse") && Array.isArray(obj)) {
      obj.forEach((row) => {
        if (!row || typeof row !== "object") return;
        row.status = "online";
        if (row.M_ID == null) row.M_ID = row.id;
        row.online = true;
        row.is_online = true;
        if (!row.avatar) row.avatar = PLACEHOLDER;
        // A previous failed batch lookup leaves a "Удалённый сотрудник" stub
        // in __caClients.  Always publish the successful API profile back to
        // that cache; otherwise ClientInline keeps rendering the stale stub
        // despite the server returning the person's real name and @tag.
        rememberStaffClient(row);
      });
      if (!obj.length) {
        try {
          const u = new URL(href, location.origin);
          const cid = Number(u.searchParams.get("id") || u.searchParams.get("ids") || u.searchParams.get("client_id") || 0);
          if (cid) obj = [deletedStaffStub(cid, "")];
        } catch (_) {}
      }
    }
    const clientById = href.match(/\/client\/(\d+)(?:\?|$)/);
    if (clientById && verb === "GET") {
      const cid = Number(clientById[1]) || 0;
      let cached = null;
      try { cached = (window.__caClients && cid) ? window.__caClients[String(cid)] : null; } catch (_) { cached = null; }
      if (!obj || typeof obj !== "object" || Array.isArray(obj) || obj.unauthorized || !obj.id) {
        obj = deletedStaffStub(cid, (cached && cached.name) || (obj && obj.name) || "");
      }
      if (cached && typeof cached === "object") {
        if (isGenericStaffLabel(obj.name) && !isGenericStaffLabel(cached.name)) obj.name = cached.name;
        if (isGenericStaffLabel(obj.tag) && !isGenericStaffLabel(cached.tag)) obj.tag = cached.tag;
        if (isGenericStaffLabel(obj.tag)) obj.tag = personalStaffTag(obj) || personalStaffTag(cached) || "";
        if ((!obj.email && cached.email) || (isGenericStaffLabel(obj.email) && cached.email)) obj.email = cached.email;
        if ((!obj.avatar || /logo-avatar|image-1024|placeholder/i.test(String(obj.avatar))) && cached.avatar) obj.avatar = cached.avatar;
      }
      obj = ensureClientShape(obj, obj.name || (cached && cached.name) || "", cid);
      rememberStaffClient(obj);
      return obj;
    }
    if (href.includes("project-stats")) {
      const now = Date.now();
      const points = [];
      const isIp = href.includes("/ip");
      const isUnique = href.includes("unique");
      if (isIp) {
        const players = Number((obj && (obj.total_players || obj.total)) || 0) || 0;
        return {
          created_at: (obj && obj.created_at) || now,
          top_cities: Array.isArray(obj && obj.top_cities) ? obj.top_cities : [],
          top_countries: Array.isArray(obj && obj.top_countries) ? obj.top_countries : [],
          total_players: players,
          countries: Array.isArray(obj && obj.countries) ? obj.countries : []
        };
      }
      let srcPoints = Array.isArray(obj && obj.time_points) ? obj.time_points : [];
      if (!srcPoints.length) {
        for (let i = 24; i >= 0; i--) {
          const t = now - i * 3600000;
          srcPoints.push({ timestamp: t, time: t, online: 0, joining: 0, queued: 0, queue: 0, total: 0, value: 0 });
        }
      }
      const normalized = srcPoints.map(function (pt) {
        const t = Number(pt.timestamp || pt.time || pt.date || 0) || now;
        const online = Number(pt.online != null ? pt.online : (pt.players != null ? pt.players : pt.value) || 0) || 0;
        const joining = Number(pt.joining || 0) || 0;
        const queued = Number(pt.queued != null ? pt.queued : pt.queue || 0) || 0;
        const total = Number(pt.total != null ? pt.total : online || 0) || 0;
        return {
          timestamp: t,
          time: t,
          online: online,
          joining: joining,
          queued: queued,
          queue: queued,
          reserved: Number(pt.reserved || 0) || 0,
          players: online,
          total: total,
          value: isUnique ? total : online,
          license: Number(pt.license || 0) || 0,
          pirate: Number(pt.pirate || 0) || 0
        };
      });
      return Object.assign({}, obj && typeof obj === "object" && !Array.isArray(obj) ? obj : {}, {
        time_points: normalized,
        countries: Array.isArray(obj && obj.countries) ? obj.countries : [],
        total: Number((obj && obj.total) || 0) || 0
      });
    }
    if (href.includes("/players/") && href.includes("/kill-feed")) {
      const src = obj && typeof obj === "object" && !Array.isArray(obj) ? obj : {};
      const rows = Array.isArray(obj) ? obj : (src.results || src.data || src.items) || [];
      const list = (Array.isArray(rows) ? rows : []).map((row, i) => {
        if (!row || typeof row !== "object") return null;
        if (row.id == null) row.id = i + 1;
        if (!row.initiator || typeof row.initiator !== "object") row.initiator = row.initiator_player || {};
        if (!row.target || typeof row.target !== "object") row.target = row.target_player || {};
        const a = String(row.initiator_steam_id || row.initiator.steam_id || "");
        const b = String(row.target_steam_id || row.target.steam_id || "");
        row.initiator = shapeKillFeedPlayer(row.initiator, a);
        row.target = shapeKillFeedPlayer(row.target, b);
        row.initiator_steam_id = String(row.initiator.steam_id || a);
        row.target_steam_id = String(row.target.steam_id || b);
        row.initiator_player = row.initiator;
        row.target_player = row.target;
        const weapon = String(row.weapon || "assets/prefabs/weapons/ak47u/ak47u.entity.prefab");
        const ammo = String(row.ammo || killAmmoForWeapon(weapon));
        row.weapon = weapon;
        row.ammo = ammo;
        row.distance = Number(row.distance || 0) || 0;
        if (!Array.isArray(row.hit_history)) row.hit_history = [];
        if (!row.hit_history.length) {
          const distance = Number(row.distance || 0) || 1;
          const bone = String(row.bone || (row.is_headshot || row.headshot ? "head" : "spine")).replace(/^\[.*/, "spine");
          const boneKey = bone.indexOf("#bone_") === 0 ? bone : ("#bone_" + bone.replace(/^#/, ""));
          row.hit_history = [
            {
              time: 0.42, attacker: "player", attacker_steam_id: a, target: "you", target_steam_id: b,
              weapon: weapon, ammo: ammo, bone: "#bone_spine", distance: Math.max(distance * 0.85, 0.1),
              hp_old: 100, hp_new: 42, info: "", ad: false, pi: 1, pm: 0, desync: 10, proj_hits: 0, proj_travel: 0.05
            },
            {
              time: 1.01, attacker: "player", attacker_steam_id: a, target: "you", target_steam_id: b,
              weapon: weapon, ammo: ammo, bone: boneKey, distance: Math.max(distance, 0.1),
              hp_old: 42, hp_new: 0, info: "killed", ad: false, pi: 1, pm: 0, desync: 14, proj_hits: 0, proj_travel: 0.08
            }
          ];
        }
        row.hit_history = row.hit_history.map(function (hit) {
          if (!hit || typeof hit !== "object") return null;
          hit.time = Number(hit.time || 0) || 0;
          hit.distance = Number(hit.distance || 0) || 0;
          hit.hp_old = Number(hit.hp_old != null ? hit.hp_old : 100) || 0;
          hit.hp_new = Number(hit.hp_new != null ? hit.hp_new : 0) || 0;
          hit.weapon = String(hit.weapon || row.weapon || "");
          hit.ammo = String(hit.ammo || ammo || killAmmoForWeapon(hit.weapon));
          hit.bone = String(hit.bone || "spine");
          if (hit.bone === "undefined" || hit.bone === "null") hit.bone = "spine";
          hit.attacker = hit.attacker || "player";
          hit.target = hit.target || "you";
          hit.attacker_steam_id = String(hit.attacker_steam_id || row.initiator_steam_id || "");
          hit.target_steam_id = String(hit.target_steam_id || row.target_steam_id || "");
          return hit;
        }).filter(Boolean);
        row.connected_steam_ids = [row.initiator.steam_id, row.target.steam_id].filter(isRealSteamId);
        return row;
      }).filter(Boolean);
      return packedResults(list, {
        has_more: false,
        hasMore: false,
        done: true,
        finished: true,
        limit: list.length + 1,
        total: list.length,
        page: 1,
        current_page: 1,
        next_cursor: null,
        next_page: null,
        last_page: 1,
        meta: { has_more: false, done: true, next_cursor: null, next_page_url: null, last_page: 1 }
      });
    }
    if (href.includes("/players/") && (href.includes("/small-stats") || /\/players\/[^/]+\/stats(?:\?|$)/.test(href))) {
      const base = obj && typeof obj === "object" && !Array.isArray(obj) ? obj : {};
      const src = Object.assign({}, base.data || {}, base.stats || {}, base);
      const nestedKills = src.kills && typeof src.kills === "object" && !Array.isArray(src.kills) ? src.kills : null;
      const kills = Number((nestedKills && nestedKills.kills) || (typeof src.kills === "number" ? src.kills : 0) || src.kills_count || 0) || 0;
      const deaths = Number((nestedKills && (nestedKills.deathes != null ? nestedKills.deathes : nestedKills.deaths)) || src.deathes || src.deaths || 0) || 0;
      const head = Number(src.headshots || src.head || (src.bone_kills && src.bone_kills.head) || (nestedKills && nestedKills.bone_kills && nestedKills.bone_kills.head) || 0) || 0;
      const body = Number(src.body || src.in_body || src.torso || (src.bone_kills && (src.bone_kills.torso || src.bone_kills.body)) || (nestedKills && nestedKills.bone_kills && (nestedKills.bone_kills.torso || nestedKills.bone_kills.body)) || Math.max(kills - head, 0)) || 0;
      const limbs = Number(src.limbs || src.in_limbs || (src.bone_kills && src.bone_kills.limbs) || (nestedKills && nestedKills.bone_kills && nestedKills.bone_kills.limbs) || 0) || 0;
      const kd = Number((nestedKills && (nestedKills.kda || nestedKills.kd)) || src.kda || src.kd || src.kdr || (deaths ? kills / deaths : kills)) || 0;
      const bone = { head: head, body: body, torso: body, limbs: limbs, arms: limbs, legs: limbs };
      const now = Date.now();
      let playStats = src.playTime && src.playTime.stats && typeof src.playTime.stats === "object" ? Object.assign({}, src.playTime.stats) : null;
      let points = Array.isArray(src.time_points) ? src.time_points.slice() : [];
      if (!playStats) {
        playStats = {};
        if (!points.length) {
          for (let i = 7; i >= 0; i--) {
            const day = new Date(now - i * 86400000);
            day.setHours(0, 0, 0, 0);
            const t = day.getTime();
            points.push({ time: t, value: 0, hours: 0 });
            playStats[String(t)] = { date: t, hours_played: 0 };
          }
        } else {
          points.forEach(function (pt) {
            const t = Number(pt.time || pt.date || 0) || 0;
            const h = Number(pt.hours != null ? pt.hours : pt.value || 0) || 0;
            playStats[String(t)] = { date: t, hours_played: h };
          });
        }
      } else if (!points.length) {
        Object.keys(playStats).forEach(function (k) {
          const row = playStats[k] || {};
          points.push({ time: Number(row.date || k) || 0, value: Number(row.hours_played || 0) || 0, hours: Number(row.hours_played || 0) || 0 });
        });
      }
      const hours = Number((src.playTime && src.playTime.total) || src.hours || src.hours_played || src.hours_on_server || 0) || 0;
      const reportsTotal = Number((src.reports && typeof src.reports === "object" ? (src.reports.total_outcome || src.reports.total) : src.reports) || 0) || 0;
      const killsObj = {
        steam_id: src.steam_id || (nestedKills && nestedKills.steam_id) || "",
        kills: kills,
        deathes: deaths,
        deaths: deaths,
        kda: kd,
        kd: kd,
        kdr: kd,
        bone_kills: bone,
        headshots: head
      };
      const flat = {
        playTime: { total: hours, stats: playStats },
        reports: { total_outcome: reportsTotal, total: reportsTotal },
        steam: { total_hours: hours },
        deathes: deaths,
        deaths: deaths,
        kd: kd,
        kda: kd,
        kdr: kd,
        headshots: head,
        shots: Number(src.shots || kills) || kills,
        hits: Number(src.hits || kills) || kills,
        hours: hours,
        hours_played: hours,
        hours_on_server: hours,
        time_points: points,
        playtime: points,
        hours_chart: points,
        bone_kills: bone,
        hit_locations: { head: head, body: body, limbs: limbs },
        head: head,
        body: body,
        limbs: limbs,
        in_head: head,
        in_body: body,
        in_torso: body,
        in_limbs: limbs,
        in_limb: limbs,
        kills_count: kills
      };
      // Overview /small-stats: kills must be a number (.toString()). Full /stats: nested object.
      if (href.includes("/small-stats")) {
        return Object.assign({ kills: kills }, flat);
      }
      return Object.assign({ kills: killsObj }, flat);
    }
    if (
      href.includes("/stats") &&
      !href.includes("/players/") &&
      !href.includes("project-stats") &&
      obj && typeof obj === "object" && !Array.isArray(obj) && obj.stats == null && obj.counters == null
    ) {
      return { stats: {}, reasons: {}, moders: [], total: 0 };
    }
    if (href.includes("/players/") && /settings-auto-kick/i.test(href)) {
      return mergePlayerAutokick(href, obj, verb);
    }
    if (href.includes("/players/") && href.includes("/details")) {
      return fixPlayerDetails(obj, href);
    }
    const lonePlayer = href.match(/\/players\/(\d+)(?:\?|$)/);
    if (lonePlayer && verb === "GET" && !/\/players\/browse/i.test(href)) {
      const sid = String(lonePlayer[1] || "").trim();
      if (sid && !isRealSteamId(sid)) {
        const src = obj && typeof obj === "object" && !Array.isArray(obj) ? obj : {};
        return shapeKillFeedPlayer(src, sid);
      }
    }
    if (href.includes("/team-history")) {
      const rows = Array.isArray(obj) ? obj : (obj && (obj.results || obj.data || obj.items));
      const list = (Array.isArray(rows) ? rows : []).map(function (row, i) {
        if (!row || typeof row !== "object") {
          return {
            id: i + 1, members: [], players: [], team: [], teammates: [], team_players: [],
            size: 1, team_size: 1, started_at: Date.now(), created_at: Date.now()
          };
        }
        if (row.id == null) row.id = i + 1;
        const mates = Array.isArray(row.teammates) ? row.teammates
          : (Array.isArray(row.players) ? row.players
            : (Array.isArray(row.members) ? row.members
              : (Array.isArray(row.team) ? row.team : [])));
        const fixed = mates.map(function (m) {
          if (!m || typeof m !== "object") {
            const sid = String(m || "");
            return { steam_id: sid, steam_name: sid, name: sid, steam_avatar: PLACEHOLDER, status: "offline", team: [] };
          }
          m.steam_id = String(m.steam_id || m.id || "");
          m.steam_name = m.steam_name || m.name || m.steam_id;
          m.name = m.name || m.steam_name;
          m.steam_avatar = imageSrc(m.steam_avatar || m.avatar || PLACEHOLDER);
          m.avatar = m.steam_avatar;
          if (m.status == null) m.status = "offline";
          if (!Array.isArray(m.team)) m.team = [];
          return m;
        }).filter(Boolean);
        row.teammates = fixed;
        row.players = fixed;
        row.members = fixed;
        row.team = fixed;
        row.friends = Array.isArray(row.friends) && row.friends.length ? row.friends : fixed.slice();
        row.team_players = Array.isArray(row.team_players) ? row.team_players : fixed.slice();
        row.size = Number(row.size || row.team_size || (fixed.length + 1)) || (fixed.length + 1);
        row.team_size = row.size;
        if (row.started_at == null) row.started_at = row.created_at || Date.now();
        if (row.created_at == null) row.created_at = row.started_at;
        if (row.last_seen_at == null) row.last_seen_at = row.ended_at || row.finished_at || row.created_at;
        let sidn = Number(row.server_id || 0);
        if (!sidn) {
          try {
            const root = document.querySelector("#app");
            const pinia = root && root.__vue_app__ && root.__vue_app__.config && root.__vue_app__.config.globalProperties && root.__vue_app__.config.globalProperties.$pinia;
            const court = pinia && pinia._s && (pinia._s.get("court") || pinia._s.get("Court"));
            const raw = court && (court.servers || (court.$state && court.$state.servers));
            const servers = raw && raw.value ? raw.value : raw;
            const first = Array.isArray(servers) ? servers[0] : null;
            sidn = Number((first && (first.id || first.server_id)) || 0) || 0;
          } catch (_) {}
        }
        row.server_id = sidn;
        return row;
      }).filter(Boolean);
      return packedResults(list, {
        has_more: false,
        hasMore: false,
        done: true,
        finished: true,
        limit: list.length + 1,
        total: list.length,
        next_cursor: null,
        next_page: null,
        last_page: 1,
        meta: { has_more: false, done: true, next_cursor: null, next_page_url: null, last_page: 1 }
      });
    }
    if (href.includes("/players/browse") || href.includes("browse-full") || href.includes("browse-minimal")) {
      const rows = Array.isArray(obj) ? obj : (obj && (obj.results || obj.data || obj.items));
      const list = Array.isArray(rows) ? rows : [];
      list.forEach((row, i) => {
        if (!row || typeof row !== "object") return;
        const fixed = fixPlayerDetails({ player: row, entity: row.entity || {}, team: row.team || [] });
        list[i] = Object.assign(row, fixed.player, { entity: fixed.entity, team: fixed.team });
      });
      if (Array.isArray(obj)) {
        return { results: list, data: list, items: list, total: list.length };
      }
      if (obj && typeof obj === "object") {
        obj.results = list;
        obj.data = obj.data || list;
        obj.items = obj.items || list;
        if (obj.total == null) obj.total = list.length;
        return obj;
      }
      return { results: list, data: list, items: list, total: list.length };
    }
    if (href.includes("/players/") && (href.includes("/comments") || href.includes("/notes"))) {
      if (verb === "POST" || verb === "PUT" || verb === "DELETE") {
        if (obj && typeof obj === "object" && !Array.isArray(obj)) {
          if (obj.id == null) obj.id = Date.now();
          if (!obj.client || typeof obj.client !== "object") obj.client = { id: 1, name: (staffProfile() && staffProfile().name) || "" };
          if (obj.text == null) obj.text = obj.message || obj.comment || obj.note || "";
          if (obj.message == null) obj.message = obj.text;
          return obj;
        }
        return obj;
      }
      const list = Array.isArray(obj) ? obj : ((obj && (obj.data || obj.results || obj.items)) || []);
      return (Array.isArray(list) ? list : []).map((row, i) => {
        if (!row || typeof row !== "object") return { id: i + 1, text: String(row || ""), message: String(row || ""), client: { id: 1, name: "" } };
        if (row.id == null) row.id = i + 1;
        if (!row.client || typeof row.client !== "object") row.client = row.author || { id: 1, name: "" };
        if (row.client.id == null) row.client.id = 1;
        if (row.text == null) row.text = row.message || row.comment || row.note || "";
        if (row.message == null) row.message = row.text;
        return row;
      });
    }
    if (href.includes("/player-message")) {
      if (verb === "POST") {
        const rows = Array.isArray(obj) ? obj : (obj && obj.data);
        const list = Array.isArray(rows) ? rows : [{ status: "fulfilled", value: obj && obj.value ? obj.value : (obj || {}) }];
        list.forEach(function (wrap) {
          const value = (wrap && wrap.value && typeof wrap.value === "object") ? wrap.value : wrap;
          if (!value || typeof value !== "object") return;
          if (value.serverId == null) value.serverId = Number(value.server_id || 1) || 1;
          if (value.server_id == null) value.server_id = value.serverId;
          if (value.result == null) value.result = true;
          if (value.initiator_id == null || value.initiator_id === 0 || value.initiator_id === "0") {
            const nid = Number((value.initiator_client && value.initiator_client.id) || value.actor_user_id || 0);
            if (nid) value.initiator_id = String(nid);
          }
          value.initiator_id = asInitiatorId(value.initiator_id, value.steam_id);
          if (!value.initiator_name) value.initiator_name = (value.initiator_client && value.initiator_client.name) || "";
          value.initiator_client = ensureClientShape(value.initiator_client, value.initiator_name, value.initiator_id);
          if (value.initiator_client.id == null || value.initiator_client.id === 0 || value.initiator_client.id === "0") {
            value.initiator_client.id = value.initiator_id && String(value.initiator_id) !== "0" ? Number(value.initiator_id) || value.initiator_client.id : value.initiator_client.id;
          }
          const cidn = Number(value.initiator_client.id);
          if (cidn) value.initiator_client.id = cidn;
          ensureIdToString(value.initiator_client, value.initiator_client.id);
          rememberStaffClient(value.initiator_client);
          if (!value.initiator_player || typeof value.initiator_player !== "object") {
            value.initiator_player = { steam_id: "0", steam_name: value.initiator_name, name: value.initiator_name, steam_avatar: PLACEHOLDER, status: "online", team: [] };
          }
          if (!Array.isArray(value.initiator_player.team)) value.initiator_player.team = [];
          if (!Array.isArray(value.team)) value.team = [];
          if (!Array.isArray(value.servers)) value.servers = [{ id: value.serverId, serverId: value.serverId }];
          if (value.text == null) value.text = value.message || "";
          if (value.message == null) value.message = value.text || "";
          if (wrap && wrap.value) wrap.value = value;
        });
        return list;
      }
      const rows = Array.isArray(obj) ? obj : (obj && (obj.data || obj.results || obj.items));
      const list = (Array.isArray(rows) ? rows : []).filter((row) => {
        if (!row || typeof row !== "object") return false;
        if (row.is_team || String(row.type || "").toLowerCase() === "team") return false;
        return true;
      });
      const cleanName = function (name, steamId) {
        const n = String(name || "").trim();
        const sid = String(steamId || "").trim();
        // Keep real Steam nicks including "." / short punctuation names
        if (n && n !== sid && !/^\d{16,}$/.test(n)) return n;
        if (n && n === sid) return n;
        return n || sid || "Игрок";
      };
      list.forEach((row, i) => {
        if (row.id == null) row.id = i + 1;
        if (!row.unique_id) row.unique_id = "msg-" + row.id;
        if (row.is_team || String(row.type || "").toLowerCase() === "team") {
          row.type = "team";
          row.is_team = true;
        } else if (!row.type) {
          row.type = row.target_steam_id || row.target_id ? "direct" : "global";
        }
        if (row.text == null) row.text = row.message || "";
        if (row.message == null) row.message = row.text || "";
        if (row.created_at == null) row.created_at = Date.now();
        if (row.server_id == null) row.server_id = 1;
        if (row.initiator_player && typeof row.initiator_player === "object") {
          row.initiator_player.steam_name = cleanName(row.initiator_player.steam_name || row.initiator_name, row.initiator_player.steam_id || row.initiator_id);
          row.initiator_player.name = row.initiator_player.steam_name;
        }
        if (row.target_player && typeof row.target_player === "object") {
          row.target_player.steam_name = cleanName(row.target_player.steam_name || row.target_name, row.target_player.steam_id || row.target_steam_id || row.target_id);
          row.target_player.name = row.target_player.steam_name;
          row.target_name = row.target_player.steam_name;
        }
        if (row.initiator_name != null) {
          row.initiator_name = cleanName(row.initiator_name, row.initiator_id || (row.initiator_player && row.initiator_player.steam_id));
        }
        if (row.type === "direct" || row.target_steam_id) {
          if (!row.target_player || typeof row.target_player !== "object") row.target_player = {};
          if (!row.target_player.steam_name || row.target_player.steam_name === "Unknown") {
            row.target_player.steam_name = cleanName(row.target_name || row.target_player.name || row.target_steam_id || "", row.target_steam_id || row.target_id);
          }
          if (!row.target_player.name) row.target_player.name = row.target_player.steam_name;
          row.target_name = row.target_player.steam_name;
        }
        if (row.from_site) {
          const frozen = Number((row.initiator_client && row.initiator_client.id) || row.actor_user_id || 0);
          row.initiator_id = asInitiatorId(frozen || row.initiator_id, "");
          if (row.initiator_client && typeof row.initiator_client === "object") {
            if (frozen) row.initiator_client.id = frozen;
            row.initiator_client = ensureClientShape(row.initiator_client, row.initiator_name, frozen);
          }
        } else {
          row.initiator_id = asInitiatorId(row.initiator_id, row.steam_id);
        }
        if (row.initiator_client && typeof row.initiator_client === "object") {
          row.initiator_client = ensureClientShape(row.initiator_client, row.initiator_name, row.initiator_client.id);
          rememberStaffClient(row.initiator_client);
        }
      });
      list.sort(function (a, b) {
        return Number(a.created_at || a.id || 0) - Number(b.created_at || b.id || 0);
      });
      if (Array.isArray(obj) || !obj || typeof obj !== "object") return { data: list, results: list, items: list, total: list.length };
      obj.data = list;
      obj.results = list;
      obj.items = list;
      obj.total = list.length;
      return obj;
    }
    if (/\/players\/[^/]+\/rcc(?:\?|$)/.test(href) && verb === "GET") {
      // The ban section in a player profile is populated through this
      // endpoint, not /ban/browse.  It therefore used to skip the moderator
      // normalizer below and the BanView component received no author.
      function fillProfileBanModerator(row) {
        if (!row || typeof row !== "object") return row;
        const rawName = String(row.actor_name || row.banned_by || row.admin_name ||
          (row.client && row.client.name) || (row.initiator_client && row.initiator_client.name) || "").trim();
        const rawId = Number(row.actor_user_id || row.client_id ||
          (row.client && row.client.id) || (row.initiator_client && row.initiator_client.id) || 0) || 0;
        let moderator = (row.client && typeof row.client === "object") ? row.client
          : ((row.initiator_client && typeof row.initiator_client === "object") ? row.initiator_client : null);
        if (!moderator) moderator = deletedStaffStub(rawId, rawName);
        moderator = ensureClientShape(moderator, rawName || moderator.name, rawId || moderator.id);
        if (rawName && !isGenericStaffLabel(rawName)) moderator.name = rawName;
        row.client = moderator;
        row.initiator_client = Object.assign({}, moderator);
        row.moderator = Object.assign({}, moderator);
        row.moderator_client = Object.assign({}, moderator);
        row.banned_by_client = Object.assign({}, moderator);
        row.author = Object.assign({}, moderator);
        row.actor = Object.assign({}, moderator);
        row.client_id = Number(moderator.id) || rawId || row.client_id || 0;
        row.actor_user_id = rawId || row.actor_user_id || row.client_id;
        // BanView can use either the client object, the name, or the tag
        // depending on the version bundled by the browser.
        row.banned_by = moderator.name || rawName || "Сотрудник";
        row.admin_name = row.banned_by;
        row.actor_name = row.banned_by;
        row.client_tag = moderator.tag || "";
        row.banned_by_tag = moderator.tag || "";
        rememberStaffClient(moderator);
        return row;
      }
      if (Array.isArray(obj)) {
        const bans = obj.map(fillProfileBanModerator);
        return { bans: bans, data: bans, results: bans, items: bans, total: bans.length };
      }
      if (!obj || typeof obj !== "object") return { bans: [], data: [], results: [], items: [], total: 0 };
      const bans = Array.isArray(obj.bans) ? obj.bans : (Array.isArray(obj.data) ? obj.data : (Array.isArray(obj.results) ? obj.results : []));
      bans.forEach(fillProfileBanModerator);
      obj.bans = bans;
      obj.data = bans;
      obj.results = bans;
      obj.items = bans;
      if (obj.total == null) obj.total = bans.length;
      return obj;
    }
    if (href.includes("/ban/browse") || href.includes("/ban?") && href.includes("browse")) {
      const rows = Array.isArray(obj) ? obj : (obj && (obj.results || obj.data || obj.items));
      let list = Array.isArray(rows) ? rows : [];
      list.forEach((row) => {
        if (!row || typeof row !== "object") return;
        if (!Array.isArray(row.server_ids)) row.server_ids = [];
        if (!Array.isArray(row.proofs)) row.proofs = [];
        if (!row.player) row.player = row.target_player || { steam_id: String(row.steam_id || ""), steam_name: String(row.steam_name || row.steam_id || "") };
        if (!row.target_player) row.target_player = row.player;
        function fixBanPlayer(p) {
          if (!p || typeof p !== "object") return p;
          const st = String(p.status || "offline");
          p.status = st;
          p.online = st === "online" || st === "active" || st === "joining" || st === "queued" || st === "afk";
          p.is_online = !!p.online;
          if (p.steam_name != null) p.name = p.steam_name || p.name || p.steam_id;
          return p;
        }
        row.player = fixBanPlayer(row.player);
        row.target_player = fixBanPlayer(row.target_player);
        if (row.id == null && row.steam_id) row.id = row.steam_id;
        if (row.computed_is_active == null) row.computed_is_active = row.active !== false;
        if (row.steam_id != null) row.steam_id = String(row.steam_id);
        const actorName = String(row.actor_name || row.banned_by || row.admin_name || (row.client && row.client.name) || (row.initiator_client && row.initiator_client.name) || "").trim();
        const isSystem = isGenericStaffLabel(actorName) || /^(rustcheck|checkapp|system|plugin|project)$/i.test(actorName.replace(/\s+/g, ""));
        let displayName = (!isSystem && actorName) ? actorName : (row.actor_email ? String(row.actor_email).split("@")[0] : "") || (row.client && !isGenericStaffLabel(row.client.name) && row.client.name) || "";
        let fallbackStaff = null;
        try { fallbackStaff = staffProfile(); } catch (_) { fallbackStaff = null; }
        if (!displayName) displayName = (fallbackStaff && fallbackStaff.name) || "Сотрудник";
        if (!row.client || typeof row.client !== "object") {
          row.client = { id: row.client_id || row.actor_user_id || 0, name: displayName, tag: "", status: "online", avatar: PLACEHOLDER };
        }
        const realId = Number(row.client_id || row.actor_user_id || row.client.id || (fallbackStaff && fallbackStaff.id) || 0) || 0;
        const hashed = stableClientId(realId, displayName || row.client.name);
        row.client = ensureClientShape(row.client, displayName || row.client.name, realId || hashed);
        if (displayName && !isGenericStaffLabel(displayName)) row.client.name = displayName;
        row.client.id = realId || hashed;
        row.client_id = realId || hashed;
        if (displayName && !isGenericStaffLabel(displayName)) {
          row.actor_name = displayName;
          row.banned_by = displayName;
          row.admin_name = displayName;
        }
        if (!row.initiator_client || typeof row.initiator_client !== "object") row.initiator_client = Object.assign({}, row.client);
        if (row.client.name) row.initiator_client.name = row.client.name;
        if (!row.initiator_client.tag || isGenericStaffLabel(row.initiator_client.tag)) row.initiator_client.tag = row.client.tag;
        rememberStaffClient(row.client);
        ensureIdToString(row.client, row.client.id != null ? row.client.id : row.client_id);
        ensureIdToString(row, row.id);
      });
      try {
        const u = new URL(href, location.origin);
        let orig = Number(
          u.searchParams.get("project_id_original") ||
          u.searchParams.get("filter[project_id_original]") ||
          u.searchParams.get("projectIdOriginal") ||
          u.searchParams.get("project_original_id") ||
          0
        ) || 0;
        if (!orig) {
          u.searchParams.forEach(function (val, key) {
            if (!orig && /original|subscription|foreign/i.test(String(key))) orig = Number(val) || 0;
          });
        }
        if (orig) {
          const me = Number((window.__caProjectId || piniaCurrentProjectId() || 0)) || 0;
          if (orig !== me) {
            list = list.filter(function (row) {
              const pid = Number((row && (row.project_id_original || row.project_id || (row.project && row.project.id))) || 0) || 0;
              return pid === orig;
            });
          }
        }
        const wantPids = [];
        u.searchParams.forEach(function (val, key) {
          if (/^project_ids(\[|$)/.test(String(key)) || key === "project_ids[]") {
            String(val || "").split(",").forEach(function (part) {
              const n = Number(part) || 0;
              if (n && wantPids.indexOf(n) < 0) wantPids.push(n);
            });
          }
        });
        if (wantPids.length) {
          const me = Number((window.__caProjectId || piniaCurrentProjectId() || 0)) || 0;
          const onlyMe = wantPids.length === 1 && wantPids[0] === me;
          if (!onlyMe) {
            list = list.filter(function (row) {
              const pid = Number((row && (row.project_id || row.project_id_original || (row.project && row.project.id))) || 0) || 0;
              return pid && pid !== me && wantPids.indexOf(pid) >= 0;
            });
          }
        }
      } catch (_) {}
      if (Array.isArray(obj)) return { results: list, data: list, items: list, total: list.length };
      if (obj && typeof obj === "object") {
        obj.results = list;
        obj.data = obj.data || list;
        obj.items = obj.items || list;
        if (obj.total == null)         obj.total = list.length;
        return obj;
      }
      return { results: list, data: list, items: list, total: list.length };
    }
    if (href.includes("/find-by-ip")) {
      const rows = Array.isArray(obj) ? obj : (obj && (obj.results || obj.data || obj.items)) || [];
      (Array.isArray(rows) ? rows : []).forEach(function (row) {
        if (!row || typeof row !== "object") return;
        const result = (row.result && typeof row.result === "object") ? row.result : row;
        const details = (result.ip_details && typeof result.ip_details === "object") ? result.ip_details : {};
        if (details.pending) delete details.pending;
        const pip = String(row.ip || details.ip || "");
        const privateIp = !pip || /^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|::1|localhost|0\.0\.0\.0)/i.test(pip);
        let country = details.country_name || details.country || row.country_name || row.country || "";
        if (!country && privateIp) country = "Локальная сеть";
        const city = details.city || row.city || "";
        const provider = details.provider || details.isp || row.provider || "";
        let code = String(details.country_code || row.country_code || "").toLowerCase();
        if (code === "un" || code === "xx" || code === "unknown") code = "";
        const ipDetails = {
          ip: pip || details.ip || "",
          country: country,
          country_name: country,
          city: city,
          provider: provider,
          isp: provider,
          country_code: code
        };
        result.ip_details = ipDetails;
        result.computed_ip = ipDetails;
        if (row.result) row.result = result;
        else {
          row.ip_details = ipDetails;
          row.computed_ip = ipDetails;
        }
      });
      if (Array.isArray(obj)) return rows;
    }
    if (href.includes("/session-history") || href.includes("/ip-history")) {
      const rows = Array.isArray(obj) ? obj : (obj && (obj.results || obj.data || obj.items)) || [];
      (Array.isArray(rows) ? rows : []).forEach(function (row) {
        if (!row || typeof row !== "object") return;
        const name = String(row.server_name || (row.server && row.server.name) || "").trim();
        if (!row.server || typeof row.server !== "object") {
          row.server = { id: row.server_id || 0, name: name };
        }
        if (name) {
          row.server.name = name;
          row.server_name = name;
        }
        const details = (row.ip_details && typeof row.ip_details === "object") ? row.ip_details : {};
        if (details.pending) delete details.pending;
        if (row.pending) delete row.pending;
        const pip = String(row.ip || details.ip || "");
        const privateIp = !pip || /^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|::1|localhost|0\.0\.0\.0)/i.test(pip);
        let country = row.country_name || row.country || details.country_name || details.country || "";
        if (!country && privateIp) country = "Локальная сеть";
        const city = row.city || details.city || "";
        const provider = row.provider || row.isp || details.provider || details.isp || "";
        let code = String(details.country_code || row.country_code || "").toLowerCase();
        if (code === "un" || code === "xx" || code === "unknown") code = "";
        const ipDetails = {
          ip: row.ip || details.ip || "",
          country: country,
          country_name: country,
          city: city,
          provider: provider,
          isp: provider,
          country_code: code
        };
        row.ip_details = ipDetails;
        row.computed_ip = ipDetails;
        row.country = country;
        row.country_name = country;
        row.city = city;
        row.provider = provider;
      });
      if (Array.isArray(obj)) return rows;
      if (obj && typeof obj === "object") {
        obj.results = rows;
        obj.data = rows;
        obj.items = rows;
        if (obj.total == null) obj.total = rows.length;
      }
    }
    if (href.includes("/court-commands/history") || href.includes("/command-log") || href.includes("/command-history")) {
      const rows = Array.isArray(obj) ? obj : (obj && (obj.results || obj.data || obj.items)) || [];
      let list = (Array.isArray(rows) ? rows : []).map(function (row, i) {
        if (!row || typeof row !== "object") {
          return { id: i + 1, commands: [], members: [], players: [], team: [], actor_name: "" };
        }
        if (row.id == null) row.id = i + 1;
        if (!Array.isArray(row.commands)) row.commands = row.command ? [String(row.command)] : [];
        if (!Array.isArray(row.members)) row.members = [];
        if (!Array.isArray(row.players)) row.players = row.members;
        if (!Array.isArray(row.team)) row.team = row.members;
        if (!row.client || typeof row.client !== "object") {
          row.client = { id: row.actor_id || row.actor_user_id || 0, name: row.actor_name || "", status: "online", avatar: PLACEHOLDER };
        }
        return row;
      });
      try {
        const u = new URL(href, location.origin);
        const sid = String(u.searchParams.get("steam_id") || u.searchParams.get("target_steam_id") || u.searchParams.get("player_id") || "").trim();
        if (sid) {
          list = list.filter(function (row) {
            const rs = String((row && (row.target_steam_id || row.steam_id || (row.target_player && row.target_player.steam_id))) || "");
            return !rs || rs === sid;
          });
        }
      } catch (_) {}
      if (Array.isArray(obj)) return { results: list, data: list, items: list, total: list.length, limit: list.length + 1, done: true, has_more: false, finished: true };
      if (obj && typeof obj === "object") {
        obj.results = list;
        obj.data = list;
        obj.items = list;
        if (obj.total == null) obj.total = list.length;
        if (obj.limit == null) obj.limit = list.length + 1;
        obj.has_more = false;
        obj.done = true;
        obj.finished = true;
        return obj;
      }
      return { data: list, results: list, items: list, total: list.length, limit: list.length + 1, done: true, has_more: false, finished: true };
    }
    if (href.includes("/player-mute") && verb === "GET" && /\/player-mute(?:\/(?:read|browse))?(?:\?|$)/.test(href)) {
      const rows = Array.isArray(obj) ? obj : (obj && (obj.results || obj.data || obj.items));
      const list = (Array.isArray(rows) ? rows : []).filter(function (row) {
        return row && typeof row === "object" && row.id != null && String(row.steam_id || row.target_steam_id || "").trim();
      });
      list.forEach(function (row) {
        let me = null;
        try { me = staffProfile(); } catch (_) { me = null; }
        let name = String(row.actor_name || row.initiator_name || (row.client && row.client.name) || "").trim();
        if (!name || isGenericStaffLabel(name)) name = (me && me.name) || "Сотрудник";
        const actorId = Number(row.client_id || row.actor_user_id || (row.client && row.client.id) || (me && me.id) || 0) || 0;
        row.client = ensureClientShape(row.client, name, actorId || stableClientId(0, name));
        row.client.name = name;
        if (me && me.tag && (!row.client.tag || isGenericStaffLabel(row.client.tag))) row.client.tag = me.tag;
        row.client_id = Number(row.client.id) || actorId;
        row.initiator_client = Object.assign({}, row.client);
        row.actor_name = name;
        row.initiator_name = name;
        if (!row.target_player || typeof row.target_player !== "object") {
          const sid = String(row.target_steam_id || row.steam_id || "");
          row.target_player = { steam_id: sid, steam_name: sid, name: sid, avatar: PLACEHOLDER };
        }
        rememberStaffClient(row.client);
      });
      if (Array.isArray(obj)) return { results: list, data: list, items: list, total: list.length };
      if (obj && typeof obj === "object") {
        obj.results = list; obj.data = list; obj.items = list; obj.total = list.length;
        return obj;
      }
      return { results: list, data: list, items: list, total: list.length };
    }
    if (href.includes("/player-mute") && verb === "DELETE") {
      if (!obj || typeof obj !== "object") obj = {};
      obj.ok = true;
      obj.computed_is_active = false;
      obj.active = false;
      if (obj.deleted_at == null) obj.deleted_at = Date.now();
      setTimeout(function () { finishUnmuteUi(obj); }, 30);
      setTimeout(function () { finishUnmuteUi(obj); }, 200);
      return obj;
    }
    if ((href.includes("/player-mute") && (verb === "POST" || verb === "PUT")) && obj && typeof obj === "object") {
      if (obj.computed_is_active == null) obj.computed_is_active = true;
      if (obj.active == null) obj.active = true;
      // Live-inject mute announce that server wrote into chat
      setTimeout(function () {
        try {
          pollLive("/player-message?pagination_direction=from&pagination_timestamp=" + (Date.now() - 120000), "chat", "player-message");
        } catch (_) {}
      }, 80);
      return obj;
    }
  if (/\/audit(?:\/browse)?(?:[/?#]|$)/i.test(href)) {
      const rows = Array.isArray(obj) ? obj : (obj && (obj.results || obj.data || obj.items));
      const rawList = Array.isArray(rows) ? rows : [];
      const list = rawList.filter(function (row) {
        if (!row || typeof row !== "object") return false;
        const payload = (row.payload && typeof row.payload === "object") ? row.payload : {};
        const ev = String(row.event || payload.event || "");
        const typ = String(row.type || "");
        if (typ !== "ChatMessage" && typ !== "PlayerMessage" && ev !== "chat.direct" && ev !== "chat.global" && ev !== "player.message") return true;
        const fromSite = payload.from_site === true || payload.source === "site" || payload.source === "staff" || payload.author_type === "staff";
        if (fromSite) return true;
        const fromGame = payload.from_site === false || payload.author_type === "player" || /plugin|game|player/.test(String(payload.source || "")) || ev === "player.message";
        const actorUid = Number(row.actor_user_id || payload.actor_user_id || 0) || 0;
        if (fromGame) return false;
        if (actorUid <= 0 && (ev === "chat.direct" || ev === "chat.global" || ev === "player.message")) return false;
        return true;
      });
      list.forEach((row, i) => {
        if (!row || typeof row !== "object") return;
        if (row.id == null) row.id = i + 1;
        if (row.M_ID == null) row.M_ID = row.id;
        if (!row.meta || typeof row.meta !== "object") row.meta = {};
        if (row.type === "PlayerMessage") row.type = "ChatMessage";
        if (row.type === "PlayerBan" && (row.meta.ban_id == null || row.meta.ban_id === "")) {
          row.meta.ban_id = row.payload && row.payload.ban_id != null ? row.payload.ban_id : 0;
        }
        if (row.type === "BanEdit" && row.meta.action == null) row.meta.action = "unban";
        if (row.type === "ChatMessage" && row.meta.message == null) row.meta.message = "";
        const sid = String(row.meta.target_steam_id || row.meta.steam_id || "");
        let tname = String(row.meta.target_name || row.meta.player_name || row.meta.name || "").trim();
        if (sid && (!tname || tname === sid || /^\d{16,}$/.test(tname))) {
          // keep sid only as last resort; SPA prefers target_name when present
          tname = tname || sid;
        }
        if (tname) {
          row.meta.target_name = tname;
          row.meta.player_name = tname;
          row.meta.name = tname;
        }
        const frozenName = String((row.meta && (row.meta.actor_name || row.meta.client_name || row.meta.initiator_name)) || row.actor_name || row.actor || (row.client && row.client.name) || "").trim();
        if (!row.client || typeof row.client !== "object" || !row.client.id) {
          row.client = deletedStaffStub(
            row.client_id || row.initiator_client_id || (row.initiator_client && row.initiator_client.id),
            frozenName
          );
        }
        row.client = ensureClientShape(row.client, frozenName || row.client.name, row.client.id);
        if (row.client.M_ID == null) row.client.M_ID = row.client.id;
        if (frozenName && !isGenericStaffLabel(frozenName)) row.client.name = frozenName;
        row.initiator_client = Object.assign({}, row.client);
        if (row.initiator_client.M_ID == null) row.initiator_client.M_ID = row.client.M_ID;
        if (row.meta) {
          const shown = (!isGenericStaffLabel(row.client.name) && row.client.name) || (!isGenericStaffLabel(frozenName) && frozenName) || "";
          if (shown) {
            row.meta.actor_name = shown;
            row.meta.client_name = shown;
            row.meta.initiator_name = shown;
          }
        }
        if (row.client_id == null) row.client_id = row.client.id;
        if (row.initiator_client_id == null) row.initiator_client_id = row.client.id;
        rememberStaffClient(row.client);
        if (row.created_at == null) row.created_at = Date.now();
        // Skip unknown/empty types that render as gray skeleton bars
        if (!row.type || row.type === "info") row._drop = true;
        try { Object.defineProperty(row, "toString", { configurable: true, value: function () { return String(this.id); } }); } catch (_) {}
      });
      const clean = list.filter((row) => row && !row._drop && row.type && row.client && row.client.id != null && row.id != null);
      // A second audit request can occur before the project store settles and
      // incorrectly return an empty list. Do not let that erase the visible
      // audit timeline that was already loaded successfully.
      if (clean.length) {
        window.__checkappAuditLogs = clean.slice();
      } else if (Array.isArray(window.__checkappAuditLogs) && window.__checkappAuditLogs.length) {
        window.__checkappAuditLogs.forEach(function (row) {
          if (row && !row._drop) clean.push(row);
        });
      }
      if (Array.isArray(obj)) return { results: clean, data: clean, items: clean, total: clean.length };
      if (obj && typeof obj === "object" && !Array.isArray(obj)) {
        obj.results = clean;
        obj.data = clean;
        obj.items = clean;
        obj.total = clean.length;
        return obj;
      }
      return { results: clean, data: clean, items: clean, total: clean.length };
    }
    if (href.includes("/signage/browse") || (href.includes("/signage") && verb === "GET")) {
      const rows = Array.isArray(obj) ? obj : (obj && (obj.results || obj.data || obj.items));
      let list = (Array.isArray(rows) ? rows : []).map((row, i) => fixSignageRow(row, i)).filter(Boolean);
      list = dedupeSignages(list);
      if (Array.isArray(obj)) return { results: list, data: list, items: list, total: list.length };
      if (obj && typeof obj === "object") {
        obj.results = list;
        obj.data = list;
        obj.items = list;
        obj.total = Math.max(list.length, Number(obj.total) || 0);
        return obj;
      }
      return { results: list, data: list, items: list, total: list.length };
    }
    if (href.includes("/signage") && verb === "DELETE") {
      const req = parseSignageDeleteBody(typeof window !== "undefined" ? window.__checkappLastSignageDelete : null);
      const netId = String((obj && obj.net_id) || req.net_id || req.id || "");
      const serverId = Number((obj && obj.server_id) || req.server_id || 1);
      const ids = (obj && (obj.net_ids || obj.ids)) || req.net_ids || req.ids || (netId ? [netId] : []);
      const list = (Array.isArray(ids) ? ids : [ids]).map(String).filter(Boolean);
      // Hide destroyed cards immediately on plugin/site delete
      try {
        list.forEach(function (nid) {
          document.querySelectorAll("[data-net-id='" + nid + "'], img[src*='signage-" + nid + "']").forEach(function (el) {
            const card = el.closest("[class*='signage'], [class*='card'], article, .relative") || el.parentElement;
            if (card) card.style.display = "none";
          });
        });
        publishCentrifuge("signage", { destroyed: true, net_ids: list, destroyed_at: Date.now() });
        publishCentrifuge("signage-destroyed", { net_ids: list, destroyed_at: Date.now() });
      } catch (_) {}
      const hasDeletePayload = obj && typeof obj === "object" && !Array.isArray(obj)
        && (obj.net_id != null || obj.destroyed_at != null || (Array.isArray(obj.variants) && obj.variants.length));
      if (hasDeletePayload) {
        return fixSignageRow(Object.assign({ destroyed_at: obj.destroyed_at || Date.now() }, obj), 0);
      }
      return fixSignageRow({
        net_id: netId || (list[0] || ""),
        server_id: serverId,
        project_id: 1,
        destroyed_at: Date.now(),
        net_ids: list,
        variants: (netId || list[0]) ? [{
          id: 1,
          net_id: netId || list[0],
          url: "/uploads/signage-" + (netId || list[0]) + ".png",
          image: "/uploads/signage-" + (netId || list[0]) + ".png",
          created_at: Date.now()
        }] : []
      }, 0);
    }
    if (href.includes("/court-commands/") && (href.includes("/prepare") || href.includes("/execute"))) {
      if (obj && typeof obj === "object" && !Array.isArray(obj)) {
        if (obj.request && (obj.response === null || obj.response)) {
          const req = obj.request;
          if (!req.command || typeof req.command !== "object") req.command = {};
          if (!req.command.name) req.command.name = req.command.title || "kill";
          if (!req.command.group) req.command.group = req.command.category || "kill";
          if (!Array.isArray(req.command.commands)) {
            req.command.commands = Array.isArray(req.commands) ? req.commands : [];
          }
          if (req.server_id == null) req.server_id = 1;
          if (!req.player || typeof req.player !== "object") {
            req.player = { steam_id: String(req.steam_id || ""), steam_name: String(req.steam_id || "") };
          }
          return obj;
        }
        const sid = String(obj.steam_id || (obj.player && obj.player.steam_id) || "");
        const cmds = obj.commands || obj.preview || [];
        const cmdList = Array.isArray(cmds) ? cmds : [cmds];
        const cid = (href.match(/\/court-commands\/([^/]+)/) || [])[1] || "1";
        const name = String((obj.command && obj.command.name) || obj.name || "kill");
        const group = String((obj.command && obj.command.group) || obj.group || name);
        return {
          request: {
            command: {
              id: Number(cid) || cid,
              name: name,
              group: group,
              force_confirmation: true,
              allow_server_choose: true,
              commands: cmdList
            },
            steam_id: sid,
            server_id: Number(obj.server_id || 1) || 1,
            args: obj.args || {},
            player: obj.player || obj.target_player || { steam_id: sid, steam_name: sid },
            commands: cmdList
          },
          response: href.includes("/execute") ? { data: cmdList.map((cmd) => ({
            success: true, ok: true, command: cmd, data: "OK", result: "OK", output: "OK", response: "OK", steam_id: sid
          })) } : null
        };
      }
    }
    if (href.includes("/client/twofactor") || href.includes("/client/2fa") || href.includes("/auth/twofactor")) {
      if (obj && typeof obj === "object" && !Array.isArray(obj)) {
        const link = obj.link || obj.url || "";
        if (link && !obj.secret) {
          const m = link.match(/secret=([^&]+)/);
          if (m) obj.secret = m[1];
        }
        if (obj.secret && !obj.link) obj.link = "otpauth://totp/Rustcheck:local?secret=" + obj.secret + "&issuer=Rustcheck";
        if (obj.secret && !obj.url) obj.url = obj.link;
      }
    }
    if (href.includes("/players/kda") || href.includes("/player/kda")) {
      const rows = Array.isArray(obj) ? obj : (obj && (obj.data || obj.results || obj.items)) || [];
      const list = (Array.isArray(rows) ? rows : []).map(function (row) {
        if (!row || typeof row !== "object") return row;
        const sid = String(row.steam_id || row.id || "");
        let kills = row.kills;
        let deaths = row.deaths != null ? row.deaths : row.deathes;
        if (kills && typeof kills === "object") {
          deaths = deaths != null ? deaths : kills.deaths || kills.deathes;
          kills = kills.kills;
        }
        kills = Number(kills || 0) || 0;
        deaths = Number(deaths || 0) || 0;
        const kd = Number(row.kda != null ? row.kda : (row.kd != null ? row.kd : (row.kdr != null ? row.kdr : (deaths ? kills / deaths : kills)))) || 0;
        return {
          steam_id: sid,
          id: sid,
          kills: kills,
          deaths: deaths,
          deathes: deaths,
          kd: kd,
          kda: kd,
          kdr: kd
        };
      });
      return list;
    }
    if (href.includes("/reports")) {
      const rows = Array.isArray(obj) ? obj : (obj && (obj.results || obj.data || obj.items));
      const list = Array.isArray(rows) ? rows : [];
      const ensureToString = (obj, id) => {
        if (!obj || typeof obj !== "object") return obj;
        if (obj.id == null && id != null) obj.id = id;
        try {
          Object.defineProperty(obj, "toString", { configurable: true, value: function () { return String(this.id != null ? this.id : (this.steam_id || "")); } });
        } catch (_) {}
        return obj;
      };
      const fixPlayer = (p, sid) => {
        const row = (p && typeof p === "object") ? p : {};
        const id = String(row.steam_id || row.id || sid || "");
        row.steam_id = id;
        row.id = id || row.id;
        row.steam_name = row.steam_name || row.name || id || ".";
        row.name = row.name || row.steam_name;
        row.steam_avatar = row.steam_avatar || row.avatar || PLACEHOLDER;
        // Strip heavy nests — deep walkFix on these freezes Reports page
        delete row.entity;
        delete row.stats;
        delete row.team;
        delete row.player_team;
        row.team = [];
        if (!row.server || typeof row.server !== "object") row.server = { id: Number(row.server_id || 1) || 1, name: "" };
        if (row.server.id == null) row.server.id = Number(row.server_id || 1) || 1;
        ensureToString(row.server, row.server.id);
        if (!row.steam_data || typeof row.steam_data !== "object") row.steam_data = {};
        row.steam_data.steamid = String(row.steam_data.steamid || id);
        row.steam_data.personaname = row.steam_data.personaname || row.steam_name;
        row.steam_data.avatarfull = row.steam_data.avatarfull || row.steam_avatar;
        if (row.kd == null) row.kd = 0;
        if (row.kdr == null) row.kdr = row.kd;
        if (row.kills == null) row.kills = 0;
        if (row.deaths == null) row.deaths = 0;
        return ensureToString(row, id);
      };
      list.forEach((row, i) => {
        if (!row || typeof row !== "object") return;
        if (row.id == null) row.id = i + 1;
        if (!row.server || typeof row.server !== "object") row.server = {};
        if (row.server.id == null) row.server.id = row.server_id || 1;
        if (!row.server.name) row.server.name = row.server.hostname || row.server_name || "";
        if (!row.server.name || /^#\d+$/.test(String(row.server.name).trim()) || /unknown|неизвестн/i.test(String(row.server.name))) {
          row.server.name = row.server.hostname || row.server_name || window.__checkappLastServerName || "";
        }
        if (!row.server.name) {
          try {
            const cached = window.__checkappServersCache;
            const first = Array.isArray(cached) ? cached[0] : null;
            if (first && first.name) row.server.name = String(first.name);
          } catch (_) {}
        }
        if (!row.server.hostname) row.server.hostname = row.server.name;
        row.server_name = row.server.name;
        row.server.title = row.server.name;
        row.server.label = row.server.name;
        if (row.server_id == null) row.server_id = row.server.id;
        ensureToString(row.server, row.server.id);
        row.initiator_player = fixPlayer(row.initiator_player || row.initiator, row.initiator_steam_id);
        row.target_player = fixPlayer(row.target_player || row.target || row.player, row.target_steam_id);
        row.initiator = row.initiator_player;
        row.target = row.target_player;
        row.player = row.target_player;
        row.initiator_steam_id = String(row.initiator_steam_id || row.initiator_player.steam_id || "");
        row.target_steam_id = String(row.target_steam_id || row.target_player.steam_id || "");
        row.created_at = Number(row.created_at) || Date.now();
        row.kd = Number(row.kd != null ? row.kd : (row.target_player && row.target_player.kd) || 0) || 0;
        row.kdr = Number(row.kdr != null ? row.kdr : row.kd) || 0;
        row.kills = Number(row.kills != null ? row.kills : (row.target_player && row.target_player.kills) || 0) || 0;
        row.deaths = Number(row.deaths != null ? row.deaths : (row.target_player && row.target_player.deaths) || 0) || 0;
        row.total_reports = Number(row.total_reports || 1) || 1;
        row.total_reports_unique = Number(row.total_reports_unique || row.total_reports || 1) || 1;
        if (row.active_check_id == null || row.active_check_id === "") row.active_check_id = 0;
        row.reason = row.reason || row.type || "";
        if (!row.client || typeof row.client !== "object") {
          row.client = { id: 0, name: "", tag: "", avatar: PLACEHOLDER, status: "online" };
        } else {
          if (!row.client.avatar) row.client.avatar = PLACEHOLDER;
          if (row.client.id == null) row.client.id = 0;
        }
        ensureToString(row.client, row.client.id);
        if (Array.isArray(row.reports)) {
          row.reports.forEach(function (r) {
            if (!r || typeof r !== "object") return;
            delete r.reports;
            if (r.id == null) r.id = row.id;
            if (!r.server || typeof r.server !== "object") r.server = row.server;
            if (r.server && r.server.id == null) r.server.id = row.server_id || 1;
            ensureToString(r.server, r.server && r.server.id);
            r.initiator_player = fixPlayer(r.initiator_player || r.initiator, r.initiator_steam_id || row.initiator_steam_id);
            ensureToString(r, r.id);
          });
        }
        ensureToString(row, row.id);
      });
      if (Array.isArray(obj)) {
        return packedResults(list, { has_more: false, done: true, finished: true, last_page: 1, limit: list.length + 1, total: list.length });
      }
      if (obj && typeof obj === "object") {
        return packedResults(list, Object.assign({}, obj, {
          has_more: false,
          hasMore: false,
          done: true,
          finished: true,
          last_page: 1,
          limit: Math.max(Number(obj.limit || 0) || 0, list.length + 1),
          total: list.length,
          next_cursor: null,
          next_page: null,
          meta: { has_more: false, done: true, last_page: 1, next_page_url: null }
        }));
      }
    }
    if (href.includes("/player-alert") || href.includes("/alerts")) {
      const rows = Array.isArray(obj) ? obj : (obj && (obj.results || obj.data || obj.items));
      const allowed = {
        dug_up_stash: 1, join_with_ip_ban: 1, join_with_external_ban: 1, detect_ra_ban: 1,
        vpn_detected: 1, license_changed: 1, auto_kick: 1
      };
      const list = (Array.isArray(rows) ? rows : []).map((row, i) => {
        if (!row || typeof row !== "object") return null;
        let typ = String(row.type || "");
        // contact/custom_api → empty skeleton rows in SPA — drop them
        if (typ === "contact" || typ === "custom" || typ === "custom_api") {
          const related = (row.meta && (row.meta.related_players || row.meta.matches)) || row.matches || [];
          if (!Array.isArray(related) || !related.length || !(row.meta && row.meta.match)) return null;
        }
        if (!typ || !allowed[typ]) return null;
        row.type = typ;
        const player = row.player && typeof row.player === "object" ? row.player : null;
        if (!player || !player.steam_id) return null;
        const sid = String(player.steam_id || row.steam_id || "");
        let nick = String(player.steam_name || player.name || player.display_name || "").trim();
        if (!nick || nick === "." || nick === "-" || nick === "—" || nick === sid || (/^\d{16,}$/.test(nick))) {
          nick = String((row.meta && (row.meta.target_name || row.meta.player_name)) || "").trim();
        }
        if (!nick || nick === "." || nick === "-" || nick === "—" || nick === sid || (/^\d{16,}$/.test(nick))) {
          nick = "Игрок " + sid.slice(-4);
        }
        player.steam_id = sid;
        player.steam_name = nick;
        player.name = nick;
        player.display_name = nick;
        let av = player.steam_avatar || player.avatar || "";
        if (!av) {
          av = PLACEHOLDER;
        }
        player.steam_avatar = imageSrc(av) || PLACEHOLDER;
        player.avatar = player.steam_avatar;
        if (!player.steam_data || typeof player.steam_data !== "object") player.steam_data = {};
        player.steam_data.personaname = nick;
        player.steam_data.avatarfull = player.steam_avatar;
        player.steam_data.avatar = player.steam_avatar;
        if (player.status == null) player.status = "offline";
        player.online = player.status === "online" || player.status === "active" || player.status === "joining";
        player.is_online = !!player.online;
        row.player = player;
        row.steam_id = sid;
        if (row.id == null) row.id = i + 1;
        row.id = Number(row.id) || (i + 1);
        row.created_at = Number(row.created_at || Date.now());
        row.hide_in_table = !!row.hide_in_table;
        row.server_id = Number(row.server_id || 1) || 1;
        row.category = String(row.category || typ);
        if (!row.meta || typeof row.meta !== "object") row.meta = {};
        row.meta.steam_id = String(row.meta.steam_id || row.steam_id);
        row.meta.player = player;
        row.meta.ip = String(row.meta.ip || player.ip || "");
        // SPA: meta.bans.some(...) — must always be an array
        if (!Array.isArray(row.meta.bans)) row.meta.bans = [];
        if (typ === "detect_ra_ban") {
          if (!row.meta.bans.length) {
            row.meta.bans = [{
              id: row.id,
              steam_id: row.steam_id,
              reason: "Ban",
              comment: "Ban",
              auto_kicked: true,
              ban_ip: "",
              ban_ip_active: false,
              computed_is_active: true,
              active: true,
              client_id: 1,
              client: { id: 1, name: "", tag: "owner", status: "online", avatar: PLACEHOLDER },
              project_name: "",
              project: { id: 0, name: "" },
              steam_name: nick,
              player: player,
              target_player: player,
              url: "https://steamcommunity.com/profiles/" + sid,
              link: "https://steamcommunity.com/profiles/" + sid
            }];
          }
          row.meta.bans = row.meta.bans.map(function (b) {
            if (!b || typeof b !== "object") return b;
            b.reason = b.reason || "Ban";
            b.comment = b.comment || b.reason;
            b.client_id = b.client_id != null ? b.client_id : 1;
            if (!b.client || typeof b.client !== "object") {
              b.client = { id: b.client_id, name: "", tag: "owner", status: "online", avatar: PLACEHOLDER };
            }
            b.client.status = "online";
            b.client.online = true;
            b.client.is_online = true;
            b.client.avatar = imageSrc(b.client.avatar || PLACEHOLDER);
            b.project_name = b.project_name || "";
            if (!b.project) b.project = { id: 1, name: b.project_name };
            b.computed_is_active = b.computed_is_active !== false;
            b.active = b.active !== false;
            b.steam_name = b.steam_name || nick;
            // Keep ban.player light — full player ref freezes alerts via walkFix cycles
            b.player = {
              steam_id: sid,
              steam_name: nick,
              name: nick,
              steam_avatar: player.steam_avatar || PLACEHOLDER,
              status: player.status || "offline"
            };
            b.target_player = b.player;
            b.url = b.url || b.link || ("https://steamcommunity.com/profiles/" + sid);
            b.link = b.link || b.url;
            return b;
          });
          row.meta.ban = row.meta.bans[0];
          row.meta.ban_id = row.meta.ban_id || (row.meta.ban && row.meta.ban.id) || row.id;
        }
        if (typ === "auto_kick") {
          row.meta.target_steam_id = String(row.meta.target_steam_id || row.steam_id);
          row.meta.type = String(row.meta.type || row.meta.kind || "steam_closed");
          if (!row.meta.meta_value || typeof row.meta.meta_value !== "object") {
            row.meta.meta_value = { reason: row.meta.reason || "", real_name: nick };
          } else if (!row.meta.meta_value.real_name) {
            row.meta.meta_value.real_name = nick;
          }
          // steam_closed SPA template prints SteamID; use empty_profile path when possible so nick shows
          if (row.meta.type === "steam_closed" && nick && nick !== sid) {
            row.meta.type = "steam_empty_profile";
          }
        }
        if (typ === "vpn_detected" && (!row.meta.ip_details || typeof row.meta.ip_details !== "object")) {
          row.meta.ip_details = { country_name: "Local", city: "LAN", provider: "Private network", ip: row.meta.ip };
        }
        if ((typ === "join_with_ip_ban" || typ === "join_with_external_ban") && row.meta.ban_id == null) {
          row.meta.ban_id = row.id;
        }
        if (typ === "license_changed") {
          row.meta.previous = row.meta.previous || row.meta.old || row.meta.from || "—";
          row.meta.current = row.meta.current || row.meta.new || row.meta.to || "—";
          row.meta.old = row.meta.old || row.meta.previous;
          row.meta.new = row.meta.new || row.meta.current;
        }
        if (typ === "dug_up_stash") {
          row.meta.grid = row.meta.grid || row.meta.square || "";
          row.meta.square = row.meta.square || row.meta.grid || "";
          row.meta.position = row.meta.position || row.meta.grid || "";
          if (!String(row.meta.grid || row.meta.position || "").trim()) return null;
        }
        try { Object.defineProperty(row, "toString", { configurable: true, value: function () { return String(this.id); } }); } catch (_) {}
        return row;
      }).filter(Boolean);
      if (Array.isArray(obj)) return { results: list, data: list, items: list, total: list.length };
      if (obj && typeof obj === "object") {
        obj.results = list;
        obj.data = list;
        obj.items = list;
        obj.total = list.length;
        obj.count = list.length;
        return obj;
      }
      return { results: list, data: list, items: list, total: list.length };
    }
    if (href.includes("/player-premium/verify")) {
      const base = obj && typeof obj === "object" && !Array.isArray(obj) ? obj : {};
      return Object.assign({ exists: false, premium: false, is_premium: false, verified: false, active: false }, base);
    }
    if (href.includes("/server") && !href.includes("server-chat") && !href.includes("server-rep") && !href.includes("servers_limit")) {
      if (Array.isArray(obj)) {
        const list = obj.map(fixServer);
        if (href.endsWith("/server") || /\/server(?:\?|$)/.test(href)) {
          window.__checkappServersCount = countPairedServers(list);
          window.__checkappServersCache = list;
          if (list[0] && list[0].name) window.__checkappLastServerName = String(list[0].name);
        }
        return list;
      }
      if (obj && typeof obj === "object") {
        if (Array.isArray(obj.servers)) {
          obj.servers = obj.servers.map(fixServer);
          window.__checkappServersCount = countPairedServers(obj.servers);
        }
        if (obj.server) obj.server = fixServer(obj.server);
        else if ("hostname" in obj || "paired" in obj || "slots" in obj) {
          const one = fixServer(obj);
          if (one && one.paired) window.__checkappServersCount = 1;
          return one;
        }
      }
    }
    if (/\/server\/pair/.test(href) && obj && typeof obj === "object") {
      if (obj.error === "server-limit-exceeded" || obj.message === "server-limit-exceeded") {
        obj.error = "server-limit-exceeded";
        obj.message = "server-limit-exceeded";
        if (window.__checkappShowServerLimitToast) window.__checkappShowServerLimitToast();
      }
    }
    if ((href.endsWith("/court") || href.includes("/court?")) && obj && typeof obj === "object" && !Array.isArray(obj)) {
      if (Array.isArray(obj.servers)) obj.servers = obj.servers.map(fixServer);
      if (obj.project_id) window.__caProjectId = Number(obj.project_id) || window.__caProjectId;
      const defaults = {
        ban_reasons: ["Чит", "Макрос", "Багоюз", "Нарушение правил (by {client_tag})", "Мультиаккаунт", "1+", "2+", "3+"],
        ban_mass_reasons: ["Игра с читером", "Тиммейт ({main_steam_id})", "1+", "2+", "3+"],
        check_verdicts: ["Чит", "Макрос", "Багоюз", "Покинул сервер во время проверки", "Игнорирование проверки", "Отказ от проверки", "По результатам проверки"],
        report_reasons: [],
        mute_reasons: [],
        delete_reports_after_ban: false,
        delete_reports_after_check: false,
        ignore_reports_after_days: 7,
        ignore_reports_after_check: 0,
        check_start_min_report: 0,
        check_start_broadcast: false,
        check_finished_clear_broadcast: false,
        announce_reporters_after_action: false,
        ban_broadcast: true,
        ban_limit_enabled: false,
        ban_limit_amount_per_interval: 5,
        ban_limit_interval_minutes: 60
      };
      obj.options = Object.assign({}, defaults, obj.options || {});
      obj.is_banned = !!(obj.is_banned || obj.blocked || projectIsBlockedNow());
      if (!obj.client || typeof obj.client !== "object") {
        try { obj.client = ensureClientShape(staffProfile(), "", 0); } catch (_) {
          obj.client = { id: 0, name: "", tag: "", avatar: PLACEHOLDER, status: "online" };
        }
      } else if (!obj.client.avatar) {
        obj.client.avatar = PLACEHOLDER;
      }
      return obj;
    }
    if (href.includes("court-api") && !href.includes("court-api/")) {
      const routes = ["/public/checks", "/public/bans", "/public/servers"];
      const base = obj && typeof obj === "object" && !Array.isArray(obj) ? obj : {};
      return Object.assign({
        enabled: false,
        api_enabled: false,
        token: "",
        api_key: "",
        public_api_key: "",
        routes: [],
        api_consumers: [],
        public_api_routes: {},
        public_api_routes_available: routes
      }, base, {
        api_consumers: Array.isArray(base.api_consumers) ? base.api_consumers : [],
        public_api_routes_available: Array.isArray(base.public_api_routes_available) ? base.public_api_routes_available : routes,
        public_api_routes: base.public_api_routes && typeof base.public_api_routes === "object" ? base.public_api_routes : {}
      });
    }
    if (href.includes("court-autokick") || /\/auto-kick(?:\?|$)/.test(href)) {
      const types = ["afk","ip_bad_provider","ip_country","ip_vpn","name_contains","steam_closed","steam_empty_profile","steam_gameban","steam_hours","steam_signed_days","steam_vac","game_language"];
      const defaults = {
        afk: { max_minutes: 30, target: "all", reason: "", list: [] },
        ip_bad_provider: { list: [], target: "all", reason: "" },
        ip_country: { list: [], mode: "blacklist", target: "all", reason: "" },
        ip_vpn: { include_providers: [], exclude_providers: [], list: [], target: "all", reason: "" },
        name_contains: { list: [], steam_id_name: false, target: "all", reason: "" },
        steam_closed: { target: "all", reason: "", list: [] },
        steam_empty_profile: { target: "all", reason: "", list: [] },
        steam_gameban: { min_bans: 1, target: "all", reason: "", list: [] },
        steam_hours: { kick_with_hidden_ga: true, kick_if_hidden_ga: true, use_spacewars_hours: false, min_hours: 50, target: "all", reason: "", list: [] },
        steam_signed_days: { min_days: 7, kick_with_hidden_signed_at: true, kick_if_hidden_profile: true, target: "all", reason: "", list: [] },
        steam_vac: { min_bans: 1, target: "all", reason: "", list: [] },
        game_language: { list: [], target: "all", reason: "" }
      };
      const raw = Array.isArray(obj) ? obj : (obj && Array.isArray(obj.data) ? obj.data : []);
      const byType = {};
      raw.forEach((row) => { if (row && row.type) byType[row.type] = row; });
      return types.map((type, idx) => {
        const prev = byType[type] || {};
        const options = Object.assign({}, defaults[type] || { target: "all", list: [] }, prev.options || {}, prev.data || {});
        if (options.kick_if_hidden_ga == null && options.kick_with_hidden_ga != null) options.kick_if_hidden_ga = options.kick_with_hidden_ga;
        if (options.kick_if_hidden_profile == null && options.kick_with_hidden_signed_at != null) options.kick_if_hidden_profile = options.kick_with_hidden_signed_at;
        if (!options.target) options.target = prev.target || "all";
        if (!Array.isArray(options.list)) options.list = [];
        if (!Array.isArray(options.include_providers)) options.include_providers = [];
        if (!Array.isArray(options.exclude_providers)) options.exclude_providers = [];
        const metaKeys = {
          steam_empty_profile: [],
          steam_closed: [],
          steam_signed_days: ["min_days", "kick_with_hidden_signed_at"],
          steam_hours: ["kick_with_hidden_ga", "use_spacewars_hours", "min_hours"],
          steam_vac: ["min_bans"],
          steam_gameban: ["min_bans"],
          ip_vpn: ["include_providers", "exclude_providers"],
          ip_bad_provider: ["list"],
          ip_country: ["list", "mode"],
          name_contains: ["list", "steam_id_name"],
          game_language: ["list"],
          afk: ["max_minutes"]
        };
        const prevMeta = prev.meta && typeof prev.meta === "object" ? prev.meta : {};
        const meta = { translations: (prevMeta.translations && typeof prevMeta.translations === "object") ? prevMeta.translations : { default: { en: "", ru: "" } } };
        (metaKeys[type] || []).forEach(function (key) {
          meta[key] = prevMeta[key] != null ? prevMeta[key] : options[key];
        });
        const id = Number(prev.id) > 0 ? Number(prev.id) : (idx + 1);
        const row = Object.assign({
          type: type,
          name: type,
          active: false,
          enabled: false,
          options: {},
          data: {},
          localize: {},
          id: id,
          M_ID: id
        }, prev, {
          id: id,
          M_ID: id,
          type: type,
          name: type,
          active: (prev.active != null) ? !!prev.active : !!prev.enabled,
          enabled: (prev.enabled != null) ? !!prev.enabled : !!prev.active,
          target: options.target || "all",
          meta: meta,
          options: options,
          data: options,
          localize: prev.localize || {}
        });
        try { Object.defineProperty(row, "toString", { configurable: true, value: function () { return String(this.id); } }); } catch (_) {}
        return row;
      });
    }
    if (
      href.includes("ban-sync/available") ||
      href.includes("available-subscriptions")
    ) {
      let list = [];
      if (Array.isArray(obj)) list = obj;
      else if (obj && Array.isArray(obj.data)) list = obj.data;
      else if (obj && Array.isArray(obj.results)) list = obj.results;
      else if (obj && Array.isArray(obj.items)) list = obj.items;
      list = (Array.isArray(list) ? list : []).map(function (row) {
        if (!row || typeof row !== "object") return row;
        const pid = Number(row.project_id_original || row.project_id || row.id || 0) || 0;
        const orig = (row.project_original && typeof row.project_original === "object") ? row.project_original : {};
        orig.id = orig.id != null ? orig.id : pid;
        orig.name = orig.name || row.name || row.title || "";
        orig.avatar = orig.avatar || row.avatar || ("https://s3.rustapp.io/assets/default-avatar.jpeg?project=" + pid);
        if (!orig.avatar || /avatar-project\/1695419722879-43ad94311081cd8185649d49/.test(String(orig.avatar))) {
          orig.avatar = "https://s3.rustapp.io/assets/default-avatar.jpeg?project=" + pid;
        }
        orig.verified = !!orig.verified;
        orig.domain = orig.domain || row.domain || "";
        row.project_original = orig;
        row.project = row.project || orig;
        row.project_id_original = pid;
        row.id = row.id != null ? row.id : pid;
        if (row.total_bans == null) row.total_bans = Number(row.bans || row.bans_count || row.total || 0) || 0;
        if (row.followers == null) row.followers = Number(row.followers || 0) || 0;
        if (row.no_license_percent == null) row.no_license_percent = Number(row.no_license_percent || 0) || 0;
        if (row.share_details == null) row.share_details = row.share_details !== false;
        if (row.share_moders == null) row.share_moders = !!row.share_moders;
        return row;
      }).filter(function (row) {
        return row && row.project_original && row.project_id_original;
      });
      // SPA: const c = await s.get(...); r.value = [...c.data]
      // axios response.data must be the array itself.
      try { Object.defineProperty(list, "data", { value: list, enumerable: false, configurable: true }); } catch (_) { list.data = list; }
      return list;
    }
    if (href.includes("ban-sync/subscriptions")) {
      let list = [];
      if (Array.isArray(obj)) list = obj;
      else if (obj && Array.isArray(obj.data)) list = obj.data;
      else if (obj && Array.isArray(obj.results)) list = obj.results;
      else if (obj && Array.isArray(obj.items)) list = obj.items;
      list = (Array.isArray(list) ? list : []).map(function (row) {
        if (!row || typeof row !== "object") return row;
        const pid = Number(row.project_id_original || row.project_id || row.id || 0) || 0;
        const orig = (row.project_original && typeof row.project_original === "object") ? row.project_original : {};
        orig.id = orig.id != null ? orig.id : pid;
        orig.name = orig.name || row.name || row.title || "";
        orig.avatar = orig.avatar || row.avatar || PLACEHOLDER;
        if (!orig.avatar || /avatar-project\/1695419722879-43ad94311081cd8185649d49/.test(String(orig.avatar))) {
          orig.avatar = "https://s3.rustapp.io/assets/default-avatar.jpeg?project=" + pid;
        }
        orig.verified = !!orig.verified;
        orig.domain = orig.domain || row.domain || "";
        row.project_original = orig;
        row.project = row.project || orig;
        row.project_id_original = pid;
        row.id = row.id != null ? row.id : pid;
        if (row.is_public == null) row.is_public = true;
        if (row.you_are_public == null) row.you_are_public = true;
        return row;
      }).filter(function (row) {
        return row && row.project_original && row.project_id_original;
      });
      // Pinia: s.value = e.data  — e.data must be the array (axios body).
      try { Object.defineProperty(list, "data", { value: list, enumerable: false, configurable: true }); } catch (_) { list.data = list; }
      return list;
    }
    if (href.includes("ban-sync/followers")) {
      let list = [];
      if (Array.isArray(obj)) list = obj;
      else if (obj && Array.isArray(obj.data)) list = obj.data;
      else if (obj && Array.isArray(obj.results)) list = obj.results;
      else if (obj && Array.isArray(obj.items)) list = obj.items;
      list = (Array.isArray(list) ? list : []).map(function (row) {
        if (!row || typeof row !== "object") return row;
        const pid = Number(row.project_id_original || row.project_id || row.id || 0) || 0;
        const orig = (row.project_original && typeof row.project_original === "object") ? row.project_original : {};
        orig.id = orig.id != null ? orig.id : pid;
        orig.name = orig.name || row.name || row.title || "";
        orig.avatar = orig.avatar || row.avatar || PLACEHOLDER;
        if (!orig.avatar || /avatar-project\/1695419722879-43ad94311081cd8185649d49/.test(String(orig.avatar))) {
          orig.avatar = "https://s3.rustapp.io/assets/default-avatar.jpeg?project=" + pid;
        }
        orig.verified = !!orig.verified;
        orig.domain = orig.domain || row.domain || "";
        row.project_original = orig;
        row.project = row.project || orig;
        row.project_id_original = pid;
        row.id = row.id != null ? row.id : pid;
        if (row.is_public == null) row.is_public = true;
        if (row.you_are_public == null) row.you_are_public = true;
        return row;
      }).filter(function (row) {
        return row && row.project_original && row.project_id_original;
      });
      try { Object.defineProperty(list, "data", { value: list, enumerable: false, configurable: true }); } catch (_) { list.data = list; }
      return list;
    }
    if (
      href.includes("ban-sync/browse")
    ) {
      let list = [];
      if (Array.isArray(obj)) list = obj;
      else if (obj && Array.isArray(obj.data)) list = obj.data;
      else if (obj && Array.isArray(obj.results)) list = obj.results;
      else if (obj && Array.isArray(obj.items)) list = obj.items;
      list = (Array.isArray(list) ? list : []).map(function (row) {
        if (!row || typeof row !== "object") return row;
        const pid = Number(row.project_id_original || row.project_id || row.id || 0) || 0;
        const orig = (row.project_original && typeof row.project_original === "object") ? row.project_original : {};
        orig.id = orig.id != null ? orig.id : pid;
        orig.name = orig.name || row.name || row.title || "";
        orig.avatar = orig.avatar || row.avatar || PLACEHOLDER;
        if (!orig.avatar || /avatar-project\/1695419722879-43ad94311081cd8185649d49/.test(String(orig.avatar))) {
          orig.avatar = "https://s3.rustapp.io/assets/default-avatar.jpeg?project=" + pid;
        }
        orig.verified = !!orig.verified;
        orig.domain = orig.domain || row.domain || "";
        row.project_original = orig;
        row.project = row.project || orig;
        row.project_id_original = pid;
        row.id = row.id != null ? row.id : pid;
        if (row.total_bans == null) row.total_bans = Number(row.bans || row.bans_count || row.total || 0) || 0;
        if (row.followers == null) row.followers = Number(row.followers || 0) || 0;
        if (row.no_license_percent == null) row.no_license_percent = Number(row.no_license_percent || 0) || 0;
        if (row.share_details == null) row.share_details = row.share_details !== false;
        if (row.share_moders == null) row.share_moders = !!row.share_moders;
        return row;
      }).filter(function (row) {
        return row && row.project_original && row.project_id_original;
      });
      const packed = (obj && typeof obj === "object" && !Array.isArray(obj)) ? obj : {};
      packed.data = list;
      packed.results = list;
      packed.items = list;
      packed.total = list.length;
      if (packed.is_public == null) packed.is_public = !!packed.share;
      if (packed.share == null) packed.share = !!packed.is_public;
      return packed;
    }
    if (href.includes("/court-commands/preset") && verb === "GET") {
      let list = [];
      if (Array.isArray(obj)) list = obj;
      else if (obj && Array.isArray(obj.data)) list = obj.data;
      else if (obj && Array.isArray(obj.results)) list = obj.results;
      if (!list.length) {
        list = [
          {id:1,name:"Kick",group:"Vanilla",category:"moderation",access:"yellow",commands:["kick {steamid} {reason}"]},
          {id:2,name:"Kill",group:"Vanilla",category:"moderation",access:"red",commands:["kill {steamid}"]},
          {id:3,name:"Mute",group:"Vanilla",category:"moderation",access:"yellow",commands:["mute {steamid} 60m {reason}"]},
          {id:4,name:"Unmute",group:"Vanilla",category:"moderation",access:"green",commands:["unmute {steamid}"]},
          {id:5,name:"Teleport to player",group:"Vanilla",category:"player",access:"green",commands:["teleport {steamid}"]},
          {id:6,name:"Bring player",group:"Vanilla",category:"player",access:"yellow",commands:["teleport {steamid} {me}"]},
          {id:7,name:"Heal",group:"Vanilla",category:"player",access:"green",commands:["heal {steamid}"]},
          {id:8,name:"Spectate",group:"Vanilla",category:"player",access:"green",commands:["spectate {steamid}"]},
          {id:9,name:"Freeze",group:"Admin",category:"moderation",access:"yellow",commands:["freeze {steamid}"]},
          {id:10,name:"Unfreeze",group:"Admin",category:"moderation",access:"green",commands:["unfreeze {steamid}"]},
          {id:11,name:"Give item",group:"Admin",category:"player",access:"yellow",commands:["inventory.giveto {steamid} rifle.ak 1"]},
          {id:12,name:"Reset metabolism",group:"Admin",category:"player",access:"green",commands:["resetmetabolis {steamid}"]}
        ];
      }
      try { Object.defineProperty(list, "data", { value: list, enumerable: false, configurable: true }); } catch (_) { list.data = list; }
      return list;
    }
    if (href.includes("/court-commands") && verb === "GET" && !href.includes("/execute") && !href.includes("/history") && !href.includes("/preset") && !href.includes("/prepare")) {
      if (Array.isArray(obj)) return obj;
      if (obj && Array.isArray(obj.data)) return obj.data;
      return [];
    }
    if ((href.endsWith("/webhook") || href.includes("/webhook?")) && verb === "GET") {
      if (Array.isArray(obj)) return obj;
      if (obj && Array.isArray(obj.data)) return obj.data;
      return obj;
    }
    if (href.includes("/court-discord") || href.includes("/court/discord")) {
      const types = ["Report", "Check", "Ban", "CheckappBan", "ManyBans"];
      let raw = Array.isArray(obj) ? obj : (obj && (obj.data || obj.results || obj.items) || []);
      if (!Array.isArray(raw) && obj && typeof obj === "object" && (obj.type || obj.kind || obj.active != null || obj.webhook)) {
        raw = [obj];
      }
      const byType = {};
      (Array.isArray(raw) ? raw : []).forEach((row) => {
        if (!row) return;
        const t = String(row.type || row.kind || "");
        types.forEach(function (name) {
          if (name.toLowerCase() === t.toLowerCase()) byType[name] = row;
        });
        if (t) byType[t] = row;
      });
      const mapped = types.map((type, idx) => {
        const prev = byType[type] || {};
        const data = Object.assign({
          mention: "",
          tag: "",
          role: "",
          ban_amount: 10,
          min_amount: 5,
          // Discord Check embed options used by SPA wizard
          check_started: prev.data && prev.data.check_started != null ? !!prev.data.check_started : true,
          check_finished: prev.data && prev.data.check_finished != null ? !!prev.data.check_finished : true,
          started: prev.data && (prev.data.started != null ? !!prev.data.started : prev.data.check_started != null ? !!prev.data.check_started : true),
          finished: prev.data && (prev.data.finished != null ? !!prev.data.finished : prev.data.check_finished != null ? !!prev.data.check_finished : true),
          minimalist: !!(prev.data && (prev.data.minimalist || prev.data.minimal)),
          minimal: !!(prev.data && (prev.data.minimalist || prev.data.minimal))
        }, (prev.data && typeof prev.data === "object") ? prev.data : {}, (prev.options && typeof prev.options === "object") ? prev.options : {});
        data.ban_amount = Number(data.ban_amount || 10);
        data.min_amount = Number(data.min_amount || 5);
        if (!Number.isFinite(data.ban_amount)) data.ban_amount = 10;
        if (!Number.isFinite(data.min_amount)) data.min_amount = 5;
        if (data.check_started == null) data.check_started = true;
        if (data.check_finished == null) data.check_finished = true;
        if (data.started == null) data.started = !!data.check_started;
        if (data.finished == null) data.finished = !!data.check_finished;
        const id = Number(prev.id) > 0 ? Number(prev.id) : (idx + 1);
        let active = (prev.active != null) ? !!prev.active : !!prev.enabled;
        return {
          type: type,
          kind: type,
          id: id,
          M_ID: id,
          m_id: id,
          active: active,
          enabled: active,
          webhook: String(prev.webhook || prev.url || ""),
          url: String(prev.webhook || prev.url || ""),
          language: prev.language || "ru",
          data: data,
          options: data
        };
      });
      return mapped;
    }
    if (href.includes("/utils/can-project-create")) {
      // Trust server when auth is present; only fall back to local counter if server omitted fields.
      if (obj && typeof obj === "object" && !Array.isArray(obj) && ("can" in obj || "allowed" in obj || "ok" in obj)) {
        const can = obj.can !== false && obj.allowed !== false && obj.ok !== false;
        if (typeof window.__checkappProjectCount !== "number" && obj.count != null) {
          window.__checkappProjectCount = Number(obj.count) || 0;
        }
        return {
          can: can,
          allowed: can,
          ok: can,
          limit: Number(obj.limit != null ? obj.limit : 2),
          count: Number(obj.count != null ? obj.count : (window.__checkappProjectCount || 0)),
          used: Number(obj.used != null ? obj.used : (obj.count != null ? obj.count : (window.__checkappProjectCount || 0)))
        };
      }
      const tier = accountTierSlug();
      const limit = projectCreateLimit(tier);
      const used = typeof window.__checkappProjectCount === "number" ? window.__checkappProjectCount : 0;
      const ok = used < limit;
      return { can: ok, allowed: ok, ok: ok, limit: limit, count: used, used: used };
    }
    if (verb === "GET" && /\/project(?:\?|$)/.test(href) && !/\/project\//.test(href)) {
      const list = Array.isArray(obj) ? obj : (obj && (obj.results || obj.data || obj.items)) || [];
      if (Array.isArray(list)) window.__checkappProjectCount = list.length;
    }
    if (verb === "POST" && /\/project(?:\?|$)/.test(href) && !/\/project\//.test(href) && obj && typeof obj === "object") {
      if (obj.error === "project-limit-exceeded" || obj.message === "project-limit-exceeded" || obj.message === "Project limit exceeded") {
        obj.message = "Project limit exceeded";
        obj.error = "project-limit-exceeded";
        showProjectLimitNativeToast();
      } else if (obj.id != null) {
        window.__checkappProjectCount = Number(window.__checkappProjectCount || 0) + 1;
      }
    }
    if (href.includes("/utils/tariff") || /\/tariff/.test(href)) {
      if (obj && typeof obj === "object" && !Array.isArray(obj) && obj.ok === false) return obj;
    }
    if (href.includes("/utils/tariff")) {
      const empty = {
        tariffs: defaultTariffs(),
        plans: defaultTariffs(),
        data: defaultTariffs(),
        results: defaultTariffs(),
        items: defaultTariffs(),
        tariff: normalizeTariffPlan({ tier: "base", month_price: 0, servers_limit: 2, players_limit: 100000, is_current: true }),
        tier_features: {}
      };
      ensureTierFeatures(empty);
      if (Array.isArray(obj)) {
        empty.tariffs = obj.map(normalizeTariffPlan);
        empty.plans = empty.tariffs;
        empty.data = empty.tariffs;
        empty.results = empty.tariffs;
        empty.items = empty.tariffs;
        empty.tariff = empty.tariffs.find(function (p) { return p && p.is_current; }) || empty.tariffs[0];
        return empty;
      }
      if (obj && typeof obj === "object") {
        return normalizeTariffPayload(obj);
      }
      return empty;
    }
    if (/\/tariff\/?(\?|$)/.test(href) && !href.includes("/utils/tariff")) {
      if (obj && typeof obj === "object") {
        return normalizeTariffPayload(obj);
      }
    }
    if (/\/tariff\/discard-trial/i.test(href) && obj && typeof obj === "object") {
      obj.is_trial = false;
      obj.is_paid = false;
      obj.frozen = true;
      obj.is_frozen = true;
      obj.renew_failed = true;
      obj.trial_ends_at = 0;
      obj.trial_ends = 0;
      obj.paid_until = 0;
      obj.active_until = 0;
      obj.subscription_ends_at = 0;
      obj.discarded = true;
      return normalizeTariffPayload(obj);
    }
    if (verb === "GET" && /\/players\/[^/]+\/checks(?:\?|$)/.test(href)) {
      const checkRows = Array.isArray(obj) ? obj : (obj && (obj.results || obj.data || obj.items)) || [];
      const checkList = Array.isArray(checkRows) ? checkRows : [];
      const extra = (obj && typeof obj === "object" && !Array.isArray(obj)) ? obj : {};
      if (extra.limit == null) extra.limit = 10;
      if (extra.total == null) extra.total = checkList.length;
      return packedResults(checkList, extra);
    }
    if (href.includes("/check") && !/\/activity|notice-state|freeze-state/.test(href)) {
      if (verb === "POST" && /\/check\/?(\?|$)/.test(href.replace(location.origin, ""))) {
        return asCheckCreateId(obj);
      }
      if (href.includes("/check/browse-anonymous")) {
        const anonRows = Array.isArray(obj) ? obj
          : (obj && (obj.checks || obj.results || obj.data || obj.items)) || [];
        let anonList = Array.isArray(anonRows) ? anonRows : [];
        const me = Number((window.__caProjectId || piniaCurrentProjectId() || 0)) || 0;
        if (me) {
          anonList = anonList.filter(function (row) {
            const pid = Number((row && (row.project_id || row.projectId || (row.project && row.project.id))) || 0) || 0;
            return pid && pid !== me;
          });
        }
        return {
          checks: anonList,
          results: anonList,
          data: anonList,
          items: anonList,
          total: anonList.length
        };
      }
      const applyCheck = (row) => {
        if (!row || typeof row !== "object") return;
        if (row.status === "FinishedClear" && (!row.verdict || /finishedclear|clear/i.test(String(row.verdict)))) row.verdict = "Чист";
        if (row.status === "FinishedBan" && (!row.verdict || /finishedban|ban/i.test(String(row.verdict)))) row.verdict = "Бан";
        if (row.status === "Canceled" && (!row.verdict || /cancel/i.test(String(row.verdict)))) row.verdict = "Отмена";
        if (row.status === "Pending") row.verdict = row.verdict && !/finished/i.test(String(row.verdict)) ? row.verdict : "На проверке";
        if (!row.verdict_label) row.verdict_label = row.verdict;
        if (!row.status_label) row.status_label = row.verdict;
        if (!row.result) row.result = row.verdict;
        const checker = row.checker || row.client || row.moderator || {};
        const frozenId = checker.id || row.checker_id || row.initiator_client_id || row.client_id;
        if (row.client_id == null && frozenId) row.client_id = frozenId;
        if (row.checker_id == null && frozenId) row.checker_id = frozenId;
        if (row.initiator_client_id == null && frozenId) row.initiator_client_id = frozenId;
        if (checker && checker.name) {
          row.checker = checker;
          if (!row.initiator_client || typeof row.initiator_client !== "object") row.initiator_client = checker;
          else if (!row.initiator_client.name) row.initiator_client.name = checker.name;
        }
        if (row.initiator_client && row.initiator_client.id) {
          rememberStaffClient(row.initiator_client);
        }
        if (row.checker && row.checker.id) {
          rememberStaffClient(row.checker);
        }
        const player = row.player || row.suspect || row.target_player;
        if (player && typeof player === "object") {
          if (!Array.isArray(player.team)) player.team = [];
          if (!player.steam_id || player.steam_id === "0") player.steam_id = row.steam_id || window.__caCheckSteam || "";
          if (player.steam_id === "0") player.steam_id = "";
          if (!player.steam_name || player.steam_name === "." || player.steam_name === "0") {
            player.steam_name = player.name || player.steam_id || window.__caCheckName || "";
          }
          row.player = player;
          row.suspect = row.suspect || player;
          row.target_player = row.target_player || player;
          const finished = !!(row.finished_at || /cancel|finished|clear|ban/i.test(String(row.status || "")));
          const live = !finished && /active|pending|started|check/i.test(String(row.status || "Pending"));
          if (row.id && player.steam_id) {
            rememberActiveCheck(player.steam_id, row.id, !live);
            if (live) {
              player.active_check_id = Number(row.id) || 0;
              player.activeCheckId = player.active_check_id;
              player.is_checking = true;
              player.checking = true;
            }
          }
        }
        if (!Array.isArray(row.team)) row.team = (player && player.team) || [];
        if (!Array.isArray(row.suspect_team)) row.suspect_team = [];
        if (!Array.isArray(row.team_steam_ids)) row.team_steam_ids = row.suspect_team.slice();
        if (!Array.isArray(row.activity)) row.activity = row.activity || [];
        if (!Array.isArray(row.reports)) row.reports = row.reports || [];
        try {
          Object.defineProperty(row, "toString", { configurable: true, value: function () { return String(this.id); } });
          Object.defineProperty(row, "valueOf", { configurable: true, value: function () { return this.id; } });
        } catch (_) {}
      };
      const rows = Array.isArray(obj) ? obj : (obj && (obj.results || obj.data || obj.items) || []);
      if (Array.isArray(rows)) rows.forEach(applyCheck);
      if (obj && typeof obj === "object" && !Array.isArray(obj) && (obj.status || obj.steam_id || obj.player || /\/check\/\d+(\?|$)/.test(href.replace(location.origin, "")))) {
        if (obj.id == null) {
          const hid = href.match(/\/check\/(\d+)/);
          if (hid) obj.id = Number(hid[1]);
        }
        if (!obj.status) obj.status = "Pending";
        applyCheck(obj);
        if (obj.steam_id || (obj.suspect && obj.suspect.steam_id)) window.__caCurrentCheck = obj;
      }
      if (verb === "GET" && href.includes("/check/browse") && /[?&]contact=/.test(href)) {
        try {
          const u = new URL(href, location.origin);
          const packed = (obj && typeof obj === "object" && !Array.isArray(obj)) ? obj : { data: rows, results: rows, items: rows };
          let list = Array.isArray(packed.data) ? packed.data : (Array.isArray(packed.results) ? packed.results : (Array.isArray(rows) ? rows : []));
          const exclude = String(
            u.searchParams.get("exclude_steam_id")
            || u.searchParams.get("steam_id")
            || (window.__caCurrentCheck && (window.__caCurrentCheck.steam_id || (window.__caCurrentCheck.suspect && window.__caCurrentCheck.suspect.steam_id)))
            || ""
          );
          if (exclude) {
            list = list.filter(function (row) {
              const sid = String((row && (row.steam_id || (row.suspect && row.suspect.steam_id) || (row.player && row.player.steam_id) || (row.target_player && row.target_player.steam_id))) || "");
              return sid && sid !== exclude;
            });
          }
          packed.data = list;
          packed.results = list;
          packed.items = list;
          packed.total = list.length;
          return packed;
        } catch (_) {}
      }
    }
    if (/\/check\/?(\?|$)/.test(href.replace(location.origin, "")) && verb === "POST") {
      return asCheckCreateId(obj);
    }
    if (verb !== "POST" && /\/check\/[^/]+\/activity/.test(href)) {
      const responseCid = (href.match(/\/check\/(\d+)\/activity/) || [])[1];
      if (String(responseCid || "") !== String(checkPageId() || "")) return;
      if (!Array.isArray(obj)) obj = (obj && (obj.data || obj.results || obj.items)) || [];
      if (!Array.isArray(obj)) obj = [];
      obj.forEach(function (item) {
        if (!item || typeof item !== "object") return;
        if (!item.meta || typeof item.meta !== "object") item.meta = item.meta || {};
        if (item.meta && item.meta.client_id != null && item.meta.client_id !== "") {
          const nid = Number(item.meta.client_id);
          if (nid) item.meta.client_id = nid;
        }
        if (item.check_id != null) {
          const nid = Number(item.check_id);
          if (nid) item.check_id = nid;
        }
        if (item.checkId != null) {
          const nid = Number(item.checkId);
          if (nid) item.checkId = nid;
        }
        if (item.initiator_client) {
          rememberStaffClient(item.initiator_client);
          delete item.initiator_client.is_moderator;
          delete item.initiator_client.isModerator;
          delete item.initiator_client.moderator;
          delete item.initiator_client.is_staff;
          delete item.initiator_client.isStaff;
        }
      });
      const hid = href.match(/\/check\/(\d+)\/activity/);
      if (hid) {
        window.__caActivityHydrated = window.__caActivityHydrated || {};
        window.__caActivityHydrated[hid[1]] = true;
      }
      return dropChatAfterCheckFinished(obj);
    }
    if (verb !== "POST" && href.includes("/activity") && obj && typeof obj === "object" && !Array.isArray(obj)) {
      obj = obj.data || obj.results || obj.items || [];
    }
    if (href.includes("/auth/sessions")) {
      const rows = Array.isArray(obj) ? obj : (obj && (obj.data || obj.results || obj.items) || []);
      // Never invent a fake 127.0.0.1 session — backend returns real IPs + GeoIP
      if (!rows.length) return [];
      const mapped = rows.map(function (row, i) {
        if (!row || typeof row !== "object") return row;
        if (!row.key) row.key = "client_serials:" + (row.id || i + 1);
        if (row.id == null) row.id = row.serial || row.key || String(i + 1);
        const ip = String(row.ip || "").trim();
        const privateIp = !ip || /^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|::1|localhost|0\.0\.0\.0)/i.test(ip);
        if (!row.ip_details || typeof row.ip_details !== "object") row.ip_details = {};
        if (!row.ip_details.ip && ip) row.ip_details.ip = ip;
        let country = row.country_name || row.country || row.ip_details.country_name || row.ip_details.country || "";
        if (String(country).toLowerCase() === "local network") country = "Локальная сеть";
        const city = row.city || row.ip_details.city || "";
        const provider = row.provider || row.isp || row.ip_details.provider || row.ip_details.isp || "";
        let code = String(row.ip_details.country_code || row.country_code || "").toLowerCase();
        if (code === "un" || code === "xx" || code === "unknown") code = "";
        row.ip_details.country_code = code;
        if (row.pending || row.ip_details.pending) {
          delete row.pending;
          delete row.ip_details.pending;
        }
        if (country) {
          row.country = country;
          row.country_name = country;
          row.ip_details.country = country;
          row.ip_details.country_name = country;
        } else {
          row.country = privateIp ? "Локальная сеть" : (row.country || "");
          row.country_name = row.country;
          row.ip_details.country_name = row.country;
          row.ip_details.country = row.country;
        }
        if (city) {
          row.city = city;
          row.ip_details.city = city;
        }
        if (provider) {
          row.provider = provider;
          row.isp = provider;
          row.ip_details.provider = provider;
          row.ip_details.isp = provider;
        }
        return ensureIdToString(row, row.id);
      });
      window.__caSessionRows = mapped.slice();
      mapped.forEach(function (row) {
        if (row && (row.current || row.is_current)) {
          try {
            var list = readJsonStore(REVOKED_SESSIONS_KEY, []);
            if (!Array.isArray(list) || !list.length) return;
            var ip = String((row.ip || (row.ip_details && row.ip_details.ip) || "")).trim();
            var drop = [ip, String(row.id || ""), String(row.key || ""), String(row.serial || ""), "client_serials:" + ip];
            writeJsonStore(REVOKED_SESSIONS_KEY, list.filter(function (k) { return drop.indexOf(String(k)) < 0; }));
          } catch (_) {}
        }
      });
      return mapped.filter(function (row) {
        return !sessionIsRevoked(row);
      });
    }
    if (href.includes("/utils/stats") && obj && typeof obj === "object") {
      if (!obj.counters || typeof obj.counters !== "object") obj.counters = {};
      if (!obj.stats || typeof obj.stats !== "object") obj.stats = obj.counters;
      ["players","checks","bans","ban","reports","messages","total_players","total_checks","total_bans","total_reports","total_messages"].forEach(function (key) {
        if (obj[key] == null) obj[key] = obj.counters[key] || obj.stats[key] || 0;
        if (obj.counters[key] == null) obj.counters[key] = obj[key];
        if (obj.stats[key] == null) obj.stats[key] = obj[key];
      });
      if (!Array.isArray(obj.orgs)) obj.orgs = obj.organizations || obj.projects || [];
      if (!Array.isArray(obj.organizations)) obj.organizations = obj.orgs;
      if (!Array.isArray(obj.projects)) obj.projects = obj.orgs;
      if (obj.bans == null) obj.bans = obj.total_bans || 0;
      if (obj.ban == null) obj.ban = obj.bans || 0;
      (obj.orgs || []).forEach(function (row, i) {
        if (!row || typeof row !== "object") return;
        if (row.id == null) row.id = i + 1;
        if (!row.name) row.name = row.title || row.domain || "RustApp";
        row.avatar = imageSrc(row.avatar || row.image || PLACEHOLDER);
        row.image = row.avatar;
        try { Object.defineProperty(row, "toString", { configurable: true, value: function () { return String(this.id); } }); } catch (_) {}
      });
      normalizeStatsPayload(obj);
    }
    if (/\/check\/(?:\d+|latest)(?:\?|$)/.test(href) && obj && typeof obj === "object" && !Array.isArray(obj) && !href.includes("browse") && !href.includes("activity") && !href.includes("notice")) {
      // The bundled ChecksPage uses ORM-style M_ID fields internally.  Missing
      // IDs make its async loader throw before assigning the received check,
      // leaving the entire page on the spinner even though /check/{id} is 200.
      if (obj.id != null && obj.M_ID == null) obj.M_ID = obj.id;
      ["player", "suspect", "target_player"].forEach(function (key) {
        const profile = obj[key];
        if (!profile || typeof profile !== "object" || Array.isArray(profile)) return;
        if (profile.id == null && profile.steam_id != null) profile.id = String(profile.steam_id);
        if (profile.M_ID == null) profile.M_ID = profile.id != null ? profile.id : profile.steam_id;
      });
      ["checker", "moderator", "initiator_client"].forEach(function (key) {
        const client = obj[key];
        if (!client || typeof client !== "object" || Array.isArray(client)) return;
        if (client.M_ID == null) client.M_ID = client.id != null ? client.id : obj.client_id;
      });
      if ((obj.status === "Started" || obj.state === "Started") && !obj.finished_at) {
        obj.status = "Pending";
        obj.state = "Pending";
      }
      const teamSrc = Array.isArray(obj.suspect_team) ? obj.suspect_team : (Array.isArray(obj.team) ? obj.team : []);
      obj.suspect_team = teamSrc.map((row) => {
        if (row == null) return "";
        if (typeof row === "string" || typeof row === "number") return String(row);
        return String(row.steam_id || row.id || "");
      }).filter(Boolean);
      const suspect = obj.suspect || obj.player || obj.target_player || {};
      if (suspect && typeof suspect === "object") {
        if (!suspect.steam_id || suspect.steam_id === "0") {
          suspect.steam_id = obj.steam_id || window.__caCheckSteam || "";
        }
        if (!suspect.steam_name) suspect.steam_name = suspect.name || suspect.steam_id || obj.steam_id || window.__caCheckName || "";
        obj.suspect = suspect;
        obj.player = obj.player || suspect;
        obj.target_player = obj.target_player || suspect;
      }
      const sidNow = String(obj.steam_id || (obj.suspect && obj.suspect.steam_id) || "");
      if ((!sidNow || sidNow === "0" || sidNow === ".") && window.__caCheckStub && Number(window.__caCheckStub.id) === Number(obj.id || 0)) {
        return window.__caCheckStub;
      }
      if (!Array.isArray(obj.suspect_team)) obj.suspect_team = [];
      return obj;
    }
    if (href.includes("notice-state")) {
      if (typeof obj === "boolean") return obj;
      if (obj && typeof obj === "object") {
        return !!(obj.active || obj.notice || obj.value || obj.state);
      }
      return !!obj;
    }
    if (href.includes("sleeping-bag")) {
      const rows = Array.isArray(obj) ? obj : (obj && (obj.data || obj.results || obj.items) || []);
      if (Array.isArray(rows)) {
        rows.forEach((row) => {
          if (!row || typeof row !== "object") return;
          const text = bagPosText(row);
          const nums = text.match(/-?\d+(?:\.\d+)?/g) || [];
          row.x = Number(nums[0] || row.x || 0);
          row.y = Number(nums[1] || row.y || 0);
          row.z = Number(nums[2] || row.z || 0);
          const grid = String(row.grid || row.square || (row.coords && row.coords.value) || "").trim();
          row.grid = grid;
          row.square = grid;
          row.coords = { value: grid, grid: grid, square: grid };
          // SPA sleeping bags: show grid like N23, not raw XYZ
          if (grid) {
            row.position = grid;
            row.coordinates = grid;
            row.coordinate = grid;
            row.position_text = grid;
          } else {
            row.position = text;
            row.coordinates = text;
            row.coordinate = text;
            row.position_text = text;
          }
          const giver = row.initiator_player || row.from_player || row.giver || row.player;
          const receiver = row.target_player || row.to_player || row.receiver || giver;
          if (giver && typeof giver === "object") {
            if (!giver.steam_name) giver.steam_name = giver.name || row.initiator_name || row.from_steam_id || row.initiator_steam_id;
            if (!giver.name) giver.name = giver.steam_name;
            row.initiator_player = giver;
            row.from_player = giver;
            row.giver = giver;
            row.initiator = giver;
          }
          if (receiver && typeof receiver === "object") {
            if (!receiver.steam_name) receiver.steam_name = receiver.name || row.target_name || row.to_steam_id || row.target_steam_id;
            if (!receiver.name) receiver.name = receiver.steam_name;
            row.target_player = receiver;
            row.to_player = receiver;
            row.receiver = receiver;
            row.target = receiver;
            row.player = receiver;
          }
        });
      }
    }
    if (obj && typeof obj === "object" && !Array.isArray(obj) && Array.isArray(obj.results) && obj.data == null) {
      obj.data = obj.results;
    }
    if (href.includes("wallet-operations")) {
      return normalizeWalletOperations(obj);
    }
    if (href.includes("/project/") && href.endsWith("/wallet") && obj && typeof obj === "object" && !Array.isArray(obj)) {
      if (obj.balance == null) obj.balance = 0;
      if (obj.amount == null) obj.amount = obj.balance;
      if (obj.value == null) obj.value = obj.balance;
    }
    return obj;
  }

  function fixProject(obj) {
    if (!obj || typeof obj !== "object") return obj;
    if (Array.isArray(obj)) return obj.map(fixProject);
    if (obj.avatar) obj.avatar = imageSrc(obj.avatar);
    if (obj.steam_avatar) obj.steam_avatar = imageSrc(obj.steam_avatar);
    if (typeof obj.image === "string") obj.image = imageSrc(obj.image);
    if (typeof obj.image_url === "string") obj.image_url = imageSrc(obj.image_url);
    if (typeof obj.avatar_url === "string") obj.avatar_url = imageSrc(obj.avatar_url);
    if (typeof obj.banner_url === "string") obj.banner_url = imageSrc(obj.banner_url);
    const isStaffRow = "client" in obj && typeof obj.client === "object" && "permissions" in obj;
    const looksLikeProject =
      !isStaffRow &&
      ("domain" in obj || "tag" in obj || "owner_client_id" in obj || "is_immutable" in obj) &&
      ("id" in obj || "name" in obj);
      if (looksLikeProject) {
      const staffRole = String(obj.role || "").toLowerCase() === "staff";
      const markedOwner = obj.is_owner === true;
      if (!Array.isArray(obj.permissions)) obj.permissions = staffRole ? [] : PERMISSIONS.slice();
      if (obj.is_immutable == null) obj.is_immutable = false;
      if (obj.can_delete == null) obj.can_delete = !!markedOwner;
      if (obj.deletable == null) obj.deletable = !!markedOwner;
      if (obj.is_owner == null) obj.is_owner = !staffRole;
      if (obj.is_admin || obj.is_immutable || permsWantAdmin(obj.permissions, obj)) {
        obj.permissions = PERMISSIONS.slice();
        obj.is_admin = true;
        if (!markedOwner) obj.is_immutable = true;
      }
      if (obj.is_owner && !staffRole) {
        obj.role = "owner";
        obj.permissions = PERMISSIONS.slice();
      } else if (staffRole || obj.is_owner === false) {
        obj.is_owner = false;
        if (!obj.role) obj.role = "staff";
      }
      if (obj.owner_client_id == null && obj.is_owner) obj.owner_client_id = Number(obj.owner_user_id || obj.id || 1) || 1;
      else obj.owner_client_id = Number(obj.owner_client_id || 0) || obj.owner_client_id;
      if (!obj.domain) obj.domain = obj.tag || obj.url || "checkapp";
      if (!obj.tag) obj.tag = obj.domain;
      if (!obj.url) obj.url = obj.domain;
      if (!obj.plan) obj.plan = "base";
      if (!obj.role) obj.role = "owner";
      if (!obj.avatar) obj.avatar = PLACEHOLDER;
      // SPA disables billing "Сменить тариф" when project.verified === true
      obj.verified = false;
      obj.min_deposite = 1;
      obj.min_deposit = 1;
      obj.min_replenishment = 1;
      applyBillingDates(obj);
      ensureIdToString(obj, obj.id != null ? obj.id : 1);
    }
    if (obj.results && Array.isArray(obj.results)) obj.results = obj.results.map(fixProject);
    return obj;
  }

  function serverLimitPayload() {
    return {
      ok: false,
      error: "server-limit-exceeded",
      message: "server-limit-exceeded",
      code: "",
      command: "",
      used: false,
      server: null,
      token: null
    };
  }

  function shouldBlockServerPair(method, url, body) {
    if (String(method || "GET").toUpperCase() === "DELETE") return false;
    if (!/\/server\/pair/.test(String(url || ""))) return false;
    let code = "";
    try {
      if (body && typeof body === "string") {
        const parsed = JSON.parse(body);
        code = String((parsed && parsed.code) || "");
      } else if (body && typeof body === "object") {
        code = String(body.code || "");
      }
    } catch (_) {}
    if (code) return false;
    const tier = currentProjectTierSlug();
    const limit = tierServerLimit(tier);
    const count = typeof window.__checkappServersCount === "number" ? window.__checkappServersCount : null;
    return count != null && count >= limit;
  }

  function accountTierSlug() {
    return currentProjectTierSlug();
  }

  function projectCreateLimit(tier) {
    const t = String(tier || "base").toLowerCase();
    if (t === "plus") return 3;
    if (t === "enterprise" || t === "custom" || t === "pro" || t === "premium") return 10;
    return 2;
  }

  function projectLimitPayload() {
    return {
      ok: false,
      can: false,
      allowed: false,
      error: "project-limit-exceeded",
      message: "Project limit exceeded",
      title: "Ошибка",
      detail: "Вы больше не можете создавать проекты, достигнул лимит!"
    };
  }

  function patchXhr(xhr, raw) {
    if (/^(PUT|POST|PATCH|DELETE)$/i.test(xhr.__checkappMethod || "") && Number(xhr.status) >= 400 && !/\/tariff/.test(xhr.__checkappUrl || "")) return;
    const url = String(xhr.__checkappUrl || "");
    const rtype = String(xhr.responseType || "");
    if (/\.cs(\?|$)/i.test(url) || url.includes("/local/Checkapp") || url.includes("/local/RustApp") || url.includes("/local/Rustcheck")) return;
    if (rtype && rtype !== "text" && rtype !== "json" && rtype !== "") return;
    let parsed = null;
    if (raw) {
      try { parsed = JSON.parse(raw); } catch (_) {}
    }
    if (parsed == null && rtype === "json") {
      try {
        const resp = xhr.response;
        if (resp && typeof resp === "object") parsed = resp;
        else if (typeof resp === "string" && resp) parsed = JSON.parse(resp);
      } catch (_) {}
    }
    if (parsed == null) {
      try {
        if (Number(xhr.status) >= 500) {
          parsed = gatewayStub(url, xhr.__checkappMethod);
          if (parsed != null) xhr.__fakeStatus = 200;
        }
      } catch (_) {}
    }
    if (parsed == null && /\/tariff/i.test(url) && !/discard-trial/i.test(url)) {
      var xhrSt = Number(xhr.status || 0);
      if (xhrSt === 402 || xhr.__tariffHttp402) {
        parsed = { ok: false, error: "insufficient_balance", message: "Not enough balance", needed_rub: 300 };
      }
    }
    if (parsed == null) return;
    let next = parsed;
    try {
      next = fixProject(normalizeApi(url, parsed, xhr.__checkappMethod));
      // Deep walkFix on /reports and /alerts freezes the page (huge/circular nests)
      if (!/\/reports|\/player-alert|\/alerts|\/ban\/browse|\/team-history|\/session-history|\/auth\/sessions|\/players\/browse|\/check|\/player-message|\/court(?:\?|$)|\/handshake|\/audit|\/kill-feed|\/stats|\/small-stats|\/clients|\/map(?:\/|\?|$)/i.test(url)) walkFix(next, 0);
      var softened = softenTariffSelect(url, xhr.status, next);
      if (softened) {
        next = softened.body;
        xhr.__fakeStatus = softened.status;
        try {
          Object.defineProperty(xhr, "status", { configurable: true, get: function () { return 200; } });
        } catch (_) {}
      }
    } catch (_) {
      next = parsed;
    }
    const text = JSON.stringify(next);
    try { xhr.__fakeText = text; } catch (_) {}
    try {
      Object.defineProperty(xhr, "responseText", { configurable: true, get: function () { return text; } });
      Object.defineProperty(xhr, "response", { configurable: true, get: function () { return rtype === "json" ? next : text; } });
    } catch (_) {}
  }

  function currentProjectSlug() {
    const skip = {
      client: 1, assets: 1, local: 1, uploads: 1, login: 1, auth: 1, plugin: 1,
      pricing: 1, profile: 1, settings: 1, players: 1, onboarding: 1, utils: 1,
      checks: 1, check: 1, reports: 1, bans: 1, chat: 1, alerts: 1, signages: 1,
      bags: 1, mutes: 1, map: 1, admin: 1, public: 1, home: 1, billing: 1, servers: 1
    };
    function remember(val) {
      const s = String(val || "").replace(/^\/+|\/+$/g, "").split("/")[0];
      if (!s || skip[s] || skip[s.toLowerCase()]) return "";
      try { localStorage.setItem("checkapp_project_slug", s); } catch (_) {}
      try { window.__caProjectSlug = s; } catch (_) {}
      return s;
    }
    const parts = String(location.pathname || "").split("/").filter(Boolean);
    const fromPath = remember(parts[0] || "");
    if (fromPath) return fromPath;
    try {
      const pinia = typeof piniaRoot === "function" ? piniaRoot() : null;
      const stores = pinia && pinia._s;
      const panel = stores && (stores.get("panel") || stores.get("Panel"));
      const p = panel && panel.project;
      const fromPinia = remember((p && (p.domain || p.tag || p.url)) || "");
      if (fromPinia) return fromPinia;
    } catch (_) {}
    try {
      const saved = remember(localStorage.getItem("checkapp_project_slug") || window.__caProjectSlug || "");
      if (saved) return saved;
    } catch (_) {}
    return "";
  }

  function projectBillingCacheKey() {
    const slug = currentProjectSlug();
    if (slug) return slug.toLowerCase();
    try {
      const root = document.querySelector("#app");
      const pinia = root && root.__vue_app__ && root.__vue_app__.config.globalProperties.$pinia;
      const panel = pinia && pinia._s && pinia._s.get("panel");
      const p = panel && panel.project;
      if (p && p.id != null) return String(p.id);
      if (p && (p.domain || p.tag)) return String(p.domain || p.tag).toLowerCase();
    } catch (_) {}
    return "";
  }

  function projectTierStorageKey(key) {
    return key ? ("checkapp_tier_slug_" + key) : "checkapp_tier_slug";
  }

  function saveProjectTariffCache(obj) {
    const key = projectBillingCacheKey();
    window.__checkappTariffByProject = window.__checkappTariffByProject || {};
    if (key && obj) window.__checkappTariffByProject[key] = obj;
    window.__checkappTariff = obj;
    window.__checkappTariffReady = !!obj;
    if (obj) {
      const slug = String((obj.tariff && (obj.tariff.tier || obj.tariff.slug)) || obj.tier || "base").toLowerCase();
      window.__checkappTier = slug;
      try {
        if (key) sessionStorage.setItem(projectTierStorageKey(key), slug);
        sessionStorage.setItem("checkapp_tier_slug", slug);
      } catch (_) {}
    }
    return obj;
  }

  function loadProjectTariffFromCache() {
    const key = projectBillingCacheKey();
    if (!key) return null;
    const map = window.__checkappTariffByProject || {};
    return map[key] || null;
  }

  function currentProjectTierSlug() {
    const cached = loadProjectTariffFromCache();
    const t = cached || window.__checkappTariff;
    if (t && t.tariff) return String(t.tariff.tier || t.tariff.slug || t.tier || "base").toLowerCase();
    const key = projectBillingCacheKey();
    try {
      if (key) {
        const stored = sessionStorage.getItem(projectTierStorageKey(key));
        if (stored) return String(stored).toLowerCase();
      }
    } catch (_) {}
    return String(window.__checkappTier || sessionStorage.getItem("checkapp_tier_slug") || "base").toLowerCase();
  }

  function refreshProjectBillingStores(force) {
    const key = projectBillingCacheKey();
    if (!key) return;
    if (!force && key === window.__checkappBillingProjectKey) return;
    window.__checkappBillingProjectKey = key;
    const hit = loadProjectTariffFromCache();
    if (hit) {
      window.__checkappTariff = hit;
      window.__checkappTariffReady = true;
    } else {
      window.__checkappTariffReady = false;
    }
    try {
      const root = document.querySelector("#app");
      const pinia = root && root.__vue_app__ && root.__vue_app__.config.globalProperties.$pinia;
      if (!pinia || !pinia._s) return;
      const payments = pinia._s.get("payments");
      const tariffProject = pinia._s.get("tariff-project");
      if (payments && typeof payments.warmup === "function") payments.warmup(true);
      if (tariffProject && typeof tariffProject.warmup === "function") tariffProject.warmup();
    } catch (_) {}
    try { syncProjectBlockedState(); } catch (_) {}
  }

  function isPublicAppPath() {
    const path = location.pathname || "/";
    return path === "/" || path === "/pricing" || /^\/client(?:\/|$)/.test(path);
  }

  function projectStubFromUrl() {
    const slug = currentProjectSlug();
    if (!slug) return null;
    const list = Array.isArray(window.__checkappProjectsCache) ? window.__checkappProjectsCache : [];
    const cached = list.find(function (p) {
      return String((p && (p.domain || p.tag || p.url)) || "").toLowerCase() === slug.toLowerCase();
    });
    if (cached) return cached;
    return {
      id: slug,
      domain: slug,
      tag: slug,
      url: slug,
      name: slug,
      plan: "base",
      role: "owner",
      is_owner: true,
      verified: false
    };
  }

  function normalizeWalletOperations(obj) {
    if (!obj || typeof obj !== "object") obj = {};
    if (!Array.isArray(obj.results)) obj.results = Array.isArray(obj.data) ? obj.data.slice() : [];
    if (!Array.isArray(obj.data)) obj.data = obj.results.slice();
    if (!Array.isArray(obj.items)) obj.items = obj.results.slice();
    if (obj.total == null) obj.total = obj.results.length;
    if (obj.limit == null) obj.limit = 50;
    if (obj.page == null) obj.page = 1;
    if (obj.current_page == null) obj.current_page = obj.page;
    if (obj.last_page == null) {
      obj.last_page = obj.total ? Math.max(1, Math.ceil(Number(obj.total) / Number(obj.limit || 50))) : 1;
    }
    obj.results.forEach(function (row) {
      if (!row || typeof row !== "object") return;
      if (row.success == null) row.success = true;
      if (!row.type) row.type = Number(row.amount || 0) >= 0 ? "in" : "out";
      if (!row.created_at) row.created_at = Date.now();
      if (!row.meta || typeof row.meta !== "object") {
        row.meta = {
          action: Number(row.amount || 0) >= 0 ? "deposite" : "renewal",
          type: "base",
          target: "project",
          method: "Баланс",
          transaction_id: String(row.id || "")
        };
      }
      if (!row.meta.action) row.meta.action = Number(row.amount || 0) >= 0 ? "deposite" : "renewal";
      if (!row.meta.type) row.meta.type = "base";
      if (!row.meta.target) row.meta.target = "project";
      if (row.meta.action === "deposite" && !row.meta.method) row.meta.method = "Баланс";
      if (!row.meta.transaction_id) row.meta.transaction_id = String(row.id || "");
    });
    return obj;
  }

  function ensurePanelProject() {
    if (isPublicAppPath()) return;
    try {
      const root = document.querySelector("#app");
      const app = root && root.__vue_app__;
      const pinia = app && app.config && app.config.globalProperties && app.config.globalProperties.$pinia;
      if (!pinia || !pinia._s) return;
      const panel = pinia._s.get("panel");
      const appStore = pinia._s.get("app");
      // The router owns initial project selection. Never seed an invented project
      // while authentication/project loading is still in progress.
      if (!appStore || !appStore.isReady || !Array.isArray(appStore.projects)) return;
      if (!panel || (panel.project && panel.project.id)) return;
      const slug = currentProjectSlug();
      const project = appStore.projects.find(function (p) {
        return p && (p.domain === slug || String(p.id) === slug);
      });
      if (project && typeof panel.updateProject === "function") panel.updateProject(project.domain, false);
    } catch (_) {}
  }

  (function prefetchProjectsEarly() {
    function loadProjects() {
      const auth = authHeaderValue();
      if (!auth) return;
      fetch("/project", { credentials: "include", cache: "no-store", headers: { Accept: "application/json", Authorization: auth } })
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (list) {
          if (Array.isArray(list)) window.__checkappProjectsCache = list;
          ensurePanelProjectDebounced();
        })
        .catch(function () {});
    }
    loadProjects();
    setInterval(loadProjects, 30000);
  })();

  let _lastEnsuredSlug = "";
  function ensurePanelProjectDebounced() {
    const slug = currentProjectSlug();
    if (slug === _lastEnsuredSlug) return;
    _lastEnsuredSlug = slug;
    ensurePanelProject();
  }
  setInterval(ensurePanelProjectDebounced, 5000);
  window.addEventListener("popstate", ensurePanelProjectDebounced);
  setInterval(function () { refreshProjectBillingStores(false); }, 30000);
  window.addEventListener("popstate", function () { refreshProjectBillingStores(true); });

  (function wrapXhrCtor() {
    const Native = window.XMLHttpRequest;
    if (Native && Native.__checkappWrapped) return;
    class CheckappXHR extends Native {
      constructor() {
        super();
        this.__fakeStatus = null;
        this.__fakeReady = null;
        this.__fakeText = null;
      }
    }
    CheckappXHR.__checkappWrapped = true;
    CheckappXHR.UNSENT = Native.UNSENT;
    CheckappXHR.OPENED = Native.OPENED;
    CheckappXHR.HEADERS_RECEIVED = Native.HEADERS_RECEIVED;
    CheckappXHR.LOADING = Native.LOADING;
    CheckappXHR.DONE = Native.DONE;
    try {
      const proto = Native.prototype;
      const descStatus = Object.getOwnPropertyDescriptor(proto, "status");
      const descReady = Object.getOwnPropertyDescriptor(proto, "readyState");
      const descText = Object.getOwnPropertyDescriptor(proto, "responseText");
      const descResp = Object.getOwnPropertyDescriptor(proto, "response");
      Object.defineProperty(proto, "status", {
        configurable: true,
        enumerable: true,
        get: function () {
          if (this && this.__fakeStatus != null) return this.__fakeStatus;
          var real = descStatus && descStatus.get ? descStatus.get.call(this) : 0;
          if (
            real === 402 &&
            this &&
            /\/tariff/i.test(String(this.__checkappUrl || "")) &&
            !/discard-trial/i.test(String(this.__checkappUrl || ""))
          ) {
            this.__tariffHttp402 = true;
          }
          return real;
        }
      });
      Object.defineProperty(proto, "readyState", {
        configurable: true,
        enumerable: true,
        get: function () {
          if (this && this.__fakeReady != null) return this.__fakeReady;
          return descReady && descReady.get ? descReady.get.call(this) : 0;
        }
      });
      Object.defineProperty(proto, "responseText", {
        configurable: true,
        enumerable: true,
        get: function () {
          if (this && this.__fakeText != null) return this.__fakeText;
          return descText && descText.get ? descText.get.call(this) : "";
        }
      });
      Object.defineProperty(proto, "response", {
        configurable: true,
        enumerable: true,
        get: function () {
          if (this && this.__fakeText != null) return this.__fakeText;
          return descResp && descResp.get ? descResp.get.call(this) : "";
        }
      });
    } catch (_) {}
    window.XMLHttpRequest = CheckappXHR;
  })();

  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  const origSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
    this.__checkappReqHeaders = this.__checkappReqHeaders || {};
    try { this.__checkappReqHeaders[String(name || "").toLowerCase()] = String(value == null ? "" : value); } catch (_) {}
    if (String(name || "").toLowerCase() === "authorization") {
      // Never let axios set empty/quoted/duplicate Authorization — XHR concatenates repeats.
      if (this.__checkappAuthSet) return;
      const auth = authHeaderValue();
      if (auth) {
        this.__checkappAuthSet = true;
        return origSetRequestHeader.call(this, "Authorization", auth);
      }
      const cleaned = cleanToken(value);
      if (!cleaned || cleaned === "undefined" || cleaned === "null") return;
      this.__checkappAuthSet = true;
      return origSetRequestHeader.call(this, "Authorization", "Bearer " + cleaned);
    }
    return origSetRequestHeader.call(this, name, value);
  };
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__checkappAuthSet = false;
    if (isAnalytics(url)) {
      this.__checkappAnalytics = true;
      this.__checkappUrl = String(url || "");
      this.__checkappMethod = method;
      return;
    }
    const next = rewriteUrl(url, method);
    this.__checkappUrl = next;
    this.__checkappMethod = method;
    return origOpen.call(this, method, next);
  };
  function localCheckPayload(url, method) {
    const href = String(url || "");
    const verb = String(method || "GET").toUpperCase();
    if (verb !== "GET") return null;
    // Never replace real check data with browser stubs.  This interceptor used
    // to answer GET /check/{id} and /check/{id}/activity locally, so the actual
    // request never reached the API and the ChecksPage stayed on its spinner.
    if (/\/check\/\d+(?:\/activity)?(?:\?|$)/.test(href)) return null;
    const detHit = href.match(/\/players\/(\d{10,})\/details(?:\?|$)/);
    if (detHit && window.__caBackendDown && Date.now() < window.__caBackendDown) {
      const stub = gatewayStub(href, "GET");
      if (stub != null) return stub;
    }
    return null;
  }

  function respondXhrJson(xhr, obj, status) {
    const text = typeof obj === "string" ? obj : JSON.stringify(obj);
    let parsed = obj;
    if (typeof obj === "string") {
      try { parsed = JSON.parse(obj); } catch (_) { parsed = obj; }
    }
    const code = Number(status || 200) || 200;
    try {
      xhr.__fakeStatus = code;
      xhr.__fakeText = text;
      xhr.__fakeReady = 4;
    } catch (_) {}
    try {
      Object.defineProperty(xhr, "status", { configurable: true, get: function () { return code; } });
      Object.defineProperty(xhr, "statusText", { configurable: true, get: function () { return code >= 400 ? "Error" : "OK"; } });
      Object.defineProperty(xhr, "readyState", { configurable: true, get: function () { return 4; } });
      Object.defineProperty(xhr, "responseText", { configurable: true, get: function () { return text; } });
      Object.defineProperty(xhr, "response", {
        configurable: true,
        get: function () { return String(xhr.responseType || "") === "json" ? parsed : text; }
      });
      xhr.getResponseHeader = function (name) {
        return String(name || "").toLowerCase() === "content-type" ? "application/json" : null;
      };
      xhr.getAllResponseHeaders = function () { return "content-type: application/json\r\n"; };
    } catch (_) {}
    setTimeout(function () {
      try { xhr.dispatchEvent(new Event("readystatechange")); } catch (_) {}
      try { xhr.dispatchEvent(new Event("load")); } catch (_) {}
      try { xhr.dispatchEvent(new Event("loadend")); } catch (_) {}
      if (typeof xhr.onreadystatechange === "function") try { xhr.onreadystatechange(); } catch (_) {}
      if (typeof xhr.onload === "function") try { xhr.onload(); } catch (_) {}
      if (typeof xhr.onloadend === "function") try { xhr.onloadend(); } catch (_) {}
    }, 0);
  }

  XMLHttpRequest.prototype.send = function (body) {
    if (this.__checkappAnalytics) {
      Object.defineProperty(this, "status", { configurable: true, get: () => 200 });
      Object.defineProperty(this, "responseText", { configurable: true, get: () => "{\"code\":200,\"events_ingested\":0}" });
      Object.defineProperty(this, "response", { configurable: true, get: () => "{\"code\":200,\"events_ingested\":0}" });
      setTimeout(() => {
        try { this.dispatchEvent(new Event("load")); } catch (_) {}
        if (typeof this.onload === "function") try { this.onload(); } catch (_) {}
      }, 0);
      return;
    }
    if (shouldBlockServerPair(this.__checkappMethod, this.__checkappUrl, body)) {
      const blocked = serverLimitPayload();
      if (window.__checkappShowServerLimitToast) window.__checkappShowServerLimitToast();
      const text = JSON.stringify(blocked);
      Object.defineProperty(this, "status", { configurable: true, get: () => 403 });
      Object.defineProperty(this, "responseText", { configurable: true, get: () => text });
      Object.defineProperty(this, "response", { configurable: true, get: () => text });
      setTimeout(() => {
        try { this.dispatchEvent(new Event("load")); } catch (_) {}
        if (typeof this.onload === "function") try { this.onload(); } catch (_) {}
      }, 0);
      return;
    }
    if (/\/realtime\/(stream|sse)|\/events\/stream/i.test(String(this.__checkappUrl || ""))) {
      Object.defineProperty(this, "status", { configurable: true, get: () => 200 });
      Object.defineProperty(this, "responseText", { configurable: true, get: () => "retry: 3600000\n\n" });
      Object.defineProperty(this, "response", { configurable: true, get: () => "retry: 3600000\n\n" });
      setTimeout(() => {
        try { this.dispatchEvent(new Event("load")); } catch (_) {}
        if (typeof this.onload === "function") try { this.onload(); } catch (_) {}
      }, 0);
      return;
    }
    try {
      const localSel = localTariffSelectReply(this.__checkappMethod, this.__checkappUrl, null, this);
      if (localSel) {
        respondXhrJson(this, localSel.body);
        return;
      }
    } catch (_) {}
    try {
      const local = localCheckPayload(this.__checkappUrl, this.__checkappMethod);
      if (local != null) {
        respondXhrJson(this, local);
        return;
      }
    } catch (_) {}
    body = sanitizeChatPost(this.__checkappUrl, this.__checkappMethod, body);
    body = attachPairServerName(this.__checkappUrl, this.__checkappMethod, body);
    body = expandStaffAdminBody(this.__checkappUrl, this.__checkappMethod, body);
    body = sanitizePlayerAutokickBody(this.__checkappUrl, this.__checkappMethod, body);

    try { rememberCheckSteamFromBody(this.__checkappUrl, this.__checkappMethod, body); } catch (_) {}
    if (typeof tryHandleDeposit === "function") {
      var depXhr = tryHandleDeposit(this.__checkappUrl, this.__checkappMethod, body);
      if (depXhr) {
        var xhrRef = this;
        depXhr.then(function (redirect) {
          try { if (window.__caGoPay) window.__caGoPay(redirect); } catch (_) {}
          respondXhrJson(xhrRef, JSON.stringify(redirect));
        }).catch(function (err) {
          try { showCheckappToast("warn", (err && err.message) || "Не удалось создать платёж.", { title: "Пополнение" }); } catch (_) {}
          respondXhrJson(xhrRef, { message: (err && err.message) || "pay" }, 400);
        });
        return;
      }
    }
    if (String(this.__checkappMethod || "").toUpperCase() === "DELETE" && /\/auth\/sessions|\/client\/sessions/i.test(String(this.__checkappUrl || ""))) {
      var sessionInfo = rememberRevokedIpFromUrl(this.__checkappUrl, body);
      if (sessionInfo && sessionInfo.ip) {
        try {
          var parsedSession = typeof body === "string" ? JSON.parse(body || "{}") : (body && typeof body === "object" ? body : {});
          if (!parsedSession || typeof parsedSession !== "object") parsedSession = {};
          if (!parsedSession.ip) {
            parsedSession.ip = sessionInfo.ip;
            if (sessionInfo.ident && !parsedSession.id) parsedSession.id = sessionInfo.ident;
            body = typeof body === "string" || body == null ? JSON.stringify(parsedSession) : parsedSession;
          }
        } catch (_) {}
      }
    }
    if (String(this.__checkappMethod || "").toUpperCase() === "DELETE" && String(this.__checkappUrl || "").includes("/signage")) {
      window.__checkappLastSignageDelete = body;
    }
    try {
      const slug = currentProjectSlug();
      if (slug) this.setRequestHeader("X-Checkapp-Project", slug);
    } catch (_) {}
    try {
      const auth = authHeaderValue();
      if (auth) this.setRequestHeader("Authorization", auth);
    } catch (_) {}
    this.addEventListener("readystatechange", function () {
      if (this.readyState < 2) return;
      try {
        if (
          Number(this.status) === 402 &&
          /\/tariff/i.test(String(this.__checkappUrl || "")) &&
          !/discard-trial/i.test(String(this.__checkappUrl || ""))
        ) {
          this.__tariffHttp402 = true;
        }
      } catch (_) {}
      if (this.readyState !== 4) return;
      try {
        const rtype = String(this.responseType || "");
        patchXhr(this, rtype === "json" ? "" : this.responseText);
      } catch (_) {}
    }, true);
    this.addEventListener("load", function () {
      try {
        const rtype = String(this.responseType || "");
        patchXhr(this, rtype === "json" ? "" : this.responseText);
      } catch (_) {}
      try {
        let parsed = null;
        try { parsed = JSON.parse(this.responseText); } catch (_) {}
        if (this.status >= 200 && this.status < 300) {
          maybePublishChat(this.__checkappUrl, this.__checkappMethod, body, parsed);
        }
        maybePublishCheck(this.__checkappUrl, this.__checkappMethod, parsed);
        maybePublishBan(this.__checkappUrl, this.__checkappMethod, parsed);
        maybeShowProjectLimitToast(this.__checkappUrl, this.__checkappMethod, this.status, parsed);
        if (
          this.status >= 200 &&
          this.status < 300 &&
          /\/auth\/(classic\/(sign-in|sign-up)|steam\/sign-in|steam\/sign-up|discord\/sign-in|discord\/sign-up)/i.test(String(this.__checkappUrl || "")) &&
          parsed
        ) {
          let token = "";
          if (typeof parsed === "string" && parsed.split(".").length === 3) token = parsed;
          else if (parsed && typeof parsed === "object") token = parsed.token || parsed.access_token || "";
          if (token) {
            storeAuthToken(token);
            const tokenText = JSON.stringify(token);
            try {
              Object.defineProperty(this, "responseText", { configurable: true, get: function () { return tokenText; } });
              Object.defineProperty(this, "response", { configurable: true, get: function () { return tokenText; } });
            } catch (_) {}
          }
        }
      } catch (_) {}
    });
    return origSend.call(this, body);
  };

  const origFetch = window.fetch.bind(window);
  window.__checkappOrigFetch = origFetch;
  window.fetch = function (input, init) {
    let url = typeof input === "string" ? input : input && input.url;
    if (isAnalytics(url)) return Promise.resolve(emptyJsonResponse());
    const methodEarly = String((init && init.method) || "GET").toUpperCase();
    const urlEarly = String(url || "");
    if (window.__checkappAutokickDemo && methodEarly !== "GET" && /auto-kick|autokick|court-autokick/i.test(urlEarly) && !/settings-auto-kick/i.test(urlEarly)) {
      return Promise.resolve(new Response(JSON.stringify({ ok: false, demo: true }), { status: 200, headers: { "Content-Type": "application/json" } }));
    }
    const next = rewriteUrl(url, (init && init.method) || "GET");
    init = Object.assign({}, init || {});
    try {
      const headers = new Headers(init.headers || {});
      const slug = currentProjectSlug();
      if (slug) headers.set("X-Checkapp-Project", slug);
      const auth = authHeaderValue();
      if (auth) {
        headers.set("Authorization", auth);
      }
      init.headers = headers;
    } catch (_) {}
    init.body = sanitizeChatPost(next, init.method, init.body);
    init.body = attachPairServerName(next, init.method, init.body);
    init.body = expandStaffAdminBody(next, init.method, init.body);
    init.body = sanitizePlayerAutokickBody(next, init.method, init.body);

    try { rememberCheckSteamFromBody(next, init.method, init.body); } catch (_) {}
    if (typeof tryHandleDeposit === "function") {
      var depFetch = tryHandleDeposit(next, init.method, init.body);
      if (depFetch) {
        return depFetch.then(function (redirect) {
          try { if (window.__caGoPay) window.__caGoPay(redirect); } catch (_) {}
          return new Response(JSON.stringify(redirect), { status: 200, headers: { "Content-Type": "application/json" } });
        }).catch(function (err) {
          try { showCheckappToast("warn", (err && err.message) || "Не удалось создать платёж.", { title: "Пополнение" }); } catch (_) {}
          return new Response(JSON.stringify({ message: (err && err.message) || "pay" }), { status: 400, headers: { "Content-Type": "application/json" } });
        });
      }
    }
    if (String(init.method || "").toUpperCase() === "DELETE" && /\/auth\/sessions|\/client\/sessions/i.test(String(next || url || ""))) {
      var sessionInfo = rememberRevokedIpFromUrl(next || url, init.body);
      try {
        var bodyObj = {};
        try { bodyObj = typeof init.body === "string" ? JSON.parse(init.body || "{}") : (init.body || {}); } catch (_) { bodyObj = {}; }
        if (!bodyObj || typeof bodyObj !== "object") bodyObj = {};
        var ip = (sessionInfo && sessionInfo.ip) || "";
        if (!ip) {
          var ipMatch = String(next || url || "").match(/(\d{1,3}(?:\.\d{1,3}){3})/);
          if (ipMatch) ip = ipMatch[1];
        }
        if (ip && !bodyObj.ip) {
          bodyObj.ip = ip;
          if (sessionInfo && sessionInfo.ident && !bodyObj.id) bodyObj.id = sessionInfo.ident;
          init.body = JSON.stringify(bodyObj);
          const headers = new Headers(init.headers || {});
          headers.set("Content-Type", "application/json");
          init.headers = headers;
        }
      } catch (_) {}
    }
    if (String(init.method || "").toUpperCase() === "DELETE" && String(next || "").includes("/signage")) {
      window.__checkappLastSignageDelete = init.body;
    }
    if (shouldBlockServerPair(methodEarly, next || url, init.body)) {
      if (window.__checkappShowServerLimitToast) window.__checkappShowServerLimitToast();
      return Promise.resolve(new Response(JSON.stringify(serverLimitPayload()), {
        status: 403,
        headers: { "Content-Type": "application/json" }
      }));
    }
    if (/\/realtime\/(stream|sse)|\/events\/stream/i.test(String(next || url || ""))) {
      return Promise.resolve(new Response("retry: 3600000\n\n", {
        status: 200,
        headers: { "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache" }
      }));
    }
    try {
      const local = localCheckPayload(next || url, methodEarly);
      if (local != null) {
        return Promise.resolve(new Response(JSON.stringify(local), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        }));
      }
    } catch (_) {}
    try {
      const localSel = localTariffSelectReply(methodEarly, next || url, init && init.headers);
      if (localSel) {
        return Promise.resolve(new Response(JSON.stringify(localSel.body), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        }));
      }
    } catch (_) {}
    const call = typeof input === "string" || next !== url
      ? origFetch(next, init)
      : origFetch(input, init);
    if (/\.cs(\?|$)/i.test(String(next || url || "")) || /\/local\/(Checkapp|RustApp|Rustcheck)/i.test(String(next || ""))) return call;
    return call.then(async (res) => {
      const hrefNow = String(next || url || "");
      if (/^(PUT|POST|PATCH|DELETE)$/i.test(methodEarly) && !res.ok && !/\/tariff/.test(hrefNow)) return res;
      const ctype = String(res.headers.get("content-type") || "");
      if (
        (res.status >= 500 || (ctype.includes("html") && !ctype.includes("json"))) &&
        !( /\/tariff/.test(hrefNow) && (res.status === 402 || res.status === 403 || res.status === 400) )
      ) {
        const stub = gatewayStub(hrefNow, methodEarly);
        if (stub != null) {
          let fixed = stub;
          try { fixed = fixProject(normalizeApi(hrefNow, stub, (init && init.method) || "GET")); } catch (_) {}
          return new Response(JSON.stringify(fixed), { status: 200, headers: { "Content-Type": "application/json" } });
        }
      }
      if ((methodEarly === "POST" || methodEarly === "PUT" || methodEarly === "PATCH") && /\/tariff/.test(hrefNow) && !/discard-trial/i.test(hrefNow)) {
        if (res.status === 402 || res.status === 403) {
          var failBody = { ok: false, error: res.status === 403 ? "project_blocked" : "insufficient_balance", message: res.status === 403 ? "project blocked" : "Not enough balance", needed_rub: 300 };
          try {
            var failText = await res.clone().text();
            var failParsed = JSON.parse(failText);
            if (failParsed && typeof failParsed === "object") failBody = failParsed;
          } catch (_) {}
          var ownFail = false;
          try {
            var failHdrs = (init && init.headers) || {};
            if (failHdrs.get && failHdrs.get("X-Checkapp-Plan-Select") === "1") ownFail = true;
            else {
              var failHk = Object.keys(failHdrs).find(function (k) { return String(k).toLowerCase() === "x-checkapp-plan-select"; });
              if (failHk && String(failHdrs[failHk]) === "1") ownFail = true;
            }
          } catch (_) {}
          if (ownFail) {
            showTariffSelectUi(res.status === 403 ? "blocked" : "funds", failBody);
            return new Response(JSON.stringify(failBody), { status: 200, headers: { "Content-Type": "application/json" } });
          }
          var softFail = softenTariffSelect(hrefNow, res.status, failBody);
          if (softFail) {
            return new Response(JSON.stringify(softFail.body), { status: 200, headers: { "Content-Type": "application/json" } });
          }
        }
      }
      if (!ctype.includes("json") && !ctype.includes("text/plain")) return res;
      try {
        const text = await res.clone().text();
        const parsed = JSON.parse(text);
        if (/\/utils\/upload/i.test(hrefNow)) {
          const url = normalizeApi(hrefNow, parsed, methodEarly);
          return new Response(JSON.stringify(url), { status: res.status, headers: { "Content-Type": "application/json" } });
        }
        try {
          if (
            res.status >= 200 &&
            res.status < 300 &&
            /\/auth\/classic\/(sign-in|sign-up)/i.test(String(next || url || "")) &&
            parsed
          ) {
            let token = "";
            if (typeof parsed === "string" && parsed.split(".").length === 3) token = parsed;
            else if (parsed && typeof parsed === "object") {
              token = parsed.token || parsed.access_token || "";
              if (parsed.client) window.__checkappClientCache = parsed.client;
            }
            if (token) {
              storeAuthToken(token);
              return new Response(JSON.stringify(token), { status: 200, headers: { "Content-Type": "application/json" } });
            }
          }
        } catch (_) {}
        const fixed = fixProject(normalizeApi(next, parsed, (init && init.method) || "GET"));
        // Deep walkFix on /reports and /alerts freezes the page (huge/circular nests)
        if (!/\/reports|\/player-alert|\/alerts|\/ban\/browse|\/team-history|\/session-history|\/auth\/sessions|\/players\/browse|\/check|\/player-message|\/court(?:\?|$)|\/handshake|\/audit|\/kill-feed|\/stats|\/small-stats|\/clients|\/map(?:\/|\?|$)/i.test(String(next || url || ""))) walkFix(fixed, 0);
        var ownSelect = false;
        try {
          var hdrs = (init && init.headers) || {};
          if (hdrs.get && hdrs.get("X-Checkapp-Plan-Select") === "1") ownSelect = true;
          else {
            var hk = Object.keys(hdrs).find(function (k) { return String(k).toLowerCase() === "x-checkapp-plan-select"; });
            if (hk && String(hdrs[hk]) === "1") ownSelect = true;
          }
        } catch (_) {}
        if ((methodEarly === "POST" || methodEarly === "PUT" || methodEarly === "PATCH") && /\/tariff/.test(String(next || url || ""))) {
          if (ownSelect) {
            if (fixed && (fixed.ok === false || res.status >= 400 || fixed.error)) {
              if (fixed.error === "insufficient_balance" || res.status === 402) showTariffSelectUi("funds", fixed);
              else if (fixed.error === "base_not_purchasable") showTariffSelectUi("base", fixed);
              else if (fixed.error === "project_blocked" || res.status === 403) showTariffSelectUi("blocked", fixed);
              else if (fixed.error === "plan_locked") showTariffSelectUi("locked", fixed);
            }
            return new Response(JSON.stringify(fixed), { status: 200, headers: { "Content-Type": "application/json" } });
          }
          var softenedFetch = softenTariffSelect(String(next || url || ""), res.status, fixed);
          if (softenedFetch) {
            return new Response(JSON.stringify(softenedFetch.body), { status: 200, headers: { "Content-Type": "application/json" } });
          }
        }
        try { if (res.status >= 200 && res.status < 300) maybePublishChat(next, (init && init.method) || "GET", init && init.body, fixed); } catch (_) {}
        try { maybePublishCheck(next, (init && init.method) || "GET", fixed); } catch (_) {}
        try { maybePublishBan(next, (init && init.method) || "GET", fixed); } catch (_) {}
        try { maybeShowProjectLimitToast(next, methodEarly, res.status, fixed); } catch (_) {}
        return new Response(JSON.stringify(fixed), { status: res.status, headers: res.headers });
      } catch (_) {
        return res;
      }
    }).catch(function (err) {
      if (/\/utils\/upload/i.test(String(next || url || ""))) {
        return Promise.reject(err || new Error("upload failed"));
      }
      if (/^(PUT|POST|PATCH|DELETE)$/i.test(methodEarly)) return Promise.reject(err);
      // Read-only legacy fallbacks
      return emptyJsonResponse();
    });
  };

  try {
    const origBeacon = navigator.sendBeacon && navigator.sendBeacon.bind(navigator);
    navigator.sendBeacon = function (url, data) {
      if (isAnalytics(url) || isRemoteApi(url)) return true;
      return origBeacon ? origBeacon(url, data) : true;
    };
  } catch (_) {}

  function parseCentrifuge(raw) {
    const text = typeof raw === "string" ? raw : "";
    const msgs = [];
    text.split(/\n/).forEach((line) => {
      const row = line.trim();
      if (!row) return;
      try {
        const parsed = JSON.parse(row);
        if (Array.isArray(parsed)) parsed.forEach((item) => msgs.push(item));
        else msgs.push(parsed);
      } catch (_) {}
    });
    if (!msgs.length) {
      try {
        const parsed = JSON.parse(text);
        if (Array.isArray(parsed)) return parsed;
        if (parsed && typeof parsed === "object") return [parsed];
      } catch (_) {}
    }
    return msgs;
  }

  const centrifugeSockets = window.__checkappCentrifugeSockets || (window.__checkappCentrifugeSockets = []);

  function staffProfile() {
    try {
      const root = document.querySelector("#app");
      const app = root && root.__vue_app__;
      const pinia = app && app.config && app.config.globalProperties && app.config.globalProperties.$pinia;
      if (pinia && pinia._s) {
        let found = null;
        pinia._s.forEach(function (store) {
          if (found || !store) return;
          const me = store.client || store.user || store.profile || (store.$state && (store.$state.client || store.$state.user));
          if (me && typeof me === "object" && (me.id || me.name)) found = me;
        });
        if (found && found.id) {
          window.__caMeId = found.id;
          const fid = Number(found.id) || 0;
          return {
            id: fid || 1,
            name: found.name || "",
            tag: found.tag || "",
            avatar: found.avatar || PLACEHOLDER,
            status: "online"
          };
        }
      }
    } catch (_) {}
    return { id: 0, name: "", tag: "", avatar: PLACEHOLDER, status: "online" };
  }

  (function checkChatNoStaffBadge() {
    function stripBadges() {
      try {
        document.querySelectorAll("img.ca-mod-badge").forEach(function (el) { el.remove(); });
      } catch (_) {}
    }
    stripBadges();
    setInterval(stripBadges, 800);
    document.addEventListener("click", function (ev) {
      try {
        const path = String(location.pathname || "") + String(location.search || "");
        if (!/stats|moders|сотрудник|statistics/i.test(path)) {
          let n = ev.target;
          for (let i = 0; i < 10 && n; i++, n = n.parentElement) {
            const txt = String(n.textContent || "").replace(/\s+/g, " ").trim();
            if (/статистик/i.test(txt) && txt.length < 40) break;
          }
        }
        setTimeout(function () {
          const cid = selectedStatsClientId();
          if (cid) window.__caStatsClientId = cid;
        }, 0);
        let node = ev.target;
        for (let i = 0; i < 14 && node; i++, node = node.parentElement) {
          const vn = node.__vueParentComponent || node.__vnode && node.__vnode.component;
          const props = (vn && vn.props) || {};
          const client = props.client || props.moder || props.moderator || props.item;
          const cid = Number((client && client.id) || props.clientId || props.client_id || (typeof props.id === "number" ? props.id : 0) || 0) || 0;
          if (cid && (client || /client|moder|staff/i.test(String((vn && vn.type && (vn.type.__name || vn.type.name)) || "")))) {
            window.__caStatsClientId = cid;
            break;
          }
        }
      } catch (_) {}
    }, true);
  })();

  function patchPlayerStatusLastSeen() {
    try {
      const pinia = piniaRoot();
      if (!pinia || !pinia._s) return;
      const store = pinia._s.get("player-status");
      if (!store || store.__caLastSeenPatched) return;
      const orig = store.getPlayerStatus;
      if (typeof orig !== "function") return;
      store.__caLastSeenPatched = true;
      store.getPlayerStatus = function (p) {
        const h = orig.call(store, p) || { status: (p && p.status) || "offline", last_online_at: 0 };
        const apiLast = Number((p && p.last_online_at) || 0) || 0;
        const st = String((p && p.status) || "").toLowerCase();
        const ws = String(h.status || "").toLowerCase();
        if (st === "joining" || st === "queued" || st === "afk") h.status = st;
        else if (ws === "joining" || ws === "queued" || ws === "afk") h.status = ws;
        else if (st === "active" || st === "online") h.status = "online";
        if (!apiLast && !playerIsLive(st) && !playerIsLive(h.status)) {
          h.last_online_at = 0;
          h.status = st || "offline";
        }
        return h;
      };
    } catch (_) {}
  }
  setInterval(patchPlayerStatusLastSeen, 800);

  function makeSiteChatMessage(text, target, meta, responseValue) {
    const now = Date.now();
    meta = meta && typeof meta === "object" ? meta : {};
    responseValue = responseValue && typeof responseValue === "object" ? responseValue : {};
    const fromProject = !!(
      meta.from_project || meta.as_project || meta.send_as_project
      || String(meta.initiator || meta.from || meta.send_as || responseValue.initiator || "").toLowerCase() === "project"
      || responseValue.initiator === "project"
    );
    // Frozen author from POST only — never current viewer / hardcoded staff.
    const saved = responseValue.initiator_client;
    if (!saved || typeof saved !== "object") return null;
    const name = String(responseValue.initiator_name || saved.name || "");
    const avatar = String((saved && saved.avatar) || responseValue.initiator_avatar || PLACEHOLDER);
    const client = Object.assign({}, saved, { name: name || saved.name, avatar: avatar, status: "online", online: true, is_online: true });
    if (fromProject) client.is_project = true;
    let cid = Number(saved.id || responseValue.actor_user_id || responseValue.initiator_id || 0);
    if (!cid || !isFinite(cid)) return null;
    client.id = cid;
    rememberStaffClient(client);
    let msgId = responseValue.id != null ? Number(responseValue.id) : 0;
    if (!msgId || !isFinite(msgId)) msgId = 0;
    const createdAt = Number(responseValue.created_at || now) || now;
    const unique = responseValue.unique_id || (msgId ? ("msg-" + msgId) : ("msg-live-" + now));
    return {
      id: msgId || ("tmp-" + now),
      M_ID: msgId || 0,
      unique_id: unique,
      steam_id: fromProject ? "project" : "site",
      initiator_id: asInitiatorId(cid),
      initiator: fromProject ? "project" : "client",
      initiator_name: name || saved.name || "",
      initiator_avatar: avatar,
      target_steam_id: target ? String(target) : (responseValue.target_steam_id || null),
      target_id: target ? String(target) : (responseValue.target_id || null),
      text: String(text || responseValue.text || responseValue.message || ""),
      message: String(text || responseValue.message || responseValue.text || ""),
      type: (target || responseValue.target_steam_id) ? "direct" : "global",
      is_team: false,
      created_at: createdAt,
      server_id: Number(responseValue.server_id || responseValue.serverId || 1) || 1,
      serverId: Number(responseValue.serverId || responseValue.server_id || 1) || 1,
      from_site: true,
      initiator_player: { steam_id: "0", steam_name: name || saved.name || "", steam_avatar: avatar, status: "online" },
      initiator_client: client,
      target_player: (target || responseValue.target_steam_id)
        ? { steam_id: String(target || responseValue.target_steam_id), steam_name: String(target || responseValue.target_steam_id), steam_avatar: PLACEHOLDER, status: "offline" }
        : null
    };
  }

  function publishCentrifuge(match, data) {
    let payload = data;
    if (payload == null || typeof payload !== "object") payload = {};
    const m = String(match || "");
    const isChat = m.includes("player-message") || m === "server-chat";
    const isCheckAct = m === "check-activity" || m.includes("check-activity");
    const isPlayerStatus = m === "player-status" || /player-status/.test(m);
    if (isChat) {
      // Live chat must be a single message object. {data:[msg]} is treated as history and prepends to the TOP.
      if (Array.isArray(data)) payload = data.length ? data[data.length - 1] : {};
      else if (data && Array.isArray(data.data) && data.data.length === 1) payload = data.data[0];
      else if (data && typeof data === "object" && (data.text || data.message || data.unique_id || data.id) && !Array.isArray(data.data)) payload = data;
      else if (data && Array.isArray(data.data) && data.data.length) payload = data.data[data.data.length - 1];
      else payload = data && typeof data === "object" ? data : {};
      if (payload && typeof payload === "object") {
        payload.initiator_id = asInitiatorId(payload.initiator_id, payload.steam_id);
        if (Array.isArray(payload.data)) delete payload.data;
        if (Array.isArray(payload.results)) delete payload.results;
        if (Array.isArray(payload.items)) delete payload.items;
      }
    }
    if (isCheckAct) {
      if (Array.isArray(data)) payload = data.length ? data[data.length - 1] : {};
      else if (data && data.check_id == null && data.checkId == null && data.data) payload = data.data;
      if (payload && typeof payload === "object") {
        const cid = Number(payload.check_id || payload.checkId || 0) || 0;
        if (cid) {
          payload.check_id = cid;
          payload.checkId = cid;
        }
        if (!payload.meta || typeof payload.meta !== "object") payload.meta = {};
        const text = payload.meta.message || payload.meta.text || payload.message || payload.text || payload.content || "";
        if (text) {
          payload.meta.message = payload.meta.message || text;
          payload.meta.text = payload.meta.text || text;
          payload.message = payload.message || text;
          payload.text = payload.text || text;
        }
        if (!payload.type && payload.kind) payload.type = payload.kind;
        if (!payload.kind && payload.type) payload.kind = payload.type;
      }
    }
    if (isPlayerStatus && (payload.players == null || typeof payload.players !== "object")) {
      payload = { players: {} };
    }
    if (m === "audit") {
      // AuditTable renders every realtime publication immediately with
      // `item.id.toString()`.  Do not forward protocol/heartbeat payloads
      // (or incomplete audit notifications) into that component.
      if (Array.isArray(payload)) payload = payload.length ? payload[0] : null;
      if (!payload || typeof payload !== "object") return;
      const auditId = payload.id != null ? payload.id : payload.M_ID;
      if (auditId == null || auditId === "") return;
      payload.id = auditId;
      if (payload.M_ID == null) payload.M_ID = auditId;
      if (!payload.meta || typeof payload.meta !== "object") payload.meta = {};
      if (!payload.type) return;
      if (!payload.client || typeof payload.client !== "object") {
        payload.client = deletedStaffStub(payload.client_id || payload.initiator_client_id || 0, payload.actor_name || "");
      }
      payload.client = ensureClientShape(payload.client, payload.actor_name || payload.client.name, payload.client.id);
      if (payload.client.M_ID == null) payload.client.M_ID = payload.client.id;
      if (payload.client_id == null) payload.client_id = payload.client.id;
    }
    if (m === "player" || m === "players") {
      if (payload.players == null || typeof payload.players !== "object") {
        if (Array.isArray(payload.data) || Array.isArray(payload.results) || Array.isArray(payload.online)) {
          payload = { players: {} };
        } else {
          const sid = String(payload.steam_id || payload.steamId || payload.playerId || "");
          const st = payload.status || payload.state || "online";
          payload = { players: sid ? { [sid]: st } : {} };
        }
      }
    }
    const socks = (window.__checkappCentrifugeSockets || centrifugeSockets).filter(function (ws) {
      return ws && ws.readyState === 1;
    });
    if (isCheckAct) {
      try {
        console.debug("[CHECK CHAT] Clients in room", socks.length);
      } catch (_) {}
    }
    // Prefer a single matching channel per socket to avoid duplicate UI inserts
    socks.forEach((ws) => {
      if (!ws || ws.readyState !== 1 || !ws.__subs) return;
      const channels = ws.__subs instanceof Set ? Array.from(ws.__subs) : Object.keys(ws.__subs);
      let best = null;
      channels.forEach((channel) => {
        if (!channel) return;
        const ch = String(channel);
        let hit = false;
        if (!m) hit = false;
        else if (isChat && /player-message/i.test(ch)) hit = true;
        else if (isChat && /server-chat/i.test(ch) && m.includes("server-chat")) hit = true;
        else if (isCheckAct && /check-activity/i.test(ch)) hit = true;
        else if (m === "player-status" && /player-status/i.test(ch)) hit = true;
        else if ((m === "player" || m === "players") && /player-status/i.test(ch)) hit = true;
        else if (m === "ban" && /ban/i.test(ch) && !/ban-sync/i.test(ch)) hit = true;
        else if (m === "audit" && /audit/i.test(ch)) hit = true;
        else if (m === "report" && /report/i.test(ch) && !/deleted/i.test(ch)) hit = true;
        else if (/check-started|check-finished|check-finish/.test(m) && new RegExp(m.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i").test(ch)) hit = true;
        else if (ch === m || ch.endsWith("/" + m) || ch.endsWith(":" + m)) hit = true;
        else if (m.length > 8 && ch.includes(m) && !/player-message|player-status|player-alert|player-mute|player-comment/i.test(ch)) hit = true;
        if (!hit) return;
        if (!best) best = channel;
        else if (isCheckAct && /check-activity/i.test(ch)) best = channel;
        else if (isChat && /player-message/i.test(ch)) best = channel;
      });
      if (!best) return;
      const emit = ws.__emit || function () {};
      emit("message", {
        data: JSON.stringify({
          push: { channel: best, pub: { data: payload, offset: Date.now() } }
        })
      });
    });
  }

  function readConnectServerName() {
    try {
      const el = document.getElementById("checkapp-server-name");
      const typed = el ? String(el.value || "").trim() : "";
      if (typed) {
        window.__checkappPairServerName = typed;
        return typed;
      }
    } catch (_) {}
    return String(window.__checkappPairServerName || "").trim();
  }

  function attachPairServerName(url, method, body) {
    if (!/\/server\/pair/.test(String(url || ""))) return body;
    const name = readConnectServerName();
    if (!name) return body;
    if (typeof body === "string") {
      try {
        const obj = body ? JSON.parse(body) : {};
        if (!obj.name && !obj.hostname) obj.name = name;
        return JSON.stringify(obj);
      } catch (_) {
        return body;
      }
    }
    if (body && typeof body === "object") {
      if (!body.name && !body.hostname) body.name = name;
      return body;
    }
    if (body == null || body === "") return JSON.stringify({ name: name });
    return body;
  }

  function sanitizeChatPost(url, method, body) {
    if (String(method || "GET").toUpperCase() !== "POST") return body;
    if (!String(url || "").includes("/player-message")) return body;
    function clean(obj) {
      if (!obj || typeof obj !== "object") return obj;
      const target = obj.target_steam_id || obj.reply_steam_id || obj.to_steam_id;
      if (target == null || target === "" || !/^\d{10,}$/.test(String(target).trim())) {
        obj.target_steam_id = null;
        obj.reply_steam_id = null;
        obj.to_steam_id = null;
      }
      return obj;
    }
    if (typeof body === "string") {
      try { return JSON.stringify(clean(JSON.parse(body))); } catch (_) { return body; }
    }
    return clean(body);
  }

  function maybePublishBan(url, method, responseObj) {
    const href = String(url || "");
    const verb = String(method || "GET").toUpperCase();
    if (verb !== "PUT" && verb !== "POST") return;
    if (!/\/players\/[^/]+\/ban(?:\?|$)/i.test(href) && href !== "/ban" && href !== "/ban/") return;
    window.__caBanJustNow = Date.now();
    const bans = (responseObj && (responseObj.bans || responseObj.data)) || [];
    const list = Array.isArray(bans) ? bans : [];
    if (list.length && list.every(function (ban) { return ban && ban.pending; })) return;
    list.forEach(function (ban) {
      if (!ban || typeof ban !== "object" || ban.pending) return;
      publishCentrifuge("ban", ban);
      publishCentrifuge("ban-update", ban);
      publishCentrifuge("player-ban", ban);
    });
    try {
      pollLive("/ban/browse?limit=30", "ban", "ban");
    } catch (_) {}
    if (onCheckPage()) {
      const cid = Number(checkPageId() || window.__caLastCheckId || 0) || 0;
      if (cid) {
        const staff = staffProfile();
        const data = {
          id: cid,
          check_id: cid,
          status: "FinishedBan",
          verdict: "Бан",
          bans: list
        };
        publishActivityItem({
          id: "finished-ban-" + cid,
          M_ID: cid,
          check_id: cid,
          checkId: cid,
          type: "Finished",
          kind: "Finished",
          created_at: Date.now(),
          meta: { status: "FinishedBan", verdict: "Бан", client_id: staff.id },
          initiator_client: staff
        });
        publishCentrifuge("check-finished", data);
        publishCentrifuge("check-finish", data);
        publishCentrifuge("project:check-finished", data);
      }
    }
    try {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", keyCode: 27, which: 27, bubbles: true }));
    } catch (_) {}
  }

  function scrollChatToBottom(force) {
    try {
      if (/\/checks\//.test(String(location.pathname || ""))) return;
      const el = document.getElementById("player-message-page-list-container");
      if (!el || el.scrollHeight < 40) return;
      const fd = String((window.getComputedStyle(el) || {}).flexDirection || "");
      const reverse = /reverse/i.test(fd);
      const nearBottom = reverse
        ? el.scrollTop < 80
        : (el.scrollHeight - el.clientHeight - el.scrollTop) < 80;
      if (!force && !nearBottom) return;
      const pinia = piniaRoot();
      const sc = pinia && pinia._s && pinia._s.get("player-message-scroll-store");
      if (sc && typeof sc.scrollToBottomInstant === "function") {
        try { sc.scrollToBottomInstant("instant"); return; } catch (_) {}
      }
      if (reverse) el.scrollTop = 0;
      else el.scrollTop = el.scrollHeight;
    } catch (_) {}
  }

  function chatPaneIsReverse() {
    try {
      const prefer = document.getElementById("player-message-page-list-container");
      if (prefer) {
        const selfFd = String((window.getComputedStyle(prefer) || {}).flexDirection || "");
        if (/reverse/i.test(selfFd)) return true;
        const kids = prefer.querySelectorAll("[class*='overflow'], [class*='flex'], [class*='messages']");
        for (let i = 0; i < kids.length; i++) {
          const fd = String((window.getComputedStyle(kids[i]) || {}).flexDirection || "");
          if (/reverse/i.test(fd)) return true;
        }
        return false;
      }
      const nodes = document.querySelectorAll("[class*='chat'] [class*='overflow'], [class*='messages'] [class*='overflow']");
      for (let i = 0; i < nodes.length; i++) {
        const el = nodes[i];
        if (!el || el.scrollHeight < 40) continue;
        const fd = String((window.getComputedStyle(el) || {}).flexDirection || "");
        if (/reverse/i.test(fd)) return true;
      }
    } catch (_) {}
    return false;
  }

  function injectSiteChatMessage(msg) {
    if (!msg || typeof msg !== "object") return;
    if (msg.is_team || String(msg.type || "").toLowerCase() === "team") return;
    const key = String(msg.unique_id || msg.id || "");
    if (!key) return;
    function place(arr, bag, k) {
      if (!Array.isArray(arr)) return;
      const sample = arr[0];
      if (sample && sample.initiator_id == null && sample.unique_id == null && sample.text == null && sample.message == null) return;
      const idx = arr.findIndex(function (row) { return row && String(row.unique_id || row.id) === key; });
      if (idx >= 0) arr.splice(idx, 1);
      arr.push(msg);
      if (bag && k && bag[k] && typeof bag[k] === "object" && "value" in bag[k]) {
        bag[k].value = arr.slice();
      }
    }
    try {
      const root = document.querySelector("#app");
      const app = root && root.__vue_app__;
      function visit(comp) {
        if (!comp) return;
        try {
          [comp.exposed, comp.setupState, comp.ctx].forEach(function (bag) {
            if (!bag || typeof bag !== "object") return;
            ["messages", "items", "list", "chat"].forEach(function (k) {
              const v = bag[k];
              const arr = v && Array.isArray(v.value) ? v.value : (Array.isArray(v) ? v : null);
              if (arr) place(arr, bag, k);
            });
          });
        } catch (_) {}
        const vn = comp.subTree;
        const walkVn = function (node) {
          if (!node) return;
          if (node.component) visit(node.component);
          if (Array.isArray(node.children)) node.children.forEach(walkVn);
        };
        walkVn(vn);
      }
      if (app && app._instance) visit(app._instance);
      const pinia = app && app.config && app.config.globalProperties && app.config.globalProperties.$pinia;
      if (pinia && pinia._s) {
        pinia._s.forEach(function (store) {
          ["messages", "items", "list"].forEach(function (k) {
            const v = store[k];
            const arr = v && Array.isArray(v.value) ? v.value : (Array.isArray(v) ? v : null);
            if (arr && arr[0] && (arr[0].initiator_id != null || arr[0].unique_id != null)) place(arr, store, k);
          });
        });
      }
    } catch (_) {}
    scrollChatToBottom();
  }

  function maybePublishChat(url, method, body, responseJson) {
    const href = String(url || "");
    const verb = String(method || "GET").toUpperCase();
    if (verb !== "POST" || !href.includes("/player-message")) return;
    let parsed = body;
    if (typeof body === "string") {
      try { parsed = JSON.parse(body); } catch (_) { parsed = {}; }
    }
    if (!parsed || typeof parsed !== "object") return;
    const text = String(parsed.text || parsed.message || "").trim();
    if (!text) return;
    const target = parsed.target_steam_id || parsed.reply_steam_id || parsed.to_steam_id || null;
    // Extract real message payload from POST response (id, created_at, initiator)
    let value = null;
    if (Array.isArray(responseJson) && responseJson[0]) {
      value = responseJson[0].value || responseJson[0];
    } else if (responseJson && typeof responseJson === "object") {
      if (responseJson.value) value = responseJson.value;
      else if (Array.isArray(responseJson.data) && responseJson.data[0]) {
        value = responseJson.data[0].value || responseJson.data[0];
      } else if (responseJson.id != null) value = responseJson;
    }
    const msg = makeSiteChatMessage(text, target, parsed, value || {});
    if (!msg) return;
    // Dedup by unique_id / id so pollLive does not reshuffle
    window.__checkappChatSeen = window.__checkappChatSeen || new Set();
    const seenKey = String(msg.unique_id || msg.id);
    if (window.__checkappChatSeen.has(seenKey)) return;
    window.__checkappChatSeen.add(seenKey);
    injectSiteChatMessage(msg);
    try {
      const pinia = piniaRoot();
      const chat = pinia && pinia._s && pinia._s.get("player-message-page-data");
      settleSiteChatMessages(chat);
    } catch (_) {}
    scrollChatToBottom(true);
  }

  function activityItemKey(row) {
    return String((row && (row.id != null ? row.id : row.M_ID)) || "");
  }
  function mergeActivityRows(a, b) {
    const byId = {};
    (Array.isArray(a) ? a : []).concat(Array.isArray(b) ? b : []).forEach(function (row) {
      const key = activityItemKey(row);
      if (!key) return;
      byId[key] = row;
    });
    return Object.keys(byId).map(function (k) { return byId[k]; }).sort(function (x, y) {
      const tx = Number((x && (x.created_at || x.createdAt)) || 0);
      const ty = Number((y && (y.created_at || y.createdAt)) || 0);
      if (tx !== ty) return tx - ty;
      return activityItemKey(x).localeCompare(activityItemKey(y));
    });
  }
  function writeActivityRef(ref, rows) {
    if (!ref || !Array.isArray(rows)) return false;
    try {
      if (typeof ref === "object" && ("value" in ref || ref.__v_isRef)) {
        const cur = Array.isArray(ref.value) ? ref.value : [];
        if (cur.length === rows.length) {
          let same = true;
          for (let i = 0; i < rows.length; i++) {
            if (activityItemKey(cur[i]) !== activityItemKey(rows[i])) { same = false; break; }
          }
          if (same) return true;
        }
        ref.value = rows.slice();
        return true;
      }
      if (Array.isArray(ref)) {
        const merged = mergeActivityRows(ref, rows);
        if (merged.length === ref.length) return true;
        ref.splice(0, ref.length);
        merged.forEach(function (row) { ref.push(row); });
        return true;
      }
    } catch (_) {}
    return false;
  }
  function walkVueTree(comp, fn, seen) {
    if (!comp || typeof comp !== "object") return;
    seen = seen || new Set();
    if (seen.has(comp)) return;
    seen.add(comp);
    try { fn(comp); } catch (_) {}
    function walkNode(node) {
      if (!node || typeof node !== "object") return;
      if (seen.has(node)) return;
      seen.add(node);
      if (node.component) walkVueTree(node.component, fn, seen);
      if (node.suspense) {
        walkNode(node.suspense.activeBranch);
        walkNode(node.suspense.vnode);
      }
      const ch = node.children;
      if (Array.isArray(ch)) ch.forEach(walkNode);
      else if (ch && typeof ch === "object") {
        if (ch.component) walkVueTree(ch.component, fn, seen);
        Object.keys(ch).forEach(function (k) {
          const slot = ch[k];
          if (typeof slot === "function") return;
          walkNode(slot);
        });
      }
      if (Array.isArray(node.dynamicChildren)) node.dynamicChildren.forEach(walkNode);
    }
    walkNode(comp.subTree || comp.vnode || comp.__vnode);
  }
  function currentCheckActivityRows(cid) {
    const wanted = String(cid || checkPageId() || "");
    const stub = Array.isArray(window.__caActivityStub) ? window.__caActivityStub : [];
    return wanted ? stub.filter(function(row) {return row && String(row.check_id || row.checkId || "") === wanted;}) : [];
  }
  function syncCheckActivityIntoVue(extraItem) {
    const pageId = String(checkPageId() || window.__caLastCheckId || "");
    if (!pageId || !onCheckPage()) return;
    let rows = currentCheckActivityRows();
    if (extraItem && extraItem.id != null) rows = mergeActivityRows(rows, [extraItem]);
    rows = rows.filter(function(row){return row && String(row.check_id || row.checkId || "") === pageId;});
    try {
      const root = document.querySelector("#app");
      const app = root && root.__vue_app__;
      const inst = app && app._instance;
      function looksActivitySlot(slot, allowEmpty) {
        if (slot == null) return false;
        const arr = (slot && typeof slot === "object" && ("value" in slot || slot.__v_isRef)) ? slot.value : slot;
        if (arr == null) return !!allowEmpty;
        if (!Array.isArray(arr)) return false;
        if (!arr.length) return true;
        const row = arr[0];
        return !!(row && (row.type || row.kind || row.check_id != null || row.checkId != null || row.meta));
      }
      function applyComp(comp) {
        if (!comp) return;
        const type = comp.type || {};
        const name = String(type.__name || type.name || "");
        const isActivity = name === "CheckExactLeftActivity";
        const bags = [comp.exposed, comp.setupState, comp.devtoolsRawSetupState, comp.ctx];
        bags.forEach(function (bag) {
          if (!bag || typeof bag !== "object") return;
          const keys = isActivity ? ["activities", "activity", "r"] : ["activities", "activity"];
          keys.forEach(function (key) {
            const slot = bag[key];
            if (!looksActivitySlot(slot, isActivity && (key === "activities" || key === "r"))) return;
            writeActivityRef(slot, rows);
          });
        });
      }
      if (inst) walkVueTree(inst, applyComp);
      try {
        document.querySelectorAll(".activity, .check-content").forEach(function (el) {
          const parent = el && (el.__vueParentComponent || el.__vnode && el.__vnode.component);
          if (parent) applyComp(parent);
        });
      } catch (_) {}
      try {
        const pinia = app && app.config && app.config.globalProperties && app.config.globalProperties.$pinia;
        if (pinia && pinia._s) {
          pinia._s.forEach(function (store) {
            try {
              ["activities", "activity"].forEach(function (key) {
                if (looksActivitySlot(store[key], false)) writeActivityRef(store[key], rows);
              });
            } catch (_) {}
          });
        }
      } catch (_) {}
    } catch (_) {}
    try { window.__caActivityStub = rows; } catch (_) {}
  }
  function injectCheckActivityIntoVue(item) {
    if (!item || item.id == null) return;
    const wanted = checkPageId();
    if (wanted && String(item.check_id || item.checkId || "") !== String(wanted)) return;
    try {
      if (!Array.isArray(window.__caActivityStub)) window.__caActivityStub = [];
      const exists = window.__caActivityStub.some(function (row) { return activityItemKey(row) === activityItemKey(item); });
      if (!exists) window.__caActivityStub.push(item);
    } catch (_) {}
    syncCheckActivityIntoVue(item);
  }

  const checkActivitySeen = (window.__checkActivitySeen = window.__checkActivitySeen || new Set());
  let lastPolledCheck = "";
  function checkPageId() {
    const m = String(location.pathname || "").match(/\/checks\/(\d+)/);
    return m ? m[1] : "";
  }
  function onCheckPage() {
    return /\/checks(\/|$|\?)/.test(String(location.pathname || ""));
  }
  function rememberCheckSteamFromBody(url, method, body) {
    if (String(method || "GET").toUpperCase() !== "POST") return;
    const href = String(url || "").replace(location.origin, "");
    if (!/\/check/.test(href) || /\/activity|notice-state|browse/.test(href)) return;
    let parsed = body;
    if (typeof body === "string") {
      const raw = body.trim();
      if (/^7656119\d{10}$/.test(raw)) {
        window.__caCheckSteam = raw;
        return;
      }
      try { parsed = JSON.parse(body); } catch (_) { parsed = {}; }
    }
    if (typeof parsed === "number" || (typeof parsed === "string" && /^7656119\d{10}$/.test(String(parsed)))) {
      window.__caCheckSteam = String(parsed);
      return;
    }
    if (!parsed || typeof parsed !== "object") return;
    const player = (parsed.player && typeof parsed.player === "object") ? parsed.player : {};
    const suspect = (parsed.suspect && typeof parsed.suspect === "object") ? parsed.suspect : {};
    const sid = String(parsed.steam_id || parsed.target_steam_id || parsed.suspect_steam_id || player.steam_id || suspect.steam_id || "").trim();
    const name = String(parsed.steam_name || parsed.name || player.steam_name || player.name || suspect.steam_name || "").trim();
    if (sid && sid !== "0") window.__caCheckSteam = sid;
    if (name && name !== "." && !/^admin$/i.test(name)) window.__caCheckName = name;
    if (sid && !window.__caCheckName) {
      try {
        const pinia = piniaRoot();
        if (pinia && pinia._s) {
          pinia._s.forEach(function (store) {
            if (window.__caCheckName || !store) return;
            const p = store.player || (store.$state && store.$state.player);
            if (p && String(p.steam_id) === sid) window.__caCheckName = p.steam_name || p.name || "";
          });
        }
      } catch (_) {}
    }
  }
  function buildCheckStub(cid, sid, name) {
    const id = Number(cid) || 0;
    const steam = String(sid || window.__caCheckSteam || "");
    const steamName = String(name || window.__caCheckName || steam || "");
    const staff = staffProfile();
    const player = {
      steam_id: steam,
      steam_name: steamName,
      name: steamName,
      team: [],
      steam_avatar: PLACEHOLDER,
      status: "online",
      online: true,
      steam: true,
      entity: {
        team: [],
        home: { time: 0, value: false },
        position: { x: 0, y: 0, z: 0, time: 0 },
        rotation: { x: 0, y: 0, z: 0, time: 0 },
        coords: { value: "", time: 0 },
        meta: { tags: {}, fields: {} },
        raid: { value: false },
        last_moved_seconds: 0
      },
      steam_data: {
        personaname: steamName,
        avatar: PLACEHOLDER,
        signed_at: 0,
        updated_at: Date.now(),
        unavailable: false,
        ban_data: { game_ban: { count: 0 }, vac_ban: { count: 0 } }
      },
      server: { id: 0, name: "", connected: false, offline: true }
    };
    return {
      id: id,
      status: "Pending",
      state: "Pending",
      steam_id: steam,
      finished_at: null,
      created_at: Date.now(),
      started_at: Date.now(),
      notice: false,
      notice_state: false,
      suspect_team: [],
      team: [],
      team_steam_ids: [],
      client_id: staff.id || 1,
      checker_id: staff.id || 1,
      player: player,
      suspect: player,
      target_player: player,
      checker: staff,
      moderator: staff,
      initiator_client: staff
    };
  }
  function applyCheckStubFromExact(result) {
    if (!result || typeof result !== "object" || Array.isArray(result)) return;
    const sid = String(result.steam_id || (result.suspect && result.suspect.steam_id) || (result.player && result.player.steam_id) || window.__caCheckSteam || "");
    if (sid) window.__caCheckSteam = sid;
    const name = String((result.suspect && (result.suspect.steam_name || result.suspect.name)) || (result.player && (result.player.steam_name || result.player.name)) || window.__caCheckName || "");
    if (name) window.__caCheckName = name;
    if (!result.steam_id && sid) result.steam_id = sid;
    if (result.suspect && !result.suspect.steam_id && sid) result.suspect.steam_id = sid;
    if (result.player && !result.player.steam_id && sid) result.player.steam_id = sid;
    if (!result.suspect) result.suspect = result.player || { steam_id: sid, steam_name: name, name: name, team: [] };
    if (!result.player) result.player = result.suspect;
    if (!result.target_player) result.target_player = result.suspect;
    if (!Array.isArray(result.suspect_team)) result.suspect_team = [];
    if (!Array.isArray(result.team)) result.team = [];
    if (!Array.isArray(result.team_steam_ids)) result.team_steam_ids = result.suspect_team.slice();
    window.__caCheckStub = result;
  }
  function peekVue(bag, key) {
    if (!bag || typeof bag !== "object") return undefined;
    try {
      const cur = bag[key];
      if (cur && typeof cur === "object" && cur.__v_isRef) return cur.value;
      return cur;
    } catch (_) {
      return undefined;
    }
  }
  function playerStatusRank(p) {
    const s = String((p && p.status) || "offline");
    if (s === "online" || s === "active" || s === "afk") return 2;
    if (s === "joining" || s === "queued") return 1;
    return 0;
  }
  function mergeCheckLive(cur, live) {
    if (!cur || !live || typeof cur !== "object" || typeof live !== "object") return;
    const lp = live.player || live.suspect;
    if (!lp || typeof lp !== "object") return;
    ["suspect", "player", "target_player"].forEach(function (k) {
      const src = (live[k] && typeof live[k] === "object") ? live[k] : lp;
      const slot = cur[k];
      if (!slot || typeof slot !== "object") {
        cur[k] = src;
        return;
      }
      if (playerStatusRank(src) > playerStatusRank(slot)) slot.status = src.status;
      const se = slot.entity && typeof slot.entity === "object" ? slot.entity : null;
      const le = src.entity && typeof src.entity === "object" ? src.entity : null;
      if (le) {
        const liveTags = le.meta && le.meta.tags ? Object.keys(le.meta.tags).length : 0;
        const curTags = se && se.meta && se.meta.tags ? Object.keys(se.meta.tags).length : 0;
        const liveTime = (le.position && Number(le.position.time || 0)) || 0;
        const curTime = (se && se.position && Number(se.position.time || 0)) || 0;
        if (!se || liveTags > curTags || liveTime >= curTime) slot.entity = le;
      }
      if (src.server && (src.server.id || src.server.name) && (!slot.server || !slot.server.id)) slot.server = src.server;
      if (src.home && (src.home.value || src.home.time)) slot.home = src.home;
      if (src.position && (src.position.x || src.position.z || src.position.time)) slot.position = src.position;
      if (src.coords && src.coords.value) slot.coords = src.coords;
    });
    if (!cur.suspect) cur.suspect = cur.player;
    if (!cur.player) cur.player = cur.suspect;
    if (!cur.target_player) cur.target_player = cur.suspect || cur.player;
  }
  function writeCheckIfEmpty(bag, key, stub) {
    if (!stub || typeof stub !== "object") return;
    const cur = peekVue(bag, key);
    const newSid = String((stub && (stub.steam_id || (stub.suspect && stub.suspect.steam_id) || (stub.player && stub.player.steam_id))) || window.__caCheckSteam || "");
    if (cur == null) {
      writeVueRef(bag, key, stub);
      return;
    }
    if (typeof cur !== "object" || Array.isArray(cur)) {
      if (newSid) writeVueRef(bag, key, stub);
      return;
    }
    const curSid = String(cur.steam_id || (cur.suspect && cur.suspect.steam_id) || (cur.player && cur.player.steam_id) || "");
    if ((!curSid || curSid === "0" || curSid === ".") && newSid) {
      writeVueRef(bag, key, stub);
      return;
    }
    const sid = newSid;
    if (sid && (!cur.steam_id || cur.steam_id === "0" || cur.steam_id === ".")) cur.steam_id = sid;
    const sname = String((stub && ((stub.suspect && stub.suspect.steam_name) || (stub.player && stub.player.steam_name))) || window.__caCheckName || "");
    ["suspect", "player", "target_player"].forEach(function (k) {
      if (!cur[k] || typeof cur[k] !== "object") {
        if (stub && stub[k]) cur[k] = stub[k];
        return;
      }
      if (sid && (!cur[k].steam_id || cur[k].steam_id === "0" || cur[k].steam_id === ".")) cur[k].steam_id = sid;
      if (sname && (!cur[k].steam_name || cur[k].steam_name === "." || cur[k].steam_name === "0")) {
        cur[k].steam_name = sname;
        cur[k].name = sname;
      }
    });
    if (!cur.suspect && stub && stub.suspect) cur.suspect = stub.suspect;
    if (!cur.player && stub && stub.player) cur.player = stub.player;
    if (!cur.target_player) cur.target_player = cur.suspect || cur.player;
    if (!Array.isArray(cur.suspect_team)) cur.suspect_team = [];
    mergeCheckLive(cur, stub);
  }
  function writeActIfEmpty(bag, key, stubAct) {
    if (!Array.isArray(stubAct) || !stubAct.length) return;
    const cur = peekVue(bag, key);
    if (cur == null) {
      writeVueRef(bag, key, stubAct.slice());
      return;
    }
    if (!Array.isArray(cur)) return;
    const merged = mergeActivityRows(cur, stubAct);
    if (merged.length !== cur.length) writeVueRef(bag, key, merged);
  }
  function forceCheckIntoVue(check) {
    if (!check || typeof check !== "object") return;
    if (!onCheckPage()) return;
    const cid = Number(check.id || checkPageId() || window.__caLastCheckId || 0) || 0;
    try {
      const root = document.querySelector("#app");
      const app = root && root.__vue_app__;
      const inst = app && app._instance;
      function visit(comp) {
        if (!comp) return;
        try {
          const setup = comp.setupState || {};
          const exposed = comp.exposed || {};
          const ctx = comp.ctx || {};
          const raw = comp.devtoolsRawSetupState || {};
          const props = comp.props || {};
          const type = comp.type || {};
          const name = String(type.__name || type.name || "");
          const bags = [raw, setup, ctx, exposed];
          if (name === "ChecksPageExact" || (props.id != null && (Number(props.id) === cid || String(props.id) === String(cid)))) {
            bags.forEach(function (bag) { writeCheckIfEmpty(bag, "r", check); });
          }
        } catch (_) {}
        const vn = comp.subTree;
        const walk = function (node) {
          if (!node) return;
          if (node.component) visit(node.component);
          if (Array.isArray(node.children)) node.children.forEach(walk);
        };
        walk(vn);
      }
      if (inst) visit(inst);
    } catch (_) {}
  }

  function goToCheckPage(cid) {
    const n = Number(cid && typeof cid === "object" ? (cid.id || cid.check_id || cid.checkId) : cid) || 0;
    const id = String(n);
    if (!id || id === "0" || !/^\d+$/.test(id)) return;
    try { window.__caLastCheckId = n; } catch (_) {}
    try { window.__caForceCheckUntil = Date.now() + 8000; } catch (_) {}
    try {
      sessionStorage.setItem("ca_force_check", JSON.stringify({
        id: n,
        until: Date.now() + 8000,
        slug: (typeof currentProjectSlug === "function" && currentProjectSlug()) || ""
      }));
    } catch (_) {}
    try {
      if (new RegExp("/checks/" + id + "(/|$)").test(String(location.pathname || ""))) return;
      const dest = checkDestForId(n);
      if (!dest) return;
      window.location.assign(dest);
      return;
    } catch (_) {}
  }
  function writeVueRef(bag, key, val) {
    if (!bag || typeof bag !== "object") return false;
    try {
      const cur = bag[key];
      if (cur && typeof cur === "object" && "value" in cur) {
        cur.value = val;
        return true;
      }
      bag[key] = val;
      return true;
    } catch (_) {
      return false;
    }
  }
  function unblockCheckUi() {
    if (!onCheckPage()) return;
    const cid = Number(checkPageId() || window.__caLastCheckId || 0) || 0;
    if (!cid) return;
    const stubCheck = (window.__caCheckStub && Number(window.__caCheckStub.id) === cid)
      ? window.__caCheckStub
      : buildCheckStub(cid, window.__caCheckSteam, window.__caCheckName);
    if (!stubCheck.suspect) stubCheck.suspect = stubCheck.player || { steam_id: String(window.__caCheckSteam || ""), steam_name: "", team: [] };
    if (window.__caCheckSteam) {
      const sid = String(window.__caCheckSteam);
      if (!stubCheck.steam_id) stubCheck.steam_id = sid;
      if (stubCheck.suspect && !stubCheck.suspect.steam_id) stubCheck.suspect.steam_id = sid;
      if (stubCheck.player && !stubCheck.player.steam_id) stubCheck.player.steam_id = sid;
    }
    const stubAct = currentCheckActivityRows(cid).length
      ? currentCheckActivityRows(cid)
      : [{ id: "started-" + cid, M_ID: cid, check_id: cid, checkId: cid, type: "Started", kind: "Started", created_at: Date.now(), meta: {} }];
    try {
      const root = document.querySelector("#app");
      const app = root && root.__vue_app__;
      const inst = app && app._instance;
      function visit(comp) {
        if (!comp) return;
        try {
          const setup = comp.setupState || {};
          const exposed = comp.exposed || {};
          const ctx = comp.ctx || {};
          const raw = comp.devtoolsRawSetupState || {};
          const props = comp.props || {};
          const type = comp.type || {};
          const name = String(type.__name || type.name || "");
          const bags = [raw, setup, ctx, exposed];
          if (name === "ChecksPageExact" || (props.id != null && (Number(props.id) === cid || String(props.id) === String(cid)))) {
            bags.forEach(function (bag) {
              writeCheckIfEmpty(bag, "r", stubCheck);
            });
          }
          const cidProp = props.checkId != null ? props.checkId : props["check-id"];
          if (name === "CheckExactLeftActivity" || (cidProp != null && (Number(cidProp) === cid || String(cidProp) === String(cid)))) {
            bags.forEach(function (bag) {
              writeActIfEmpty(bag, "activities", stubAct);
              writeActIfEmpty(bag, "r", stubAct);
            });
          }
        } catch (_) {}
        const vn = comp.subTree;
        const walk = function (node) {
          if (!node) return;
          if (node.component) visit(node.component);
          if (Array.isArray(node.children)) node.children.forEach(walk);
        };
        walk(vn);
      }
      if (inst) visit(inst);
    } catch (_) {}
  }
  // A check is created before Vue mounts the route components.  The original
  // code prepared a stub but never put it into those components, leaving both
  // panels on their loading skeleton until a manual F5.  Retry briefly while
  // the navigation mounts, then the normal API response replaces this stub.
  function scheduleCheckUiUnblock() {
    [0, 30, 100, 250, 600, 1200, 2500, 4000].forEach(function (delay) {
      setTimeout(function () {
        unblockCheckUi();
        syncCheckActivityIntoVue();
      }, delay);
    });
  }
  function guardRouterOpen() {
    try {
      const root = document.querySelector("#app");
      const app = root && root.__vue_app__;
      const router = app && app.config && app.config.globalProperties && app.config.globalProperties.$router;
      if (!router || router.__checkappOpenGuarded) return;
      router.__checkappOpenGuarded = true;
      ["push", "replace"].forEach(function (m) {
        if (typeof router[m] !== "function") return;
        const orig = router[m].bind(router);
        router[m] = function (to) {
          try {
            const destPath = typeof to === "string" ? to : String((to && (to.path || to.fullPath || to.name)) || "");
            if (window.__caLastCheckId && Date.now() < (window.__caForceCheckUntil || 0)) {
              const dest = checkDestForId(window.__caLastCheckId);
              if (dest && /(^|\/)(client\/)?profile(?:\/|$|\?|#)|^\/$|^\/client(?:\/auth)?(?:\/|$|\?|#)|projects|onboarding/i.test(destPath)) {
                return orig(dest);
              }
            }
            if (to && typeof to === "object") {
              const params = to.params ? Object.assign({}, to.params) : {};
              const slug = currentProjectSlug();
              if (slug && /check|player|report|ban|court|mute|alert|signage|chat/i.test(destPath + String(to.name || ""))) {
                if (!params.project || params.project === "undefined" || params.project === "checks") {
                  params.project = slug;
                }
              }
              let id = params.id || params.check_id || params.checkId || params.check;
              if (id == null) id = to.id || to.check_id || to.checkId || (to.query && (to.query.id || to.query.check_id || to.query.checkId));
              if (id && typeof id === "object") id = id.id || id.check_id || id.checkId;
              // Never replace a historical check's pending route parameter
              // with the last active check ID.
              if (id != null && id !== "undefined" && id !== "") params.id = String(id);
              else delete params.id;
              const query = to.query && typeof to.query === "object" ? Object.assign({}, to.query) : to.query;
              if (query && typeof query === "object") {
                Object.keys(query).forEach(function (k) {
                  if (query[k] == null || query[k] === "undefined" || query[k] === "null") delete query[k];
                  else if (typeof query[k] === "object") {
                    const nested = query[k].id || query[k].steam_id;
                    if (nested != null) query[k] = nested;
                    else delete query[k];
                  }
                });
              }
              to = Object.assign({}, to, { params: params, query: query });
            }
          } catch (_) {}
          return orig(to);
        };
      });
      if (!router.__checkappCheckAfter && typeof router.afterEach === "function") {
        router.__checkappCheckAfter = true;
        router.afterEach(function (to) {
          try {
            const path = String((to && to.fullPath) || (to && to.path) || location.pathname || "");
            if (/\/checks\/\d+/.test(path)) scheduleCheckUiUnblock();
          } catch (_) {}
        });
      }
    } catch (_) {}
  }
  setTimeout(guardRouterOpen, 200);
  setInterval(guardRouterOpen, 800);
  // Prefer the ID encoded by a historical check row over Vue's generic
  // "open active check" handler.  Capture phase runs before that handler.
  document.addEventListener("click", function (ev) {
    try {
      let node = ev.target;
      for (let i = 0; i < 12 && node; i += 1, node = node.parentElement) {
        const href = String((node.getAttribute && node.getAttribute("href")) || "");
        const hit = href.match(/\/checks\/(\d+)(?:[/?#]|$)/);
        if (!hit) continue;
        const id = hit[1];
        if (String(checkPageId() || "") === id) return;
        ev.preventDefault();
        ev.stopImmediatePropagation();
        const parts = String(location.pathname || "").split("/").filter(Boolean);
        const slug = parts[0] || "";
        location.assign((slug ? "/" + slug : "") + "/checks/" + id);
        return;
      }
      // The table body uses a div click handler rather than an anchor.  Read
      // the #ID from that row before Vue falls back to the active check.
      if (/\/checks\/?$/.test(String(location.pathname || ""))) {
        node = ev.target;
        for (let i = 0; i < 10 && node; i += 1, node = node.parentElement) {
          // Find the ID leaf inside this specific row.  Reading the whole
          // page container always selected the first row (#1).
          const leaves = [node].concat(Array.from(node.querySelectorAll ? node.querySelectorAll("span,p,div,a,button") : []));
          const hitNode = leaves.find(function (el) {
            return el && (!el.children || el.children.length === 0) && /^#\d+$/.test(String(el.textContent || "").trim());
          });
          const hit = hitNode && String(hitNode.textContent || "").trim().match(/^#(\d+)$/);
          if (!hit) continue;
          ev.preventDefault();
          ev.stopImmediatePropagation();
          const parts = String(location.pathname || "").split("/").filter(Boolean);
          const slug = parts[0] || "";
          location.assign((slug ? "/" + slug : "") + "/checks/" + hit[1]);
          return;
        }
      }
    } catch (_) {}
  }, true);
  function publishActivityItem(item) {
    if (!item || item.id == null) return;
    const wanted = checkPageId();
    if (wanted && String(item.check_id || item.checkId || "") !== String(wanted)) return;
    const key = String(item.check_id || item.checkId || "") + ":" + String(item.id);
    // Never inject fake finish chat bubbles into the check timeline
    const txt = String(item.text || item.message || "").trim().toLowerCase();
    if (txt.indexOf("проверка завершена") === 0 || txt.indexOf("check finished") === 0) {
      if (String(item.type || item.kind || "") !== "Finished") {
        checkActivitySeen.add(key);
        return;
      }
      delete item.text;
      delete item.message;
    }
    const already = checkActivitySeen.has(key);
    if (!already) checkActivitySeen.add(key);
    if (!item.meta || typeof item.meta !== "object") item.meta = {};
    if (item.meta.client_id != null) {
      const nid = Number(item.meta.client_id);
      if (nid) item.meta.client_id = nid;
    }
    if (item.initiator_client) {
      rememberStaffClient(item.initiator_client);
      delete item.initiator_client.is_moderator;
      delete item.initiator_client.isModerator;
      delete item.initiator_client.moderator;
      delete item.initiator_client.is_staff;
      delete item.initiator_client.isStaff;
    }
    const cid = item.check_id != null ? item.check_id : item.checkId;
    const cidNum = Number(cid);
    const cidStr = String(cidNum || cid || "");
    const base = Object.assign({}, item, {
      check_id: cidNum || cid,
      checkId: cidNum || cid,
      check_id_str: cidStr
    });
    try {
      console.debug("[CHECK CHAT] Event received", "checkId", cidNum, "id", key, "type", item.type);
    } catch (_) {}
    if (!already) publishCentrifuge("check-activity", base);
    try {
      if (!Array.isArray(window.__caActivityStub)) window.__caActivityStub = [];
      const exists = window.__caActivityStub.some(function (row) { return row && String(row.id) === String(item.id); });
      if (!exists) window.__caActivityStub.push(base);
    } catch (_) {}
    injectCheckActivityIntoVue(base);
    try { console.debug("[CHECK CHAT] Message appended", key); } catch (_) {}
    scrollChatToBottom();
  }
  function ingestActivityList(items, pushNew) {
    if (!Array.isArray(items)) return;
    items.forEach(function (item) {
      if (!item || item.id == null) return;
      publishActivityItem(item);
    });
  }
  function pollCheckActivity() {
    if (!onCheckPage()) return;
    if (document.hidden) return;
    const cid = checkPageId();
    if (!cid) return;
    window.__checkActivityPollBusy = true;
    const headers = { Accept: "application/json" };
    try {
      const slug = currentProjectSlug();
      if (slug) headers["X-Checkapp-Project"] = slug;
    } catch (_) {}
    try {
      const tok = (typeof readAuthToken === "function") ? readAuthToken() : "";
      if (tok) headers.Authorization = "Bearer " + tok;
    } catch (_) {}
    const ac = (typeof AbortController !== "undefined") ? new AbortController() : null;
    const timer = setTimeout(function () { try { if (ac) ac.abort(); } catch (_) {} }, 8000);
    fetch(location.origin + "/check/" + cid + "/activity", {
      headers: headers,
      credentials: "include",
      signal: ac ? ac.signal : undefined
    }).then(function (res) {
      clearTimeout(timer);
      if (!res || !res.ok) return null;
      return res.json().catch(function () { return null; });
    }).then(function (json) {
      if (String(checkPageId()) !== String(cid)) return;
      const rows = Array.isArray(json) ? json : (json && (json.data || json.results || json.items)) || [];
      if (Array.isArray(rows) && rows.length) {
        const prev = currentCheckActivityRows();
        const byId = {};
        prev.concat(rows).forEach(function (row) {
          if (row && row.id != null) byId[String(row.id)] = row;
        });
        window.__caActivityStub = Object.keys(byId).map(function (k) { return byId[k]; });
        ingestActivityList(rows, true);
        syncCheckActivityIntoVue();
        setTimeout(syncCheckActivityIntoVue, 50);
        setTimeout(syncCheckActivityIntoVue, 250);
      } else {
        syncCheckActivityIntoVue();
      }
    }).catch(function () {}).then(function () {
      window.__checkActivityPollBusy = false;
    });
  }

  window.__checkappPublishFreezeActivity = function(item) {
    if (!item || item.type !== "FreezeChanged") return;
    publishActivityItem(item);
    syncCheckActivityIntoVue(item);
    [0,50,200].forEach(function(delay){setTimeout(function(){syncCheckActivityIntoVue(item);},delay);});
  };

  function maybePublishCheck(url, method, result) {
    const href = String(url || "");
    const verb = String(method || "GET").toUpperCase();
    if (verb === "PUT" && /\/check\/\d+\/freeze-state(?:[?#]|$)/.test(href)) {
      if (result && result.ok && result.activity) {
        publishActivityItem(result.activity);
        syncCheckActivityIntoVue();
        [0,50,200].forEach(function(delay){setTimeout(syncCheckActivityIntoVue,delay);});
      }
      return;
    }
    // POST check chat/activity — publish new items immediately (no F5)
    if (verb === "POST" && /\/check\/[^/]+\/(activity|message|chat|player-message)/.test(href)) {
      let rows = Array.isArray(result) ? result : (result && (result.data || result.results || result.items)) || [];
      if ((!Array.isArray(rows) || !rows.length) && result && typeof result === "object" && !Array.isArray(result) && result.id != null) {
        rows = [result];
      }
      ingestActivityList(rows, true);
      syncCheckActivityIntoVue();
      [0, 50, 200].forEach(function (delay) {
        setTimeout(syncCheckActivityIntoVue, delay);
      });
      scrollChatToBottom();
      setTimeout(scrollChatToBottom, 16);
      setTimeout(scrollChatToBottom, 80);
      return;
    }
    if (verb !== "POST" && /\/check\/[^/]+\/activity/.test(href)) {
      const rows = Array.isArray(result) ? result : (result && (result.data || result.results)) || [];
      if (Array.isArray(rows) && rows.length) {
        const prev = currentCheckActivityRows();
        const byId = {};
        prev.concat(rows).forEach(function (row) {
          if (row && row.id != null) byId[String(row.id)] = row;
        });
        window.__caActivityStub = Object.keys(byId).map(function (k) { return byId[k]; });
        ingestActivityList(rows, true);
        syncCheckActivityIntoVue();
        [0, 50, 200, 500, 1200].forEach(function (delay) {
          setTimeout(syncCheckActivityIntoVue, delay);
        });
      }
      return;
    }
    if (verb === "GET" && /\/check\/\d+(\?|$)/.test(href.replace(location.origin, "")) && !/\/activity|notice-state|freeze-state/.test(href)) {
      if (result && typeof result === "object" && !Array.isArray(result) && (result.id || result.steam_id || result.suspect)) {
        const sid = String(result.steam_id || (result.suspect && result.suspect.steam_id) || (result.player && result.player.steam_id) || "");
        if (sid && sid !== "0" && sid !== ".") {
          applyCheckStubFromExact(result);
          forceCheckIntoVue(result);
        }
        scheduleCheckUiUnblock();
      }
      return;
    }
    if (verb === "POST" && /\/check\/?(\?|$)/.test(href.replace(location.origin, ""))) {
      const cid = Number(
        typeof result === "number" ? result
        : (result && (result.id || result.check_id || result.checkId))
      ) || 0;
      if (cid) {
        const staff = staffProfile();
        const sid = String((result && result.steam_id) || window.__caCheckSteam || "");
        const sname = String((result && (result.steam_name || result.name)) || window.__caCheckName || sid || "");
        if (sid) window.__caCheckSteam = sid;
        if (sname) window.__caCheckName = sname;
        const started = {
          id: "started-" + cid,
          M_ID: Number(cid),
          check_id: Number(cid),
          checkId: Number(cid),
          type: "Started",
          kind: "Started",
          created_at: Date.now(),
          meta: { client_id: staff.id, actor_name: staff.name || "" },
          initiator_client: staff
        };
        window.__caLastCheckId = cid;
        try { window.__caForceCheckUntil = Date.now() + 8000; } catch (_) {}
        try {
          sessionStorage.setItem("ca_force_check", JSON.stringify({
            id: cid,
            until: Date.now() + 8000,
            slug: (typeof currentProjectSlug === "function" && currentProjectSlug()) || ""
          }));
        } catch (_) {}
        window.__caActivityStub = [started];
        window.__caCheckStub = buildCheckStub(cid, sid, sname);
        if (sid) rememberActiveCheck(sid, cid, false);
        publishActivityItem(started);
        // Full check object only. A bare {id, check_id} would replace Vue `r`
        // in subscribeCheckFinished and leave both panes on the skeleton.
        publishCentrifuge("check-started", window.__caCheckStub);
        goToCheckPage(cid);
        scheduleCheckUiUnblock();
      }
      return;
    }
    if ((verb === "DELETE" || verb === "PUT" || verb === "PATCH") && /\/check\/\d+/.test(href) && !/\/activity|notice-state|freeze-state/.test(href)) {
      const data = result && typeof result === "object" ? result : { status: "FinishedClear" };
      const cidMatch = href.match(/\/check\/(\d+)/);
      const cid = cidMatch ? Number(cidMatch[1]) : Number(data.id || 0);
      const staff = staffProfile();
      let status = String(data.status || data.state || "");
      let verdict = String(data.verdict || data.result || "");
      const recentBan = window.__caBanJustNow && (Date.now() - window.__caBanJustNow) < 120000;
      if (!status) {
        if ((Array.isArray(data.bans) && data.bans.length) || /ban/i.test(verdict) || recentBan) status = "FinishedBan";
        else status = "FinishedClear";
      }
      if (recentBan && !/ban/i.test(status) && !/cancel/i.test(status)) {
        status = "FinishedBan";
        verdict = "Бан";
      }
      if (!verdict) {
        if (/ban/i.test(status)) verdict = "Бан";
        else if (/cancel/i.test(status)) verdict = "Отмена";
        else verdict = "Чист";
      }
      publishActivityItem({
        id: "finished-" + cid,
        M_ID: cid,
        check_id: Number(cid),
        checkId: Number(cid),
        type: "Finished",
        kind: "Finished",
        created_at: Date.now(),
        meta: { status: status, verdict: verdict, client_id: staff.id },
        initiator_client: staff
      });
      try {
        const sid = String((data && (data.steam_id || (data.player && data.player.steam_id) || (data.suspect && data.suspect.steam_id))) || window.__caCheckSteam || "");
        if (sid) rememberActiveCheck(sid, cid, true);
      } catch (_) {}
      publishCentrifuge("check-finished", data);
      publishCentrifuge("check-finish", data);
      publishCentrifuge("project:check-finished", data);
      return;
    }
    if (verb === "POST" && href.includes("/player-message") && onCheckPage()) {
      const cid = Number(checkPageId() || 0);
      if (!cid) return;
      let value = null;
      if (Array.isArray(result) && result[0]) value = result[0].value || result[0];
      else if (result && result.value) value = result.value;
      else if (result && result.id != null) value = result;
      const text = String((value && (value.text || value.message)) || "").trim();
      if (!text) return;
      const mid = (value && (value.id || value.messageId)) || Date.now();
      const staff = (value && value.initiator_client) || staffProfile();
      if (staff && typeof staff === "object") {
        delete staff.is_moderator;
        delete staff.isModerator;
        delete staff.moderator;
        delete staff.is_staff;
        delete staff.isStaff;
        if (!staff.avatar) staff.avatar = PLACEHOLDER;
      }
      publishActivityItem({
        id: "chat-" + mid,
        M_ID: Number(mid) || 0,
        check_id: cid,
        checkId: cid,
        type: "MessageFromModerator",
        kind: "MessageFromModerator",
        text: text,
        message: text,
        created_at: Number((value && value.created_at) || Date.now()),
        meta: {
          text: text,
          message: text,
          client_id: Number((staff && staff.id) || 0) || undefined
        },
        initiator_client: staff
      });
      syncCheckActivityIntoVue();
      [0, 50, 200, 500].forEach(function (delay) {
        setTimeout(syncCheckActivityIntoVue, delay);
      });
      scrollChatToBottom();
    }
  }

  function injectChatMessages(rows) {
    // Live messages must go through Centrifugo with SPA direction "from" (append).
    // Direct Pinia appendMessages(..., "to") prepends and duplicates WS delivery — do not use here.
    if (!Array.isArray(rows) || !rows.length) return;
    publishCentrifuge("player-message", rows);
    scrollChatToBottom();
  }

  function finishUnmuteUi(mutePayload) {
    try {
      // Close Naive confirm dialogs that reappear when mute stays "active" locally
      document.querySelectorAll(".n-dialog, .n-modal, [class*='n-dialog'], [role='dialog']").forEach(function (el) {
        const txt = String(el.textContent || "");
        if (/unmute|размут|снять мут|mute-view|подтверд/i.test(txt)) {
          const btn = el.querySelector(".n-button--default-type, button.n-button");
          // Prefer close/cancel after success — hide whole dialog
          el.style.display = "none";
          try { el.remove(); } catch (_) {}
        }
      });
    } catch (_) {}
    try {
      const root = document.querySelector("#app");
      const app = root && root.__vue_app__;
      const pinia = app && app.config && app.config.globalProperties && app.config.globalProperties.$pinia;
      if (pinia && pinia._s && mutePayload) {
        pinia._s.forEach(function (store) {
          try {
            const list = store.mutes || store.items || (store.$state && store.$state.mutes);
            if (Array.isArray(list)) {
              list.forEach(function (m) {
                if (!m || String(m.id) !== String(mutePayload.id)) return;
                m.computed_is_active = false;
                m.active = false;
                m.deleted_at = mutePayload.deleted_at || Date.now();
              });
            }
          } catch (_) {}
        });
      }
    } catch (_) {}
    // Close mute view modal buttons
    try {
      document.querySelectorAll(".n-card, .n-modal, [class*='mute']").forEach(function (el) {
        const title = String(el.textContent || "");
        if (/мут|mute/i.test(title) && /#\d+|ID/i.test(title)) {
          const closeBtn = el.querySelector(".n-base-close, .n-base-icon, [class*='close']");
          if (closeBtn && typeof closeBtn.click === "function") {
            setTimeout(function () { try { closeBtn.click(); } catch (_) {} }, 80);
          }
        }
      });
    } catch (_) {}
  }

  const liveSeen = { chat: Date.now() - 4000, check: 0, ban: 0, player: 0, alert: 0 };
  function quietPoll(url, headers) {
    if (window.__caBackendDown && Date.now() < window.__caBackendDown) return Promise.resolve(null);
    const ac = (typeof AbortController !== "undefined") ? new AbortController() : null;
    // Do not abort a valid players request while the server is under load.
    // An aborted request appears in DevTools as ERR_CONNECTION_RESET.
    const timer = setTimeout(function () { try { if (ac) ac.abort(); } catch (_) {} }, 12000);
    const opts = { headers: headers || {}, credentials: "include" };
    if (ac) opts.signal = ac.signal;
    return fetch(url, opts).then(function (res) {
      clearTimeout(timer);
      if (!res || res.status >= 500) {
        window.__caBackendDown = Date.now() + 15000;
        return null;
      }
      return res.json().catch(function () { return null; });
    }).catch(function (err) {
      clearTimeout(timer);
      const aborted = !!(err && (err.name === "AbortError" || /abort/i.test(String(err && err.message || ""))));
      if (!aborted) window.__caBackendDown = Date.now() + 15000;
      return null;
    });
  }
  function pollLive(path, key, channel) {
    const headers = { Accept: "application/json" };
    try {
      const slug = currentProjectSlug();
      if (slug) headers["X-Checkapp-Project"] = slug;
    } catch (_) {}
    try {
      const auth = authHeaderValue();
      if (auth) headers.Authorization = auth;
    } catch (_) {}
    quietPoll(location.origin + path, headers).then(function (json) {
      if (!json) return;
      const rows = (json && (json.data || json.results || json.items)) || (Array.isArray(json) ? json : []);
      if (!Array.isArray(rows) || !rows.length) return;
      if (key === "player") {
        rows.forEach(function (row) {
          try {
            const fixed = fixPlayerDetails({ player: row, entity: row.entity || {}, team: row.team || [] });
            if (fixed && fixed.player) Object.assign(row, fixed.player);
          } catch (_) {}
        });
      }
      const newest = Math.max.apply(null, rows.map(function (row) { return Number(row.created_at || row.updated_at || row.id || 0); }));
      const fresh = liveSeen[key] ? rows.filter(function (row) { return Number(row.created_at || row.updated_at || row.id || 0) > liveSeen[key]; }) : [];
      if (fresh.length) {
        if (key === "chat") {
          window.__checkappChatSeen = window.__checkappChatSeen || new Set();
          const unseen = fresh.filter(function (row) {
            const k = String((row && (row.unique_id || row.id)) || "");
            if (!k || window.__checkappChatSeen.has(k)) return false;
            window.__checkappChatSeen.add(k);
            return true;
          });
          if (unseen.length) {
            unseen.sort(function (a, b) {
              return Number(a.created_at || a.id || 0) - Number(b.created_at || b.id || 0);
            });
            unseen.forEach(function (row) {
              if (row && (row.is_team || String(row.type || "").toLowerCase() === "team")) return;
              injectSiteChatMessage(row);
              publishCentrifuge("player-message", row);
            });
            try { settleSiteChatMessages(piniaRoot() && piniaRoot()._s && piniaRoot()._s.get("player-message-page-data")); } catch (_) {}
            scrollChatToBottom();
          }
        } else if (key !== "player") publishCentrifuge(channel, { data: fresh, results: fresh });
      }
      if (newest > (liveSeen[key] || 0)) liveSeen[key] = newest;
    }).catch(function () {});
  }
  let realtimeSince = 0;
  let realtimeEs = null;
  let realtimeReconnectTimer = 0;
  let realtimeBackoff = 500;
  let realtimeSlug = "";
  function dispatchRealtimeEvent(evt, streamPid) {
    if (!evt || typeof evt !== "object") return;
    const evtPid = evt.projectId || evt.project_id || streamPid;
    const slugPid = streamPid;
    if (slugPid && evtPid && String(evtPid) !== String(slugPid)) return;
    const typ = String(evt.type || "");
    const payload = evt.payload && typeof evt.payload === "object" ? evt.payload : evt;
    const payloadPid = payload.projectId || payload.project_id || evtPid;
    if (slugPid && payloadPid && String(payloadPid) !== String(slugPid)) return;
    if (evt.id && Number(evt.id) > realtimeSince) realtimeSince = Number(evt.id);
    if (typ === "check.message.created" || typ === "check-activity") {
      const wantCheck = checkPageId();
      const gotCheck = payload.checkId || payload.check_id || (payload.message && (payload.message.checkId || payload.message.check_id));
      if (!wantCheck || !gotCheck || String(gotCheck) !== String(wantCheck)) return;
      const msg = (typ === "check-activity" && (payload.type || payload.kind || payload.text))
        ? payload
        : (payload.message || payload);
      if (msg && typeof msg === "object") {
        if (!msg.meta || typeof msg.meta !== "object") msg.meta = {};
        if (!Array.isArray(window.__checkappMessages)) window.__checkappMessages = [];
        publishActivityItem(msg);
        scrollChatToBottom();
      }
      return;
    }
    if (typ === "chat.message") {
      if (payload.is_team || String(payload.type || "").toLowerCase() === "team") return;
      const fromSite = payload.from_site === true || payload.authorType === "staff" || payload.author_type === "staff";
      const fromProject = payload.authorType === "project" || payload.author_type === "project" || payload.steam_id === "project" || payload.initiator === "project";
      const chatName = payload.initiator_name || payload.authorName || payload.author_name || "";
      const playerSid = String(payload.steam_id || (!fromSite && payload.authorId) || "");
      let chatCid = Number(payload.initiator_id || payload.authorId || payload.actor_user_id || 0);
      if (!fromSite) chatCid = 0;
      if (!chatCid || !isFinite(chatCid)) chatCid = 0;
      const chatClient = payload.initiator_client && typeof payload.initiator_client === "object"
        ? payload.initiator_client
        : { id: chatCid || 1, name: chatName, status: "online" };
      if (fromProject) { chatCid = Number(payload.initiator_id || (1000000 + Number(payload.project_id || evtPid || 0))); chatClient.id = chatCid; chatClient.is_project = true; }
      if (fromSite && chatCid && !fromProject) {
        chatClient.id = chatCid;
        rememberStaffClient(chatClient);
      }
      const mid = payload.messageId || payload.id || Date.now();
      const chatMsg = {
        id: mid,
        unique_id: payload.unique_id || ("msg-" + mid),
        text: payload.text || payload.message || payload.content || "",
        message: payload.message || payload.text || payload.content || "",
        initiator_id: fromSite ? asInitiatorId(chatCid || chatClient.id) : playerSid,
        initiator: fromProject ? "project" : (fromSite ? "client" : "player"),
        initiator_name: chatName || (chatClient && chatClient.name) || playerSid || "",
        initiator_avatar: (chatClient && chatClient.avatar) || payload.initiator_avatar || PLACEHOLDER,
        initiator_client: fromSite ? chatClient : null,
        initiator_player: fromSite
          ? { steam_id: "0", steam_name: chatName || chatClient.name || "", name: chatName || "", status: "online" }
          : {
              steam_id: playerSid || "0",
              steam_name: chatName || playerSid || "",
              name: chatName || playerSid || "",
              steam_avatar: PLACEHOLDER,
              status: "online"
            },
        from_site: fromSite,
        created_at: payload.createdAt || payload.created_at || Date.now(),
        type: payload.type || (payload.target_steam_id ? "direct" : "global"),
        target_steam_id: payload.target_steam_id || null,
        steam_id: fromProject ? "project" : (fromSite ? "site" : playerSid),
        server_id: payload.server_id || payload.serverId || 1
      };
      injectSiteChatMessage(chatMsg);
      publishCentrifuge("player-message", chatMsg);
      try {
        const pinia = piniaRoot();
        const chat = pinia && pinia._s && pinia._s.get("player-message-page-data");
        settleSiteChatMessages(chat);
      } catch (_) {}
      if (onCheckPage()) {
        const content = payload.content || payload.text || payload.message || "";
        const msgSid = playerSid;
        const checkSid = String(window.__caCheckSteam || "");
        const cidPay = Number(payload.checkId || payload.check_id || 0) || 0;
        const cidPage = Number(checkPageId() || 0) || 0;
        const messageCid = Number(payload.checkId || payload.check_id || 0);
        if (!messageCid || messageCid !== cidPage) return;
        if (cidPay && cidPage && cidPay !== cidPage) return;
        if (!fromSite && checkSid && msgSid && msgSid !== checkSid && msgSid !== "0") return;
        publishActivityItem({
          id: "chat-" + mid,
          M_ID: Number(mid) || 0,
          check_id: Number(payload.checkId || payload.check_id || checkPageId() || 0),
          checkId: Number(payload.checkId || payload.check_id || checkPageId() || 0),
          type: fromSite ? "MessageFromModerator" : "MessageFromPlayer",
          kind: fromSite ? "MessageFromModerator" : "MessageFromPlayer",
          text: content,
          message: content,
          created_at: payload.createdAt || payload.created_at || Date.now(),
          meta: {
            text: content,
            message: content,
            author_name: payload.authorName || payload.author_name || chatName || "",
            is_contact: !!(payload.is_contact || payload.contact),
            related_players: Array.isArray(payload.related_players) ? payload.related_players : [],
            matches: Array.isArray(payload.matches) ? payload.matches : [],
            match: !!(payload.match || payload.contact_match),
            client_id: fromSite ? (chatCid || Number(chatClient.id) || undefined) : 0,
            steam_id: msgSid || checkSid || "0"
          },
          initiator_client: fromSite ? Object.assign({}, chatClient || {}, {
            avatar: (chatClient && chatClient.avatar) || PLACEHOLDER,
            name: (chatClient && chatClient.name) || chatName || ""
          }) : {
            id: 0,
            steam_id: msgSid || "0",
            name: chatName || "",
            steam_name: chatName || "",
            status: "online"
          },
          initiator_player: {
            steam_id: fromSite ? "0" : (msgSid || "0"),
            steam_name: chatName || "",
            name: chatName || "",
            status: "online"
          }
        });
        scrollChatToBottom();
      }
      return;
    }
    if (typ === "player.joined") {
      const sid = String(payload.steam_id || payload.playerId || "");
      let st = String(payload.status || "online").toLowerCase();
      if (st === "active") st = "online";
      if (st === "queue" || st === "queueing") st = "queued";
      if (!/^(online|joining|queued|afk|unstable)$/.test(st)) st = "online";
      if (sid) publishCentrifuge("player-status", { players: { [sid]: st } });
    } else if (typ === "player.left") {
      const sid = String(payload.steam_id || payload.playerId || "");
      if (sid) publishCentrifuge("player-status", { players: { [sid]: "offline" } });
    } else if (typ === "player.status" || typ === "player.updated") {
      const map = payload.players;
      if (map && typeof map === "object" && !Array.isArray(map)) {
        const out = {};
        Object.keys(map).forEach(function (k) {
          const v = map[k];
          let st = String(typeof v === "string" ? v : (v && v.status) || "").toLowerCase();
          if (st === "active") st = "online";
          if (st === "queue" || st === "queueing") st = "queued";
          if (/^(online|joining|queued|afk|unstable|offline)$/.test(st)) out[k] = st;
        });
        if (Object.keys(out).length) publishCentrifuge("player-status", { players: out });
      }
    }
    else if (typ === "ban.created" || typ === "ban.removed") publishCentrifuge("ban", payload);
    else if (typ.indexOf("mute") === 0) publishCentrifuge("player-mute", payload);
    else if (typ === "notification.created") publishCentrifuge("player-alert", payload);
    else if (typ === "audit.created") publishCentrifuge("audit", payload);
    else if (typ === "report.created") publishCentrifuge("report", payload);
    else if (typ === "check.created") publishCentrifuge("check", payload);
    else if (typ === "ip.updated" || typ === "steam.updated") {
      try {
        window.dispatchEvent(new CustomEvent("checkapp-" + typ.replace(".", "-"), { detail: payload }));
      } catch (_) {}
    }
    else publishCentrifuge(typ, payload);
    if (evt.id && Number(evt.id) > realtimeSince) realtimeSince = Number(evt.id);
  }
  function pollRealtimeEvents() {
    const headers = { Accept: "application/json" };
    try {
      const slug = currentProjectSlug();
      if (slug) headers["X-Checkapp-Project"] = slug;
    } catch (_) {}
    try {
      const auth = authHeaderValue();
      if (auth) headers.Authorization = auth;
    } catch (_) {}
    quietPoll(location.origin + "/realtime/poll?since=" + (realtimeSince || 0), headers).then(function (json) {
      if (!json) return;
      const events = (json && (json.events || json.data || json.results)) || [];
      const pid = Number((json && (json.projectId || json.project_id)) || 0) || 0;
      if (!Array.isArray(events) || !events.length) {
        if (json && json.last_id) realtimeSince = Number(json.last_id) || realtimeSince;
        return;
      }
      events.forEach(function (evt) {
        dispatchRealtimeEvent(evt, pid);
      });
    }).catch(function () {});
  }
  function connectRealtimeStream() {
    // EventSource /realtime/stream holds Python threads; nginx then 502s /tariff /wallet.
    try {
      if (realtimeEs) realtimeEs.close();
    } catch (_) {}
    realtimeEs = null;
    clearTimeout(realtimeReconnectTimer);
  }
  connectRealtimeStream();
  window.addEventListener("popstate", function () {
    const slug = currentProjectSlug() || "";
    if (slug !== realtimeSlug) {
      realtimeSince = 0;
      connectRealtimeStream();
    }
  });
  setInterval(function () {
    const slug = currentProjectSlug() || "";
    if (slug !== realtimeSlug) {
      realtimeSince = 0;
      connectRealtimeStream();
    }
  }, 4000);
  // Reconnect backfill only — not the live path
  setInterval(function () {
    if (!realtimeEs || realtimeEs.readyState !== 1) return;
  }, 30000);

  // The SPA briefly restores its old chat store while the route mounts, then
  // replaces it with a later request.  Load the current page of chat ourselves
  // on entry and apply it again while that mount settles, so old messages never
  // flash before the actual current chat appears.
  let lastChatRoute = "";
  function refreshCurrentChatPage() {
    const pinia = piniaRoot();
    const chat = pinia && pinia._s && pinia._s.get("player-message-page-data");
    if (!chat || /\/checks\//.test(String(location.pathname || ""))) return;
    const ref = chat.messages;
    const existing = ref && Array.isArray(ref.value) ? ref.value : (Array.isArray(chat.messages) ? chat.messages : null);
    if (existing && existing.length) return;
    const headers = { Accept: "application/json" };
    const slug = currentProjectSlug();
    if (slug) headers["X-Checkapp-Project"] = slug;
    const auth = authHeaderValue();
    if (auth) headers.Authorization = auth;
    origFetch(location.origin + "/player-message?limit=80", {
      headers: headers,
      cache: "no-store"
    }).then(function (res) {
      return res && res.ok ? res.json() : null;
    }).then(function (json) {
      if (!json) return;
      const still = chat.messages;
      const now = still && Array.isArray(still.value) ? still.value : (Array.isArray(chat.messages) ? chat.messages : null);
      if (now && now.length) return;
      const fixed = normalizeApi("/player-message", json, "GET");
      const rows = (fixed && (fixed.data || fixed.results || fixed.items)) || [];
      if (!Array.isArray(rows) || !rows.length) return;
      const replacement = rows.slice().sort(function (a, b) {
        return Number(a.created_at || a.id || 0) - Number(b.created_at || b.id || 0);
      });
      if (still && typeof still === "object" && "value" in still) still.value = replacement;
      else if (Array.isArray(chat.messages)) chat.messages.splice(0, chat.messages.length, ...replacement);
      window.__checkappChatSeen = new Set(replacement.map(function (row) {
        return String((row && (row.unique_id || row.id)) || "");
      }).filter(Boolean));
    }).catch(function () {});
  }
  setInterval(function () {
    const route = String(location.pathname || "") + String(location.search || "");
    if (!document.getElementById("player-message-page-list-container")) {
      lastChatRoute = route;
      return;
    }
    const pinia = piniaRoot();
    const chat = pinia && pinia._s && pinia._s.get("player-message-page-data");
    if (!chat || /\/checks\//.test(route) || route === lastChatRoute) return;
    lastChatRoute = route;
    setTimeout(refreshCurrentChatPage, 900);
  }, 250);
  setInterval(function () {
    const path = String(location.pathname || "");
    const pinia = piniaRoot();
    const chat = pinia && pinia._s && pinia._s.get("player-message-page-data");
    if (chat && !/\/checks\//.test(path)) {
      const chatTs = liveSeen.chat > 10000 ? liveSeen.chat : (Date.now() - 4000);
      pollLive("/player-message?pagination_direction=from&pagination_timestamp=" + chatTs, "chat", "player-message");
    }
    // Minimal players are needed only on the players screen, not on every
    // tab.  This removes the repeated connection resets and frees the API for
    // the page the staff member is actually viewing.
    if (/\/players(?:\/|$)/.test(path)) pollLive("/players/browse-minimal?limit=40", "player", "player");
  }, 8000);
  setInterval(pollRealtimeEvents, 2000);
  setInterval(pollCheckActivity, 1200);
  setInterval(function () {
    if (!onCheckPage()) return;
    syncCheckActivityIntoVue();
  }, 800);

  // Keep staff marked online in SPA presence store (clients map values = user id)
  function forceStaffOnlinePresence() {
    try {
      const root = document.querySelector("#app");
      const app = root && root.__vue_app__;
      const pinia = app && app.config && app.config.globalProperties && app.config.globalProperties.$pinia;
      if (!pinia || !pinia._s) return;
      pinia._s.forEach(function (store) {
        try {
          if (!store || typeof store !== "object") return;
          if (store.clients && typeof store.clients === "object") {
            const meId = String((window.__caMeId || store.client && store.client.id || store.user && store.user.id || "") || "");
            if (meId && meId !== "0") {
              store.clients["local-" + meId] = meId;
              store.clients[meId] = meId;
            }
          }
          if (store.$state && store.$state.clients && typeof store.$state.clients === "object") {
            const meId = String((window.__caMeId || "") || "");
            if (meId && meId !== "0") {
              store.$state.clients["local-" + meId] = meId;
              store.$state.clients[meId] = meId;
            }
          }
        } catch (_) {}
      });
    } catch (_) {}
    centrifugeSockets.forEach(function (ws) {
      if (!ws || ws.readyState !== 1 || !ws.__subs) return;
      const channels = ws.__subs instanceof Set ? Array.from(ws.__subs) : Object.keys(ws.__subs);
      const emit = ws.__emit;
      if (typeof emit !== "function") return;
      channels.forEach(function (channel) {
        if (!/situation|presence|refresh/i.test(String(channel || ""))) return;
        try {
          emit("message", {
            data: JSON.stringify({
              push: { channel: channel, join: { info: { user: String(window.__caMeId || "1"), client: "local-" + String(window.__caMeId || "1") } } }
            })
          });
        } catch (_) {}
      });
    });
  }
  setInterval(forceStaffOnlinePresence, 2000);
  setTimeout(forceStaffOnlinePresence, 800);

  try {
    if (/\[object Object\]|object%20Object/i.test(location.pathname)) {
      history.replaceState(null, "", location.pathname.replace(/\/checks\/[^/]+/, "/checks") + location.search);
    }
  } catch (_) {}

  function fakeCentrifuge(url) {
    const listeners = { open: [], message: [], close: [], error: [] };
    const handlers = { open: null, message: null, error: null, close: null };
    const subs = new Set();
    const ws = {
      url: url,
      readyState: 0,
      bufferedAmount: 0,
      extensions: "",
      protocol: "json",
      binaryType: "blob",
      addEventListener: function (type, fn) {
        if (!listeners[type]) listeners[type] = [];
        listeners[type].push(fn);
        if (type === "open" && ws.readyState === 1) {
          try { fn({}); } catch (_) {}
        }
      },
      removeEventListener: function (type, fn) {
        if (!listeners[type]) return;
        listeners[type] = listeners[type].filter((x) => x !== fn);
      },
      dispatchEvent: function () { return true; },
      send: function (raw) {
        parseCentrifuge(raw).forEach((msg) => {
          const id = msg && msg.id;
          let reply = null;
          if (msg && msg.connect) {
            try { console.debug("[CHECK CHAT] WebSocket connected"); } catch (_) {}
            reply = { id: id, connect: { client: "local-1", version: "5.2.2", ping: 0, pong: true, expires: false, ttl: 0, session: "local", node: "local", data: { user: "1", id: 1 } } };
          } else if (msg && msg.subscribe) {
            const channel = msg.subscribe.channel;
            if (channel) subs.add(channel);
            reply = { id: id, subscribe: { recoverable: false, positioned: false, epoch: "0", offset: 0 } };
            setTimeout(function () {
              try {
                emit("message", { data: JSON.stringify({
                  push: { channel: channel, join: { info: { user: String(window.__caMeId || "1"), client: "local-" + String(window.__caMeId || "1") } } }
                }) });
              } catch (_) {}
              if (/check-activity/i.test(String(channel || ""))) {
                try {
                  console.debug("[CHECK CHAT] Joined room", channel);
                } catch (_) {}
              }
            }, 40);
          } else if (msg && msg.unsubscribe) {
            reply = { id: id, unsubscribe: {} };
          } else if (msg && msg.ping) {
            reply = { id: id, ping: {} };
          } else if (msg && msg.refresh) {
            reply = { id: id, refresh: { expires: false } };
          } else if (msg && msg.rpc) {
            reply = { id: id, rpc: { data: {} } };
          } else if (msg && msg.presence) {
            reply = { id: id, presence: { presence: {
              "local-1": { user: "1", client: "local-1" },
              "local": { user: "1", client: "local" }
            }, clients: {
              "local-1": { user: "1", client: "local-1" },
              "local": { user: "1", client: "local" }
            } } };
          } else if (msg && msg.presence_stats) {
            reply = { id: id, presence_stats: { num_clients: 1, num_users: 1 } };
          } else if (msg && msg.history) {
            reply = { id: id, history: { publications: [], offset: 0, epoch: "0" } };
          } else if (id != null) {
            reply = { id: id };
          }
          if (reply) emit("message", { data: JSON.stringify(reply) });
        });
      },
      close: function (code, reason) {
        if (ws.readyState === 3) return;
        ws.readyState = 3;
        try {
          const idx = centrifugeSockets.indexOf(ws);
          if (idx >= 0) centrifugeSockets.splice(idx, 1);
          if (Array.isArray(window.__checkappCentrifugeSockets)) {
            const i2 = window.__checkappCentrifugeSockets.indexOf(ws);
            if (i2 >= 0) window.__checkappCentrifugeSockets.splice(i2, 1);
          }
        } catch (_) {}
        emit("close", { code: code || 1000, reason: reason || "", wasClean: true });
      }
    };
    ws.__subs = subs;
    ws.__emit = emit;
    centrifugeSockets.push(ws);
    function emit(type, ev) {
      const fn = handlers[type];
      if (typeof fn === "function") {
        try { fn(ev); } catch (_) {}
      }
      (listeners[type] || []).forEach((cb) => {
        try { cb(ev); } catch (_) {}
      });
    }
    function openNow() {
      if (ws.__opened) return;
      ws.__opened = true;
      ws.readyState = 1;
      emit("open", {});
    }
    ws.readyState = 1;
    setTimeout(openNow, 0);
    Object.defineProperty(ws, "onopen", {
      get: function () { return handlers.open; },
      set: function (fn) {
        handlers.open = fn;
        if (ws.readyState === 1 && fn) openNow();
      }
    });
    Object.defineProperty(ws, "onmessage", {
      get: function () { return handlers.message; },
      set: function (fn) { handlers.message = fn; }
    });
    Object.defineProperty(ws, "onerror", {
      get: function () { return handlers.error; },
      set: function (fn) { handlers.error = fn; }
    });
    Object.defineProperty(ws, "onclose", {
      get: function () { return handlers.close; },
      set: function (fn) { handlers.close = fn; }
    });
    return ws;
  }

  const OrigWebSocket = window.WebSocket;
  window.WebSocket = function (url, protocols) {
    const href = String(url || "");
    // Always fake centrifugo — including local ws://127.0.0.1/connection/websocket
    if (
      href.includes("centrifugo") ||
      href.includes("rustapp.io") ||
      href.includes("connection/websocket") ||
      href.includes("/connection/") ||
      href.includes(".checkapp") ||
      href.includes("s3.checkapp") ||
      (href.startsWith("wss://") && !href.includes(location.host)) ||
      (href.startsWith("ws://") && !href.includes(location.host))
    ) {
      return fakeCentrifuge(href);
    }
    return protocols !== undefined ? new OrigWebSocket(url, protocols) : new OrigWebSocket(url);
  };
  window.WebSocket.CONNECTING = 0;
  window.WebSocket.OPEN = 1;
  window.WebSocket.CLOSING = 2;
  window.WebSocket.CLOSED = 3;

  function patchUrlSetter(proto, prop) {
    const desc = Object.getOwnPropertyDescriptor(proto, prop);
    if (!desc || !desc.set) return;
    Object.defineProperty(proto, prop, {
      configurable: true,
      enumerable: desc.enumerable,
      get: desc.get,
      set: function (value) {
        desc.set.call(this, imageSrc(value));
      }
    });
  }
  patchUrlSetter(HTMLImageElement.prototype, "src");
  document.addEventListener("error", function (ev) {
    const img = ev.target;
    if (!img || img.tagName !== "IMG") return;
    if (img.dataset && img.dataset.caPh === "1") return;
    const raw = String(img.getAttribute("src") || img.src || "");
    if (!raw || raw.startsWith("data:") || raw.startsWith("blob:")) return;
    if (raw.indexOf("/local/") >= 0 || raw.indexOf("/uploads/") >= 0) return;
    try {
      if (img.dataset) img.dataset.caPh = "1";
      img.src = PLACEHOLDER;
    } catch (_) {}
  }, true);
  patchUrlSetter(HTMLMediaElement.prototype, "src");
  patchUrlSetter(HTMLSourceElement.prototype, "src");
  patchUrlSetter(HTMLVideoElement.prototype, "poster");

  const origSetAttr = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function (name, value) {
    const key = String(name || "").toLowerCase();
    if ((key === "src" || key === "poster") && value) {
      value = imageSrc(value);
    } else if ((key === "href" || key === "xlink:href") && this.tagName === "image" && value) {
      value = imageSrc(value);
    } else if (key === "style" && value) {
      value = rewriteCssUrls(value);
    }
    return origSetAttr.call(this, name, value);
  };

  try {
    const styleProto = CSSStyleDeclaration.prototype;
    const origSetProp = styleProto.setProperty;
    styleProto.setProperty = function (name, value, priority) {
      const raw = String(value || "");
      if (raw && (/url\(/i.test(raw) || /(?:s3|r2)\./i.test(raw) || /rustapp/i.test(raw))) {
        value = rewriteCssUrls(raw);
      }
      return origSetProp.call(this, name, value, priority);
    };
    function patchCssProp(prop) {
      const desc = Object.getOwnPropertyDescriptor(styleProto, prop);
      if (!desc || !desc.set) return;
      Object.defineProperty(styleProto, prop, {
        configurable: true,
        enumerable: desc.enumerable,
        get: desc.get,
        set: function (value) {
          desc.set.call(this, rewriteCssUrls(String(value || "")));
        }
      });
    }
    patchCssProp("cssText");
    patchCssProp("background");
    patchCssProp("backgroundImage");
  } catch (_) {}

  function fixMediaNode(el) {
    if (!el || el.nodeType !== 1) return;
    const tag = el.tagName;
    if (tag === "IMG" || tag === "SOURCE" || tag === "VIDEO") {
      const raw = el.getAttribute("src") || el.src;
      if (raw && isDeadMedia(raw)) {
        const next = imageSrc(raw);
        if (next && el.src !== next) el.src = next;
      }
      if (tag === "VIDEO") {
        const poster = el.getAttribute("poster") || el.poster;
        if (poster && isDeadMedia(poster)) el.poster = imageSrc(poster);
      }
    }
    if (tag === "image") {
      const href = el.getAttribute("href") || el.getAttributeNS("http://www.w3.org/1999/xlink", "href");
      if (href && isDeadMedia(href)) {
        const next = imageSrc(href);
        origSetAttr.call(el, "href", next);
        try { el.setAttributeNS("http://www.w3.org/1999/xlink", "href", next); } catch (_) {}
      }
    }
    const st = el.getAttribute && el.getAttribute("style");
    if (st && (st.includes("checkapp") || st.includes("rustapp") || st.includes("rustcheck") || st.includes("s3.") || st.includes("r2."))) {
      const next = rewriteCssUrls(st);
      if (next !== st) origSetAttr.call(el, "style", next);
    }
  }

  function rewriteTelegramLinks() {
    document.querySelectorAll("a[href]").forEach((el) => {
      const href = el.getAttribute("href") || "";
      const txt = String(el.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
      if (/^support$|^поддержка$/i.test(txt)) {
        el.setAttribute("href", "https://t.me/skvirt32");
        el.setAttribute("target", "_blank");
        el.setAttribute("rel", "noopener noreferrer");
        return;
      }
      if (/t\.me\/rustapp/i.test(href) || /telegram\.me\/rustapp/i.test(href) || /t\.me\/(rustapp_help|rustappio|rust_app|Rustcheckapp)/i.test(href)) {
        el.setAttribute("href", "https://t.me/skvirt32");
        el.setAttribute("target", "_blank");
        el.setAttribute("rel", "noopener noreferrer");
      }
    });
    // The footer uses icons without text.  Its support icon is a direct
    // Telegram link in the original bundle, so update it by URL as well.
    document.querySelectorAll(".btn-footer[href*='t.me'], .btn-footer[href*='telegram.me']").forEach(function (el) {
      el.setAttribute("href", "https://t.me/skvirt32");
      el.setAttribute("target", "_blank");
      el.setAttribute("rel", "noopener noreferrer");
    });
  }

  function patchProjectSidebarLinks() {
    const path = location.pathname || "";
    if (path === "/" || path.replace(/\/+$/, "") === "" || /^\/(client|admin|profile|auth|login|signup)(\/|$)/i.test(path)) return;
    const aside = document.querySelector("aside:not([class*='player']):not([class*='check']):not([class*='drawer'])");
    if (!aside) return;
    aside.querySelectorAll("a[href], button").forEach(function (el) {
      const href = String(el.getAttribute("href") || "").toLowerCase();
      const txt = String(el.textContent || "").replace(/\s+/g, " ").trim();
      const label = txt.toLowerCase();
      if (/docs\.(checkapp|rustapp)/i.test(href) || /^docs$|^документация$/i.test(label)) {
        const row = el.closest("li") || el.closest("[class*='item']") || el;
        row.setAttribute("data-checkapp-hide-docs", "1");
        row.style.setProperty("display", "none", "important");
        try { row.remove(); } catch (_) {}
        return;
      }
      if (/^support$|^поддержка$/i.test(label)) {
        if (el.tagName === "A") {
          el.setAttribute("href", "https://t.me/skvirt32");
          el.setAttribute("target", "_blank");
          el.setAttribute("rel", "noopener noreferrer");
        } else {
          el.onclick = function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            window.open("https://t.me/skvirt32", "_blank", "noopener,noreferrer");
          };
        }
      }
    });
  }

  function scanMedia() {
    document.querySelectorAll("img,video,source").forEach(fixMediaNode);
  }

  function startMediaWatch() {
    if (!document.documentElement) {
      setTimeout(startMediaWatch, 0);
      return;
    }
    scanMedia();
    rewriteTelegramLinks();
    patchProjectSidebarLinks();
    const mo = new MutationObserver((muts) => {
      for (let i = 0; i < muts.length; i++) {
        if (muts[i].type === "attributes") {
          fixMediaNode(muts[i].target);
          continue;
        }
        const nodes = muts[i].addedNodes;
        if (!nodes) continue;
        for (let j = 0; j < nodes.length; j++) {
          const n = nodes[j];
          if (!n || n.nodeType !== 1) continue;
          const tag = n.tagName;
          if (tag === "IMG" || tag === "VIDEO" || tag === "SOURCE") {
            fixMediaNode(n);
            continue;
          }
          if (tag === "INPUT" || tag === "TEXTAREA" || n.isContentEditable) continue;
          if (n.querySelector) {
            const media = n.querySelectorAll("img,video,source");
            for (let k = 0; k < media.length; k++) fixMediaNode(media[k]);
            const links = n.querySelectorAll("a[href]");
            for (let k = 0; k < links.length; k++) {
              const linkEl = links[k];
              const href = linkEl.getAttribute("href") || "";
              const txt = String(linkEl.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
              if (/^support$|^поддержка$/i.test(txt)) {
                linkEl.setAttribute("href", "https://t.me/skvirt32");
                linkEl.setAttribute("target", "_blank");
                linkEl.setAttribute("rel", "noopener noreferrer");
                continue;
              }
              if (/t\.me\/(rustapp|rustapp_help|rustappio|rust_app|Rustcheckapp)/i.test(href)) {
                linkEl.setAttribute("href", "https://t.me/RustCheckcc");
                linkEl.setAttribute("target", "_blank");
                linkEl.setAttribute("rel", "noopener noreferrer");
              }
            }
          }
        }
      }
    });
    mo.observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ["style", "src", "poster"] });
  }
  startMediaWatch();

  window.addEventListener("error", (e) => {
    const el = e.target;
    if (el && el.tagName) {
      if (el.tagName === "IMG" && !el.dataset.checkappImg) {
        el.dataset.checkappImg = "1";
        el.src = PLACEHOLDER;
      }
      return;
    }
    e.preventDefault();
    e.stopImmediatePropagation();
  }, true);

  window.addEventListener("unhandledrejection", (e) => {
    const reason = e && e.reason;
    const msg = String((reason && reason.message) || reason || "");
    if (/Project limit exceeded|project-limit-exceeded|достигнул лимит|не можете создавать проект/i.test(msg)) {
      showProjectLimitNativeToast();
      return;
    }
    e.preventDefault();
  });

  function hideTariffCrashDialogs(root) {
    const scope = root && root.querySelectorAll ? root : document;
    const nodes = scope.querySelectorAll
      ? scope.querySelectorAll(".notification,[class*='notification'],[class*='n-message'],[class*='n-notification'],[class*='n-dialog'],.n-message,.n-notification,.n-dialog,.n-modal,.n-card,.vfm,.vfm__content,[role='dialog'],[role='alertdialog']")
      : [];
    for (let i = 0; i < nodes.length; i++) {
      const box = nodes[i];
      if (!box || box.dataset.checkappToastKeep === "1") continue;
      if (box.id === "checkapp-notice-root" || box.id === "checkapp-funds-modal" || box.id === "checkapp-plan-modal") continue;
      if (box.closest && box.closest("#checkapp-notice-root,#checkapp-funds-modal,#checkapp-plan-modal,[data-checkapp-toast-keep='1']")) continue;
      if (box.closest && box.closest("aside,nav,[class*='sidebar'],[class*='SideBar'],[class*='side-bar'],[class*='navigation']")) continue;
      const t = (box.textContent || "").replace(/\s+/g, " ").trim();
      if (!t || t.length > 420) continue;
      const crash = /Payment Required|status code 402|\b402\b|AxiosError/i.test(t);
      const leftoverBase = lastTariffErrKind === "funds" && /Базовый тариф нельзя выбрать|выдаётся автоматически при создании проекта/i.test(t);
      const leftoverFundsNative = /Request failed with status code 402|Payment Required|AxiosError/i.test(t) && !/Не хватает средств|нужно ещё/i.test(t);
      if (!crash && !leftoverBase && !leftoverFundsNative) continue;
      const wrap = (box.closest && (box.closest(".vfm,.n-modal-container,.n-dialog,.n-notification-container") || box)) || box;
      try { wrap.style.display = "none"; } catch (_) {}
      try { wrap.setAttribute("data-checkapp-hidden-toast", "1"); } catch (_) {}
      try { wrap.remove(); } catch (_) {}
    }
  }

  function hideMidToasts(root) {
    hideTariffCrashDialogs(root);
    const scope = root && root.querySelectorAll ? root : document;
    const nodes = scope.querySelectorAll
      ? scope.querySelectorAll(".notification,[class*='notification'],[class*='n-message'],[class*='n-notification'],[class*='n-dialog'],.n-message,.n-notification,.n-dialog,.n-modal,[role='dialog']")
      : [];
    for (let i = 0; i < nodes.length; i++) {
      const box = nodes[i];
      if (!box || box.dataset.checkappToastKeep === "1") continue;
      if (box.closest("aside,nav,[class*='sidebar'],[class*='SideBar'],[class*='side-bar'],[class*='navigation']")) continue;
      const t = (box.textContent || "").replace(/\s+/g, " ").trim();
      const looksEmpty = t.length === 0 || t === "!" || t === "×" || t === "x";
      if (looksEmpty && box.querySelector && box.querySelector("svg,i,[class*='icon'],[class*='error']")) {
        box.style.display = "none";
        box.setAttribute("data-checkapp-hidden-toast", "1");
        continue;
      }
      if (t.length > 320) continue;
      if (/Критическая ошибка|Critical error|Критична помилка|критическая ошибка|unhandled-exception|Cannot read properties of undefined \(reading 'toString'\)|502 Bad Gateway|Bad Gateway/i.test(t)) {
        box.style.display = "none";
        box.setAttribute("data-checkapp-hidden-toast", "1");
        try { box.remove(); } catch (_) {}
        continue;
      }
      if (/не хватает средств|недостаточно средств|not enough funds|Not enough balance/i.test(t)) {
        if (/понятно|нужно ещё|тарифного плана/i.test(t)) continue;
        box.style.display = "none";
        box.setAttribute("data-checkapp-hidden-toast", "1");
        continue;
      }
      if (/AxiosError|Internal Server Error|500 Internal|PrismaClient|Database error|Network Error|Failed to fetch|Not Found|403 Forbidden|401 Unauthorized|Payment Required|status code 402/i.test(t)) {
        box.style.display = "none";
        box.setAttribute("data-checkapp-hidden-toast", "1");
        if (/Payment Required|status code 402|\b402\b/i.test(t)) continue;
        if (window.__checkappShowHumanError) {
          window.__checkappShowHumanError({ message: t }, /404|Not Found/i.test(t) ? 404 : (/403|Forbidden/i.test(t) ? 403 : 500), { toast: true });
        }
        continue;
      }
    }
  }

  function restoreSidebarAccount() {
    try {
      // Left nav only — never touch player/check right panel (class often contains "sidebar")
      const candidatesRoots = [];
      document.querySelectorAll("aside, nav").forEach(function (el) {
        const cls = String(el.className || "").toLowerCase();
        if (cls.includes("player") || cls.includes("check") || cls.includes("drawer")) return;
        // prefer left project navigation (usually first aside)
        candidatesRoots.push(el);
      });
      const root = candidatesRoots[0];
      if (!root) return;
      const candidates = root.querySelectorAll("a,button,div,img");
      for (let i = 0; i < candidates.length; i++) {
        const el = candidates[i];
        if (!el || el.dataset.checkappHiddenToast === "1") continue;
        const st = window.getComputedStyle ? getComputedStyle(el) : null;
        const hidden = (el.style && el.style.display === "none") || (st && st.display === "none");
        if (!hidden) continue;
        const hasImg = el.tagName === "IMG" || (el.querySelector && el.querySelector("img"));
        const nearLogout = el.parentElement && el.parentElement.querySelector && (
          el.parentElement.innerHTML.includes("logout") || el.parentElement.querySelector("[class*='logout'],[class*='exit'],[class*='sign-out']")
        );
        if (hasImg || nearLogout || (el.getAttribute("href") || "").includes("profile") || (el.getAttribute("href") || "").includes("client")) {
          el.style.display = "";
          el.style.opacity = "1";
          el.style.visibility = "visible";
        }
      }
    } catch (_) {}
  }
  const toastWatch = new MutationObserver((muts) => {
    for (let i = 0; i < muts.length; i++) {
      const nodes = muts[i].addedNodes;
      if (!nodes) continue;
      for (let j = 0; j < nodes.length; j++) {
        const n = nodes[j];
        if (n && n.nodeType === 1) hideMidToasts(n);
      }
    }
  });
  if (document.documentElement) toastWatch.observe(document.documentElement, { childList: true, subtree: true });
  setInterval(hideMidToasts, 2000);
  setInterval(restoreSidebarAccount, 2000);
  setTimeout(restoreSidebarAccount, 800);
  setInterval(patchProjectSidebarLinks, 1500);
  setTimeout(patchProjectSidebarLinks, 600);
  setInterval(function () {
    if (isLandingPage()) ensureDiscordButton();
    mountRcHome();
    mountRcProfile();
    bootAppBg();
  }, 2500);
  setTimeout(ensureDiscordButton, 400);
  setTimeout(mountRcHome, 50);
  setTimeout(mountRcProfile, 50);
  setTimeout(bootAppBg, 50);
  window.addEventListener("popstate", mountRcHome);
  window.addEventListener("popstate", mountRcProfile);
  window.addEventListener("popstate", bootAppBg);
  setInterval(patchBlockedProjectScreen, 800);
  setTimeout(patchBlockedProjectScreen, 900);
  window.addEventListener("popstate", patchBlockedProjectScreen);
  setInterval(function () {
    patchLandingHomeProjects();
  }, 1200);
  setTimeout(patchLandingHomeProjects, 900);
  window.addEventListener("popstate", patchLandingHomeProjects);
  setInterval(mountLandingProjectsCarousel, 1500);
  setTimeout(mountLandingProjectsCarousel, 600);
  window.addEventListener("popstate", mountLandingProjectsCarousel);
  window.addEventListener("popstate", patchProjectSidebarLinks);
  window.addEventListener("popstate", patchBrandName);
  window.addEventListener("popstate", patchLandingLogo);
  window.addEventListener("popstate", patchI18nBrand);
  window.addEventListener("popstate", patchPanelBrand);

  setInterval(() => {
    document.querySelectorAll('input[type="email"]').forEach((el) => {
      el.type = "text";
      el.removeAttribute("pattern");
    });
    rewriteTelegramLinks();
    patchProjectSidebarLinks();
    patchBrandName();
    patchLandingLogo();
    patchI18nBrand();
    patchPanelBrand();
    patchBlockedProjectScreen();
    if (!window.__checkappLandingStable) {
      patchLandingHomeProjects();
    }
  }, 4000);

  (function injectUiFixes() {
    let lastMarkedPath = location.pathname || "";
    function markPage() {
      try {
        const path = location.pathname || "";
        const isHome = path === "/" || path.replace(/\/+$/, "") === "";
        const wasHome = lastMarkedPath === "/" || lastMarkedPath.replace(/\/+$/, "") === "";
        if (isHome) {
          if (RC_CLASSIC) {
            document.documentElement.classList.remove("checkapp-home", "checkapp-home-ready", "checkapp-home-revealed", "checkapp-home-stable");
          } else {
            document.documentElement.classList.add("checkapp-home");
          }
          if (!wasHome) {
            document.documentElement.classList.remove("checkapp-home-ready", "checkapp-home-revealed", "checkapp-home-stable");
            window.__checkappLandingStable = false;
            window.__checkappLandingLegalDone = false;
            window.__checkappLandingFeedReady = false;
            if (window.__checkappLandingRevealTimer) {
              clearTimeout(window.__checkappLandingRevealTimer);
              window.__checkappLandingRevealTimer = null;
            }
          } else if (window.__checkappLandingStable) {
            document.documentElement.classList.add("checkapp-home-ready", "checkapp-home-revealed", "checkapp-home-stable");
          }
        } else {
          document.documentElement.classList.remove("checkapp-home", "checkapp-home-ready", "checkapp-home-revealed", "checkapp-home-stable");
          window.__checkappLandingStable = false;
        }
        lastMarkedPath = path;
        document.body.setAttribute("data-checkapp-page", path);
        const sec = (location.search.match(/[?&]section=([^&]+)/i) || [])[1] || "";
        document.body.setAttribute("data-checkapp-section", sec.toLowerCase());
      } catch (_) {}
    }
    function run() {
      markPage();
      const css = [
        "body.checkapp-plan-open{overflow:hidden!important;}",
        "body.checkapp-plan-open .vfm,body.checkapp-plan-open .vfm__overlay,body.checkapp-plan-open .vfm--overlay{pointer-events:none!important;opacity:0!important;visibility:hidden!important;}",
        "body.checkapp-plan-open #checkapp-plan-modal{display:flex!important;opacity:1!important;visibility:visible!important;z-index:100001!important;pointer-events:auto!important;}",
        "body.checkapp-plan-open #checkapp-plan-modal .checkapp-plan-overlay{background:rgba(0,0,0,.45)!important;backdrop-filter:blur(3px)!important;-webkit-backdrop-filter:blur(3px)!important;pointer-events:auto!important;opacity:1!important;}",
        "body.checkapp-plan-open #checkapp-plan-modal .cpm-rustapp{pointer-events:auto!important;}",
        ".vfm,.vfm__container,[class*='vfm']{z-index:9999!important;}",
        ".execute-command-modal,.execute-command-modal .vfm__content,.execute-command-modal [class*='content']{background:#1a1a1a!important;color:#fff!important;border-radius:14px!important;box-shadow:0 24px 80px rgba(0,0,0,.65)!important;min-width:420px!important;max-width:560px!important;padding:0!important;opacity:1!important;overflow:hidden!important;}",
        ".execute-command-modal .vfm__content > *,.execute-command-modal [class*='modal']{background:transparent!important;}",
        ".execute-command-modal input,.execute-command-modal select,.execute-command-modal textarea{background:#141414!important;border:1px solid #2c2c2c!important;border-radius:10px!important;color:#fff!important;}",
        ".execute-command-modal [class*='preview'],.execute-command-modal input[readonly],.execute-command-modal .preview{background:repeating-linear-gradient(-45deg,#171717,#171717 8px,#1d1d1d 8px,#1d1d1d 16px)!important;border:1px solid #2c2c2c!important;border-radius:10px!important;}",
        ".vfm__content:has(.change-plan-modal),.vfm__content:has(.plan-list),.vfm__content:has(.plan),.change-plan-modal,.change-plan-modal.vfm__content{background:#1a1a1a!important;color:#fff!important;border-radius:14px!important;box-shadow:0 24px 80px rgba(0,0,0,.75)!important;opacity:1!important;visibility:visible!important;padding:0!important;min-width:min(95vw,860px)!important;max-width:1000px!important;overflow:hidden!important;}",
        ".change-plan-modal .plan-list,.change-plan-modal .content,.vfm__content:has(.plan-list) .plan-list{background:#1a1a1a!important;opacity:1!important;visibility:visible!important;}",
        ".change-plan-modal .plan,.vfm__content .plan{background:#1a1a1a!important;color:#fff!important;border-right:1px solid #2a2a2a!important;padding:22px 20px!important;opacity:1!important;}",
        ".change-plan-modal .plan:last-child{border-right:none!important;}",
        ".change-plan-modal .select-button,.change-plan-modal button.select-button{width:100%!important;border-radius:10px!important;border:none!important;padding:10px 12px!important;font-weight:600!important;opacity:1!important;}",
        ".change-plan-modal .select-button.base,.change-plan-modal button.base,.change-plan-modal .select-button.current{background:#2a2a2a!important;color:#cfcfcf!important;}",
        ".change-plan-modal .select-button.plus,.change-plan-modal button.plus{background:#1a3d2a!important;color:#7dffa3!important;}",
        ".change-plan-modal .select-button.enterprise,.change-plan-modal button.enterprise{background:#3a2a1a!important;color:#e8b86d!important;}",
        ".vfm__content:not(.execute-command-modal):not(.change-plan-modal):not(.client-edit-modal):not(:has(.execute-command-modal)):not(:has(.change-plan-modal)):not(:has(.plan-list)):not(:has(.plan)):not(:has(.client-edit-modal)),.vfm-content:not(.execute-command-modal):not(.change-plan-modal):not(.client-edit-modal){background:#1c1c1c!important;color:#fff!important;border-radius:12px!important;box-shadow:0 24px 80px rgba(0,0,0,.6)!important;min-width:320px!important;min-height:120px!important;padding:20px!important;opacity:1!important;}",
        "[class*='comment'] [class*='card'],.player-note,.player-comment,[class*='PlayerComment'],[class*='player-comment']{background:#efe6d6!important;color:#1a1a1a!important;border-radius:10px!important;}",
        "body[data-checkapp-page*='/alerts'] .alert-skeleton{display:none!important;}",
        "body[data-checkapp-page*='/alerts'] [data-checkapp-empty-alert='1']{display:none!important;height:0!important;min-height:0!important;margin:0!important;padding:0!important;overflow:hidden!important;border:0!important;}",
        "body[data-checkapp-page*='/alerts'] tr:has(.alert-skeleton):not(:has(img)):not(:has([class*='avatar'] img)),body[data-checkapp-page*='/alerts'] [class*='alert-row']:has(.alert-skeleton):not(:has(img)){display:none!important;}",
        /* Never hide page content wrappers — only the lock overlay (.root-cont) */
        ".no-plan-content .root-cont,#checkapp-tier-gate,#checkapp-tier-lock,#checkapp-autokick-lock,.ck-tier-lock-box{display:none!important;visibility:hidden!important;pointer-events:none!important;}",
        ".no-plan-content{filter:none!important;-webkit-filter:none!important;min-height:0!important;}",
        ".n-message:not(:has(.n-message__content :not(:empty))),.n-notification:not(:has(.n-notification-main__content :not(:empty))),[class*='n-message'][data-checkapp-hidden-toast],[class*='n-notification'][data-checkapp-hidden-toast]{display:none!important;}",
        "aside:not([class*='player']):not([class*='check']) .account-avatar,aside:not([class*='player']):not([class*='check']) [class*='account'] img{opacity:1!important;visibility:visible!important;display:inline-block!important;}",
        ".landing-page header img,.landing-page header a img,.landing-page main section:first-of-type img,aside:not([class*='player']):not([class*='check']) a[href='/'] img,aside:not([class*='player']):not([class*='check']) [class*='logo'] img{max-height:52px!important;width:auto!important;object-fit:contain!important;border-radius:12px!important;}",
        ".landing-page main section:first-of-type canvas,.landing-page main section:first-of-type video,.landing-page main section:first-of-type [data-checkapp-hide-hero-art='1']{display:none!important;visibility:hidden!important;width:0!important;height:0!important;opacity:0!important;pointer-events:none!important;}",
        "#checkapp-hero-logo{display:block!important;visibility:visible!important;opacity:1!important;margin:0 auto 16px!important;width:112px!important;height:112px!important;max-width:112px!important;max-height:112px!important;border-radius:16px!important;object-fit:cover!important;position:relative!important;z-index:3!important;}",
        ".landing-page main section:first-of-type img{max-height:112px!important;max-width:112px!important;min-height:72px!important;border-radius:16px!important;}",
        ".landing-page header a[href='/'],.landing-page header [class*='logo']{display:inline-flex!important;align-items:center!important;gap:10px!important;}",
        ".landing-page header img[src*='logo'],.landing-page header img[src*='logo-avatar']{max-height:56px!important;min-height:40px!important;}",
        "aside:not([class*='player']):not([class*='check']) [class*='account'] a,aside:not([class*='player']):not([class*='check']) [class*='bottom'] a,aside:not([class*='player']):not([class*='check']) [class*='links'] a{padding-left:6px!important;margin-left:4px!important;}",
        "aside:not([class*='player']):not([class*='check']) [class*='account'] [class*='links'],aside:not([class*='player']):not([class*='check']) [class*='bottom']{padding-left:8px!important;justify-content:flex-start!important;gap:10px!important;}",
        ".combatlog-modal,.combatlog-modal .vfm__content{background:#1a1a1a!important;color:#fff!important;opacity:1!important;}",
        "a[href*='docs.rustapp.io'],a[href*='docs.checkapp']{display:none!important;visibility:hidden!important;width:0!important;height:0!important;margin:0!important;padding:0!important;overflow:hidden!important;pointer-events:none!important;}",
        ".landing-page video[src*='landing-map'],.landing-page video[src*='map.webm']{display:none!important;visibility:hidden!important;height:0!important;max-height:0!important;position:absolute!important;pointer-events:none!important;opacity:0!important;}",
        /* Remove empty map frame / black border under removed hero map */
        ".landing-page main>section:first-of-type>div:first-child{border:none!important;outline:none!important;box-shadow:none!important;background:transparent!important;background-image:none!important;min-height:0!important;height:auto!important;aspect-ratio:auto!important;padding:0!important;margin-bottom:8px!important;overflow:visible!important;}",
        ".landing-page main>section:first-of-type>div:first-child::before,.landing-page main>section:first-of-type>div:first-child::after{display:none!important;content:none!important;}",
        ".landing-page .checkapp-discord-btn{width:28px!important;height:28px!important;border-radius:8px!important;}",
        ".landing-page footer .socials,.landing-page footer [class*='social']{display:inline-flex!important;align-items:center!important;gap:10px!important;vertical-align:middle!important;}",
        ".landing-page footer .socials a,.landing-page footer [class*='social'] a{display:inline-flex!important;align-items:center!important;justify-content:center!important;width:28px!important;height:28px!important;line-height:1!important;}",
        "img.ca-mod-badge{display:inline-block!important;width:16px!important;height:16px!important;margin:0 4px 0 0!important;padding:0!important;vertical-align:-3px!important;object-fit:contain!important;}",
        /* Keep only Telegram + Discord in landing footer */
        ".landing-page footer a[href*='github'],.landing-page footer a[href*='x.com'],.landing-page footer a[href*='twitter.com'],.landing-page footer a[aria-label*='GitHub' i],.landing-page footer a[aria-label='X' i],.landing-page footer a[aria-label='Twitter' i],.landing-page footer a[data-checkapp-hide-social]{display:none!important;visibility:hidden!important;width:0!important;height:0!important;overflow:hidden!important;pointer-events:none!important;margin:0!important;padding:0!important;}",
        /* Opaque change-plan modal (SPA often opens empty/transparent shell) */
        ".vfm:has(.change-plan-modal),.vfm:has(.plan-list),.vfm--absolute:has(.change-plan-modal){opacity:1!important;visibility:visible!important;z-index:10050!important;}",
        ".vfm__content.change-plan-modal,.change-plan-modal,.vfm__content:has(.change-plan-modal),.vfm__content:has(.plan-list){background:#1a1a1a!important;background-color:#1a1a1a!important;color:#fff!important;opacity:1!important;visibility:visible!important;min-width:min(92vw,860px)!important;max-width:960px!important;border-radius:14px!important;box-shadow:0 24px 80px rgba(0,0,0,.75)!important;}",
        ".change-plan-modal *,.vfm__content:has(.plan-list) *{opacity:1!important;}",
        "#checkapp-plan-modal.checkapp-plan-root{position:fixed!important;inset:0!important;z-index:100001!important;display:flex!important;align-items:center!important;justify-content:center!important;background:transparent!important;padding:16px!important;pointer-events:auto!important;}",
        "#checkapp-plan-modal .checkapp-plan-overlay{position:absolute!important;inset:0!important;background:rgba(0,0,0,.45)!important;backdrop-filter:blur(3px)!important;-webkit-backdrop-filter:blur(3px)!important;pointer-events:auto!important;z-index:1!important;}",
        "#checkapp-plan-modal .cpm-rustapp{position:relative!important;z-index:2!important;pointer-events:auto!important;opacity:1!important;visibility:visible!important;background:#141414!important;color:#fff!important;border-radius:14px!important;box-shadow:0 24px 80px rgba(0,0,0,.75)!important;width:min(95vw,920px)!important;overflow:hidden!important;border:1px solid #2a2a2a!important;}",
        "#checkapp-plugin-modal.ck-pl-overlay{position:fixed!important;inset:0!important;z-index:10070!important;display:flex!important;align-items:center!important;justify-content:center!important;background:rgba(0,0,0,.42)!important;backdrop-filter:blur(1px)!important;-webkit-backdrop-filter:blur(1px)!important;padding:16px!important;}",
        "#checkapp-tier-lock,#checkapp-autokick-lock{position:absolute!important;inset:0!important;z-index:50!important;display:flex!important;align-items:center!important;justify-content:center!important;background:rgba(0,0,0,.32)!important;backdrop-filter:blur(4px)!important;-webkit-backdrop-filter:blur(4px)!important;padding:24px!important;pointer-events:auto!important;min-height:200px!important;}",
        "#checkapp-tier-lock .ck-tier-lock-box,#checkapp-autokick-lock .ck-tier-lock-box{max-width:420px!important;text-align:center!important;color:#fff!important;position:relative!important;z-index:2!important;}",
        "#checkapp-tier-lock .ck-tier-lock-icon{width:42px!important;height:42px!important;border-radius:10px!important;background:#1a3d2a!important;display:inline-flex!important;align-items:center!important;justify-content:center!important;margin:0 auto 14px!important;font-size:18px!important;}",
        "#checkapp-tier-lock .ck-tier-lock-title{font-size:18px!important;font-weight:700!important;margin-bottom:8px!important;}",
        "#checkapp-tier-lock .ck-tier-lock-sub{font-size:14px!important;color:#aaa!important;line-height:1.45!important;}",
        "#checkapp-tier-lock .ck-tier-demo-btn{margin-top:16px!important;background:#3a3a3a!important;color:#fff!important;border:none!important;border-radius:10px!important;padding:10px 18px!important;font-size:14px!important;font-weight:600!important;cursor:pointer!important;}",
        "#checkapp-api-lock{border:1px solid #c47a2c!important;border-radius:12px!important;padding:22px 24px!important;background:repeating-linear-gradient(-45deg,#141414,#141414 10px,#171717 10px,#171717 20px)!important;color:#fff!important;max-width:720px!important;}",
        "#checkapp-api-lock h3{margin:0 0 10px!important;font-size:18px!important;font-weight:700!important;}",
        "#checkapp-api-lock p{margin:0 0 16px!important;font-size:14px!important;color:#aaa!important;line-height:1.5!important;}",
        "#checkapp-api-lock .ck-api-upgrade{background:#3b82f6!important;color:#fff!important;border:none!important;border-radius:10px!important;padding:10px 16px!important;font-size:14px!important;font-weight:600!important;cursor:pointer!important;}",
        "body[data-checkapp-section='api'] .no-plan-content .root-cont{display:none!important;}",
        "#checkapp-tier-gate{position:fixed!important;z-index:99990!important;display:none!important;}",
        "#checkapp-tier-gate .ck-tier-lock-box{max-width:420px!important;text-align:center!important;color:#fff!important;}",
        "body.checkapp-plan-open .vfm:not(#checkapp-plan-modal),body.checkapp-plan-open .vfm--fixed:not(#checkapp-plan-modal),body.checkapp-plan-open .vfm--absolute:not(#checkapp-plan-modal){display:none!important;pointer-events:none!important;visibility:hidden!important;opacity:0!important;}",
        "body.checkapp-plan-open #checkapp-tier-gate,body.checkapp-plan-open #checkapp-tier-lock,body.checkapp-plan-open #checkapp-autokick-lock{display:none!important;}",
        ".landing-page a[href*='/map'],.landing-page [data-checkapp-hide-map-tab='1'],button[data-checkapp-hide-map-tab='1']{display:none!important;visibility:hidden!important;width:0!important;height:0!important;min-width:0!important;padding:0!important;margin:0!important;overflow:hidden!important;border:none!important;pointer-events:none!important;}",
        ".navigation .search,.navigation .search-full,.navigation .search-small,.navigation .header .search,.fake-wrapper,.fake-modal,.vfm:has(.fake-modal),.vfm:has(.fake-wrapper),[data-checkapp-hide-sidebar-search='1']{display:none!important;visibility:hidden!important;height:0!important;width:0!important;min-height:0!important;min-width:0!important;margin:0!important;padding:0!important;overflow:hidden!important;pointer-events:none!important;opacity:0!important;}",
        ".landing-page button[data-checkapp-hide-map-tab='1'],.landing-page [role='tab'][data-checkapp-hide-map-tab='1'],main button[data-checkapp-hide-map-tab='1']{display:none!important;}",
        ".landing-page main nav button[class*='active'],.landing-page main button.active,.landing-page [class*='demo'] button.active,.landing-page main [role='tab'][aria-selected='true']{background:#3a3a3a!important;color:#fff!important;box-shadow:none!important;}",
        "img[src*='map.webp'],img[src*='map-preview'],.landing-page [data-checkapp-hide-map='1']{display:none!important;}",
        "html.checkapp-home .landing-page main [data-checkapp-hide-demo-tabs='1'],html.checkapp-home .landing-page main [data-checkapp-hide-demo-shot='1'],html.checkapp-home .landing-page main [data-checkapp-hide-online='1'],html.checkapp-home .landing-page main [data-checkapp-hide-feature-tab='1'],body[data-checkapp-page='/'] .landing-page main [data-checkapp-hide-demo-tabs='1'],body[data-checkapp-page='/'] .landing-page main [data-checkapp-hide-demo-shot='1'],body[data-checkapp-page='/'] .landing-page main [data-checkapp-hide-online='1'],body[data-checkapp-page='/'] .landing-page main [data-checkapp-hide-feature-tab='1']{display:none!important;}",
        "html.checkapp-home .landing-page main>section:has([style*='landing-mt-bg']):not(:has(.stats-card)),html.checkapp-home .landing-page main>section:has(img[src*='players.webp']):not(:has(.stats-card)){display:none!important;visibility:hidden!important;height:0!important;min-height:0!important;margin:0!important;padding:0!important;overflow:hidden!important;}",
        "html.checkapp-home:not(.checkapp-home-ready) .landing-page{visibility:hidden!important;pointer-events:none!important;}",
        "html.checkapp-home.checkapp-home-ready .landing-page{visibility:visible!important;pointer-events:auto!important;}",
        "html.checkapp-home:not(.checkapp-home-ready) .landing-page>header,html.checkapp-home:not(.checkapp-home-ready) .landing-page main>section,html.checkapp-home:not(.checkapp-home-ready) .landing-page footer{opacity:0!important;transform:translate3d(0,20px,0)}",
        "html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page>header,html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page main>section:not([data-checkapp-hide='1']):not([data-checkapp-hide-trust='1']),html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page footer{opacity:1!important;transform:translate3d(0,0,0)!important;transition:opacity .75s cubic-bezier(.22,1,.36,1),transform .75s cubic-bezier(.22,1,.36,1)}",
        "html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page>header{transition-delay:.05s}",
        "html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page main>section:nth-of-type(1):not([data-checkapp-hide='1']):not([data-checkapp-hide-trust='1']){opacity:1!important;transform:none!important;transition:none!important;}",
        "html.checkapp-home .landing-page main>section:first-of-type p.text-grey-400,html.checkapp-home .landing-page main>section:first-of-type p[data-checkapp-hero-subtitle='1']{color:#eaeaea!important;-webkit-text-fill-color:#eaeaea!important;opacity:1!important;transition:none!important;animation:none!important;}",
        "html.checkapp-home .landing-page main>section[data-checkapp-hide-trust='1']{display:none!important;visibility:hidden!important;height:0!important;min-height:0!important;max-height:0!important;margin:0!important;padding:0!important;overflow:hidden!important;opacity:0!important;pointer-events:none!important;}",
        "html.checkapp-home .landing-page main>section[data-checkapp-projects-carousel='1']{display:block!important;visibility:visible!important;opacity:1!important;height:auto!important;min-height:0!important;max-height:none!important;overflow:visible!important;pointer-events:auto!important;}",
        "html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page footer{transition-delay:.58s}",
        "html.checkapp-home.checkapp-home-ready .landing-page .stats-card{transition-property:all!important;transition-duration:.3s!important;transition-timing-function:cubic-bezier(.4,0,.2,1)!important;transition-delay:0s!important;}",
        "html.checkapp-home .landing-page main>section:has(.scroll-container):not([data-checkapp-hide-trust='1']),html.checkapp-home #checkapp-projects-ribbon{display:block!important;visibility:visible!important;opacity:1!important;height:auto!important;min-height:56px!important;overflow:hidden!important;padding:18px 0 24px!important;pointer-events:none!important;}",
        "html.checkapp-home,html.checkapp-home body{background:#1e1e1e!important;}",
        "@media (prefers-reduced-motion:reduce){html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page>header,html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page main>section:not([data-checkapp-hide='1']):not([data-checkapp-hide-trust='1']),html.checkapp-home.checkapp-home-ready:not(.checkapp-home-revealed) .landing-page footer{transition-duration:.35s;transition-delay:0s!important;transform:none!important}}",
        ".landing-page .plan-card div.mb-5,.landing-page .plan-card div.mb-5 span,.landing-page .plan-card div.mb-5 *{color:#f2f2f2!important;}",
        ".landing-page .plan-card .checkapp-price-free,.landing-page .plan-card span.checkapp-price-free{color:#f2f2f2!important;font-size:2.25rem!important;font-weight:700!important;line-height:1.1!important;}",
        ".landing-page .plan-card .mb-5:not(:has(.plan-icon)):not([data-checkapp-price-ready='1']){opacity:0!important;min-height:2.25rem!important;pointer-events:none!important;}",
        ".landing-page .plan-card .mb-5[data-checkapp-price-ready='1']{opacity:1!important;}",
        "#checkapp-plan-modal .cpm-rustapp-head{display:flex!important;align-items:center!important;justify-content:space-between!important;padding:20px 22px 16px!important;}",
        "#checkapp-plan-modal .cpm-rustapp-head h2{margin:0!important;font-size:18px!important;font-weight:600!important;}",
        "#checkapp-plan-modal .cpm-rustapp-close{background:transparent!important;border:none!important;color:#888!important;font-size:24px!important;line-height:1!important;cursor:pointer!important;padding:0 4px!important;}",
        "#checkapp-plan-modal .cpm-rustapp-grid{display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr))!important;}",
        "@media (max-width:860px){#checkapp-plan-modal .cpm-rustapp-grid{grid-template-columns:1fr!important;}}",
        "#checkapp-plan-modal .cpm-rustapp-plan{padding:22px 20px 18px!important;border-right:1px solid #2a2a2a!important;display:flex!important;flex-direction:column!important;gap:12px!important;min-height:100%!important;}",
        "#checkapp-plan-modal .cpm-rustapp-plan:last-child{border-right:none!important;}",
        "#checkapp-plan-modal .cpm-plan-top{display:flex!important;align-items:center!important;gap:8px!important;}",
        "#checkapp-plan-modal .cpm-plan-name{font-size:16px!important;font-weight:600!important;}",
        "#checkapp-plan-modal .cpm-plan-bolt{width:18px!important;height:18px!important;display:inline-flex!important;}",
        "#checkapp-plan-modal .cpm-plan-bolt.base{color:#3b82f6!important;}",
        "#checkapp-plan-modal .cpm-plan-bolt.plus{color:#22c55e!important;}",
        "#checkapp-plan-modal .cpm-plan-bolt.enterprise{color:#e8b86d!important;}",
        "#checkapp-plan-modal .cpm-plan-price{font-size:28px!important;font-weight:700!important;line-height:1.2!important;}",
        "#checkapp-plan-modal .cpm-plan-price span{font-size:14px!important;font-weight:400!important;color:#888!important;margin-left:2px!important;}",
        "#checkapp-plan-modal .cpm-plan-btn{width:100%!important;display:block!important;box-sizing:border-box!important;border:none!important;border-radius:10px!important;padding:10px 12px!important;font-size:14px!important;font-weight:600!important;cursor:pointer!important;min-height:40px!important;line-height:1.2!important;appearance:none!important;-webkit-appearance:none!important;text-align:center!important;}",
        "#checkapp-plan-modal .cpm-plan-btn.current{background:#2a2a2a!important;color:#cfcfcf!important;cursor:default!important;}",
        "#checkapp-plan-modal .cpm-plan-btn.pick{background:#1a3d2a!important;color:#7dffa3!important;}",
        "#checkapp-plan-modal .cpm-plan-btn.contact{background:#3a2a1a!important;color:#e8b86d!important;}",
        "#checkapp-plan-modal .cpm-plan-btn:disabled{opacity:1!important;}",
        "#checkapp-plan-modal .cpm-plan-divider{border:none!important;border-top:1px dashed #333!important;margin:4px 0 8px!important;}",
        "#checkapp-plan-modal .cpm-plan-features{list-style:none!important;margin:0!important;padding:0!important;display:flex!important;flex-direction:column!important;gap:10px!important;}",
        "#checkapp-plan-modal .cpm-plan-features li{display:flex!important;align-items:flex-start!important;gap:8px!important;font-size:13px!important;color:#ccc!important;line-height:1.35!important;}",
        "#checkapp-plan-modal .cpm-plan-features li svg{width:16px!important;height:16px!important;opacity:.75!important;flex:0 0 auto!important;margin-top:1px!important;}",
        "#checkapp-plan-modal .cpm-rustapp-foot{display:flex!important;align-items:flex-start!important;gap:8px!important;padding:14px 22px 18px!important;border-top:1px solid #2a2a2a!important;font-size:12px!important;color:#888!important;}",
        "#checkapp-plan-modal .cpm-rustapp-foot a{color:#aaa!important;text-decoration:underline!important;}",
        /* Plugin picker — clean black modal: only version choice */
        "#checkapp-plugin-modal.ck-pl-overlay{position:fixed!important;inset:0!important;z-index:1000004!important;display:flex!important;align-items:center!important;justify-content:center!important;padding:16px!important;background:rgba(0,0,0,.55)!important;backdrop-filter:blur(4px)!important;-webkit-backdrop-filter:blur(4px)!important;opacity:0!important;transition:opacity .2s ease!important;}",
        "#checkapp-plugin-modal.ck-pl-overlay.is-open{opacity:1!important;}",
        "#checkapp-plugin-modal .ck-pl-dialog{position:relative!important;background:#141414!important;color:#fff!important;border-radius:14px!important;box-shadow:0 24px 80px rgba(0,0,0,.75)!important;width:min(92vw,440px)!important;overflow:hidden!important;border:1px solid #2a2a2a!important;padding:28px 24px 22px!important;transform:translateY(10px) scale(.98)!important;transition:transform .22s ease!important;}",
        "#checkapp-plugin-modal.is-open .ck-pl-dialog{transform:translateY(0) scale(1)!important;}",
        "#checkapp-plugin-modal .ck-pl-x{position:absolute!important;top:12px!important;right:12px!important;width:32px!important;height:32px!important;border:none!important;border-radius:8px!important;background:#1e1e1e!important;color:#aaa!important;font-size:20px!important;line-height:1!important;cursor:pointer!important;}",
        "#checkapp-plugin-modal .ck-pl-x:hover{color:#fff!important;background:#252525!important;}",
        "#checkapp-plugin-modal .ck-pl-clean-title{font-size:18px!important;font-weight:700!important;color:#fff!important;text-align:center!important;margin:0 0 18px!important;}",
        "#checkapp-plugin-modal .ck-pl-versions{display:flex!important;flex-direction:column!important;gap:10px!important;margin-bottom:18px!important;}",
        "#checkapp-plugin-modal .ck-pl-ver{display:flex!important;align-items:center!important;gap:12px!important;width:100%!important;text-align:left!important;padding:14px 14px!important;border-radius:12px!important;border:1px solid #2a2a2a!important;background:#1a1a1a!important;color:#fff!important;cursor:pointer!important;transition:border-color .15s ease,background .15s ease,transform .15s ease!important;}",
        "#checkapp-plugin-modal .ck-pl-ver:hover{border-color:#3a3a3a!important;background:#1e1e1e!important;transform:translateY(-1px)!important;}",
        "#checkapp-plugin-modal .ck-pl-ver.is-selected{border-color:#4ade80!important;background:#152018!important;box-shadow:0 0 0 1px rgba(74,222,128,.25)!important;}",
        "#checkapp-plugin-modal .ck-pl-radio{width:18px!important;height:18px!important;border-radius:999px!important;border:2px solid #555!important;flex:0 0 auto!important;position:relative!important;}",
        "#checkapp-plugin-modal .ck-pl-ver.is-selected .ck-pl-radio{border-color:#4ade80!important;}",
        "#checkapp-plugin-modal .ck-pl-ver.is-selected .ck-pl-radio:after{content:''!important;position:absolute!important;inset:3px!important;border-radius:999px!important;background:#4ade80!important;}",
        "#checkapp-plugin-modal .ck-pl-ver-text{display:flex!important;flex-direction:column!important;gap:2px!important;min-width:0!important;}",
        "#checkapp-plugin-modal .ck-pl-ver-text strong{font-size:14px!important;font-weight:600!important;color:#fff!important;}",
        "#checkapp-plugin-modal .ck-pl-ver-text em{font-style:normal!important;font-size:12px!important;color:#888!important;}",
        "#checkapp-plugin-modal .ck-pl-download{width:100%!important;border:none!important;border-radius:10px!important;padding:12px 16px!important;font-size:14px!important;font-weight:600!important;cursor:pointer!important;background:#1a3d2a!important;color:#7dffa3!important;transition:filter .15s ease,transform .15s ease!important;}",
        "#checkapp-plugin-modal .ck-pl-download:hover{filter:brightness(1.08)!important;}",
        "#checkapp-plugin-modal .ck-pl-download:disabled{opacity:.45!important;cursor:not-allowed!important;filter:none!important;}",
        /* legacy plugin modal leftovers hidden */
        "#checkapp-plugin-modal .ck-pl-head,#checkapp-plugin-modal .ck-pl-sub,#checkapp-plugin-modal .ck-pl-icon,#checkapp-plugin-modal .ck-pl-row,#checkapp-plugin-modal .ck-pl-dots,#checkapp-plugin-modal .ck-pl-toggle,#checkapp-plugin-modal .ck-pl-value{display:none!important;}",
        /* Discord/integration wizard switches must stay clickable */
        ".vfm .n-switch,.vfm .n-switch *,.vfm__content .n-switch,.n-modal .n-switch{pointer-events:auto!important;cursor:pointer!important;}",
        ".vfm .n-switch.n-switch--disabled,.vfm .n-switch[aria-disabled='true']{opacity:1!important;pointer-events:auto!important;}",
        ".custom-switch,.custom-switch input,.custom-switch *{pointer-events:auto!important;cursor:pointer!important;}",
        ".custom-switch input[disabled],.custom-switch input:disabled{pointer-events:auto!important;opacity:1!important;}"
      ].join("");
      let st = document.getElementById("checkapp-ui-fixes");
      if (!st) {
        st = document.createElement("style");
        st.id = "checkapp-ui-fixes";
        (document.head || document.documentElement).appendChild(st);
      }
      if (st.textContent !== css) st.textContent = css;
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run);
    else run();
    setInterval(markPage, 2000);
    window.addEventListener("popstate", markPage);
  })();

  (function redirectNativePlanModal() {
    function forcePricesInNativeModal() {
      document.querySelectorAll(".change-plan-modal .plan, .vfm__content .plan, .plan-list .plan, .change-plan-modal").forEach(function (card) {
        var txt = String(card.textContent || "");
        var tier = /enterprise/i.test(txt) ? "enterprise" : (/plus/i.test(txt) ? "plus" : (/base/i.test(txt) ? "base" : ""));
        if (!tier && card.classList) {
          if (card.classList.contains("base")) tier = "base";
          else if (card.classList.contains("plus")) tier = "plus";
          else if (card.classList.contains("enterprise")) tier = "enterprise";
        }
        card.querySelectorAll("span, p, div, strong, b").forEach(function (el) {
          if (!el || (el.children && el.children.length > 0)) return;
          var t = String(el.textContent || "").trim();
          if (!t || t.length > 40) return;
          if (tier === "base" || (!tier && /₽\s*300|₽\s*0\b|^0$|^300$/.test(t))) {
            if (/₽\s*\d+/.test(t) || /^\d+\s*₽?$/.test(t) || /^₽\s*0/.test(t)) {
              el.textContent = "Free";
            }
            if (/^\/\s*мес/i.test(t)) el.style.display = "none";
          }
          if (tier === "plus" || (!tier && /₽\s*500/.test(t))) {
            if (/₽\s*500/.test(t) || t === "500" || /₽\s*400/.test(t) || t === "400") el.textContent = "₽300";
          }
        });
        // Block Base "Выбрать"
        if (tier === "base") {
          card.querySelectorAll("button, .select-button, [role='button']").forEach(function (btn) {
            if (btn.disabled || /текущий|current/i.test(String(btn.textContent || ""))) return;
            if (btn.dataset.checkappBaseBlock === "1") return;
            btn.dataset.checkappBaseBlock = "1";
            btn.addEventListener("click", function (ev) {
              ev.preventDefault();
              ev.stopPropagation();
              ev.stopImmediatePropagation();
              showBaseTariffToast();
              return false;
            }, true);
          });
        }
      });
      // Landing pricing section
      document.querySelectorAll("main, .landing-page, [class*='pricing']").forEach(function (root) {
        root.querySelectorAll("span, p, div, strong").forEach(function (el) {
          if (!el || el.children.length) return;
          var t = String(el.textContent || "").trim();
          var parent = String((el.parentElement && el.parentElement.textContent) || "");
          if (/base/i.test(parent) && /₽\s*300|^₽\s*0$|^300$/.test(t) && t.length < 20) el.textContent = "Free";
          if (/plus/i.test(parent) && /₽\s*(500|400)|^500$|^400$/.test(t) && t.length < 20) el.textContent = "₽300";
        });
      });
    }

    function patchPiniaTariffs() {
      try {
        var root = document.querySelector("#app");
        var app = root && root.__vue_app__;
        var pinia = app && app.config && app.config.globalProperties && app.config.globalProperties.$pinia;
        if (!pinia || !pinia._s) return;
        pinia._s.forEach(function (store) {
          if (!store || typeof store !== "object") return;
          var lists = [];
          if (Array.isArray(store.tariffs)) lists.push(store.tariffs);
          if (Array.isArray(store.plans)) lists.push(store.plans);
          if (store.tariffInfo && Array.isArray(store.tariffInfo.tariffs)) lists.push(store.tariffInfo.tariffs);
          if (store.tariffProject && Array.isArray(store.tariffProject.tariffs)) lists.push(store.tariffProject.tariffs);
          if (store.tariffProject && store.tariffProject.tariff) lists.push([store.tariffProject.tariff]);
          lists.forEach(function (arr) {
            arr.forEach(function (p) {
              if (!p || typeof p !== "object") return;
              var tier = String(p.tier || p.slug || p.name || "").toLowerCase();
              if (tier === "base" || tier === "basic" || tier === "starter") {
                p.month_price = 0; p.price_month = 0; p.price = 0; p.is_free = true; p.can_select = false;
              } else if (tier === "plus") {
                p.month_price = 30000; p.price_month = 30000; p.price = 30000;
              } else if (tier === "enterprise" || tier === "custom") {
                p.month_price = 1000000; p.price_month = 1000000;
              }
            });
          });
        });
      } catch (_) {}
    }

    function swapNativePlan() {
      patchPiniaTariffs();
      forcePricesInNativeModal();
      var native = document.querySelector(".vfm .change-plan-modal:not(.checkapp-plan-sheet), .vfm__content .change-plan-modal:not(.checkapp-plan-sheet), .change-plan-modal:not(.checkapp-plan-sheet)");
      if (!native) return;
      var vfm = native.closest(".vfm");
      if (vfm && vfm.id !== "checkapp-plan-modal") {
        vfm.style.setProperty("display", "none", "important");
        vfm.style.setProperty("pointer-events", "none", "important");
        vfm.style.setProperty("opacity", "0", "important");
        vfm.style.setProperty("visibility", "hidden", "important");
      }
      if (!document.getElementById("checkapp-plan-modal") && typeof window.__checkappOpenPlanModal === "function") {
        window.__checkappOpenPlanModal();
      }
    }

    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.closest) return;
      var btn = t.closest("button, a, [role='button']");
      if (!btn) return;
      var txt = String(btn.textContent || "").trim();
      if (/^сменить|^change|улучшить тариф|сменить тариф|change plan|upgrade plan|выбрать тариф/i.test(txt)) {
        setTimeout(swapNativePlan, 30);
        setTimeout(swapNativePlan, 120);
        setTimeout(swapNativePlan, 350);
      }
      // Native Base select inside change-plan
      var planCard = t.closest(".plan, .change-plan-modal .plan");
      if (planCard && /base/i.test(String(planCard.textContent || "").slice(0, 80)) && /выбрать|select|chose/i.test(txt)) {
        if (!/plus|enterprise/i.test(String(planCard.querySelector("p, .tier, [class*='tier']") && planCard.querySelector("p, .tier, [class*='tier']").textContent || planCard.textContent || "").slice(0, 40))) {
          var head = String((planCard.querySelector("p") && planCard.querySelector("p").textContent) || "").toLowerCase();
          if (head.indexOf("base") >= 0) {
            ev.preventDefault();
            ev.stopPropagation();
            ev.stopImmediatePropagation();
            showBaseTariffToast();
            return false;
          }
        }
      }
    }, true);

    setInterval(function () {
      if (document.querySelector(".change-plan-modal:not(.checkapp-plan-sheet), .vfm .change-plan-modal")) {
        patchPiniaTariffs();
        forcePricesInNativeModal();
        swapNativePlan();
      }
    }, 1500);

    try {
      new MutationObserver(function () {
        if (document.querySelector(".change-plan-modal:not(.checkapp-plan-sheet)")) swapNativePlan();
      }).observe(document.documentElement, { childList: true, subtree: true });
    } catch (_) {}
  })();

  (function translateCombatLogRu() {
    const map = {
      Time: "Время",
      Attacker: "Атакующий",
      Target: "Цель",
      Weapon: "Оружие",
      Ammo: "Патроны",
      Bone: "Кость",
      Distance: "Дистанция",
      Old_hp: "Старое HP",
      New_hp: "Новое HP",
      Info: "Инфо",
      Unknown: "Неизвестно",
      killed: "убит",
      head: "голова",
      spine: "торс",
      torso: "торс",
      pelvis: "таз",
      "left arm": "левая рука",
      "right arm": "правая рука",
      "left leg": "левая нога",
      "right leg": "правая нога",
      "left hand": "левая кисть",
      "right hand": "правая кисть",
      "left foot": "левая стопа",
      "right foot": "правая стопа",
      neck: "шея",
      chest: "грудь"
    };
    function run() {
      const root = document.querySelector(".combatlog-modal");
      if (!root) return;
      root.querySelectorAll("th, td, span, p, div").forEach((el) => {
        if (!el || el.children.length) return;
        const t = String(el.textContent || "").trim();
        if (map[t]) el.textContent = map[t];
      });
    }
    setInterval(run, 500);
  })();

  (function dedupeSignageCards() {
    // Disabled: aggressive DOM fingerprinting hid the only card after refresh.
    // Server-side 0-based pagination already prevents duplicates.
  })();

  (function patchVueErrors() {
    const start = Date.now();
    const timer = setInterval(() => {
      const root = document.querySelector("#app") || document.querySelector("#app");
      const app = root && root.__vue_app__;
      if (!app || !app.config) {
        if (Date.now() - start > 15000) clearInterval(timer);
        return;
      }
      clearInterval(timer);
      const prev = app.config.errorHandler;
      const seenErr = Object.create(null);
      app.config.errorHandler = function (err, inst, info) {
        const msg = String((err && err.message) || err || "");
        if (/reading 'avatar'|initiator_id\.trim|filter is not a function|reading 'length'|reading 'map'|Cannot convert undefined or null to object|reading 'startTime'|reading 'toString'|502 Bad Gateway|<html>|Bad Gateway|ERR_BAD_RESPONSE/i.test(msg)) {
          return;
        }
        console.warn("[checkapp]", msg, info || "");
      };
    }, 100);
  })();

  (function patchProfileTelegramUnavailable() {
    function run() {
      document.querySelectorAll("button, a, [role='button']").forEach(function (el) {
        if (!el || el.dataset.checkappTgOff === "1") return;
        if (el.closest("footer, .landing-page, header, nav, aside")) return;
        const href = String(el.getAttribute("href") || "");
        if (/t\.me|telegram\.me/i.test(href)) return;
        const self = String(el.textContent || "").replace(/\s+/g, " ").trim();
        const parent = el.parentElement;
        const blob = String((parent && parent.textContent) || self);
        if (!/telegram/i.test(blob) && !/telegram/i.test(self)) return;
        const isAction = /подключ|connect|привяз|недоступ|telegram/i.test(self);
        if (!isAction) return;
        el.dataset.checkappTgOff = "1";
        el.setAttribute("disabled", "disabled");
        el.setAttribute("aria-disabled", "true");
        el.style.pointerEvents = "none";
        el.style.opacity = "0.55";
        if (el.tagName === "A") el.removeAttribute("href");
        if (self.length < 48) {
          if (!el.querySelector("svg, img")) {
            el.textContent = "Недоступно";
          } else {
            el.childNodes.forEach(function (n) {
              if (n.nodeType === 3 && String(n.textContent).trim()) n.textContent = " Недоступно";
            });
          }
        }
      });
    }
    setInterval(run, 700);
    try {
      new MutationObserver(run).observe(document.documentElement, { childList: true, subtree: true });
    } catch (_) {}
  })();

  (function patchConfigUrls() {
    function lockUrls(store) {
      if (!store || !store.Urls) return false;
      const ws = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/connection/websocket";
      try {
        Object.defineProperty(store.Urls, "Core", {
          configurable: true,
          enumerable: true,
          get: function () { return location.origin; },
          set: function () {}
        });
        Object.defineProperty(store.Urls, "Court", {
          configurable: true,
          enumerable: true,
          get: function () { return location.origin; },
          set: function () {}
        });
        Object.defineProperty(store.Urls, "Centrifugo", {
          configurable: true,
          enumerable: true,
          get: function () { return ws; },
          set: function () {}
        });
        store.Urls.Images = function (path) { return localImages(path); };
        store.Urls.__checkappPatched = true;
        return true;
      } catch (_) {
        try {
          store.Urls.Core = location.origin;
          store.Urls.Court = location.origin;
          store.Urls.Centrifugo = ws;
          store.Urls.Images = function (path) { return localImages(path); };
          store.Urls.__checkappPatched = true;
          return true;
        } catch (_) {}
      }
      return false;
    }
    setInterval(function () {
      try {
        const root = document.querySelector("#app");
        const app = root && root.__vue_app__;
        const pinia = app && app.config && app.config.globalProperties && app.config.globalProperties.$pinia;
        const store = pinia && pinia._s && pinia._s.get("config");
        if (store) lockUrls(store);
        patchCentrifugoStore(pinia);
      } catch (_) {}
    }, 50);
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) return;
      try {
        const root = document.querySelector("#app");
        const app = root && root.__vue_app__;
        const pinia = app && app.config && app.config.globalProperties && app.config.globalProperties.$pinia;
        patchCentrifugoStore(pinia);
      } catch (_) {}
    });

    function silenceCentrifugeClient(client) {
      if (!client || client.__caSilentErr) return;
      client.__caSilentErr = true;
      try { client._serverPing = 0; } catch (_) {}
      try { client._waitServerPing = function () {}; } catch (_) {}
      try { if (typeof client._clearServerPingTimeout === "function") client._clearServerPingTimeout(); } catch (_) {}
      try {
        if (client._config) {
          client._config.maxServerPingDelay = 0;
          if (client._config.timeout < 60000) client._config.timeout = 60000;
        }
      } catch (_) {}
      try {
        if (typeof client.removeAllListeners === "function") client.removeAllListeners("error");
      } catch (_) {}
      try {
        const origOn = client.on && client.on.bind(client);
        if (origOn) {
          client.on = function (ev, fn) {
            if (String(ev) === "error") return client;
            return origOn(ev, fn);
          };
        }
      } catch (_) {}
      try {
        const origEmit = client.emit && client.emit.bind(client);
        if (origEmit) {
          client.emit = function (ev) {
            if (String(ev) === "error") return true;
            return origEmit.apply(client, arguments);
          };
        }
      } catch (_) {}
    }

    function dismissCentrifugoSituation(pinia) {
      try {
        const sit = pinia && pinia._s && pinia._s.get("situation");
        if (!sit || typeof sit.close !== "function") return;
        let row = sit.current;
        if (row && typeof row === "object" && "value" in row) row = row.value;
        if (row && typeof row === "object" && "value" in row && row.value && (row.value.name || row.value.text_ru)) {
          row = row.value;
        }
        const blob = String((row && (row.name || "")) + " " + (row && (row.text_ru || row.text_en || row.text || "")));
        if (/error-centrifugo|серверу событий|event server/i.test(blob)) sit.close();
      } catch (_) {}
    }

    function hookClientFromSub(ret) {
      try {
        const sub = ret && (ret.sub || ret);
        const client = sub && (sub._centrifuge || (sub.sub && sub.sub._centrifuge));
        if (client) silenceCentrifugeClient(client);
      } catch (_) {}
    }

    function patchCentrifugoStore(pinia) {
      if (!pinia || !pinia._s) return;
      dismissCentrifugoSituation(pinia);
      const cf = pinia._s.get("centrifugo");
      if (!cf) return;
      if (cf.__checkappPatchedLive) return;
      cf.__checkappPatchedLive = true;
      try {
        cf.onError = function () { return { unsubscribe: function () {} }; };
      } catch (_) {}
      try {
        if (typeof cf.connect === "function") {
          const origConnect = cf.connect.bind(cf);
          cf.connect = function (token) {
            const out = origConnect(token);
            setTimeout(function () {
              try {
                if (typeof cf.subscribeSituation === "function") {
                  hookClientFromSub(cf.subscribeSituation(function () {}));
                }
              } catch (_) {}
            }, 0);
            return out;
          };
        }
      } catch (_) {}
      try {
        if (typeof cf.subscribeCheckActivity === "function") {
            const orig = cf.subscribeCheckActivity.bind(cf);
          cf.subscribeCheckActivity = function (projectId, cb) {
            const seen = Object.create(null);
            return orig(projectId, function (h) {
              if (!h || typeof h !== "object" || typeof cb !== "function") return;
              if (h.check_id == null && h.checkId == null) {
                if (h.data && typeof h.data === "object" && !Array.isArray(h.data)) h = h.data;
                else if (Array.isArray(h.data) && h.data[0]) h = h.data[0];
              }
              if (h && h.message && typeof h.message === "object" && !Array.isArray(h.message) && (h.message.type || h.message.kind || h.message.text || h.message.id != null)) {
                h = Object.assign({}, h.message, {
                  check_id: h.check_id != null ? h.check_id : h.message.check_id,
                  checkId: h.checkId != null ? h.checkId : h.message.checkId
                });
              }
              if (!h || typeof h !== "object") return;
              if (!h.meta || typeof h.meta !== "object") h.meta = {};
              const id = String(h.id != null ? h.id : "");
              if (id && seen[id]) return;
              if (id) seen[id] = 1;
              const cid = h.check_id != null ? h.check_id : h.checkId;
              const n = Number(cid);
              const s = String(n || cid || "");
              try {
                cb(Object.assign({}, h, { check_id: n, checkId: n, meta: h.meta }));
                if (s && String(n) === s) {
                  cb(Object.assign({}, h, { check_id: s, checkId: n, meta: h.meta }));
                }
              } catch (_) {}
            });
          };
        }
      } catch (_) {}
      try {
        if (typeof cf.subscribeCheckFinished === "function") {
          const origFin = cf.subscribeCheckFinished.bind(cf);
          cf.subscribeCheckFinished = function (projectId, cb) {
            try {
              if (projectId == null || projectId === "" || projectId === undefined) {
                projectId = piniaCurrentProjectId() || 0;
              }
              return origFin(projectId, function (c) {
                if (typeof cb !== "function") return;
                if (!c || typeof c !== "object" || Array.isArray(c)) return;
                const sid = String(c.steam_id || (c.suspect && c.suspect.steam_id) || (c.player && c.player.steam_id) || "");
                if (!sid || sid === "0" || sid === ".") return;
                if (!c.suspect && !c.player) return;
                const nid = Number(c.id || c.check_id || c.checkId || 0) || 0;
                cb(Object.assign({}, c, { id: nid || c.id }));
              });
            } catch (_) {
              return { unsubscribe: function () {} };
            }
          };
        }
      } catch (_) {}
      try {
        if (typeof cf.subscribePlayerStatus === "function") {
          const origPs = cf.subscribePlayerStatus.bind(cf);
          cf.subscribePlayerStatus = function (projectId, cb) {
            return origPs(projectId, function (p) {
              if (typeof cb !== "function") return;
              const safe = (p && typeof p === "object" && p.players && typeof p.players === "object") ? p : { players: {} };
              cb(safe);
            });
          };
        }
      } catch (_) {}
      try {
        if (typeof cf.subscribeSituation === "function") {
          const origSit = cf.subscribeSituation.bind(cf);
          cf.subscribeSituation = function (cb) {
            const ret = origSit(function (p) {
              if (typeof cb !== "function") return;
              cb(p && typeof p === "object" ? p : {});
            });
            hookClientFromSub(ret);
            return ret;
          };
          try { hookClientFromSub(origSit(function () {})); } catch (_) {}
        }
      } catch (_) {}
      try {
        if (typeof cf.subscribePlayerMessages === "function") {
          const origPm = cf.subscribePlayerMessages.bind(cf);
          cf.subscribePlayerMessages = function (projectId, cb) {
            return origPm(projectId, function (payload) {
              if (typeof cb !== "function") return;
              let data = payload;
              if (payload == null) data = { data: [] };
              else if (Array.isArray(payload)) data = { data: payload };
              else if (payload && Array.isArray(payload.data)) data = payload;
              else if (payload && typeof payload === "object" && (payload.text || payload.message || payload.id != null)) data = { data: [payload] };
              else data = { data: [] };
              (data.data || []).forEach(function (row) {
                if (row && typeof row === "object") row.initiator_id = asInitiatorId(row.initiator_id, row.steam_id);
              });
              cb(data);
            });
          };
        }
      } catch (_) {}
    }
  })();

  function unmountCheckappMap() {
    const box = document.getElementById("checkapp-live-map");
    if (box) box.remove();
    const wip = document.getElementById("checkapp-map-wip");
    if (wip) wip.remove();
    if (window.__checkappMapTimer) {
      clearInterval(window.__checkappMapTimer);
      window.__checkappMapTimer = 0;
    }
  }

  function mountCheckappMap() {}

  function restoreMapNav() {
    document.querySelectorAll("a[href*='/map'], [data-checkapp-hide-map-tab='1']").forEach(function (el) {
      if (el.closest && el.closest(".landing-page")) return;
      try {
        el.removeAttribute("data-checkapp-hide-map-tab");
        el.style.removeProperty("display");
        el.style.removeProperty("visibility");
        el.style.removeProperty("pointer-events");
        el.style.removeProperty("width");
        el.style.removeProperty("height");
        el.style.removeProperty("overflow");
        el.style.removeProperty("opacity");
      } catch (_) {}
    });
  }

  function replaceLegalText(value) {
    const host = (typeof location !== "undefined" && location.host) ? location.host : "127.0.0.1:8081";
    const origin = (typeof location !== "undefined" && location.origin) ? location.origin : ("http://" + host);
    return replaceBrandText(value)
      .replace(/https?:\/\/(?:www\.)?rustapp\.io/gi, origin)
      .replace(/https?:\/\/(?:www\.)?rustcheck\.cc/gi, origin)
      .replace(/https?:\/\/(?:www\.)?russiachect\.ru/gi, origin)
      .replace(/\brustapp\.io\b/gi, host)
      .replace(/\brustcheck\.cc\b/gi, host)
      .replace(/\brussiachect\.ru\b/gi, host)
      .replace(/help@rustapp\.io/gi, "help@" + host)
      .replace(/help@rustcheck\.cc/gi, "help@" + host)
      .replace(/help@russiachect\.ru/gi, "help@" + host)
      .replace(/help@checkapp\.local/gi, "help@" + host);
  }

  function replaceBrandText(value) {
    return String(value || "")
      .replace(/Checkapp\.cs/g, "RustApp.cs")
      .replace(/RustCheck\.cs/g, "RustApp.cs")
      .replace(/Rustcheck\.cs/g, "RustApp.cs")
      .replace(/Checkapp 266/g, "RustApp 266")
      .replace(/RustApp 266/g, "RustApp 266")
      .replace(/Rustcheck 266/g, "RustApp 266")
      .replace(/Checkapp official/g, "RustApp official")
      .replace(/RustCheck official/g, "RustApp official")
      .replace(/Rustcheck official/g, "RustApp official")
      .replace(/на все ваши серверы/gi, "в этот проект")
      .replace(/на всі ваші сервери/gi, "в цей проєкт")
      .replace(/all your servers/gi, "this project")
      /* visible brand only — case sensitive so help@checkapp.local and the
         window.__checkapp* hooks stay untouched */
      .replace(/CHECKAPP/g, "RUSTAPP")
      .replace(/Checkapp/g, "RustApp")
      .replace(/RustCheck/g, "RustApp")
      .replace(/Rustcheck/g, "RustApp");
  }

  function patchI18nMessageTree(obj) {
    if (!obj || typeof obj !== "object") return;
    if (Array.isArray(obj)) {
      obj.forEach(patchI18nMessageTree);
      return;
    }
    if (typeof obj.s === "string" && /Checkapp|RustApp|Rustcheck\.cs/i.test(obj.s)) {
      obj.s = replaceBrandText(obj.s);
    }
    Object.keys(obj).forEach(function (key) {
      const val = obj[key];
      if (typeof val === "string" && /Checkapp|RustApp|Rustcheck\.cs/i.test(val)) {
        obj[key] = replaceBrandText(val);
      } else if (val && typeof val === "object") {
        patchI18nMessageTree(val);
      }
    });
  }

  function patchBrandInRoot(root) {
    if (!root || !root.nodeType) return;
    const skip = "script,style,code,pre,[data-checkapp-brand-skip='1']";
    try {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        const parent = node.parentElement;
        if (parent && parent.closest && parent.closest(skip)) continue;
        const t = node.textContent || "";
        if (/Checkapp|RustApp|Rustcheck\.cs/i.test(t)) {
          node.textContent = replaceBrandText(t);
        }
      }
    } catch (_) {}
    root.querySelectorAll && root.querySelectorAll(".command, .bright, [class*='plugin'], [class*='command']").forEach(function (el) {
      if (!el || el.closest(skip)) return;
      const t = el.textContent || "";
      if (/Checkapp|RustApp|Rustcheck\.cs/i.test(t)) el.textContent = replaceBrandText(t);
    });
  }

  function patchPanelBrand() {
    const app = document.getElementById("app");
    if (app) patchBrandInRoot(app);
    document.querySelectorAll(".vfm, .vfm__content, .vfm-content, .vfm__overlay").forEach(patchBrandInRoot);
  }

  function patchBrandName(root) {
    const scope = root && root.querySelectorAll ? root : document;
    const skipSel = "script,style,code,pre,[data-checkapp-brand-skip='1']";
    function walkText(node) {
      if (!node) return;
      if (node.nodeType === 3) {
        const t = node.textContent || "";
        if (/Checkapp|RustApp|Rustcheck\.cs/i.test(t)) node.textContent = replaceBrandText(t);
        return;
      }
      if (node.nodeType !== 1 || node.closest && node.closest(skipSel)) return;
      for (let i = 0; i < node.childNodes.length; i++) walkText(node.childNodes[i]);
    }
    scope.querySelectorAll("title").forEach(function (el) {
      if (/Checkapp|RustApp/i.test(el.textContent || "")) el.textContent = replaceBrandText(el.textContent || "");
    });
    if (document.title && /Checkapp|RustApp/i.test(document.title)) document.title = replaceBrandText(document.title);
    scope.querySelectorAll(".landing-page, .landing-page header, .landing-page footer, .landing-page main").forEach(walkText);
    scope.querySelectorAll(".landing-page header,.landing-page footer,aside:not([class*='player']):not([class*='check']),nav:not([class*='player'])").forEach(function (area) {
      area.querySelectorAll("*").forEach(function (el) {
        if (!el || el.closest(skipSel)) return;
        if (el.children && el.children.length) return;
        const t = el.textContent;
        if (t && /Checkapp|RustApp/i.test(t)) el.textContent = replaceBrandText(t);
      });
    });
  }

  function patchLandingHeroSubtitle() {
    const path = location.pathname || "/";
    if (path !== "/" && path.replace(/\/+$/, "") !== "") return;
    document.querySelectorAll(".landing-page main section:first-of-type p").forEach(function (p) {
      const t = String(p.textContent || "").replace(/\s+/g, " ").trim();
      if (!/простой и надежный|simple and honest|простий і надійний/i.test(t)) return;
      p.dataset.checkappHeroSubtitle = "1";
      p.style.setProperty("color", "#eaeaea", "important");
      p.style.setProperty("opacity", "1", "important");
      p.style.setProperty("transition", "none", "important");
    });
  }

  function replaceLandingHeroLogo() {
    const path = location.pathname || "/";
    if (path !== "/" && path.replace(/\/+$/, "") !== "") return;
    const section = document.querySelector(".landing-page main section:first-of-type");
    if (!section) return;

    // Old hero used Pixi/canvas map preview — hide only map wrappers, not text blocks.
    section.querySelectorAll(":scope > div").forEach(function (wrap, idx) {
      if (idx > 0) return;
      if (wrap.querySelector("h1, h2, p")) return;
      if (!wrap.querySelector("canvas, video")) return;
      if (wrap.dataset.checkappHideHeroArt === "1") return;
      wrap.style.setProperty("display", "none", "important");
      wrap.style.setProperty("visibility", "hidden", "important");
      wrap.style.setProperty("height", "0", "important");
      wrap.style.setProperty("min-height", "0", "important");
      wrap.style.setProperty("overflow", "hidden", "important");
      wrap.dataset.checkappHideHeroArt = "1";
    });

    section.querySelectorAll("canvas, video").forEach(function (el) {
      if (el.dataset.checkappHideHeroArt === "1") return;
      el.style.setProperty("display", "none", "important");
      el.style.setProperty("visibility", "hidden", "important");
      el.style.setProperty("width", "0", "important");
      el.style.setProperty("height", "0", "important");
      el.style.setProperty("opacity", "0", "important");
      el.style.setProperty("pointer-events", "none", "important");
      el.dataset.checkappHideHeroArt = "1";
    });

    section.querySelectorAll("img, svg").forEach(function (el) {
      if (el.id === "checkapp-hero-logo") return;
      if (el.dataset.checkappHideHeroArt === "1") return;
      const src = String(el.getAttribute("src") || el.currentSrc || "");
      if (!/logo-mark|rustlogo|logo-avatar|1780921773745/i.test(src)) return;
      el.style.setProperty("display", "none", "important");
      el.dataset.checkappHideHeroArt = "1";
    });

    let img = document.getElementById("checkapp-hero-logo");
    if (!img) {
      img = document.createElement("img");
      img.id = "checkapp-hero-logo";
      img.alt = "RustApp";
      img.dataset.checkappLogoPatched = "1";
      img.style.cssText = "display:block!important;margin:0 auto 16px!important;width:112px!important;height:112px!important;max-width:112px!important;max-height:112px!important;border-radius:16px!important;object-fit:cover!important;position:relative!important;z-index:2!important;";
      const anchor = section.querySelector("h1") || section.querySelector("p");
      if (anchor && anchor.parentElement) anchor.parentElement.insertBefore(img, anchor);
      else section.insertBefore(img, section.firstChild);
    }
    if (img.src !== BRAND_LOGO) img.src = BRAND_LOGO;
    patchLandingHeroSubtitle();
  }

  function patchLandingLogo() {
    if (!isLandingPage()) return;
    const logo = BRAND_LOGO;
    replaceLandingHeroLogo();
    patchLandingHeroSubtitle();
    document.querySelectorAll(
      ".landing-page header img, .landing-page header a[href='/'] img, .landing-page [class*='logo'] img, .landing-page a[href='/'] img"
    ).forEach(function (img) {
      if (!img || img.id === "checkapp-hero-logo") return;
      if (img.dataset.checkappLogoPatched === "1" && img.src === logo) return;
      const src = String(img.getAttribute("src") || img.currentSrc || "");
      if (!/logo-mark|rustlogo|logo-avatar|1780921773745|checkapp|rustapp/i.test(src)) return;
      if (img.src !== logo) img.src = logo;
      img.alt = "RustApp";
      img.dataset.checkappLogoPatched = "1";
    });
    document.querySelectorAll(".landing-page header a[href='/'], .landing-page header [class*='logo']").forEach(function (wrap) {
      wrap.querySelectorAll("span, p, div, strong, b").forEach(function (el) {
        if (el.children && el.children.length) return;
        const t = el.textContent || "";
        if (/Checkapp|RustApp/i.test(t)) el.textContent = replaceBrandText(t);
      });
    });
  }

  function patchI18nBrand() {
    try {
      const root = document.querySelector("#app");
      const app = root && root.__vue_app__;
      if (!app || !app.config || !app.config.globalProperties) return false;
      const i18n = app.config.globalProperties.$i18n;
      if (!i18n) return false;
      if (!i18n.__checkappBrandPatched) {
        const orig = i18n.t.bind(i18n);
        const billingOverrides = {
          "court.navigation.moderation.text": "MODERATION",
          "court.navigation.settings.text": "CONTROL",
          "court.navigation.project.text": "PROJECT",
          "court.navigation.settings.info": "Настройки",
          "payments.project-ban.title": "🔒 Проект заблокирован",
          "payments.project-ban.subtitle": "Этот проект был заблокирован администрацией. Покупка или продление подписки для заблокированного проекта недоступны. Пока администратор не снимет блокировку, проект использовать нельзя.",
          "payments.project-forezen.title": "❄️ Проект заморожен",
          "payments.project-forezen.subtitle": "Срок подписки закончился. Продлите подписку, чтобы продолжить использование проекта.",
          "payments.project-forezen.cash.subtitle": "Не хватает средств для оплаты тарифа, пополните баланс!",
          "payments.project-forezen.limits.subtitle": "Срок подписки закончился. Продлите подписку, чтобы продолжить использование проекта.",
          "billing.project-ban.title": "🔒 Проект заблокирован",
          "billing.project-ban.subtitle": "Этот проект был заблокирован администрацией. Покупка или продление подписки для заблокированного проекта недоступны. Пока администратор не снимет блокировку, проект использовать нельзя.",
          "billing.project-forezen.title": "❄️ Проект заморожен",
          "billing.project-forezen.subtitle": "Срок подписки закончился. Продлите подписку, чтобы продолжить использование проекта.",
          "modal.server.download": "Скачайте и поместите плагин <span class='bright'>RustApp.cs</span> в папку <span class='bright'>plugins</span> на вашем сервере.",
          "modal.server.plugin-version-devblog-266": "RustApp 266",
          "modal.server.plugin-name": "RustApp.cs",
          "servers.required-update": "Серверам требуется обновление плагина RustApp! Рекомендуем устанавливать актуальные версии — в них могут быть новые функции и важные исправления.",
          "chat-all-servers-at-the-start": "Сообщение будет отправлено в этот проект.",
          "chat-all-servers-at-the-end": "Сообщение будет отправлено в этот проект.",
          "chat.all-servers-at-the-start": "Сообщение будет отправлено в этот проект.",
          "chat.all-servers-at-the-end": "Сообщение будет отправлено в этот проект.",
          "notify.chat-all-servers-at-the-start": "Сообщение будет отправлено в этот проект.",
          "notify.chat-all-servers-at-the-end": "Сообщение будет отправлено в этот проект.",
          "general.unavailable": "Недоступно",
          "integrations.telegram": "Telegram",
          "profile.telegram.unavailable": "Недоступно",
          "modal.client.telegram": "Недоступно",
          "integrations.telegram.connect": "Недоступно",
          "profile.integrations.telegram.connect": "Недоступно"
        };
        i18n.t = function (key) {
          const k = String(key || "");
          if (billingOverrides[k]) return billingOverrides[k];
          let out = orig.apply(i18n, arguments);
          if (typeof out === "string") {
            if (/на все ваши серверы|на всі ваші сервери|all your servers/i.test(out)) {
              out = "Сообщение будет отправлено в этот проект.";
            }
            if (/Checkapp|RustApp|Rustcheck\.cs/i.test(out)) out = replaceBrandText(out);
            if (/telegram/i.test(k) && /connect|подключ|привяз|unavailable/i.test(k + " " + out)) {
              if (/подключ|connect|привяз/i.test(out) && out.length < 40) out = "Недоступно";
            }
          }
          return out;
        };
        i18n.__checkappBrandPatched = true;
      }
      try {
        const msgs = i18n.global && i18n.global.messages;
        const raw = msgs && (msgs.value || msgs);
        if (raw) patchI18nMessageTree(raw);
        const locale = i18n.global && i18n.global.locale && (i18n.global.locale.value || i18n.global.locale);
        if (locale && raw && raw[locale]) patchI18nMessageTree(raw[locale]);
        i18n.__checkappMessagesPatched = true;
      } catch (_) {}
      return true;
    } catch (_) {
      return false;
    }
  }

  function readPanelProjectFlags() {
    try {
      const root = document.querySelector("#app");
      const pinia = root && root.__vue_app__ && root.__vue_app__.config.globalProperties.$pinia;
      const panel = pinia && pinia._s && pinia._s.get("panel");
      const project = panel && panel.project;
      if (!project || typeof project !== "object") return null;
      return {
        blocked: !!(project.blocked || project.is_blocked || project.is_banned || project.banned),
        frozen: !!(project.frozen || project.is_frozen),
        lifecycle: project.lifecycle || project.project_status || ""
      };
    } catch (_) {
      return null;
    }
  }

  function currentProjectBlockedFlag() {
    const slug = currentProjectSlug();
    const list = window.__checkappProjectsCache || [];
    for (let i = 0; i < list.length; i++) {
      const p = list[i];
      if (!p) continue;
      const match = !slug || String(p.domain || p.tag || "").toLowerCase() === slug.toLowerCase() || String(p.id) === slug;
      if (match && (p.blocked || p.is_blocked || p.is_banned || p.banned)) return true;
    }
    return projectIsBlockedNow();
  }

  function projectIsBlockedNow() {
    const tariff = window.__checkappTariff;
    if (tariff && (tariff.blocked || tariff.is_blocked || tariff.is_banned)) return true;
    const flags = readPanelProjectFlags();
    return !!(flags && flags.blocked);
  }

  function syncProjectBlockedState() {
    const blocked = currentProjectBlockedFlag();
    try {
      const root = document.querySelector("#app");
      const pinia = root && root.__vue_app__ && root.__vue_app__.config.globalProperties.$pinia;
      if (!pinia || !pinia._s) return;
      const court = pinia._s.get("court");
      if (court) court.is_banned = blocked;
      const panel = pinia._s.get("panel");
      if (panel && panel.project && typeof panel.project === "object") {
        panel.project.blocked = blocked;
        panel.project.is_blocked = blocked;
        panel.project.is_banned = blocked;
        panel.project.banned = blocked;
        if (blocked) {
          panel.project.frozen = false;
          panel.project.is_frozen = false;
        }
      }
      const tp = pinia._s.get("tariff-project");
      if (tp && blocked) {
        tp.blocked = true;
        tp.is_blocked = true;
        tp.is_banned = true;
        tp.renew_failed = false;
        tp.usage_failed = false;
        tp.frozen = false;
        tp.is_frozen = false;
      }
      if (window.__checkappTariff && blocked) {
        window.__checkappTariff.blocked = true;
        window.__checkappTariff.is_blocked = true;
        window.__checkappTariff.is_banned = true;
        window.__checkappTariff.renew_failed = false;
        window.__checkappTariff.frozen = false;
      }
    } catch (_) {}
  }

  function patchBlockedOverlayContent(root) {
    if (!root || root.dataset.checkappBlockedOverlayPatched === "1") return;
    const text = String(root.textContent || "").replace(/\s+/g, " ").trim();
    if (!/проект (заблокирован|заморожен)/i.test(text)) return;
    root.querySelectorAll("h1,h2,h3,h4,p,span,div").forEach(function (el) {
      if (el.children && el.children.length) return;
      const t = String(el.textContent || "").trim();
      if (/^❄️?$|^🧊?$|^⛄?$|^snowflake$/i.test(t) || t === "❄" || t === "❄️") el.textContent = "🔒";
      else if (/^🔒?$|^lock$/i.test(t) && t.length <= 2) el.textContent = "🔒";
      else if (/проект заморожен/i.test(t)) el.textContent = "🔒 Проект заблокирован";
      else if (/срок подписки|продлите подписку|лимит|не хватает средств|telegram|свяжитесь/i.test(t)) {
        el.textContent = "Этот проект был заблокирован администрацией. Покупка или продление подписки для заблокированного проекта недоступны. Пока администратор не снимет блокировку, проект использовать нельзя.";
      }
    });
    root.querySelectorAll("button,a,[role='button']").forEach(function (el) {
      const t = String(el.textContent || "").trim();
      if (/(биллинг|тариф|оплат|куп|продл|change plan|upgrade|go-to-tariff|telegram|t\.me)/i.test(t)) {
        el.style.display = "none";
        el.setAttribute("aria-hidden", "true");
        el.tabIndex = -1;
      }
    });
    root.dataset.checkappBlockedOverlayPatched = "1";
  }

  function patchBlockedProjectScreen() {
    if (isLandingPage() || isPublicAppPath()) return;
    syncProjectBlockedState();
    const blocked = currentProjectBlockedFlag();
    if (!blocked) {
      document.querySelectorAll("[data-checkapp-blocked-overlay-patched='1']").forEach(function (el) {
        delete el.dataset.checkappBlockedOverlayPatched;
      });
      return;
    }
    document.querySelectorAll("main section, main > div, main .card, main [class*='notify'], main [class*='Notify']").forEach(function (el) {
      const t = String(el.textContent || "");
      if (/проект (заблокирован|заморожен)/i.test(t)) patchBlockedOverlayContent(el);
    });
    document.querySelectorAll(
      "button,a,[role='button'],.select-button,.cpm-plan-btn,.change-plan-modal .select-button"
    ).forEach(function (el) {
      const txt = String(el.textContent || "").trim();
      if (!/(выбрать|сменить тариф|улучшить|оплат|куп|продл|change plan|upgrade|select|пополн)/i.test(txt)) return;
      if (el.closest("#checkapp-notice-root")) return;
      el.disabled = true;
      el.setAttribute("aria-disabled", "true");
      el.style.opacity = "0.45";
      el.style.pointerEvents = "none";
    });
  }

  function isLandingTrustReviewsSection(section) {
    if (!section || section.dataset.checkappProjectsCarousel === "1") return false;
    const headings = section.querySelectorAll("h1,h2,h3,h4,span,p");
    for (let i = 0; i < headings.length; i++) {
      const el = headings[i];
      if (el.children && el.children.length) continue;
      const t = String(el.textContent || "").trim();
      if (!t) continue;
      if (
        /^Нам доверяют$/i.test(t) || /^НАМ ДОВЕРЯЮТ$/i.test(t) ||
        /^Отзывы организаций$/i.test(t) || /^Loved by Orgs$/i.test(t) ||
        /^What orgs are saying$/i.test(t) ||
        /^Почитайте,\s*что говорят о работе с нами/i.test(t) ||
        /^Read what those for whom we work/i.test(t)
      ) return true;
    }
    return false;
  }

  function isLandingProjectsCarouselSection(section) {
    if (!section || section.dataset.checkappHideTrust === "1") return false;
    if (isLandingTrustReviewsSection(section)) return false;
    const projects = section.querySelectorAll(".project");
    if (projects.length >= 2) return true;
    const rows = section.querySelectorAll(":scope > div > div");
    if (rows.length >= 2) {
      let withCards = 0;
      rows.forEach(function (row) {
        if (row.querySelector(".project, .skeleton")) withCards++;
      });
      if (withCards >= 2) return true;
    }
    return false;
  }

  function patchLandingHomeProjects() {
    const path = location.pathname || "/";
    if (path !== "/" && path.replace(/\/+$/, "") !== "") return;
    document.querySelectorAll(".landing-page main > section, main > section").forEach(function (section) {
      if (isLandingTrustReviewsSection(section)) {
        if (section.dataset.checkappHideTrust === "1") return;
        section.style.setProperty("display", "none", "important");
        section.style.setProperty("visibility", "hidden", "important");
        section.style.setProperty("height", "0", "important");
        section.style.setProperty("min-height", "0", "important");
        section.style.setProperty("max-height", "0", "important");
        section.style.setProperty("margin", "0", "important");
        section.style.setProperty("padding", "0", "important");
        section.style.setProperty("overflow", "hidden", "important");
        section.style.setProperty("opacity", "0", "important");
        section.style.setProperty("pointer-events", "none", "important");
        section.dataset.checkappHideTrust = "1";
        return;
      }
      if (section.querySelector(".scroll-container") || section.id === "checkapp-projects-ribbon" || isLandingProjectsCarouselSection(section)) {
        showLandingRibbonSection(section);
      }
    });
    mountLandingProjectsCarousel();
  }

  (function prefetchLandingStatsEarly() {
    function loadLandingStats() {
      const path = location.pathname || "/";
      if (path !== "/" && path.replace(/\/+$/, "") !== "") return;
      fetchLandingStatsNormalized().then(function (obj) {
        if (!obj) return;
        mountLandingProjectsCarousel();
      });
    }
    loadLandingStats();
    setInterval(loadLandingStats, 20000);
    window.addEventListener("popstate", loadLandingStats);
  })();

  if (!window.__checkappLandingLogoObserver) {
    let logoPatchQueued = false;
    window.__checkappLandingLogoObserver = new MutationObserver(function () {
      if (!isLandingPage()) return;
      if (window.__checkappLandingStable) return;
      if (logoPatchQueued) return;
      logoPatchQueued = true;
      requestAnimationFrame(function () {
        logoPatchQueued = false;
        try {
          patchLandingLogo();
          patchBrandName(document.querySelector(".landing-page") || document);
          patchI18nBrand();
          mountLandingProjectsCarousel();
        } catch (_) {}
      });
    });
    window.__checkappLandingLogoObserver.observe(document.documentElement, { childList: true, subtree: true });
  }

  function isRcHomePath() {
    const path = location.pathname || "/";
    return path === "/" || path === "/index.html" || /^\/client\/auth/.test(path);
  }

  function isRcProfilePath() {
    const path = location.pathname || "/";
    return (
      /^\/client\/profile(?:\/|$)/.test(path) ||
      path === "/profile" ||
      path === "/client" ||
      path === "/home" ||
      /^\/client\/create(?:\/|$)/.test(path)
    );
  }

  function isVueProjectPickerVisible() {
    const nodes = document.querySelectorAll(".profile");
    for (let i = 0; i < nodes.length; i++) {
      const el = nodes[i];
      if (!el || el.closest(".vfm, .signage-card, .client-edit-modal, .player-modal, #rc-dash")) continue;
      const txt = String(el.textContent || "");
      if (/Создать новый проект|Create a new project|Настройки аккаунта|Account settings|Личный профиль|Personal profile|Выйти с аккаунта/i.test(txt)) {
        return true;
      }
    }
    return false;
  }

  function hideVueProjectPicker() {
    document.querySelectorAll(".profile").forEach(function (el) {
      if (!el || el.closest(".vfm, .signage-card, .client-edit-modal, .player-modal, #rc-dash")) return;
      const txt = String(el.textContent || "");
      if (!/Создать новый проект|Create a new project|Настройки аккаунта|Account settings|Личный профиль|Personal profile|Выйти с аккаунта/i.test(txt)) return;
      el.style.setProperty("display", "none", "important");
      el.style.setProperty("visibility", "hidden", "important");
      el.style.setProperty("pointer-events", "none", "important");
      el.setAttribute("data-rc-vue-picker-hidden", "1");
    });
  }

  function unmountRcProfile() {
    if (document.documentElement.classList.contains("rc-dash-modal")) return;
    if (isVueProjectPickerVisible()) return;
    if (window.unmountRcDash) window.unmountRcDash();
    var css = document.getElementById("rc-dash-css");
    if (css) css.remove();
    var dashScript = document.getElementById("rc-dash-js");
    if (dashScript) { /* keep script cached */ }
    const el = document.getElementById("rc-profile-bg");
    if (el) el.remove();
    const dismiss = document.getElementById("rc-profile-dismiss");
    if (dismiss) dismiss.remove();
    document.documentElement.classList.remove("rc-profile-on", "rc-dash-on");
  }

  function loadRcDash(cb) {
    /* classic mode keeps the real SPA profile — never pull in the rc-dash layer */
    if (RC_CLASSIC) return;
    const src = "/rc-dash.js?v=23";
    function boot() { if (typeof cb === "function") cb(); }
    let s = document.getElementById("rc-dash-js");
    if (s && s.getAttribute("src") !== src) {
      s.remove();
      s = null;
      window.mountRcDash = null;
      window.unmountRcDash = null;
      window.openRcDashSettings = null;
      window.openRcDashCreate = null;
    }
    if (window.mountRcDash) {
      boot();
      return;
    }
    if (s && (s.getAttribute("data-rc-loaded") === "1" || s.dataset.rcError === "1")) {
      s.remove();
      s = null;
      window.mountRcDash = null;
      window.unmountRcDash = null;
      window.openRcDashSettings = null;
      window.openRcDashCreate = null;
    }
    if (!s) {
      s = document.createElement("script");
      s.id = "rc-dash-js";
      s.src = src;
      s.onload = function () {
        s.setAttribute("data-rc-loaded", "1");
        boot();
      };
      s.onerror = function () {
        s.dataset.rcError = "1";
        try { s.remove(); } catch (_) {}
      };
      document.head.appendChild(s);
    } else {
      s.addEventListener("load", function () {
        s.setAttribute("data-rc-loaded", "1");
        boot();
      }, { once: true });
    }
  }

  function mountRcProfile() {
    /* classic mode: show the original Vue profile, no rc-dash replacement */
    if (RC_CLASSIC) return;
    const path = location.pathname || "/";
    if (/^\/client\/create(?:\/|$)/.test(path)) {
      try { sessionStorage.setItem("rc-open-create", "1"); } catch (_) {}
      location.replace("/client/profile" + location.search + location.hash);
      return;
    }
    if (!isRcProfilePath() && !isVueProjectPickerVisible()) {
      unmountRcProfile();
      return;
    }
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", mountRcProfile, { once: true });
      return;
    }
    if (!document.body) return;
    hideVueProjectPicker();
    loadRcDash(function () {
      hideVueProjectPicker();
      if (window.mountRcDash) window.mountRcDash();
      hideVueProjectPicker();
    });
  }

  (function hijackVuePersonalProfile() {
    /* classic mode: the original SPA owns the profile screen — never hijack
       its clicks and never hide the real Vue profile modal */
    if (RC_CLASSIC) return;
    let lastGo = 0;
    let seenModal = false;
    function hideVueProfileModal() {
      document.querySelectorAll(".client-edit-modal").forEach(function (modal) {
        const wrap = modal.closest(".vfm, .vfm__container, .n-modal-container, [class*='vfm']") || modal;
        wrap.style.setProperty("display", "none", "important");
        wrap.style.setProperty("visibility", "hidden", "important");
        wrap.style.setProperty("pointer-events", "none", "important");
      });
    }
    function goRcPersonalProfile() {
      hideVueProfileModal();
      const overlay = document.getElementById("settingsOverlay");
      if (overlay && overlay.classList.contains("active") && document.getElementById("rc-dash")) return;
      if (Date.now() - lastGo < 700) return;
      lastGo = Date.now();
      try { sessionStorage.removeItem("rc-open-settings"); } catch (_) {}
      try { sessionStorage.removeItem("rc-profile-return"); } catch (_) {}
      if (isRcProfilePath() || isVueProjectPickerVisible()) {
        mountRcProfile();
        setTimeout(function () {
          if (window.openRcDashSettings) window.openRcDashSettings();
        }, 50);
        return;
      }
      loadRcDash(function () {
        if (window.mountRcDash) window.mountRcDash({ modal: true });
      });
    }
    function goRcCreateProject() {
      if (Date.now() - lastGo < 400) return;
      lastGo = Date.now();
      try { sessionStorage.setItem("rc-open-create", "1"); } catch (_) {}
      if (isRcProfilePath() || isVueProjectPickerVisible() || document.getElementById("rc-dash")) {
        mountRcProfile();
        setTimeout(function () {
          if (window.openRcDashCreate) window.openRcDashCreate();
        }, 60);
        return;
      }
      location.assign("/client/profile#create");
    }
    window.goRcPersonalProfile = goRcPersonalProfile;
    window.goRcCreateProject = goRcCreateProject;
    if (!document.getElementById("rc-hide-vue-profile")) {
      const style = document.createElement("style");
      style.id = "rc-hide-vue-profile";
      style.textContent =
        ".client-edit-modal,.vfm:has(.client-edit-modal),.vfm__container:has(.client-edit-modal),.n-modal-container:has(.client-edit-modal){display:none!important;visibility:hidden!important;pointer-events:none!important}" +
        "html.rc-dash-on .profile:not(.signage-card):not(.client-edit-modal):not(.player-modal)," +
        "html.rc-dash-on .profile[data-rc-vue-picker-hidden]{display:none!important;visibility:hidden!important;pointer-events:none!important}";
      (document.head || document.documentElement).appendChild(style);
    }
    document.addEventListener("click", function (e) {
      const t = e.target;
      if (!t || !t.closest) return;
      if (t.closest("#rc-dash, #rc-home, .settings-overlay, .modal-overlay")) return;

      const vuePicker = t.closest(".profile");
      if (vuePicker && !vuePicker.closest(".vfm, .signage-card, .client-edit-modal, .player-modal")) {
        const row = t.closest("a, button, [role='button'], .item, .action, .button, .ra-button");
        if (row) {
          const label = String((row.textContent || "") + " " + (row.getAttribute("aria-label") || "")).trim();
          if (/Настройки аккаунта|Account settings|Личный профиль|Personal profile/i.test(label)) {
            e.preventDefault();
            e.stopPropagation();
            if (e.stopImmediatePropagation) e.stopImmediatePropagation();
            goRcPersonalProfile();
            return;
          }
          if (/Создать новый проект|Create a new project|Создать проект/i.test(label)) {
            e.preventDefault();
            e.stopPropagation();
            if (e.stopImmediatePropagation) e.stopImmediatePropagation();
            goRcCreateProject();
            return;
          }
        }
      }

      const footer = t.closest(".navigation .footer");
      if (!footer) return;
      if (t.closest("[class*='logout'],[class*='sign-out'],.exit")) return;
      const profileBtn = footer.querySelector("a.btn-footer, button.btn-footer, .n-avatar, [class*='avatar']");
      const hit = t.closest("a.btn-footer, button.btn-footer, .n-avatar, [class*='avatar'], img");
      if (!profileBtn || !hit || !(profileBtn === hit || profileBtn.contains(hit) || hit.contains(profileBtn))) return;
      e.preventDefault();
      e.stopPropagation();
      if (e.stopImmediatePropagation) e.stopImmediatePropagation();
      goRcPersonalProfile();
    }, true);
    function watchModal() {
      if (isVueProjectPickerVisible()) {
        mountRcProfile();
      }
      const exists = !!document.querySelector(".client-edit-modal");
      if (!exists) {
        seenModal = false;
        return;
      }
      if (seenModal) return;
      seenModal = true;
      goRcPersonalProfile();
    }
    try {
      const app = document.getElementById("app") || document.body;
      new MutationObserver(watchModal).observe(app, { childList: true, subtree: true });
    } catch (_) {}
    setInterval(watchModal, 400);
  })();

  function unmountRcHome() {
    const el = document.getElementById("rc-home");
    if (el) el.remove();
    document.documentElement.classList.remove("rc-home-on", "rc-home-light");
  }

  function mountRcHome() {
    if (RC_CLASSIC) { unmountRcHome(); return; }
    if (!isRcHomePath()) {
      unmountRcHome();
      return;
    }
    if (document.getElementById("rc-home")) return;
    if (!document.getElementById("rc-home-css")) {
      const link = document.createElement("link");
      link.id = "rc-home-css";
      link.rel = "stylesheet";
      link.href = "/rc-home.css?v=16";
      document.head.appendChild(link);
    } else {
      const link = document.getElementById("rc-home-css");
      if (link && link.getAttribute("href") !== "/rc-home.css?v=16") link.href = "/rc-home.css?v=16";
    }
    /* critical chip fix — even if cached CSS is stale on VDS */
    if (!document.getElementById("rc-home-chips-critical")) {
      const crit = document.createElement("style");
      crit.id = "rc-home-chips-critical";
      crit.textContent =
        "#rc-home .chips{display:flex!important;flex-wrap:wrap!important;align-items:center!important;gap:8px!important;}" +
        "#rc-home .chip{display:inline-flex!important;flex-direction:row!important;align-items:center!important;gap:7px!important;" +
        "width:auto!important;height:auto!important;min-height:34px!important;padding:8px 12px!important;border-radius:999px!important;" +
        "border:1px solid rgba(255,255,255,.06)!important;background:rgba(255,255,255,.018)!important;font-size:11px!important;color:#a9a9a9!important;white-space:nowrap!important;}" +
        "#rc-home .chip svg,#rc-home .chip .ico{width:14px!important;height:14px!important;min-width:14px!important;min-height:14px!important;" +
        "max-width:14px!important;max-height:14px!important;flex:0 0 14px!important;display:block!important;}" +
        "#rc-home .chip span{display:inline!important;font-size:11px!important;color:inherit!important;opacity:1!important;visibility:visible!important;white-space:nowrap!important;}";
      (document.head || document.documentElement).appendChild(crit);
    }
    document.documentElement.classList.add("rc-home-on");
    const root = document.createElement("div");
    root.id = "rc-home";
    root.innerHTML =
      '<div class="bg"></div><div class="noise"></div>' +
      '<div class="controls"><div class="control-pill">' +
        '<button class="lang-btn active" type="button" data-lang="ru">RU</button>' +
        '<button class="lang-btn" type="button" data-lang="en">EN</button>' +
        '<button class="theme-btn" type="button" id="themeToggle" aria-label="Theme">' +
          '<svg id="themeIcon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>' +
        "</button></div></div>" +
      '<main><section class="shell"><div class="hero">' +
        '<div class="eyebrow" data-i18n="eyebrow">RustApp Panel</div>' +
        '<h1 data-i18n-html="title">Управление без <span class="dim">лишнего.</span></h1>' +
        '<p class="lead" data-i18n="lead">Простой и надежный инструмент для серьезных проектов. Минималистичный, легкий, безопасный.</p>' +
        '<div class="chips">' +
          '<div class="chip"><svg class="ico" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg><span data-i18n="chip1">Мониторинг в реальном времени</span></div>' +
          '<div class="chip"><svg class="ico" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c.8-4.3 3.5-6.5 8-6.5s7.2 2.2 8 6.5"/></svg><span data-i18n="chip2">Проверки игроков</span></div>' +
          '<div class="chip"><svg class="ico" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M9 12h6M9 16h4"/></svg><span data-i18n="chip3">Журнал аудита</span></div>' +
          '<div class="chip"><svg class="ico" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 4 7v6c0 5 3.4 8.4 8 9.5 4.6-1.1 8-4.5 8-9.5V7Z"/><path d="m9 12 2 2 4-4"/></svg><span data-i18n="chip4">Модерация</span></div>' +
          '<div class="chip"><svg class="ico" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg><span data-i18n="chip5">Изоляция проектов</span></div>' +
        "</div></div>" +
        '<form class="card" id="rc-form">' +
          '<div class="card-head"><div><h2 data-i18n="loginTitle">Вход в панель</h2><p data-i18n="loginSub">Используйте данные своего аккаунта</p></div></div>' +
          '<div class="field"><label data-i18n="loginLabel">Логин или email</label><div class="input">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="8" r="4"/><path d="M4 21c.8-4.3 3.5-6.5 8-6.5s7.2 2.2 8 6.5"/></svg>' +
            '<input id="rc-email" autocomplete="username" data-i18n-placeholder="loginPlaceholder" placeholder="Введите логин" /></div></div>' +
          '<div class="field"><label data-i18n="passwordLabel">Пароль</label><div class="input">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>' +
            '<input id="rc-pass" type="password" autocomplete="current-password" data-i18n-placeholder="passwordPlaceholder" placeholder="Введите пароль" /></div></div>' +
          '<div class="row" id="rc-forgot-row"><a class="forgot" href="https://t.me/RustCheckcc" target="_blank" rel="noreferrer" data-i18n="forgot">Забыли пароль?</a></div>' +
          '<p class="auth-error" id="rc-auth-error"></p>' +
          '<button type="submit" data-i18n="loginButton">ВОЙТИ В ПАНЕЛЬ</button>' +
          '<div class="auth-switch"><a href="#" id="rc-auth-switch" data-i18n="switchToSignup">Нет аккаунта? Создать</a></div>' +
          '<div class="divider"></div><div class="foot">RustApp Panel © 2026</div>' +
        "</form>" +
      "</section></main>" +
      '<footer class="site-footer"><div class="footer-inner"><div class="footer-socials">' +
        '<a class="social" href="https://t.me/RustCheckcc" target="_blank" rel="noreferrer" aria-label="Telegram" data-checkapp-telegram="1">' +
          '<svg viewBox="0 0 24 24"><path d="M21.6 3.2 18.4 19c-.24 1.12-.88 1.39-1.78.87l-4.87-3.59-2.35 2.26c-.26.26-.48.48-.98.48l.35-4.96 9.02-8.15c.39-.35-.09-.55-.61-.2L6.03 12.73 1.23 11.23c-1.04-.33-1.06-1.04.22-1.54L20.22 2.46c.87-.32 1.63.2 1.38.74Z"/></svg></a>' +
        '<a class="social discord" href="https://discord.gg/w2n9RarMpB" target="_blank" rel="noreferrer" aria-label="Discord" data-checkapp-discord="1">' +
          '<svg viewBox="0 0 24 24"><path d="M19.54 5.34A16.3 16.3 0 0 0 15.44 4l-.5 1.02a15.2 15.2 0 0 0-5.86 0L8.56 4a16.4 16.4 0 0 0-4.1 1.34C1.87 9.18 1.17 12.93 1.52 16.62a16.5 16.5 0 0 0 5.03 2.55l1.22-1.67c-.67-.25-1.31-.56-1.92-.93l.47-.36c3.7 1.72 7.72 1.72 11.38 0l.48.36c-.61.37-1.26.68-1.93.93l1.22 1.67a16.5 16.5 0 0 0 5.03-2.55c.42-4.28-.72-8-2.96-11.28ZM8.85 14.34c-1.11 0-2.02-1.03-2.02-2.29s.89-2.29 2.02-2.29c1.14 0 2.04 1.04 2.02 2.29 0 1.26-.89 2.29-2.02 2.29Zm6.3 0c-1.11 0-2.02-1.03-2.02-2.29s.89-2.29 2.02-2.29c1.14 0 2.04 1.04 2.02 2.29 0 1.26-.88 2.29-2.02 2.29Z"/></svg></a>' +
      "</div></div></footer>";
    document.body.appendChild(root);

    const translations = {
      ru: { eyebrow: "RustApp Panel", title: 'Управление без <span class="dim">лишнего.</span>', lead: "Простой и надежный инструмент для серьезных проектов. Минималистичный, легкий, безопасный.", chip1: "Мониторинг в реальном времени", chip2: "Проверки игроков", chip3: "Журнал аудита", chip4: "Модерация", chip5: "Изоляция проектов", loginTitle: "Вход в панель", loginSub: "Используйте данные своего аккаунта", signupTitle: "Создать аккаунт", signupSub: "Регистрация занимает меньше минуты", loginLabel: "Логин или email", loginPlaceholder: "Введите логин", passwordLabel: "Пароль", passwordPlaceholder: "Введите пароль", forgot: "Забыли пароль?", loginButton: "ВОЙТИ В ПАНЕЛЬ", signupButton: "СОЗДАТЬ АККАУНТ", switchToSignup: "Нет аккаунта? Создать", switchToLogin: "Уже есть аккаунт? Войти", errAuth: "Неверный логин или пароль", errExists: "Этот email уже зарегистрирован", errInvalid: "Проверьте email и пароль" },
      en: { eyebrow: "RustApp Panel", title: 'Control without <span class="dim">noise.</span>', lead: "A simple and reliable tool for serious projects. Minimal, lightweight, secure.", chip1: "Real-time monitoring", chip2: "Player checks", chip3: "Audit log", chip4: "Moderation", chip5: "Project isolation", loginTitle: "Panel login", loginSub: "Use your account credentials", signupTitle: "Create account", signupSub: "Registration takes less than a minute", loginLabel: "Login or email", loginPlaceholder: "Enter login", passwordLabel: "Password", passwordPlaceholder: "Enter password", forgot: "Forgot password?", loginButton: "LOG IN", signupButton: "CREATE ACCOUNT", switchToSignup: "No account? Sign up", switchToLogin: "Already have an account? Log in", errAuth: "Wrong login or password", errExists: "This email is already registered", errInvalid: "Check email and password" }
    };

    function setLang(lang) {
      const t = translations[lang];
      document.documentElement.lang = lang;
      root.querySelectorAll("[data-i18n]").forEach(function (el) { el.textContent = t[el.dataset.i18n]; });
      root.querySelectorAll("[data-i18n-html]").forEach(function (el) { el.innerHTML = t[el.dataset.i18nHtml]; });
      root.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) { el.placeholder = t[el.dataset.i18nPlaceholder]; });
      root.querySelectorAll(".lang-btn").forEach(function (btn) { btn.classList.toggle("active", btn.dataset.lang === lang); });
      localStorage.setItem("rustcheck-lang", lang);
      applyAuthMode();
    }

    root.querySelectorAll(".lang-btn").forEach(function (btn) {
      btn.addEventListener("click", function () { setLang(btn.dataset.lang); });
    });

    const themeToggle = document.getElementById("themeToggle");
    const themeIcon = document.getElementById("themeIcon");
    function setTheme(theme) {
      root.classList.toggle("light", theme === "light");
      document.documentElement.classList.toggle("rc-home-light", theme === "light");
      themeIcon.innerHTML = theme === "light"
        ? '<path d="M21 12.8A8.5 8.5 0 1 1 11.2 3 6.5 6.5 0 0 0 21 12.8Z"/>'
        : '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>';
      localStorage.setItem("rustcheck-theme", theme);
    }
    themeToggle.addEventListener("click", function () {
      setTheme(root.classList.contains("light") ? "dark" : "light");
    });

    let signupMode = false;
    const errEl = document.getElementById("rc-auth-error");
    const switchEl = document.getElementById("rc-auth-switch");
    const forgotRow = document.getElementById("rc-forgot-row");
    function currentDict() {
      return translations[localStorage.getItem("rustcheck-lang") || "ru"] || translations.ru;
    }
    function showAuthError(msg) {
      if (!errEl) return;
      errEl.textContent = msg || "";
      errEl.classList.toggle("show", !!msg);
    }
    function applyAuthMode() {
      const t = currentDict();
      const title = root.querySelector("[data-i18n='loginTitle']");
      const sub = root.querySelector("[data-i18n='loginSub']");
      const btn = root.querySelector("#rc-form button[type='submit']");
      if (title) title.textContent = signupMode ? t.signupTitle : t.loginTitle;
      if (sub) sub.textContent = signupMode ? t.signupSub : t.loginSub;
      if (btn) btn.textContent = signupMode ? t.signupButton : t.loginButton;
      if (switchEl) switchEl.textContent = signupMode ? t.switchToLogin : t.switchToSignup;
      if (forgotRow) forgotRow.style.display = signupMode ? "none" : "";
      const pass = document.getElementById("rc-pass");
      if (pass) pass.autocomplete = signupMode ? "new-password" : "current-password";
      showAuthError("");
    }

    setLang(localStorage.getItem("rustcheck-lang") || "ru");
    setTheme(localStorage.getItem("rustcheck-theme") || "dark");

    if (switchEl) {
      switchEl.addEventListener("click", function (e) {
        e.preventDefault();
        signupMode = !signupMode;
        applyAuthMode();
      });
    }

    document.getElementById("rc-form").addEventListener("submit", function (e) {
      e.preventDefault();
      const email = String(document.getElementById("rc-email").value || "").trim();
      const password = String(document.getElementById("rc-pass").value || "");
      const btn = e.target.querySelector("button[type='submit']");
      if (!email || !password) return;
      btn.disabled = true;
      showAuthError("");
      const t = currentDict();
      const path = signupMode ? "/auth/classic/sign-up" : "/auth/classic/sign-in";
      const payload = signupMode
        ? { email: email, password: password, name: email.split("@")[0] }
        : { email: email, password: password, login: email };
      const post = (typeof window.__checkappOrigFetch === "function") ? window.__checkappOrigFetch : fetch.bind(window);
      post(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload)
      }).then(function (res) {
        return res.text().then(function (raw) {
          let data = raw;
          try { data = JSON.parse(raw); } catch (_) {}
          return { res: res, data: data };
        });
      }).then(function (out) {
        let token = "";
        if (typeof out.data === "string" && out.data.split(".").length === 3) token = out.data;
        else if (out.data && typeof out.data === "object") token = out.data.token || out.data.access_token || "";
        if (!out.res.ok || !token) {
          const msg = String((out.data && (out.data.message || out.data.error)) || "");
          if (/email\.exists|already registered|уже зарегистр/i.test(msg)) throw new Error("exists");
          if (signupMode) throw new Error("invalid");
          throw new Error("auth");
        }
        storeAuthToken(token);
        if (signupMode) sessionStorage.setItem("rc-complete-registration", "1");
        location.assign("/client/profile");
      }).catch(function (err) {
        btn.disabled = false;
        const code = String((err && err.message) || "");
        showAuthError(code === "exists" ? t.errExists : (code === "invalid" ? t.errInvalid : t.errAuth));
      });
    });
  }

  function isLandingPage() {
    const path = location.pathname || "/";
    return path === "/" || path === "/pricing" || /^\/client\/auth/.test(path) || /^\/profile/.test(path);
  }

  function cleanupDiscordSpam() {
    document.querySelectorAll("a[data-checkapp-discord]").forEach(function (el) {
      if (!isLandingPage()) el.remove();
    });
    if (!isLandingPage()) {
      document.querySelectorAll("a").forEach(function (a) {
        const label = (a.textContent || "").trim();
        if (label === "Discord" && !a.querySelector("svg") && !a.classList.contains("checkapp-discord-btn")) {
          a.remove();
        }
      });
    }
  }

  function ensureDiscordButton() {
    if (document.getElementById("rc-home")) return;
    if (!isLandingPage()) return;
    const footer = document.querySelector(".landing-page footer") || document.querySelector("main footer") || document.querySelector("footer");
    if (!footer) return;
    const socials = footer.querySelector(".socials") || footer.querySelector("[class*='social']") || footer.querySelector(".footer-content") || footer;
    let btn = footer.querySelector("a[data-checkapp-discord]");
    if (!btn) {
      btn = document.createElement("a");
      btn.setAttribute("data-checkapp-discord", "1");
      btn.target = "_blank";
      btn.rel = "noreferrer noopener";
      btn.className = "checkapp-discord-btn";
      btn.title = "Discord";
      btn.setAttribute("aria-label", "Discord");
      btn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M20.317 4.3698a19.7913 19.7913 0 00-4.8851-1.5152.0741.0741 0 00-.0785.0371c-.211.3753-.4447.8648-.6083 1.2495-1.8447-.2762-3.68-.2762-5.4868 0-.1636-.3933-.4058-.8742-.6177-1.2495a.077.077 0 00-.0785-.037 19.7363 19.7363 0 00-4.8852 1.515.0699.0699 0 00-.0321.0277C.5334 9.0458-.319 13.5799.0992 18.0578a.0824.0824 0 00.0312.0561c2.0528 1.5076 4.0413 2.4228 5.9929 3.0294a.0777.0777 0 00.0842-.0276c.4616-.6304.8731-1.2952 1.226-1.9944a.076.076 0 00-.0416-.1057c-.4616-.6304-.8731-1.2952-1.226-1.9942a.076.076 0 00-.0416-.1057 12.865 12.865 0 01-1.872-.8914.077.077 0 01-.0076-.1287c.1258-.0943.2517-.1925.3718-.2914a.0743.0743 0 01.0776-.0105c3.9278 1.7933 8.18 1.7933 12.0614 0a.0739.0739 0 01.0785.0095c.1202.0989.246.1981.3728.2924a.077.077 0 01-.0066.1276 12.291 12.291 0 01-1.873.8894.0766.0766 0 00-.0407.1067c.3604.698.7719 1.3628 1.2252 1.9932a.076.076 0 00.0842.0286c1.961-.6067 3.9495-1.5219 6.0023-3.0294a.077.077 0 00.0313-.0552c.5004-5.177-.8382-9.6739-3.5485-13.6604a.061.061 0 00-.0312-.0286zM8.02 15.3312c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9555-2.4189 2.157-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.9555 2.4189-2.1569 2.4189zm7.9748 0c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9554-2.4189 2.1569-2.419 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.946 2.4189-2.1568 2.4189z"/></svg>';
    }
    btn.href = "https://discord.gg/w2n9RarMpB";
    document.querySelectorAll('a[href*="discord.gg"], a[href*="discord.com/invite"], a[data-checkapp-discord]').forEach(function (a) {
      a.href = "https://discord.gg/w2n9RarMpB";
    });
    btn.style.setProperty("display", "inline-flex", "important");
    btn.style.setProperty("visibility", "visible", "important");
    btn.style.setProperty("opacity", "1", "important");
    if (btn.parentElement !== socials) {
      socials.appendChild(btn);
    }
    const tg = socials.querySelector('a[href*="t.me"], a[href*="telegram"], a[data-checkapp-telegram]');
    if (tg && tg.parentElement === socials && btn.previousElementSibling !== tg && btn !== tg.nextElementSibling) {
      tg.insertAdjacentElement("afterend", btn);
    }
    if (!document.getElementById("checkapp-discord-btn-style")) {
      const st = document.createElement("style");
      st.id = "checkapp-discord-btn-style";
      st.textContent = ".landing-page footer .socials,.landing-page footer [class*='social']{display:inline-flex!important;align-items:center!important;gap:10px!important;}.checkapp-discord-btn{display:inline-flex!important;align-items:center!important;justify-content:center!important;width:28px!important;height:28px!important;border-radius:8px!important;background:#5865f2!important;color:#fff!important;transition:background .2s!important;vertical-align:middle!important;visibility:visible!important;opacity:1!important;}.checkapp-discord-btn:hover{background:#4752c4!important;color:#fff!important;}.checkapp-discord-btn svg{width:18px!important;height:18px!important;display:block!important;}";
      document.head.appendChild(st);
    }
  }

  function patchLandingPrices() {
    // Landing / pricing: Base → Free, Plus → ₽300/месяц
    const roots = [];
    try {
      if (document.body) roots.push(document.body);
      document.querySelectorAll(".landing-page, [class*='pricing'], [class*='tariff'], .change-plan-modal, .plan-list, #checkapp-plan-modal").forEach(function (el) {
        roots.push(el);
      });
    } catch (_) {}
    const seen = new Set();
    roots.forEach(function (root) {
      if (!root || seen.has(root)) return;
      seen.add(root);
      root.querySelectorAll("h1,h2,h3,h4,p,span,div,strong,b,button,li").forEach(function (el) {
        if (!el || el.children.length > 3) return;
        const raw = String(el.textContent || "").trim();
        if (!raw || raw.length > 48) return;
        const parentTxt = String((el.parentElement && el.parentElement.textContent) || "");
        const isBaseBlock = /base/i.test(parentTxt) && !/plus|enterprise/i.test(raw);
        const isPlusBlock = /plus/i.test(parentTxt) && !/enterprise|base/i.test(raw);
        // Price-looking nodes near Base/Plus cards
        if (/^(₽\s*)?(300|500|0)\s*(₽)?(\s*\/\s*мес(яц)?)?$/i.test(raw) || /^(₽\s*)?(300|500)\s*₽?$/i.test(raw)) {
          if (isBaseBlock || (/base/i.test(parentTxt) && !/plus/i.test(parentTxt))) {
            if (el.childNodes.length === 1 && el.childNodes[0].nodeType === 3) el.textContent = "Free";
            else if (!el.children.length) el.textContent = "Free";
          } else if (isPlusBlock || /plus/i.test(parentTxt)) {
            if (el.childNodes.length === 1 && el.childNodes[0].nodeType === 3) el.textContent = "₽300";
            else if (!el.children.length) el.textContent = "₽300";
          }
        }
        if (/^₽\s*300(\s*\/\s*мес)?/i.test(raw) && /base/i.test(parentTxt)) {
          if (!el.children.length || (el.childNodes.length === 1 && el.childNodes[0].nodeType === 3)) el.textContent = "Free";
        }
        if (/^(\$\s*)?[\d.,]+(\s*\/\s*(month|мес(яц)?))?$/i.test(raw) && (isPlusBlock || /plus/i.test(parentTxt))) {
          if (el.childNodes.length === 1 && el.childNodes[0].nodeType === 3) el.textContent = "₽300";
          else if (!el.children.length) el.textContent = "₽300";
        }
        // Suffix "/месяц" under Base Free — hide
        if (isBaseBlock && /^\/\s*мес/i.test(raw)) {
          el.style.display = "none";
        }
      });
    });
    patchPricingPlanCards();
    // Native change-plan modal: rewrite prices + block Base select
    document.querySelectorAll(".change-plan-modal .plan, .vfm__content .plan, .plan-list .plan").forEach(function (card) {
      const txt = String(card.textContent || "");
      const tier = /enterprise/i.test(txt) ? "enterprise" : (/plus/i.test(txt) ? "plus" : (/base/i.test(txt) ? "base" : ""));
      if (!tier) return;
      card.querySelectorAll("div, span, p, strong, b").forEach(function (el) {
        if (el.children.length) return;
        const t = String(el.textContent || "").trim();
        if (!t || t.length > 32) return;
        if (tier === "base" && (/₽\s*\d+/.test(t) || /^\d+\s*₽/.test(t) || t === "₽300" || t === "300")) {
          el.textContent = "Free";
        }
        if (tier === "plus" && (/₽\s*500/.test(t) || t === "500" || /₽\s*400/.test(t) || t === "400")) {
          el.textContent = "₽300";
        }
        if (tier === "base" && /^\/\s*мес/i.test(t)) el.style.display = "none";
      });
      const btn = card.querySelector("button, .select-button, [class*='select']");
      if (btn && tier === "base" && !btn.disabled && !btn.dataset.checkappBaseBlock) {
        btn.dataset.checkappBaseBlock = "1";
        btn.addEventListener("click", function (ev) {
          const cur = window.__checkappTariff && window.__checkappTariff.tariff;
          const curTier = String((cur && (cur.tier || cur.slug)) || "").toLowerCase();
          // Always block selecting Base (given only on project create)
          ev.preventDefault();
          ev.stopPropagation();
          ev.stopImmediatePropagation();
          showBaseTariffToast();
          return false;
        }, true);
      }
    });
  }

  function patchPricingPlanCards() {
    function paintPriceWhite(el) {
      if (!el) return;
      el.style.setProperty("color", "#f2f2f2", "important");
      const wrap = el.closest(".mb-5") || el.parentElement;
      if (wrap) wrap.style.setProperty("color", "#f2f2f2", "important");
    }
    function setBaseFreePrice(card) {
      card.querySelectorAll(".mb-5").forEach(function (box) {
        if (box.querySelector(".plan-icon")) return;
        const txt = String(box.textContent || "").replace(/\s+/g, " ").trim();
        if (/^(base|plus)$/i.test(txt)) return;
        if (!/free|\$|₽|€|^0/i.test(txt)) return;
        box.dataset.checkappFreePrice = "1";
        box.dataset.checkappPriceReady = "1";
        box.innerHTML = '<span class="text-grey-50 text-4xl font-bold checkapp-price-free">Free</span>';
      });
    }
    function setPlusRubPrice(card) {
      card.querySelectorAll(".mb-5").forEach(function (box) {
        if (box.querySelector(".plan-icon")) return;
        const txt = String(box.textContent || "").replace(/\s+/g, " ").trim();
        if (/^(base|plus)$/i.test(txt)) return;
        if (!/\$|₽|€|\d/.test(txt)) return;
        box.dataset.checkappPriceReady = "1";
        box.innerHTML = '<span class="text-grey-50 text-4xl font-bold checkapp-price-free">₽300</span><span class="text-grey-400"> /месяц</span>';
      });
    }
    function markPriceBoxesReady(card) {
      card.querySelectorAll(".mb-5").forEach(function (box) {
        if (box.querySelector(".plan-icon")) return;
        box.dataset.checkappPriceReady = "1";
      });
    }
    document.querySelectorAll(".plan-card, [class*='plan-card']").forEach(function (card) {
      if (card.classList && card.classList.contains("enterprise-card")) return;
      const head = String((card.querySelector("span") && card.querySelector("span").textContent) || "").trim().toLowerCase();
      const tier = head === "plus" ? "plus" : (head === "base" ? "base" : "");
      if (!tier) return;
      card.querySelectorAll(".mb-5").forEach(function (box) {
        box.style.setProperty("color", "#f2f2f2", "important");
        box.querySelectorAll("span, div, p").forEach(function (el) {
          el.style.setProperty("color", "#f2f2f2", "important");
        });
      });
      card.querySelectorAll("span, div, p, strong, b").forEach(function (el) {
        if (el.children.length) return;
        const t = String(el.textContent || "").trim();
        if (!t || t.length > 28) return;
        if (tier === "base") {
          if (/^(\$|₽|€)\s*0(\s*\/\s*(month|мес(яц)?))?$/i.test(t) ||
              /^0(\s*(\$|₽|€))?(\s*\/\s*(month|мес(яц)?))?$/i.test(t) ||
              /^(\$|₽|€)\s*0$/i.test(t) || t === "0" ||
              /^free\s*\/\s*(month|мес(яц)?)$/i.test(t)) {
            el.textContent = "Free";
            paintPriceWhite(el);
          }
          if (t === "Free") paintPriceWhite(el);
          if (/^\/\s*(month|мес(яц)?)/i.test(t)) {
            el.style.display = "none";
          }
        } else if (tier === "plus") {
          if (/^(\$|₽)\s*[\d.,]+/i.test(t) || t === "$500" || t === "500" || t === "₽400" || t === "₽300") {
            el.textContent = "₽300";
            paintPriceWhite(el);
          }
          if (/^\/\s*(month|мес(яц)?)/i.test(t)) {
            el.textContent = "/месяц";
            paintPriceWhite(el);
          }
        }
      });
      card.querySelectorAll("div, span, p").forEach(function (el) {
        if (tier !== "base") return;
        const combined = String(el.textContent || "").replace(/\s+/g, " ").trim();
        if (/^free\s*\/\s*(month|мес(яц)?)$/i.test(combined) && combined.length < 24) {
          el.textContent = "Free";
          paintPriceWhite(el);
        }
        if (combined === "Free") paintPriceWhite(el);
      });
      if (tier === "base") setBaseFreePrice(card);
      if (tier === "plus") setPlusRubPrice(card);
      markPriceBoxesReady(card);
    });
  }

  (function bootPricingPatchEarly() {
    let queued = false;
    function shouldRun() {
      const path = location.pathname || "";
      return path === "/pricing" || path === "/";
    }
    function run() {
      if (!shouldRun()) return;
      patchPricingPlanCards();
    }
    function queueRun() {
      if (!shouldRun() || queued) return;
      queued = true;
      requestAnimationFrame(function () {
        queued = false;
        run();
      });
    }
    run();
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", run);
    }
    try {
      new MutationObserver(queueRun).observe(document.documentElement, { childList: true, subtree: true });
    } catch (_) {}
    window.addEventListener("popstate", run);
  })();

  function patchLegalContent() {
    document.querySelectorAll(".modal, [class*='modal'], [class*='Modal']").forEach(function (root) {
      root.querySelectorAll("p, li, span, a, strong, h1, h2, h3, h4, div").forEach(function (el) {
        if (el.closest("a[data-checkapp-discord]")) return;
        if (el.innerHTML && /rustapp/i.test(el.innerHTML) && el.children.length) {
          el.innerHTML = replaceLegalText(el.innerHTML);
        } else if (el.childNodes.length === 1 && el.childNodes[0].nodeType === 3 && /rustapp/i.test(el.textContent || "")) {
          el.textContent = replaceLegalText(el.textContent);
        }
      });
    });
  }

  function patchStatsBackgrounds() {
    injectLandingStatsBgStyles();
  }

  function watchStatsBackgrounds() {
    if (window.__checkappStatsBgWatch) return;
    window.__checkappStatsBgWatch = true;
    injectLandingStatsBgStyles();
  }

  (function bootLandingStatsBg() {
    const path = location.pathname || "/";
    if (path !== "/" && path.replace(/\/+$/, "") !== "") return;
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", watchStatsBackgrounds);
    } else {
      watchStatsBackgrounds();
    }
  })();

  function removeLandingFeatureDemo() {
    const path = location.pathname || "/";
    if (path !== "/") return;
    const featureTabRe = /^(игроки|players|чат|chat|проверки|checks|inspections|рисунки|signages|drawings|баны|bans|статистика|statistics)$/i;
    const onlineRe = /(серверов онлайн|servers online|игроков онлайн|players online|юзеров онлайн|users online|модераторов онлайн|moderators online)/i;
    const demoImgRe = /players\.webp|chat\.webp|check\.webp|drawings\.webp|bans\.webp|stats-players\.webp/i;

    // Undo old broad hides from previous patch
    document.querySelectorAll(".landing-page main > section[data-checkapp-hide-demo='1'], main > section[data-checkapp-hide-demo='1']").forEach(function (section) {
      section.style.removeProperty("display");
      section.style.removeProperty("visibility");
      section.style.removeProperty("height");
      section.style.removeProperty("min-height");
      section.style.removeProperty("margin");
      section.style.removeProperty("padding");
      section.style.removeProperty("overflow");
      delete section.dataset.checkappHideDemo;
    });

    document.querySelectorAll(".landing-page main > section, main > section").forEach(function (section) {
      const hasDemo = section.querySelector("[style*='landing-mt-bg'], [style*='landing-mt-bg-2']") ||
        section.querySelector("img[src*='players.webp'], img[src*='chat.webp'], img[src*='check.webp'], img[src*='bans.webp'], img[src*='stats-players.webp'], img[src*='drawings.webp']");
      if (!hasDemo) return;
      if (section.querySelector(".stats-card, .stats-bg")) return;

      section.querySelectorAll("button, [role='tab'], div[class*='cursor-pointer']").forEach(function (el) {
        if (el.dataset.checkappHideFeatureTab === "1") return;
        if (el.closest(".stats-card, .stats-bg")) return;
        const label = String(el.textContent || "").replace(/\s+/g, " ").trim();
        if (!featureTabRe.test(label)) return;
        el.style.setProperty("display", "none", "important");
        el.dataset.checkappHideFeatureTab = "1";
      });

      section.querySelectorAll("div, nav").forEach(function (row) {
        if (row.dataset.checkappHideDemoTabs === "1") return;
        if (row.closest(".stats-card, .stats-bg")) return;
        const tabs = row.querySelectorAll("button, [role='tab'], div[class*='cursor-pointer']");
        if (tabs.length < 3) return;
        let featureCount = 0;
        tabs.forEach(function (tab) {
          const label = String(tab.textContent || "").replace(/\s+/g, " ").trim();
          if (featureTabRe.test(label)) featureCount++;
        });
        if (featureCount >= 3) {
          row.style.setProperty("display", "none", "important");
          row.dataset.checkappHideDemoTabs = "1";
        }
      });

      section.querySelectorAll("img").forEach(function (img) {
        const src = String(img.getAttribute("src") || "");
        if (!demoImgRe.test(src)) return;
        img.style.setProperty("display", "none", "important");
        const shotWrap = img.closest("[class*='max-w-5xl']") || img.closest("[class*='overflow-hidden']") || img.parentElement;
        if (shotWrap && shotWrap !== section && !shotWrap.closest(".stats-card")) {
          shotWrap.style.setProperty("display", "none", "important");
          shotWrap.dataset.checkappHideDemoShot = "1";
        }
      });

      section.querySelectorAll("[class*='flex'][class*='wrap'], [class*='flex'][class*='gap']").forEach(function (row) {
        if (row.dataset.checkappHideOnline === "1") return;
        if (row.closest(".stats-card, .stats-bg, [class*='stats-card']")) return;
        let onlineHits = 0;
        row.querySelectorAll("p, span, div").forEach(function (node) {
          if (node.children && node.children.length > 6) return;
          if (onlineRe.test(String(node.textContent || "").replace(/\s+/g, " "))) onlineHits++;
        });
        if (onlineHits >= 2) {
          row.style.setProperty("display", "none", "important");
          row.dataset.checkappHideOnline = "1";
        }
      });

      section.querySelectorAll("p, span").forEach(function (el) {
        if (el.dataset.checkappHideOnline === "1") return;
        if (el.closest(".stats-card, .stats-bg, [class*='stats-card'], [data-checkapp-hide-online='1']")) return;
        if (el.children && el.children.length > 6) return;
        const t = String(el.textContent || "").replace(/\s+/g, " ").trim();
        if (!onlineRe.test(t)) return;
        const row = el.closest("[class*='flex'][class*='wrap']") ||
          el.closest("[class*='flex'][class*='gap']") ||
          el.parentElement;
        if (row && !row.closest(".stats-card, .stats-bg")) {
          row.style.setProperty("display", "none", "important");
          row.dataset.checkappHideOnline = "1";
        }
      });

      const shell = section.querySelector("[style*='landing-mt-bg']");
      if (shell && shell.dataset.checkappDemoTrimmed !== "1") {
        shell.style.setProperty("display", "none", "important");
        shell.dataset.checkappDemoTrimmed = "1";
      }
      section.style.setProperty("padding", "0", "important");
      section.style.setProperty("margin", "0", "important");
      section.style.setProperty("min-height", "0", "important");
    });
  }

  function patchLandingLegal() {
    try {
      cleanupDiscordSpam();
      patchLegalContent();
      patchLandingPrices();
      if (!isLandingPage()) return;
      if (window.__checkappLandingLegalDone) {
        ensureDiscordButton();
        return;
      }
      removeLandingFeatureDemo();
      if (!document.documentElement.classList.contains("checkapp-home-revealed")) {
        revealLandingHomePage();
      } else {
        try { lockLandingHomeStable(); } catch (_) {}
      }
      replaceLandingHeroLogo();
      patchLandingHeroSubtitle();
      patchBrandName(document.querySelector(".landing-page") || document);
      patchLandingLogo();
      patchI18nBrand();
      patchLandingHomeProjects();
      // Remove Documentation nav link only (exact docs host / label)
      document.querySelectorAll("a[href*='docs.rustapp'], a").forEach(function (a) {
        const href = (a.getAttribute("href") || "").toLowerCase();
        const label = (a.textContent || "").trim().toLowerCase();
        if (href.includes("docs.rustapp") || label === "документация" || label === "documentation" || label === "docs") {
          a.style.display = "none";
          const li = a.closest("li");
          if (li) li.style.display = "none";
        }
      });
      // Hide hero map video only — never hide parent (logo/CTA live in same wrapper)
      document.querySelectorAll("video").forEach(function (v) {
        const src = String(v.getAttribute("src") || v.getAttribute("preview") || v.currentSrc || "");
        if (/landing-map|map\.webm|map-preview/i.test(src)) {
          v.style.setProperty("display", "none", "important");
          v.style.setProperty("visibility", "hidden", "important");
          v.style.setProperty("height", "0", "important");
          v.style.setProperty("opacity", "0", "important");
          v.removeAttribute("autoplay");
          try { v.pause(); } catch (_) {}
          // Strip frame from the map container without hiding Checkapp logo siblings
          const wrap = v.parentElement;
          if (wrap && wrap !== document.body) {
            wrap.style.setProperty("border", "none", "important");
            wrap.style.setProperty("outline", "none", "important");
            wrap.style.setProperty("box-shadow", "none", "important");
            wrap.style.setProperty("background", "transparent", "important");
            wrap.style.setProperty("min-height", "0", "important");
            wrap.style.setProperty("height", "auto", "important");
            wrap.style.setProperty("aspect-ratio", "auto", "important");
            wrap.style.setProperty("padding", "0", "important");
            wrap.style.setProperty("overflow", "visible", "important");
            wrap.classList.add("checkapp-hero-no-map");
          }
        }
      });
      const footers = document.querySelectorAll(".landing-page footer, main footer, footer");
      footers.forEach(function (el) {
        function isBannedSocial(a) {
          if (!a || a.getAttribute("data-checkapp-discord") === "1") return false;
          const href = (a.getAttribute("href") || "").toLowerCase();
          const label = (a.getAttribute("aria-label") || a.getAttribute("title") || a.textContent || "").toLowerCase().trim();
          const svg = (a.querySelector("svg") && a.querySelector("svg").innerHTML) || "";
          if (href.includes("github") || href.includes("x.com") || href.includes("twitter") || href.includes("x.com")) return true;
          if (label.includes("github") || label === "x" || label === "twitter" || label.includes("git hub")) return true;
          // GitHub / X icon path fingerprints when href is missing or router-link
          if (/M12 0c-6\.626|octocat|github/i.test(svg)) return true;
          if (/M18\.244 2\.25h3\.308l-7\.227|twitter|M23 3a10\.9/i.test(svg)) return true;
          return false;
        }
        el.querySelectorAll("a").forEach(function (a) {
          if (!isBannedSocial(a)) return;
          a.setAttribute("data-checkapp-hide-social", "1");
          a.style.setProperty("display", "none", "important");
          try { a.remove(); } catch (_) {}
        });
        // ensure Telegram button exists
        const socials = el.querySelector(".socials") || el.querySelector("[class*='social']") || el;
        if (socials && !socials.querySelector("a[href*='t.me'], a[href*='telegram']")) {
          const tg = document.createElement("a");
          tg.href = "https://t.me/RustCheckcc";
          tg.target = "_blank";
          tg.rel = "noreferrer noopener";
          tg.title = "Telegram";
          tg.setAttribute("aria-label", "Telegram");
          tg.setAttribute("data-checkapp-telegram", "1");
          tg.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg>';
          socials.appendChild(tg);
        }
        socials.querySelectorAll("a[href*='t.me'], a[href*='telegram'], a[data-checkapp-telegram]").forEach(function (a) {
          a.setAttribute("href", "https://t.me/RustCheckcc");
          a.style.display = "inline-flex";
          a.style.alignItems = "center";
          a.style.justifyContent = "center";
          a.style.width = "28px";
          a.style.height = "28px";
        });
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        const doomed = [];
        while (walker.nextNode()) {
          const t = walker.currentNode;
          const v = t.nodeValue || "";
          if (/Afineevsky|INN 390514490479|OGRN:\s*321392600034709/i.test(v)) doomed.push(t);
          else if (/rustapp/i.test(v)) t.nodeValue = replaceLegalText(v);
        }
        doomed.forEach(function (t) { t.nodeValue = ""; });
        if (socials) {
          socials.style.display = "inline-flex";
          socials.style.alignItems = "center";
          socials.style.gap = "10px";
        }
      });
      ensureDiscordButton();
      patchStatsBackgrounds();
      window.__checkappLandingLegalDone = true;
    } catch (err) {
      try { console.warn("[checkapp] landing patch", err); } catch (_) {}
    }
  }

  function removeMapFromUi() {
    restoreMapNav();
  }

  function hideDrawingsAndMap() {
    const path = location.pathname || "";
    restoreMapNav();
    const verdictMap = { FinishedClear: "Чист", FinishedBan: "Бан", Canceled: "Отмена", Cancelled: "Отмена", Pending: "На проверке" };
    if (/\/checks/.test(path)) {
      document.querySelectorAll("td, span, div, p, button, a").forEach((el) => {
        if (el.childNodes.length !== 1 || el.childNodes[0].nodeType !== 3) return;
        const t = (el.textContent || "").trim();
        if (verdictMap[t]) el.textContent = verdictMap[t];
      });
    }
    if (isLandingPage() && !window.__checkappLandingLegalDone) {
      patchLandingLegal();
    }
  }

  setInterval(hideDrawingsAndMap, 300);
  hideDrawingsAndMap();
  window.addEventListener("popstate", hideDrawingsAndMap);

  (function patchFinishedCheckActions() {
    function checkIdInRow(row) {
      if (!row) return "";
      const candidates = [row].concat(Array.from(row.querySelectorAll ? row.querySelectorAll("span,p,div,a,button") : []));
      const found = candidates.find(function (el) {
        return el && (!el.children || el.children.length === 0) && /^#\d+$/.test(String(el.textContent || "").trim());
      });
      return found ? String(found.textContent || "").trim().slice(1) : "";
    }
    function run() {
      if (!/\/checks\/?$/.test(String(location.pathname || ""))) return;
      document.querySelectorAll("button,a,[role='button']").forEach(function (button) {
        const label = String(button.textContent || "").replace(/\s+/g, " ").trim();
        if (!/^Начать проверку$/i.test(label)) return;
        let row = button;
        let id = "";
        for (let i = 0; i < 8 && row; i += 1, row = row.parentElement) {
          id = checkIdInRow(row);
          if (id) break;
        }
        if (!id) return;
        const rowText = String((row && row.textContent) || "");
        if (!/Чист|Бан|Отмена|FinishedClear|FinishedBan|Canceled/i.test(rowText)) return;
        button.textContent = "Перейти к проверке";
        button.setAttribute("data-checkapp-check-id", id);
      });
    }
    setInterval(run, 250);
    setTimeout(run, 400);
  })();

  (function cleanupAlertAuditGaps() {
    function run() {
      const path = location.pathname || "";
      if (path.includes("/alerts")) {
        // Only hide rows that are STILL pure skeleton after load (no real text, no avatar img)
        document.querySelectorAll("[class*='alert-row'], .n-data-table-tr, tr").forEach(function (row) {
          if (row.getAttribute("data-checkapp-empty-alert") === "1") return;
          const hasSk = row.querySelector(".alert-skeleton");
          if (!hasSk) return;
          const txt = String(row.textContent || "").replace(/\s+/g, " ").trim();
          const hasImg = row.querySelector("img");
          if (hasImg || txt.length > 20) return;
          row.style.display = "none";
          row.setAttribute("data-checkapp-empty-alert", "1");
        });
        document.querySelectorAll(".skeleton.shrink-0, .skeleton.rounded-md.shrink-0").forEach(function (sk) {
          if (sk.offsetWidth < 8 || sk.offsetHeight < 8) return;
          if (sk.querySelector("img")) return;
          if (sk.dataset.checkappAvatarFixed === "1") return;
          sk.dataset.checkappAvatarFixed = "1";
          sk.style.background = "transparent";
          sk.innerHTML = "";
          const img = document.createElement("img");
          img.src = PLACEHOLDER;
          img.alt = "";
          img.style.cssText = "width:100%;height:100%;object-fit:cover;border-radius:8px;display:block;";
          img.onerror = function () { img.src = location.origin + "/local/logo-avatar.png"; };
          sk.appendChild(img);
        });
        document.querySelectorAll("img").forEach(function (img) {
          if (img.dataset.checkappErrBound === "1") return;
          img.dataset.checkappErrBound = "1";
          img.addEventListener("error", function () {
            if (/logo-avatar|placeholder/i.test(img.src)) return;
            img.src = PLACEHOLDER;
          });
        });
      }
      // Discord/integration wizard: unlock custom-switch + n-switch (SPA disables when modelValue===undefined)
      document.querySelectorAll(".custom-switch input[type='checkbox'], .vfm .n-switch, .n-modal .n-switch, .n-dropdown-menu input[type='checkbox'], [role='menu'] input[type='checkbox']").forEach(function (el) {
        try {
          const sw = el.classList && el.classList.contains("n-switch") ? el : (el.closest(".custom-switch, .n-switch") || el);
          if (sw && sw.classList) {
            sw.classList.remove("n-switch--disabled");
            sw.removeAttribute("disabled");
            sw.setAttribute("aria-disabled", "false");
            sw.style.pointerEvents = "auto";
            sw.style.cursor = "pointer";
          }
          el.removeAttribute("disabled");
          el.disabled = false;
          el.style.pointerEvents = "auto";
          el.style.cursor = "pointer";
        } catch (_) {}
      });
    }
    setInterval(run, 400);
    window.addEventListener("popstate", run);
    // Force toggle when SPA keeps inputs disabled
    document.addEventListener("click", function (ev) {
      const t = ev.target;
      if (!t || !t.closest) return;
      const label = t.closest(".custom-switch");
      if (!label) return;
      const input = label.querySelector("input[type='checkbox']");
      if (!input) return;
      if (input.disabled || input.getAttribute("disabled") != null) {
        input.disabled = false;
        input.removeAttribute("disabled");
        try {
          const next = !input.checked;
          input.checked = next;
          input.dispatchEvent(new Event("input", { bubbles: true }));
          input.dispatchEvent(new Event("change", { bubbles: true }));
        } catch (_) {}
      }
    }, true);
  })();

  (function enforceTierAndBilling() {
    window.__checkappTariff = window.__checkappTariff || null;
    window.__checkappTariffReady = !!(window.__checkappTariffReady || window.__checkappTariff);
    window.__checkappAutokickDemo = !!window.__checkappAutokickDemo;

    function tierSlugFast() {
      return currentProjectTierSlug();
    }

    function isPlusTier() {
      return true; // Base = full access
    }

    function refreshTierFromServer() {
      const headers = { Accept: "application/json" };
      const slug = currentProjectSlug();
      if (slug) headers["X-Checkapp-Project"] = slug;
      fetch("/tariff/", { credentials: "include", cache: "no-store", headers: headers })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (!data) return;
          normalizeTariffPayload(data);
        })
        .catch(function () {});
    }

    function isPlusOnlyRoute() {
      const path = location.pathname || "";
      const full = path + (location.search || "");
      if (/\/stats(?:\/|$|\?)/i.test(path) || /\/project-stats/i.test(path) || /\/statistics/i.test(path)) return true;
      if (/\/auto-kick(?:\/|$|\?)/i.test(path)) return true;
      if (/\/integrations\/(api|custom|rcc)/i.test(path)) return true;
      if (/\/settings\/(?:integrations\/)?(api|auto-kick|autokick)/i.test(path)) return true;
      if (/\/settings/i.test(full) && /(?:section=|tab=)(api|auto-kick|autokick|integrations)/i.test(full)) return true;
      return false;
    }

    function loadTariff() {
      const headers = { Accept: "application/json" };
      const slug = currentProjectSlug();
      if (slug) headers["X-Checkapp-Project"] = slug;
      return fetch("/utils/tariff", { credentials: "include", cache: "no-store", headers: headers })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (data) normalizeTariffPayload(data);
          window.__checkappTariffReady = true;
        })
        .catch(function () {
          window.__checkappTariffReady = true;
        });
    }

    function paintPlanButtons(root) {
      if (!root) return;
      root.querySelectorAll(".cpm-plan-btn").forEach(function (btn) {
        btn.style.setProperty("width", "100%", "important");
        btn.style.setProperty("display", "block", "important");
        btn.style.setProperty("box-sizing", "border-box", "important");
        btn.style.setProperty("border", "none", "important");
        btn.style.setProperty("border-radius", "10px", "important");
        btn.style.setProperty("padding", "10px 12px", "important");
        btn.style.setProperty("font-size", "14px", "important");
        btn.style.setProperty("font-weight", "600", "important");
        btn.style.setProperty("min-height", "40px", "important");
        btn.style.setProperty("line-height", "1.2", "important");
        btn.style.setProperty("text-align", "center", "important");
        btn.style.setProperty("appearance", "none", "important");
        btn.style.setProperty("-webkit-appearance", "none", "important");
        if (btn.classList.contains("current")) {
          btn.style.setProperty("background", "#2a2a2a", "important");
          btn.style.setProperty("background-color", "#2a2a2a", "important");
          btn.style.setProperty("color", "#cfcfcf", "important");
          btn.style.setProperty("cursor", "default", "important");
        } else if (btn.classList.contains("pick")) {
          btn.style.setProperty("background", "#1a3d2a", "important");
          btn.style.setProperty("background-color", "#1a3d2a", "important");
          btn.style.setProperty("color", "#7dffa3", "important");
          btn.style.setProperty("cursor", "pointer", "important");
        } else if (btn.classList.contains("contact")) {
          btn.style.setProperty("background", "#3a2a1a", "important");
          btn.style.setProperty("background-color", "#3a2a1a", "important");
          btn.style.setProperty("color", "#e8b86d", "important");
          btn.style.setProperty("cursor", "pointer", "important");
        }
      });
    }

    function hideNativePlanModals() {
      document.querySelectorAll(".vfm").forEach(function (vfm) {
        if (vfm.id === "checkapp-plan-modal") return;
        if (vfm.querySelector(".change-plan-modal:not(.checkapp-plan-sheet), .plan-list, .plan.select-button")) {
          vfm.style.setProperty("display", "none", "important");
          vfm.style.setProperty("pointer-events", "none", "important");
        }
      });
    }

    window.__checkappPaintPlanButtons = paintPlanButtons;
    window.__checkappHideNativePlanModals = hideNativePlanModals;

    function findSectionHost() {
      const nativeWrap = document.querySelector(".no-plan-content");
      if (nativeWrap && nativeWrap.offsetHeight > 80) return nativeWrap;
      const tabPanel = document.querySelector(".n-tab-pane--active, [role='tabpanel']:not([hidden])");
      if (tabPanel && tabPanel.offsetHeight > 120) return tabPanel;
      const main = document.querySelector("main");
      if (main) {
        const kids = Array.from(main.children).filter(function (c) {
          return c && c.offsetHeight > 80 && c.tagName !== "NAV";
        });
        if (kids.length >= 2) return kids[kids.length - 1];
        const inner = main.querySelector("[class*='page'], [class*='content'], [class*='body'], .overflow-hidden");
        if (inner && inner.offsetHeight > 120) return inner;
        return main;
      }
      return document.querySelector("#app [class*='layout'] > div:last-child, #app > div > div:last-child");
    }

    function enhanceNativeTierLock() {
      // Full access — strip lock overlays only, keep page content
      document.querySelectorAll(".no-plan-content .root-cont").forEach(function (el) {
        try { el.remove(); } catch (_) {}
      });
      document.querySelectorAll(".no-plan-content").forEach(function (wrap) {
        wrap.style.setProperty("filter", "none", "important");
        wrap.style.setProperty("-webkit-filter", "none", "important");
        wrap.style.setProperty("min-height", "0", "important");
        wrap.classList.remove("no-plan-content");
      });
      patchNativeTierLockText();
    }

    function mainContentRect() {
      const main = document.querySelector("main") || document.querySelector("[class*='layout'] > div:last-child");
      if (!main) return null;
      const r = main.getBoundingClientRect();
      if (r.width < 80 || r.height < 80) return null;
      return r;
    }

    function hasVisibleNativeLock() {
      const el = document.querySelector(".no-plan-content .root-cont");
      if (!el) return false;
      const st = window.getComputedStyle(el);
      return st.display !== "none" && st.visibility !== "hidden" && el.offsetParent !== null;
    }

    function showTierGate(withDemo) {
      let gate = document.getElementById("checkapp-tier-gate");
      if (!gate) {
        gate = document.createElement("div");
        gate.id = "checkapp-tier-gate";
        document.body.appendChild(gate);
      }
      gate.innerHTML = tierLockHtml(withDemo);
      const r = mainContentRect();
      if (r) {
        gate.style.top = Math.max(0, Math.round(r.top)) + "px";
        gate.style.left = Math.max(0, Math.round(r.left)) + "px";
        gate.style.width = Math.round(r.width) + "px";
        gate.style.height = Math.round(r.height) + "px";
        gate.style.right = "auto";
        gate.style.bottom = "auto";
      } else {
        gate.style.top = "0";
        gate.style.left = "0";
        gate.style.right = "0";
        gate.style.bottom = "0";
        gate.style.width = "auto";
        gate.style.height = "auto";
      }
      if (withDemo) {
        const demoBtn = gate.querySelector(".ck-tier-demo-btn");
        if (demoBtn) {
          demoBtn.addEventListener("click", function () {
            window.__checkappAutokickDemo = true;
            gate.remove();
          });
        }
      }
    }

    function removeEl(id) {
      document.querySelectorAll("#" + id).forEach(function (el) { el.remove(); });
    }

    function openBillingPlan() {
      if (typeof window.__checkappOpenPlanModal === "function") window.__checkappOpenPlanModal();
    }

    function isStatsPage() {
      return /\/stats(?:\/|$|\?)/i.test(location.pathname || "") || /\/project-stats/i.test(location.pathname || "");
    }

    function settingsCtx() {
      const path = location.pathname || "";
      const q = location.search || "";
      return path + q;
    }

    function activeSettingsTab() {
      const active = document.querySelector(".n-tabs-tab--active, [role='tab'][aria-selected='true'], [class*='tab'][class*='active']");
      return String((active && active.textContent) || "").trim().toLowerCase();
    }

    function isSettingsApi() {
      const s = settingsCtx();
      const tab = activeSettingsTab();
      return (/\/settings/i.test(s) && (/(?:section=|tab=)api/i.test(s) || /\/settings\/(?:integrations\/)?api/i.test(s)))
        || /\/integrations\/api/i.test(s)
        || tab === "api";
    }

    function isSettingsAutokick() {
      const s = settingsCtx();
      const tab = activeSettingsTab();
      return (/\/settings/i.test(s) && (/(?:section=|tab=)(auto-kick|autokick)/i.test(s) || /\/settings\/auto-kick/i.test(s) || /\/auto-kick/i.test(s)))
        || /\/auto-kick/i.test(s)
        || /авто-кик|auto-kick|autokick/.test(tab);
    }

    function tierLockHtml(withDemo) {
      let html =
        '<div class="ck-tier-lock-box">' +
          '<div class="ck-tier-lock-icon">⚡</div>' +
          '<div class="ck-tier-lock-title">Нет доступа к разделу!</div>' +
          '<div class="ck-tier-lock-sub">Текущий тариф не позволяет использовать этот функционал, перейдите на «plus» чтобы получить доступ.</div>';
      if (withDemo) html += '<button type="button" class="ck-tier-demo-btn">Показать демо</button>';
      return html + "</div>";
    }

    function attachTierLock(host, id, withDemo) {
      host = host || findSectionHost() || document.querySelector("main");
      if (!host || host === document.body) return;
      if (host.offsetHeight < 120) host.style.minHeight = "320px";
      removeEl(id === "checkapp-autokick-lock" ? "checkapp-tier-lock" : "checkapp-autokick-lock");
      let box = document.getElementById(id);
      if (box && box.parentElement !== host) {
        box.remove();
        box = null;
      }
      if (!box) {
        const pos = window.getComputedStyle(host).position;
        if (pos === "static") host.style.position = "relative";
        box = document.createElement("div");
        box.id = id;
        box.innerHTML = tierLockHtml(withDemo);
        host.appendChild(box);
        if (withDemo) {
          const demoBtn = box.querySelector(".ck-tier-demo-btn");
          if (demoBtn) {
            demoBtn.addEventListener("click", function () {
              window.__checkappAutokickDemo = true;
              box.remove();
            });
          }
        }
      }
    }

    function clearAllTierLocks() {
      removeEl("checkapp-tier-lock");
      removeEl("checkapp-autokick-lock");
      removeEl("checkapp-tier-gate");
    }
    window.__checkappClearTierLocks = clearAllTierLocks;

    function enforceStatsLock() {
      // Base/Plus: full access — hide ONLY lock overlays, never remove page content
      clearAllTierLocks();
      document.querySelectorAll(".no-plan-content .root-cont, .ck-tier-lock-box, #checkapp-tier-gate, #checkapp-tier-lock, #checkapp-autokick-lock").forEach(function (el) {
        try { el.style.display = "none"; el.remove(); } catch (_) {}
      });
      document.querySelectorAll(".no-plan-content").forEach(function (wrap) {
        try {
          wrap.classList.remove("no-plan-content");
          wrap.style.filter = "none";
          wrap.style.webkitFilter = "none";
          wrap.style.minHeight = "";
          wrap.style.opacity = "1";
          wrap.style.pointerEvents = "auto";
        } catch (_) {}
      });
    }

    function enforceApiBanner() {
      removeEl("checkapp-api-lock");
    }

    function enforceAutokickLock() {
      enforceStatsLock();
    }

    function cleanupBillingOverlays() {
      if (!document.getElementById("checkapp-plan-modal")) return;
      document.querySelectorAll(".vfm:not(#checkapp-plan-modal)").forEach(function (vfm) {
        if (vfm.querySelector(".change-plan-modal:not(.checkapp-plan-sheet)")) {
          vfm.style.setProperty("display", "none", "important");
        }
      });
    }

    function isBillingView() {
      const path = location.pathname || "";
      const full = path + (location.search || "");
      if (/\/billing|\/payments/i.test(path)) return true;
      if (/\/settings/i.test(path)) return true;
      if (/(?:section=|tab=)(?:billing|payments|tariff)/i.test(full)) return true;
      const bodyTxt = String((document.body && document.body.innerText) || "");
      return /Текущий тариф|Current plan|Биллинг|Billing/i.test(bodyTxt);
    }

    function patchBillingUi() {
      if (!isBillingView()) return;
      const t = loadProjectTariffFromCache() || window.__checkappTariff;
      if (!t || t.is_paid) return;
      let trial = Number(t.trial_ends_at || t.trial_ends || t.active_until || 0);
      if (!t.is_trial && !(trial > Date.now())) return;
      if (!trial || trial <= Date.now()) return;
      const dateStr = new Date(trial).toLocaleString("ru-RU", {
        day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit"
      }).replace(/\.$/, "");
      // Remove duplicate top trial chip — SPA already shows the main trial block.
      const chip = document.getElementById("checkapp-trial-chip");
      if (chip) chip.remove();
      document.querySelectorAll("main p, main span, main div, main h3, main h4, main small, [class*='subtitle']").forEach(function (el) {
        if (el.closest && el.closest("#checkapp-plan-modal, #checkapp-tier-gate, #checkapp-tier-lock, #checkapp-trial-chip")) return;
        const txt = String(el.textContent || "").trim();
        if (!txt || (el.children && el.children.length > 2)) return;
        if (/Оплачен до/i.test(txt)) {
          el.textContent = txt.replace(/Оплачен до[\s\S]*$/i, "пробный доступ до " + dateStr);
        } else if (/^до \d/i.test(txt) && /Текущий тариф|Current plan/i.test(String(el.parentElement && el.parentElement.textContent || ""))) {
          el.textContent = "пробный доступ до " + dateStr;
        }
      });
    }

    function patchNativeTierLockText() {
      // Only strip lock overlays — do NOT delete page wrappers
      document.querySelectorAll(".no-plan-content .root-cont").forEach(function (el) {
        try { el.remove(); } catch (_) {}
      });
      document.querySelectorAll("p.title, .title, h3, h4, div").forEach(function (el) {
        if (el.children && el.children.length) return;
        const txt = String(el.textContent || "").trim();
        if (/^Нет доступа к разделу!?$/i.test(txt)) {
          try {
            const box = el.closest(".root-cont, .ck-tier-lock-box");
            if (box) box.remove();
            else el.style.display = "none";
          } catch (_) {}
        }
      });
    }

    function markSection() {
      try {
        const sec = (location.search.match(/[?&]section=([^&]+)/i) || [])[1] || "";
        document.body.setAttribute("data-checkapp-section", sec.toLowerCase());
      } catch (_) {}
    }

    function runGates() {
      markSection();
      enforceApiBanner();
      enforceStatsLock();
      patchNativeTierLockText();
      patchBillingUi();
      cleanupBillingOverlays();
    }

    loadTariff();
    refreshTierFromServer();
    setInterval(function () {
      if (/\/settings\/billing/i.test(location.pathname || "")) {
        runGates();
      }
    }, 2000);
    // Tier gates handled by checkapp-gates.js (loaded after SPA)
    window.addEventListener("popstate", function () {
      window.__checkappAutokickDemo = false;
      loadTariff();
    });
  })();

  // SPA requires wallet.balance before discardTrial — bypass and freeze on click.
  (function wireDiscardTrialButton() {
    function authHeaders() {
      const headers = { Accept: "application/json", "Content-Type": "application/json" };
      try {
        const token = cleanToken(localStorage.getItem("token") || localStorage.getItem("access_token") || "");
        if (token) headers.Authorization = "Bearer " + token;
      } catch (_) {}
      try {
        const slug = (location.pathname || "").split("/").filter(Boolean)[0] || "";
        if (slug && !/^(client|settings|pricing|auth)$/i.test(slug)) {
          headers["X-Checkapp-Project"] = slug;
        }
      } catch (_) {}
      return headers;
    }

    function isDiscardTrialControl(el) {
      if (!el || el.nodeType !== 1) return false;
      const txt = String(el.textContent || "").replace(/\s+/g, " ").trim();
      if (!txt) return false;
      return /Завершить пробн|End trial|Finish trial|Завершити пробн|Discard trial/i.test(txt);
    }

    async function discardAndFreeze() {
      try {
        const res = await fetch("/tariff/discard-trial", {
          method: "POST",
          credentials: "include",
          cache: "no-store",
          headers: authHeaders(),
          body: "{}"
        });
        let data = null;
        try { data = await res.json(); } catch (_) { data = null; }
        if (data && typeof data === "object") {
          data.is_trial = false;
          data.is_paid = false;
          data.frozen = true;
          data.is_frozen = true;
          data.renew_failed = true;
          data.trial_ends_at = 0;
          data.active_until = 0;
          data.paid_until = 0;
          window.__checkappTariff = normalizeTariffPayload(data);
          window.__checkappTariffReady = true;
        }
        try {
          const chip = document.getElementById("checkapp-trial-chip");
          if (chip) chip.remove();
        } catch (_) {}
        try {
          if (window.__checkappToast) window.__checkappToast("warn", "Пробный период завершён — проект заморожен до оплаты Plus");
        } catch (_) {}
        setTimeout(function () { location.reload(); }, 350);
      } catch (err) {
        try {
          alert("Не удалось завершить пробный период");
        } catch (_) {}
      }
    }

    document.addEventListener("click", function (ev) {
      const t = ev.target;
      if (!t) return;
      const btn = (t.closest && (t.closest("button") || t.closest("a") || t.closest("[role='button']"))) || t;
      if (!isDiscardTrialControl(btn)) return;
      ev.preventDefault();
      ev.stopPropagation();
      if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();
      discardAndFreeze();
    }, true);
  })();

  (function customPlanAndPluginModals() {
    function closeModal(id) {
      const el = document.getElementById(id);
      if (!el) {
        if (id === "checkapp-plan-modal") document.body.classList.remove("checkapp-plan-open");
        return;
      }
      el.remove();
      if (id === "checkapp-plan-modal") {
        document.body.classList.remove("checkapp-plan-open");
      }
    }

    function authHeaders() {
      const headers = { Accept: "application/json", "Content-Type": "application/json" };
      try {
        const token = localStorage.getItem("token") || localStorage.getItem("access_token") || "";
        if (token) headers.Authorization = token.indexOf("Bearer") === 0 ? token : ("Bearer " + token);
      } catch (_) {}
      try {
        const slug = (location.pathname || "").split("/").filter(Boolean)[0] || "";
        if (slug && slug !== "client" && slug !== "settings") headers["X-Checkapp-Project"] = slug;
      } catch (_) {}
      return headers;
    }

    function defaultPlanList() {
      const cur = window.__checkappTariff && window.__checkappTariff.tariff;
      const curTier = String((cur && (cur.tier || cur.slug)) || "base").toLowerCase();
      return [
        { id: 1, tier: "base", name: "Base", month_price: 0, is_current: curTier === "base" },
        { id: 2, tier: "plus", name: "Plus", month_price: 30000, is_current: curTier === "plus" },
        { id: 3, tier: "enterprise", name: "Enterprise", month_price: 1000000, is_current: curTier === "enterprise", contact: true }
      ];
    }

    async function fetchTariffs() {
      try {
        const res = await fetch("/utils/tariff", { headers: authHeaders() });
        const data = await res.json();
        if (data) window.__checkappTariff = normalizeTariffPayload(data);
        const list = (data && (data.tariffs || data.plans || data.data)) || [];
        return Array.isArray(list) && list.length ? list : defaultPlanList();
      } catch (_) {
        return defaultPlanList();
      }
    }

    function rub(price) {
      const n = Number(price || 0);
      if (n >= 1000000) return "Custom";
      return "₽" + Math.round(n / 100).toLocaleString("ru-RU");
    }

    function planIconUsers() {
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>';
    }
    function planIconServer() {
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><path d="M6 6h.01M6 18h.01"/></svg>';
    }
    function planIconSpark() {
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l2 7h7l-5.5 4 2 7-5.5-4-5.5 4 2-7L3 9h7z"/></svg>';
    }
    function planIconHeadset() {
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 11v3a4 4 0 0 0 4 4h1"/><path d="M21 11v3a4 4 0 0 1-4 4h-1"/><path d="M7 15a4 4 0 0 0 8 0v-4a4 4 0 0 0-8 0z"/></svg>';
    }
    function planBoltClass(tier) {
      if (tier === "plus") return "plus";
      if (tier === "enterprise") return "enterprise";
      return "base";
    }
    function planFeatures(tier) {
      if (tier === "base") {
        return [
          { icon: planIconUsers(), text: "Все функции" },
          { icon: planIconServer(), text: "Тест 7 дней при создании проекта" },
          { icon: planIconSpark(), text: "Без оплаты — только пробный доступ" }
        ];
      }
      if (tier === "plus") {
        return [
          { icon: planIconUsers(), text: "Все функции" },
          { icon: planIconServer(), text: "5 серверов" },
          { icon: planIconSpark(), text: "Подписка на 30 дней" }
        ];
      }
      if (tier === "enterprise") {
        return [
          { icon: planIconUsers(), text: "Все функции" },
          { icon: planIconServer(), text: "От 5 серверов" },
          { icon: planIconHeadset(), text: "Приоритетная поддержка" }
        ];
      }
      return [
        { icon: planIconUsers(), text: "Все функции" },
        { icon: planIconServer(), text: "Тест 7 дней" },
        { icon: planIconSpark(), text: "Пробный доступ" }
      ];
    }

    function renderPlanGrid(grid, tariffs) {
      if (!grid) return;
      grid.innerHTML = "";
      tariffs.forEach(function (plan) {
        const tier = String(plan.tier || plan.slug || plan.name || "base").toLowerCase();
        const current = !!(plan.is_current || plan.current);
        const isEnterprise = tier === "enterprise" || Number(plan.month_price) >= 1000000 || plan.contact;
        const isBase = (tier === "base") || (Number(plan.month_price || 0) <= 0 && !isEnterprise);
        const cur = window.__checkappTariff && window.__checkappTariff.tariff;
        const curTier = String((cur && (cur.tier || cur.slug)) || "").toLowerCase();
        const lockedDowngrade = (curTier === "enterprise" || curTier === "custom" || curTier === "pro" || curTier === "premium")
          && (isBase || tier === "plus");
        let priceTxt;
        let suffix;
        if (isEnterprise) {
          priceTxt = "Custom";
          suffix = "";
        } else if (isBase) {
          priceTxt = "Free";
          suffix = "";
        } else {
          priceTxt = rub(plan.month_price);
          suffix = '<span>/месяц</span>';
        }
        let btnClass = current ? "current" : (isEnterprise ? "contact" : "pick");
        let btnLabel = current ? "Текущий тариф" : (isEnterprise ? "Связаться" : "Выбрать");
        if (isBase && !current) {
          btnClass = "pick base-blocked";
          btnLabel = "Выбрать";
        }
        if (lockedDowngrade && !current) {
          btnClass = "pick plan-locked";
          btnLabel = "Недоступно";
        }
        const col = document.createElement("div");
        col.className = "cpm-rustapp-plan plan " + tier;
        let featHtml = "";
        planFeatures(tier).forEach(function (f) {
          featHtml += '<li>' + f.icon + "<span>" + f.text + "</span></li>";
        });
        col.innerHTML =
          '<div class="cpm-plan-top"><span class="cpm-plan-name">' + tier.charAt(0).toUpperCase() + tier.slice(1) + '</span>' +
            '<span class="cpm-plan-bolt ' + planBoltClass(tier) + '"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M13 2L3 14h8l-1 8 10-12h-8l1-8z"/></svg></span></div>' +
          '<div class="cpm-plan-price">' + priceTxt + suffix + "</div>" +
          '<button type="button" class="cpm-plan-btn select-button ' + btnClass + '" data-tier="' + tier + '" data-id="' + (plan.id || tier) + '"' + (current ? " disabled" : "") + ">" + btnLabel + "</button>" +
          '<hr class="cpm-plan-divider" />' +
          '<ul class="cpm-plan-features">' + featHtml + "</ul>";
        grid.appendChild(col);
        if (window.__checkappPaintPlanButtons) window.__checkappPaintPlanButtons(col);
      });
    }

    window.__checkappOpenPlanModal = function openPlanModal() {
      if (document.getElementById("checkapp-plan-modal")) return;
      if (typeof window.__checkappClearTierLocks === "function") window.__checkappClearTierLocks();
      if (window.__checkappHideNativePlanModals) window.__checkappHideNativePlanModals();
      document.querySelectorAll(".vfm").forEach(function (n) {
        if (n.id === "checkapp-plan-modal") return;
        if (n.querySelector(".change-plan-modal:not(.checkapp-plan-sheet)")) {
          n.style.setProperty("display", "none", "important");
        }
      });
      const tariffs = defaultPlanList();
      const root = document.createElement("div");
      root.id = "checkapp-plan-modal";
      root.className = "checkapp-plan-root";
      root.innerHTML =
        '<div class="checkapp-plan-overlay"></div>' +
        '<div class="cpm-rustapp checkapp-plan-sheet" role="dialog" aria-modal="true">' +
          '<div class="cpm-rustapp-head"><h2>Выберите тариф</h2><button type="button" class="cpm-rustapp-close" data-close="1" aria-label="Закрыть">×</button></div>' +
          '<div class="cpm-rustapp-grid"></div>' +
          '<div class="cpm-rustapp-foot">' +
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>' +
            '<span>Тарифы могут отличаться возможностями, смотрите <a href="/pricing">сравнение тарифов</a>.</span>' +
          "</div>" +
        "</div>";
      const grid = root.querySelector(".cpm-rustapp-grid");
      renderPlanGrid(grid, tariffs);
      if (window.__checkappPaintPlanButtons) window.__checkappPaintPlanButtons(root);
      root.addEventListener("click", async function (ev) {
        const t = ev.target;
        if (!t) return;
        if (t === root.querySelector(".checkapp-plan-overlay") || t.getAttribute("data-close") || (t.closest && t.closest("[data-close]"))) {
          closeModal("checkapp-plan-modal");
          return;
        }
        const btn = t.closest ? t.closest(".cpm-plan-btn.pick, .cpm-plan-btn.contact, button.pick, button.contact") : null;
        if (!btn || btn.disabled) return;
        const id = btn.getAttribute("data-id") || btn.getAttribute("data-tier");
        const tier = String(btn.getAttribute("data-tier") || id || "").toLowerCase();
        if (btn.classList.contains("contact")) {
          window.open("https://t.me/RustCheckcc", "_blank");
          return;
        }
        if (tier === "base" || id === "1" || id === "base") {
          showBaseTariffToast();
          return;
        }
        const cur = window.__checkappTariff && window.__checkappTariff.tariff;
        const curTier = String((cur && (cur.tier || cur.slug)) || "").toLowerCase();
        if ((curTier === "enterprise" || curTier === "custom" || curTier === "pro" || curTier === "premium")
            && (tier === "plus" || tier === "base")) {
          showPlanLockedToast();
          return;
        }
        if (btn.classList.contains("plan-locked")) {
          showPlanLockedToast();
          return;
        }
        btn.disabled = true;
        btn.textContent = "...";
        try {
          await fetch("/tariff/" + encodeURIComponent(tier || "plus") + "/select", {
            method: "POST",
            headers: Object.assign({}, authHeaders(), { "X-Checkapp-Plan-Select": "1" }),
            body: "{}"
          })
            .then(async function (res) {
              const data = await res.json().catch(function () { return {}; });
              if (data.error === "base_not_purchasable") {
                showBaseTariffToast(data.message);
                btn.disabled = false;
                btn.textContent = "Выбрать";
                return;
              }
              if (data.error === "plan_locked" || data.error === "cannot_change_plan") {
                showPlanLockedToast(data.message);
                btn.disabled = false;
                btn.textContent = "Выбрать";
                return;
              }
              if (data.error === "insufficient_balance" || res.status === 402) {
                if (window.__checkappOpenInsufficientFunds) {
                  window.__checkappOpenInsufficientFunds(Number(data.needed_rub || Math.ceil(Number(data.needed || 0) / 100)));
                }
                btn.disabled = false;
                btn.textContent = "Выбрать";
                return;
              }
              if (data.error === "project_blocked" || res.status === 403) {
                if (window.__checkappShowProjectBlocked) window.__checkappShowProjectBlocked();
                btn.disabled = false;
                btn.textContent = "Выбрать";
                return;
              }
              if (!res.ok || data.ok === false) {
                if (window.__checkappShowHumanError) window.__checkappShowHumanError(data, res.status);
                btn.disabled = false;
                btn.textContent = "Выбрать";
                return;
              }
              closeModal("checkapp-plan-modal");
              location.reload();
            });
        } catch (_) {
          btn.disabled = false;
          btn.textContent = "Выбрать";
          showTariffSelectUi("funds", { needed_rub: 300 });
        }
      });
      document.body.appendChild(root);
      document.body.classList.add("checkapp-plan-open");
      fetchTariffs().then(function (fresh) {
        const modal = document.getElementById("checkapp-plan-modal");
        if (!modal || !Array.isArray(fresh) || !fresh.length) return;
        renderPlanGrid(modal.querySelector(".cpm-rustapp-grid"), fresh);
        if (window.__checkappPaintPlanButtons) window.__checkappPaintPlanButtons(modal);
      }).catch(function () {});
    };

    const pluginCfg = {
      download_url: "",
      filename: "RustApp.cs",
      local_url: "/plugin/download"
    };

    fetch("/plugin/config", { credentials: "same-origin", cache: "no-store" })
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (data) {
        if (data && typeof data === "object") Object.assign(pluginCfg, data);
      })
      .catch(function () {});

    function pluginDownloadHref() {
      const ext = String(pluginCfg.download_url || "").trim();
      const isLocalHost = /^(localhost|127\.0\.0\.1)$/i.test(location.hostname);
      if (ext && !(isLocalHost && /rustcheck\.cc/i.test(ext))) {
        // Trust only an external mirror on a different host. If the absolute
        // URL points at this very host but with another scheme/port (e.g.
        // https:// vs the plain-http origin we are on), fall back to the
        // same-origin path — otherwise the download opens a dead connection.
        let sameHost = false;
        try {
          sameHost = new URL(ext, location.origin).host === location.host;
        } catch (_) {}
        if (!sameHost) return ext;
      }
      const local = String(pluginCfg.local_url || "/plugin/download");
      const base = local.startsWith("http") ? local : (location.origin + local);
      return base + (base.indexOf("?") >= 0 ? "&" : "?") + "t=" + Date.now();
    }

    function triggerFileDownload() {
      const url = pluginDownloadHref();
      const filename = String(pluginCfg.filename || "RustApp.cs");
      const sameOrigin = url.indexOf(location.origin) === 0 || url.charAt(0) === "/";
      if (sameOrigin) {
        const iframe = document.createElement("iframe");
        iframe.style.display = "none";
        iframe.setAttribute("aria-hidden", "true");
        iframe.src = url.charAt(0) === "/" ? (location.origin + url) : url;
        document.body.appendChild(iframe);
        setTimeout(function () {
          if (iframe.parentNode) iframe.parentNode.removeChild(iframe);
        }, 15000);
        const a = document.createElement("a");
        a.href = url.charAt(0) === "/" ? (location.origin + url) : url;
        a.download = filename;
        a.style.display = "none";
        document.body.appendChild(a);
        a.click();
        setTimeout(function () {
          if (a.parentNode) a.parentNode.removeChild(a);
        }, 2000);
        return Promise.resolve(true);
      }
      window.open(url, "_blank", "noopener");
      return Promise.resolve(true);
    }

    async function downloadRustcheck() {
      try {
        return triggerFileDownload();
      } catch (_) {
        try {
          window.location.assign(pluginDownloadHref());
        } catch (e2) {
          window.open(pluginDownloadHref(), "_blank");
        }
        return false;
      }
    }

    window.__checkappDownloadPlugin = downloadRustcheck;

    window.__checkappOpenPluginModal = function openPluginModal() {
      closeModal("checkapp-plugin-modal");
      const root = document.createElement("div");
      root.id = "checkapp-plugin-modal";
      root.className = "ck-pl-overlay";
      root.innerHTML =
        '<div class="vfm__content ck-pl-dialog ck-pl-clean" role="dialog" aria-modal="true">' +
          '<button type="button" class="ck-pl-x" data-close aria-label="Закрыть">×</button>' +
          '<div class="ck-pl-clean-title">Какую версию скачать?</div>' +
          '<div class="ck-pl-versions" role="radiogroup" aria-label="Версия плагина">' +
            '<button type="button" class="ck-pl-ver is-selected" data-ver="266" role="radio" aria-checked="true">' +
              '<span class="ck-pl-radio"></span>' +
              '<span class="ck-pl-ver-text"><strong>RustApp Plugin</strong><em>версия 266 · Oxide/uMod</em></span>' +
            "</button>" +
            '<button type="button" class="ck-pl-ver" data-ver="official" role="radio" aria-checked="false">' +
              '<span class="ck-pl-radio"></span>' +
              '<span class="ck-pl-ver-text"><strong>RustApp Plugin</strong><em>official — в разработке</em></span>' +
            "</button>" +
          "</div>" +
          '<button type="button" class="ck-pl-download" data-dl>Скачать</button>' +
        "</div>";
      let selected = "266";
      const dlBtn = root.querySelector("[data-dl]");
      function syncSelection() {
        root.querySelectorAll(".ck-pl-ver").forEach(function (btn) {
          const on = btn.getAttribute("data-ver") === selected;
          btn.classList.toggle("is-selected", on);
          btn.setAttribute("aria-checked", on ? "true" : "false");
        });
        if (dlBtn) {
          dlBtn.disabled = selected === "official";
          dlBtn.textContent = selected === "official" ? "Скоро" : "Скачать";
        }
      }
      root.addEventListener("click", function (ev) {
        const t = ev.target;
        if (!t) return;
        if (t === root || t.getAttribute("data-close") || (t.closest && t.closest("[data-close]"))) {
          closeModal("checkapp-plugin-modal");
          return;
        }
        const verBtn = t.closest ? t.closest(".ck-pl-ver") : null;
        if (verBtn) {
          selected = verBtn.getAttribute("data-ver") || "266";
          syncSelection();
          return;
        }
        if (t.getAttribute("data-dl") || (t.closest && t.closest("[data-dl]"))) {
          if (selected === "official") return;
          ev.preventDefault();
          const btn = t.closest ? t.closest("[data-dl]") : t;
          if (btn) { btn.disabled = true; btn.textContent = "Загрузка..."; }
          downloadRustcheck().finally(function () {
            if (btn) { btn.disabled = false; btn.textContent = "Скачать"; }
            setTimeout(function () { closeModal("checkapp-plugin-modal"); }, 350);
          });
        }
      });
      syncSelection();
      document.body.appendChild(root);
      requestAnimationFrame(function () {
        root.classList.add("is-open");
      });
    };

    function isBillingChangeBtn(el) {
      if (!el || el.closest && el.closest("#checkapp-plan-modal")) return false;
      const txt = String(el.textContent || "").trim();
      const isChange = /^сменить/i.test(txt) || /^change/i.test(txt) || /^upgrade/i.test(txt)
        || /сменить тариф|change plan|улучшить тариф|upgrade plan|выбрать тариф/i.test(txt);
      if (!isChange) return false;
      const path = location.pathname || "";
      const full = path + (location.search || "");
      if (/\/billing|\/payments|\/settings/i.test(path)) return true;
      if (/(?:section=|tab=)(?:billing|payments|tariff)/i.test(full)) return true;
      const card = el.closest("section, article, [class*='card'], [class*='plan'], [class*='billing'], div");
      if (card && /текущий тариф|current plan|биллинг|billing|тариф/i.test(String(card.textContent || ""))) return true;
      return false;
    }

    function isPluginDownloadTarget(el) {
      if (!el) return false;
      if (el.closest && el.closest("#checkapp-plugin-modal, #checkapp-plugin-connect-field")) return false;
      const txt = String(el.textContent || "");
      if (/Checkapp\.cs|RustApp\.cs|Rustcheck\.cs|RustCheck\.cs/i.test(txt)) return true;
      if (/скачать плагин|download plugin|server-context-download|загрузить плагин|скачать rustcheck/i.test(txt)) return true;
      if (/подключить сервер|connect server|добавить сервер|add server|pair server|привязать сервер|подключение сервера/i.test(txt)) return true;
      if (/скачать|download/i.test(txt) && /плагин|plugin|\.cs/i.test(txt)) return true;
      if (el.classList && el.classList.contains("command") && /Checkapp|RustApp|Rustcheck/i.test(txt)) return true;
      if (el.getAttribute && /checkapp\.cs|rustapp\.cs|rustcheck\.cs/i.test(String(el.getAttribute("download") || ""))) return true;
      return false;
    }

    function isPlanButton(el) {
      if (!el || el.closest && el.closest("#checkapp-plan-modal")) return false;
      const txt = String(el.textContent || "").trim();
      return /^сменить/i.test(txt) || /^change/i.test(txt) || /^upgrade/i.test(txt)
        || /улучшить тариф|сменить тариф|change plan|upgrade plan/i.test(txt);
    }

    document.addEventListener("click", function (ev) {
      const t = ev.target;
      if (!t || !t.closest) return;
      const btn = t.closest("button, a, [role='button'], .command, [data-dl-plugin]");
      if (!btn) return;
      if (btn.getAttribute && btn.getAttribute("data-dl-plugin") === "1") {
        ev.preventDefault();
        ev.stopPropagation();
        if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();
        window.__checkappOpenPluginModal();
        return;
      }
      if (isBillingChangeBtn(btn) || isPlanButton(btn)) {
        ev.preventDefault();
        ev.stopPropagation();
        if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();
        window.__checkappOpenPlanModal();
        return;
      }
      if (isPluginDownloadTarget(btn)) {
        ev.preventDefault();
        ev.stopPropagation();
        if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();
        window.__checkappOpenPluginModal();
      }
    }, true);

    // Replace native Checkapp.cs row in connect modal with download field (name asked AFTER pair)
    function patchConnectPluginField() {
      patchPanelBrand();
      patchI18nBrand();
      const modal = document.querySelector(".vfm__content, .vfm-content");
      if (!modal) return;
      const modalTxt = String(modal.textContent || "");
      if (!/подключ|connect|pair|плагин|plugin|Checkapp\.cs|RustApp\.cs|Rustcheck\.cs|RustCheck\.cs/i.test(modalTxt)) return;
      if (modal.querySelector("#checkapp-plugin-connect-field")) return;
      let anchor = null;
      modal.querySelectorAll(".command, div, button, a").forEach(function (el) {
        if (anchor) return;
        if (/Checkapp\.cs|RustApp\.cs|Rustcheck\.cs|RustCheck\.cs/i.test(el.textContent || "")) {
          anchor = el.closest(".command") || el;
        }
      });
      const block = document.createElement("div");
      block.id = "checkapp-plugin-connect-field";
      block.className = "ck-pl-field";
      block.style.cssText = "margin:8px 0 12px;width:100%;";
      block.innerHTML =
        '<label style="display:block;font-size:13px;color:#9a9a9a;margin-bottom:6px;">Плагин для сервера</label>' +
        '<button type="button" class="ck-pl-open" data-dl-plugin="1">' +
          '<span>RustApp · RustApp.cs</span>' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12"/><path d="M8 11l4 4 4-4"/><path d="M4 21h16"/></svg>' +
        "</button>" +
        '<div style="font-size:12px;color:#888;margin-top:6px;">После ra.pair на сайте появится окно с названием сервера</div>';
      if (anchor && anchor.parentNode) {
        const step = anchor.closest("div") || anchor.parentNode;
        anchor.style.display = "none";
        if (step && step.parentNode) step.parentNode.insertBefore(block, step);
        else anchor.parentNode.insertBefore(block, anchor);
      } else {
        const body = modal.querySelector("[class*='body'], [class*='content'], [class*='step']") || modal;
        body.insertBefore(block, body.firstChild);
      }
    }
    setInterval(patchConnectPluginField, 500);

    setInterval(function () {
      const hint = document.getElementById("checkapp-discord-redirect-hint");
      if (hint) hint.remove();
    }, 400);

    // Remove leftover bad injected sidebar button if any
    setInterval(function () {
      const bad = document.getElementById("checkapp-change-tariff-btn");
      if (bad) bad.remove();
    }, 500);

    if (/court-plan|change-plan|plan=1/i.test(location.search || "")) {
      setTimeout(function () {
        if (typeof window.__checkappOpenPlanModal === "function") window.__checkappOpenPlanModal();
      }, 400);
    }

    function showLimitToast(message) {
      showCheckappToast("warn", message, { title: "Ограничение тарифа", force: true });
    }

    window.__checkappShowServerLimitToast = function () {
      showLimitToast("На тарифе Base можно подключить не больше 2 серверов. Перейдите на Plus для большего лимита.");
    };

    function guardServerConnectButtons() {
      if (!/\/servers(?:\/|$|\?)/i.test(location.pathname || "")) return;
      const t = loadProjectTariffFromCache() || window.__checkappTariff;
      const tier = currentProjectTierSlug();
      const limit = tierServerLimit(tier);
      const count = typeof window.__checkappServersCount === "number" ? window.__checkappServersCount : null;
      if (count == null || count < limit) return;
      document.querySelectorAll("button,a,[role='button']").forEach(function (el) {
        const txt = String(el.textContent || "").trim();
        if (!/(подключить сервер|connect server|подключить|connect)/i.test(txt)) return;
        if (el.dataset.checkappServerBlocked === "1") return;
        el.dataset.checkappServerBlocked = "1";
        el.style.opacity = "0.45";
        el.style.pointerEvents = "auto";
        el.addEventListener("click", function (ev) {
          ev.preventDefault();
          ev.stopImmediatePropagation();
          if (window.__checkappShowServerLimitToast) window.__checkappShowServerLimitToast();
        }, true);
      });
    }

    setInterval(guardServerConnectButtons, 700);
    fetch("/project", { credentials: "include", cache: "no-store", headers: (function () {
      const h = { Accept: "application/json" };
      try {
        const t = localStorage.getItem("token") || localStorage.getItem("access_token") || "";
        if (t) h.Authorization = t.indexOf("Bearer") === 0 ? t : ("Bearer " + t);
      } catch (_) {}
      return h;
    })() })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (data) {
        const list = Array.isArray(data) ? data : (data && (data.results || data.data || data.items)) || [];
        window.__checkappProjectCount = list.length;
      })
      .catch(function () {});
    fetch("/server", { credentials: "include", cache: "no-store", headers: (function () {
      const h = { Accept: "application/json", "X-Checkapp-Project": currentProjectSlug() || "" };
      try {
        const t = localStorage.getItem("token") || localStorage.getItem("access_token") || "";
        if (t) h.Authorization = t.indexOf("Bearer") === 0 ? t : ("Bearer " + t);
      } catch (_) {}
      return h;
    })() })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (data) {
        const list = Array.isArray(data) ? data : (data && data.servers) || [];
        window.__checkappServersCount = countPairedServers(list);
        guardServerConnectButtons();
      })
      .catch(function () {});
  })();

  // Legal documents are available from the personal profile sidebar.
  (function legalDocumentsInTopup() {
    const documents = {
      privacy: {
        title: "Политика конфиденциальности",
        text: `03.09.2026

1. Общие положения
1.1. Настоящая Политика конфиденциальности (далее — «Политика») регулирует порядок обработки и защиты информации, которую Пользователь передаёт при использовании сервиса rustcheck.cc (далее — «Сервис»).
1.2. Используя Сервис, Пользователь подтверждает своё согласие с условиями Политики. Если Пользователь не согласен с условиями — он обязан прекратить использование Сервиса.

2. Сбор информации
2.1. Сервис может собирать идентификаторы аккаунта (логин, ID, никнейм), техническую информацию (IP-адрес, данные о браузере, устройстве и операционной системе), а также историю взаимодействий с Сервисом.
2.2. Сервис не требует паспортных данных, документов, фотографий или другой личной информации, кроме минимально необходимой для работы.

3. Использование информации
Полученная информация используется для обеспечения работы функционала, связи с Пользователем (включая уведомления и поддержку), анализа и улучшения работы Сервиса.

4. Передача информации третьим лицам
Администрация не передаёт данные третьим лицам, кроме случаев, когда это требуется законом, необходимо для исполнения обязательств перед Пользователем (например, для работы платёжных систем), либо когда Пользователь дал согласие.

5. Хранение и защита данных
Данные хранятся в течение срока, необходимого для достижения целей обработки. Администрация принимает разумные меры защиты, но не гарантирует абсолютную безопасность информации при передаче через интернет.

6. Отказ от ответственности
Пользователь понимает риски передачи информации через интернет. Администрация не несёт ответственности за утрату, кражу или раскрытие данных по вине третьих лиц или самого Пользователя.

7. Изменения в Политике
Администрация вправе изменять Политику без предварительного уведомления. Продолжение использования Сервиса после изменений означает согласие с новой редакцией.`
      },
      terms: {
        title: "Пользовательское соглашение",
        text: `03.09.2026

1. Общие положения
Настоящее Пользовательское соглашение регулирует порядок использования онлайн-сервиса rustcheck.cc. Используя Сервис, включая регистрацию, оплату услуг или получение доступа к материалам, Пользователь подтверждает, что ознакомился с условиями и принимает их в полном объёме. При несогласии с условиями Пользователь обязан прекратить использование Сервиса.

2. Характер услуг и цифровых товаров
Сервис предоставляет цифровые товары и услуги нематериального характера: информационные материалы, обучающие программы, консультации, цифровые продукты и сервисные услуги. Материалы могут включать информацию из открытых источников, авторские материалы, аналитические обзоры, подборки, рекомендации и структурированные данные. Их ценность заключается в систематизации, анализе, форме подачи, сопровождении и обновлениях; уникальность отдельных фрагментов не гарантируется.

3. Отказ от гарантий и ответственности
Сервис предоставляется на условиях «как есть». Администрация не гарантирует соответствие ожиданиям Пользователя, достижение финансовых или иных результатов, а также бесперебойную и безошибочную работу. Пользователь принимает решения о применении материалов самостоятельно и на свой риск.

4. Законность использования
Сервис не предназначен для поощрения, организации или содействия противоправной деятельности. Пользователь обязуется использовать Сервис в рамках применимого законодательства и правил третьих сторон.

5. Интеллектуальная собственность
Материалы Сервиса охраняются законодательством об интеллектуальной собственности. Их нельзя копировать, распространять, перепродавать или передавать третьим лицам без разрешения правообладателя.

6. Ограничение доступа
Администрация вправе ограничить доступ при нарушении условий, выявлении злоупотреблений или требованиях законодательства и платёжных провайдеров.

7. Платежи и возвраты
Оплата цифровых товаров и услуг производится на условиях, указанных в Сервисе до оплаты. После предоставления доступа возврат средств не производится, кроме случаев, когда услуга не оказана по технической вине Сервиса или доступ фактически не предоставлен. По вопросу возврата необходимо обратиться в поддержку в течение 24 часов с момента оплаты. Запрещено инициировать chargeback без предварительного обращения в поддержку.

8. Конфиденциальность
Администрация может собирать минимально необходимые технические данные для работы Сервиса и принимает разумные меры их защиты.

9. Изменение условий
Администрация вправе вносить изменения в Соглашение. Продолжение использования Сервиса означает согласие с обновлённой редакцией.

10. Контактная информация
По всем вопросам Пользователь может обратиться в службу поддержки через форму в боте.`
      }
    };

    function addStyle() {
      if (document.getElementById("checkapp-legal-style")) return;
      const style = document.createElement("style");
      style.id = "checkapp-legal-style";
      style.textContent = "#checkapp-legal-modal{position:fixed;inset:0;z-index:1000020;display:flex;align-items:center;justify-content:center;padding:16px;background:rgba(0,0,0,.6);backdrop-filter:blur(3px)}#checkapp-legal-modal .ck-legal-box{width:min(92vw,620px);max-height:min(82vh,720px);display:flex;flex-direction:column;background:#1a1a1a;color:#f4f4f4;border:1px solid #303030;border-radius:12px;box-shadow:0 24px 80px rgba(0,0,0,.8);overflow:hidden}#checkapp-legal-modal .ck-legal-head{display:flex;align-items:center;justify-content:space-between;padding:17px 20px;border-bottom:1px solid #2c2c2c;font-size:17px;font-weight:700}#checkapp-legal-modal .ck-legal-close{border:0;background:#292929;color:#bbb;border-radius:7px;width:30px;height:30px;font-size:20px;cursor:pointer}#checkapp-legal-modal .ck-legal-text{white-space:pre-line;overflow:auto;padding:18px 20px 24px;color:#c7c7c7;font-size:14px;line-height:1.55}#checkapp-legal-modal .ck-legal-foot{padding:12px 20px;border-top:1px solid #2c2c2c;text-align:right}#checkapp-legal-modal .ck-legal-ok,.ck-legal-link{border:0;border-radius:8px;padding:9px 12px;background:#2d2d2d;color:#ddd;font-size:13px;cursor:pointer}.client-edit-modal{position:relative}#checkapp-profile-legal-links{position:absolute!important;left:16px!important;bottom:16px!important;display:flex!important;gap:8px!important;align-items:center!important;z-index:80!important;margin:0!important;padding:0!important;pointer-events:auto!important;visibility:visible!important;opacity:1!important}#checkapp-profile-legal-links button{margin:0;background:#242424;color:#d7d7d7;border:0;border-radius:8px;padding:8px 10px;font-size:13px;cursor:pointer}.client-edit-modal .integrations>.integration,.client-edit-modal .integrations>.flex{display:flex!important;justify-content:space-between!important;align-items:center!important;width:100%}.client-edit-modal .ca-int-ava-host{border-radius:50%!important;overflow:hidden!important;display:flex!important;align-items:center!important;justify-content:center!important;flex-shrink:0!important}.client-edit-modal img.ca-int-ava{border-radius:50%!important;object-fit:cover!important;display:block!important}";
      document.head.appendChild(style);
    }

    function openDocument(kind) {
      const doc = documents[kind];
      if (!doc) return;
      const old = document.getElementById("checkapp-legal-modal");
      if (old) old.remove();
      addStyle();
      const root = document.createElement("div");
      root.id = "checkapp-legal-modal";
      root.innerHTML = '<div class="ck-legal-box" role="dialog" aria-modal="true"><div class="ck-legal-head"><span></span></div><div class="ck-legal-text"></div><div class="ck-legal-foot"><button class="ck-legal-ok">Закрыть</button></div></div>';
      root.querySelector(".ck-legal-head span").textContent = doc.title;
      root.querySelector(".ck-legal-text").textContent = doc.text;
      const close = function () { root.remove(); };
      root.querySelectorAll("button").forEach(function (button) { button.addEventListener("click", close); });
      root.addEventListener("click", function (event) { if (event.target === root) close(); });
      document.body.appendChild(root);
    }
    window.__checkappOpenLegal = openDocument;

    addStyle();
  })();

  document.addEventListener("change", function (ev) {
    const t = ev.target;
    if (!t || t.type !== "checkbox") return;
    if (t.dataset.caAdminExpand === "1") return;
    const wrap = t.closest("label, .checkbox, [class*='check'], div") || t.parentElement;
    const text = String((wrap && wrap.textContent) || "");
    if (!/права администратора|administrator rights|полный доступ|full control/i.test(text)) return;
    if (!t.checked) return;
    const root = t.closest(".modal, [class*='modal'], .vfm, form, [class*='drawer'], [class*='client']") || document.body;
    const boxes = Array.from(root.querySelectorAll("input[type=checkbox]"));
    if (boxes.length < 8) return;
    boxes.forEach(function (cb) {
      if (cb === t || cb.checked) return;
      cb.dataset.caAdminExpand = "1";
      cb.checked = true;
      try { cb.dispatchEvent(new Event("input", { bubbles: true })); } catch (_) {}
      try { cb.dispatchEvent(new Event("change", { bubbles: true })); } catch (_) {}
      cb.dataset.caAdminExpand = "";
    });
  }, true);

  document.addEventListener("click", function (ev) {
    const page = String(document.body && document.body.innerText || "");
    if (page.indexOf("Безопасность") < 0) return;
    const t = ev.target;
    if (!t || !t.closest) return;
    const btn = t.closest("button, [role=button], a");
    if (!btn) return;
    const label = String(btn.getAttribute("aria-label") || btn.title || btn.textContent || "").trim();
    if (label && !/закры|заверш|end|revoke|logout|удал|×|✕|^x$/i.test(label) && !btn.querySelector("svg")) return;
    let node = btn;
    for (let i = 0; i < 8 && node; i++) {
      const text = String(node.innerText || "");
      const ipm = text.match(/(\d{1,3}(?:\.\d{1,3}){3})/);
      if (ipm) {
        rememberRevokedSession({ ip: ipm[1], id: ipm[1], key: "client_serials:" + ipm[1], serial: ipm[1] });
        return;
      }
      node = node.parentElement;
    }
  }, true);

  function payAuthHeaders() {
    var headers = { "Content-Type": "application/json", Accept: "application/json" };
    var tok = "";
    try { tok = readAuthToken(); } catch (_) {}
    if (tok) headers.Authorization = "Bearer " + tok;
    try {
      var slug = currentProjectSlug();
      if (slug) headers["X-Checkapp-Project"] = slug;
    } catch (_) {}
    return headers;
  }

  function amountToRub(n) {
    n = Number(n || 0);
    if (n >= 10000) return Math.round(n / 100);
    return Math.round(n);
  }

  function plategaMethodId(raw) {
    var text = String(raw || "").toLowerCase();
    if (/crypto|крипт|usdt/.test(text)) return 13;
    if (/sbp|сбп|tinkoff-sbp/.test(text)) return 2;
    var n = Number(raw);
    if (n === 2 || n === 13) return n;
    return 0;
  }

  function parseDepositRequest(url, method, body) {
    if (String(method || "").toUpperCase() !== "POST") return null;
    if (window.__caPlategaAllowTopup) return null;
    var href = String(url || "");
    if (/wallet-operations/i.test(href)) return null;
    if (!/\/(wallet-topup|wallet)(\/|$|\?)/i.test(href)) return null;
    var parsed = {};
    try { parsed = typeof body === "string" ? JSON.parse(body || "{}") : (body && typeof body === "object" ? body : {}); } catch (_) { parsed = {}; }
    if (parsed && (parsed.renew || parsed.pay || parsed.auto_renew) && !(parsed.amount || parsed.value || parsed.sum || parsed.method)) return null;
    var amt = Number((parsed && (parsed.amount || parsed.value || parsed.sum)) || 0);
    var meth = (parsed && (parsed.method || parsed.payment_method || parsed.paymentMethod)) || window.__caPayMethod || "";
    if (!amt && !meth) return null;
    return { amount: amt, method: meth };
  }

  function tryHandleDeposit(url, method, body) {
    var dep = parseDepositRequest(url, method, body);
    if (!dep) return null;
    var code = plategaMethodId(dep.method);
    if (!code) code = window.__caPayMethod === 13 ? 13 : 2;
    if (code !== 2 && code !== 13) {
      try { showCheckappToast("warn", "Сейчас можно оплатить только СБП или Crypto.", { title: "Пополнение" }); } catch (_) {}
      return Promise.reject(new Error("Сейчас можно оплатить только СБП или Crypto."));
    }
    var rub = amountToRub(dep.amount);
    if (rub < 1) {
      return Promise.reject(new Error("Сумма должна быть больше 0 ₽."));
    }
    var post = (typeof window.__checkappOrigFetch === "function") ? window.__checkappOrigFetch : fetch.bind(window);
    var ctrl = null;
    var timer = null;
    try { if (typeof AbortController === "function") ctrl = new AbortController(); } catch (_) {}
    if (ctrl) {
      timer = setTimeout(function () { try { ctrl.abort(); } catch (_) {} }, 18000);
    }
    return post("/billing/platega/create", {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers: payAuthHeaders(),
      body: JSON.stringify({
        amount_rub: rub,
        payment_method: code,
        method: code === 13 ? "crypto" : "tinkoff-sbp",
        project: (typeof currentProjectSlug === "function" && currentProjectSlug()) || ""
      }),
      signal: ctrl ? ctrl.signal : undefined
    }).then(function (res) {
      return res.text().then(function (raw) {
        var data = {};
        try { data = JSON.parse(raw); } catch (_) { data = {}; }
        var href = "";
        if (typeof data === "string") href = data;
        else if (data) href = data.redirect || data.url || data.paymentLink || "";
        if (href && /^https?:\/\//i.test(String(href))) {
          try { if (window.__caGoPay) window.__caGoPay(href); } catch (_) {}
          return String(href);
        }
        var msg = (data && (data.message || data.error)) || "";
        if (!msg) {
          if (/<!DOCTYPE/i.test(raw) || /<html/i.test(raw) || /"ok"\s*:\s*true/i.test(raw) && !/redirect/i.test(raw)) {
            msg = "Python на сервере старый. Залей platega_pay.py + server.py и выполни restart-site.sh. В /utils/build должно быть platega-v52.";
          }
        }
        throw new Error(msg || "Не удалось создать платёж.");
      });
    }).catch(function (err) {
      if (err && (err.name === "AbortError" || /aborted/i.test(String(err && err.message || "")))) {
        throw new Error("Платёжная система не ответила. Попробуй ещё раз.");
      }
      throw err;
    }).finally(function () {
      if (timer) clearTimeout(timer);
    });
  }

  (function nativePayMethodsOnly() {
    function patchMethodCards(root) {
      if (!root || root.nodeType !== 1) return;
      var cards = [];
      if (root.classList && root.classList.contains("method")) cards.push(root);
      if (root.querySelectorAll) cards = cards.concat(Array.from(root.querySelectorAll(".method")));
      if (!cards.length) return;
      var sbp = null;
      var selectedBlocked = null;
      cards.forEach(function (el) {
        var lab = String(el.textContent || "");
        var allow = /сбп|sbp|crypto|крипт/i.test(lab) && !/paypal|google|карт|visa|eu|европ/i.test(lab);
        if (allow) {
          if (/сбп|sbp/i.test(lab)) sbp = el;
          el.style.opacity = "";
          el.style.pointerEvents = "";
          el.style.filter = "";
          return;
        }
        el.style.opacity = "0.42";
        el.style.pointerEvents = "none";
        el.style.filter = "grayscale(0.25)";
        if (el.classList && el.classList.contains("selected")) selectedBlocked = el;
      });
      if (sbp && selectedBlocked && !sbp.dataset.caPayClicked) {
        sbp.dataset.caPayClicked = "1";
        try { sbp.click(); } catch (_) {}
      }
    }

    function patchPiniaMinDeposit() {
      try {
        var root = document.querySelector("#app");
        var pinia = root && root.__vue_app__ && root.__vue_app__.config.globalProperties.$pinia;
        var panel = pinia && pinia._s && pinia._s.get("panel");
        var project = panel && panel.project;
        if (project && typeof project === "object") {
          project.min_deposite = 1;
          project.min_deposit = 1;
          project.min_replenishment = 1;
        }
      } catch (_) {}
    }

    function patchAmountMin(root) {
      if (!root || root.nodeType !== 1) return;
      patchPiniaMinDeposit();
      var scope = root;
      try {
        if (root.closest) scope = root.closest(".vfm, .modal, [class*='payment']") || root;
      } catch (_) {}
      var inputs = [];
      if (scope.tagName === "INPUT") inputs.push(scope);
      if (scope.querySelectorAll) inputs = inputs.concat(Array.from(scope.querySelectorAll("input")));
      inputs.forEach(function (el) {
        var min = Number(el.min || el.getAttribute("min") || 0);
        var wrap = el.closest ? (el.closest("label, .field, .form-group, div") || el.parentElement) : el.parentElement;
        var lab = String((wrap && wrap.textContent) || el.placeholder || "");
        if (min >= 100 || /сумм|amount|₽/i.test(lab)) {
          el.min = "1";
          try { el.setAttribute("min", "1"); } catch (_) {}
          if (el.type === "number") el.step = "1";
        }
      });
      if (scope.querySelectorAll) {
        Array.from(scope.querySelectorAll("p, span, div, small, label")).forEach(function (el) {
          if (el.children && el.children.length) return;
          var t = String(el.textContent || "");
          if (!/мин\.?\s*сумма пополнения|min\.?\s*replenishment|validator\.minsum/i.test(t)) return;
          el.textContent = t.replace(/₽?\s*100\b/g, "₽1").replace(/\b100\b/g, "1");
          el.style.display = "none";
        });
        Array.from(scope.querySelectorAll("button")).forEach(function (btn) {
          var lab = String(btn.textContent || "");
          if (!/пополнить|pay|top.?up/i.test(lab)) return;
          if (btn.disabled) {
            btn.disabled = false;
            btn.removeAttribute("disabled");
            btn.classList.remove("disabled", "is-disabled", "opacity-50");
            btn.style.pointerEvents = "";
            btn.style.opacity = "";
          }
        });
      }
    }

    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.closest) return;
      var card = t.closest(".method");
      if (!card) return;
      var id = plategaMethodId(card.textContent);
      if (id) window.__caPayMethod = id;
    }, true);

    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.closest) return;
      var modal = t.closest(".vfm, .modal");
      if (!modal || !modal.querySelector(".method")) return;
      var btn = t.closest("button");
      if (!btn || !/пополнить/i.test(String(btn.textContent || ""))) return;
      var inp = modal.querySelector("input[type='number'], input[type='text'], input");
      var amt = Number((inp && inp.value) || 0);
      if (!(amt >= 1) || amt >= 100) return;
      var minsum = false;
      try {
        Array.from(modal.querySelectorAll("p, span, small, div")).forEach(function (el) {
          if (el.children && el.children.length) return;
          if (/мин\.?\s*сумма пополнения/i.test(String(el.textContent || ""))) minsum = true;
        });
      } catch (_) {}
      if (!btn.disabled && !minsum) return;
      ev.preventDefault();
      ev.stopImmediatePropagation();
      var dep = tryHandleDeposit("/wallet-topup", "POST", { amount: amt, method: window.__caPayMethod || 2 });
      if (!dep || typeof dep.then !== "function") return;
      dep.then(function (redirect) {
        try { if (window.__caGoPay) window.__caGoPay(redirect); } catch (_) {}
      }).catch(function (err) {
        try { showCheckappToast("warn", (err && err.message) || "Не удалось создать платёж.", { title: "Пополнение" }); } catch (_) {}
      });
    }, true);

    setInterval(function () {
      patchPiniaMinDeposit();
      try { patchAmountMin(document.documentElement); } catch (_) {}
    }, 500);

    if (typeof MutationObserver === "function") {
      var obs = new MutationObserver(function (records) {
        for (var i = 0; i < records.length; i++) {
          var nodes = records[i].addedNodes;
          for (var j = 0; j < nodes.length; j++) {
            var node = nodes[j];
            if (!node || node.nodeType !== 1) continue;
            patchMethodCards(node);
            patchAmountMin(node);
          }
        }
      });
      try { obs.observe(document.documentElement, { childList: true, subtree: true }); } catch (_) {}
    }

    (function checkReturn() {
      var q = new URLSearchParams(location.search || "");
      var order = q.get("platega");
      var fail = q.get("platega_fail");
      if (!order && !fail) return;
      var post = (typeof window.__checkappOrigFetch === "function") ? window.__checkappOrigFetch : fetch.bind(window);
      if (fail && !order) {
        try { showCheckappToast("warn", "Оплата не завершена.", { title: "Пополнение" }); } catch (_) {}
        return;
      }
      post("/billing/platega/status?order=" + encodeURIComponent(order), { credentials: "include", headers: payAuthHeaders() })
        .then(function (res) { return res.json().catch(function () { return {}; }); })
        .then(function (data) {
          if (data && data.status === "CONFIRMED") {
            try { showCheckappToast("ok", "Баланс пополнен на " + (data.amount_rub || "") + " ₽.", { title: "Оплата прошла" }); } catch (_) {}
          } else if (data && data.status === "CANCELED") {
            try { showCheckappToast("warn", "Платёж отменён.", { title: "Пополнение" }); } catch (_) {}
          }
        })
        .catch(function () {});
    })();
  })();

})();
