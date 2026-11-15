/**
 * Local API bridge for the offline RustApp copy.
 * Rewrites core/court/centrifugo hosts to this origin. Does not change CSS.
 */
(function () {
  if (window.__rustappLocalBridge) return;
  window.__rustappLocalBridge = 1;

  function restoreCdn(href) {
    href = String(href || "");
    try {
      var u = new URL(href, location.origin);
      var host = String(u.hostname || "").toLowerCase();
      if (/^s3\./i.test(host) && host !== "s3.rustapp.io") {
        return "https://s3.rustapp.io" + u.pathname + u.search + u.hash;
      }
      if (/^r2\./i.test(host) && host !== "r2.rustapp.io") {
        return "https://r2.rustapp.io" + u.pathname + u.search + u.hash;
      }
    } catch (_) {}
    return href;
  }

  function viaProxy(href) {
    try {
      var u = new URL(href, location.origin);
      var host = String(u.hostname || "").toLowerCase();
      if (host === "s3.rustapp.io") return location.origin + "/__cdn/s3" + u.pathname + u.search;
      if (host === "r2.rustapp.io") return location.origin + "/__cdn/r2" + u.pathname + u.search;
    } catch (_) {}
    return href;
  }

  function cdnUrl(raw) {
    var href = String(raw || "");
    if (!href || href.indexOf("data:") === 0 || href.indexOf("blob:") === 0) return href;
    if (href.indexOf("/__cdn/") >= 0) return href;
    href = restoreCdn(href);
    try {
      var u = new URL(href, location.origin);
      var host = String(u.hostname || "").toLowerCase();
      if (host === location.hostname || host === "127.0.0.1" || host === "localhost") {
        if (/\/(avatar-|landing\/|assets\/|plugin-sign|custom\/|logo)/i.test(u.pathname)) {
          href = "https://s3.rustapp.io" + u.pathname + u.search;
        }
      }
    } catch (_) {}
    return viaProxy(href);
  }

  function publicImage(path) {
    var a = String(path || "");
    if (!a || a === "[object Object]") {
      return cdnUrl("https://s3.rustapp.io/assets/default-avatar.jpeg");
    }
    if (/^https?:\/\//i.test(a) || a.indexOf("//") === 0) return cdnUrl(a);
    if (a.indexOf("plugin-sign") >= 0) return cdnUrl("https://r2.rustapp.io/" + a.replace(/^\//, ""));
    return cdnUrl("https://s3.rustapp.io/" + a.replace(/^\//, ""));
  }

  function fixImg(el) {
    if (!el || el.nodeType !== 1) return;
    var tag = el.tagName;
    if (tag === "IMG" || tag === "VIDEO" || tag === "SOURCE") {
      var raw = el.getAttribute("src") || el.src || "";
      var next = cdnUrl(raw);
      if (next && next !== raw) {
        try { el.src = next; } catch (_) {}
      }
      var srcset = el.getAttribute && el.getAttribute("srcset");
      if (srcset) {
        var nsset = srcset.split(",").map(function (part) {
          var bits = part.trim().split(/\s+/);
          if (!bits[0]) return part;
          bits[0] = cdnUrl(bits[0]);
          return bits.join(" ");
        }).join(", ");
        if (nsset !== srcset) el.setAttribute("srcset", nsset);
      }
      var poster = el.getAttribute && el.getAttribute("poster");
      if (poster) {
        var p2 = cdnUrl(poster);
        if (p2 && p2 !== poster) el.setAttribute("poster", p2);
      }
    }
    var st = el.getAttribute && el.getAttribute("style");
    if (st && /url\(/i.test(st)) {
      var ns = st.replace(/url\(\s*(['"]?)(.*?)\1\s*\)/g, function (_, q, u) {
        return "url(" + q + cdnUrl(u) + q + ")";
      });
      if (ns !== st) el.setAttribute("style", ns);
    }
  }

  function watchImages() {
    function sweep(root) {
      try {
        (root.querySelectorAll ? root : document).querySelectorAll("img,video,source,[style*='url(']").forEach(fixImg);
      } catch (_) {}
    }
    if (document.documentElement) {
      new MutationObserver(function (recs) {
        recs.forEach(function (rec) {
          rec.addedNodes && rec.addedNodes.forEach(function (node) {
            if (!node || node.nodeType !== 1) return;
            if (node.tagName === "IMG" || node.tagName === "VIDEO" || node.tagName === "SOURCE") fixImg(node);
            else sweep(node);
          });
        });
      }).observe(document.documentElement, { childList: true, subtree: true });
    }
    setInterval(function () { sweep(document); }, 800);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", watchImages);
  else watchImages();

  try {
    var desc = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, "src");
    if (desc && desc.set) {
      Object.defineProperty(HTMLImageElement.prototype, "src", {
        configurable: true,
        enumerable: desc.enumerable,
        get: desc.get,
        set: function (v) { desc.set.call(this, cdnUrl(v)); }
      });
    }
  } catch (_) {}
  try {
    var osa = Element.prototype.setAttribute;
    Element.prototype.setAttribute = function (name, value) {
      var key = String(name || "").toLowerCase();
      if ((key === "src" || key === "poster" || key === "href") && this.tagName && /^(IMG|VIDEO|SOURCE|IMAGE|USE)$/i.test(this.tagName)) {
        value = cdnUrl(value);
      }
      return osa.call(this, name, value);
    };
  } catch (_) {}

  function toLocal(raw) {
    var href = String(raw || "");
    if (!href || href.charAt(0) === "/" || href.indexOf("data:") === 0 || href.indexOf("blob:") === 0) return href;
    try {
      var u = new URL(href, location.origin);
      var host = String(u.hostname || "").toLowerCase();
      if (host === "s3.rustapp.io" || /^s3\./i.test(host)) {
        return location.origin + "/__cdn/s3" + u.pathname + u.search + u.hash;
      }
      if (host === "r2.rustapp.io" || /^r2\./i.test(host)) {
        return location.origin + "/__cdn/r2" + u.pathname + u.search + u.hash;
      }
      if (host === location.hostname || host === "127.0.0.1" || host === "localhost") return href;
      if (
        host.indexOf("core.") === 0 ||
        host.indexOf("court.") === 0 ||
        host.indexOf("centrifugo.") === 0 ||
        /centrifugo/i.test(host)
      ) {
        return location.origin + u.pathname + u.search + u.hash;
      }
    } catch (_) {}
    if (/^https?:\/\/(core|court|centrifugo)\./i.test(href)) {
      return location.origin + href.replace(/^https?:\/\/[^/]+/i, "");
    }
    return href;
  }

  function clearAuth() {
    try {
      localStorage.removeItem("access_token");
      localStorage.removeItem("token");
      sessionStorage.removeItem("access_token");
    } catch (_) {}
    try {
      var root = document.querySelector("#app");
      var pinia = root && root.__vue_app__ && root.__vue_app__.config.globalProperties.$pinia;
      var ast = pinia && pinia._s && pinia._s.get("app");
      if (ast) {
        ast.access_token = "";
        ast.client = null;
        ast.projects = [];
      }
    } catch (_) {}
  }

  function goRoute(path) {
    try {
      var root = document.querySelector("#app");
      var router = root && root.__vue_app__ && root.__vue_app__.config.globalProperties.$router;
      if (router) router.push(path).catch(function () { location.href = path; });
      else location.href = path;
    } catch (_) {
      location.href = path;
    }
  }

  function localPathFromHref(href) {
    href = String(href || "");
    if (!href || href.charAt(0) === "#") return "";
    try {
      var u = new URL(href, location.origin);
      var host = String(u.hostname || "").toLowerCase();
      if (host === "rustapp.io" || host === "www.rustapp.io") return (u.pathname || "/") + u.search + u.hash;
      if ((host === location.hostname || host === "127.0.0.1" || host === "localhost") && u.protocol === "https:") {
        return (u.pathname || "/") + u.search + u.hash;
      }
    } catch (_) {}
    if (href === "/" || href === "/profile") return href === "/profile" ? "/client/profile" : "/";
    return "";
  }

  document.addEventListener("click", function (ev) {
    var el = ev.target && ev.target.closest && ev.target.closest("a,button,[role='button'],.btn-footer");
    if (!el) return;
    var href = String(el.getAttribute("href") || el.getAttribute("to") || "");
    var text = String(el.textContent || "").replace(/\s+/g, " ").trim();
    var cls = String(el.className || "");

    if (/\bbtn-footer\b/.test(cls) && /\bred\b/.test(cls)) {
      ev.preventDefault();
      ev.stopPropagation();
      goRoute("/client/profile");
      return;
    }

    if (/выйти с аккаунта|выйти из аккаунта|^выйти$|logout|sign out/i.test(text)) {
      ev.preventDefault();
      ev.stopPropagation();
      clearAuth();
      goRoute("/client/auth");
      return;
    }

    if (href === "/profile" || href === "/app") {
      ev.preventDefault();
      ev.stopPropagation();
      goRoute("/client/profile");
      return;
    }

    var local = localPathFromHref(href);
    if (local) {
      if (local === "/profile") local = "/client/profile";
      if (el.tagName === "A" || href) {
        ev.preventDefault();
        ev.stopPropagation();
        goRoute(local);
      }
    }
  }, true);

  var ofetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url);
    var method = String((init && init.method) || (input && input.method) || "GET").toUpperCase();
    if (/\/auth\/sessions/i.test(String(url || "")) && method === "DELETE") {
      clearAuth();
    }
    var next = toLocal(url);
    var req;
    if (typeof input === "string" || next !== url) req = ofetch(next, init);
    else req = ofetch(input, init);
    if (/\/auth\/sessions/i.test(String(url || "")) && method === "DELETE") {
      return req.then(function (res) {
        clearAuth();
        setTimeout(function () { goRoute("/client/auth"); }, 50);
        return res;
      });
    }
    return req;
  };

  var oopen = XMLHttpRequest.prototype.open;
  var osend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__raMethod = method;
    this.__raUrl = url;
    var args = Array.prototype.slice.call(arguments, 2);
    return oopen.apply(this, [method, toLocal(url)].concat(args));
  };
  XMLHttpRequest.prototype.send = function () {
    if (/DELETE/i.test(String(this.__raMethod || "")) && /\/auth\/sessions/i.test(String(this.__raUrl || ""))) {
      this.addEventListener("loadend", function () {
        clearAuth();
        setTimeout(function () { goRoute("/client/auth"); }, 50);
      });
    }
    return osend.apply(this, arguments);
  };

  var OWS = window.WebSocket;
  window.__rustappCentrifugeSockets = window.__rustappCentrifugeSockets || [];
  window.WebSocket = function (url, protocols) {
    var href = String(url || "");
    if (
      /centrifugo|connection\/websocket|core\.|court\./i.test(href) ||
      ((href.indexOf("ws://") === 0 || href.indexOf("wss://") === 0) && href.indexOf(location.host) < 0)
    ) {
      var listeners = { open: [], message: [], close: [], error: [] };
      var handlers = { open: null, message: null, error: null, close: null };
      var subs = {};
      function emit(type, ev) {
        var fn = handlers[type];
        if (typeof fn === "function") {
          try { fn(ev); } catch (_) {}
        }
        (listeners[type] || []).forEach(function (cb) {
          try { cb(ev); } catch (_) {}
        });
      }
      var fake = {
        url: href,
        readyState: 0,
        bufferedAmount: 0,
        extensions: "",
        protocol: "json",
        binaryType: "blob",
        __subs: subs,
        addEventListener: function (type, fn) {
          if (!listeners[type]) listeners[type] = [];
          listeners[type].push(fn);
          if (type === "open" && fake.readyState === 1) {
            try { fn({}); } catch (_) {}
          }
        },
        removeEventListener: function (type, fn) {
          if (!listeners[type]) return;
          listeners[type] = listeners[type].filter(function (x) { return x !== fn; });
        },
        dispatchEvent: function () { return true; },
        send: function (raw) {
          var text = String(raw || "");
          var rows = text.indexOf("\n") >= 0 ? text.split("\n") : [text];
          rows.forEach(function (row) {
            if (!row) return;
            var msg;
            try { msg = JSON.parse(row); } catch (_) { return; }
            var id = msg && msg.id;
            var reply = null;
            if (msg && msg.connect) {
              reply = {
                id: id,
                connect: {
                  client: "local-1",
                  version: "5.2.2",
                  ping: 25,
                  pong: true,
                  expires: false,
                  session: "local",
                  node: "local",
                  data: { user: "1", id: 1 }
                }
              };
            } else if (msg && msg.subscribe) {
              var channel = msg.subscribe.channel;
              if (channel) subs[channel] = 1;
              reply = { id: id, subscribe: { recoverable: false, positioned: false, epoch: "0", offset: 0 } };
            } else if (msg && msg.unsubscribe) {
              reply = { id: id, unsubscribe: {} };
            } else if (msg && msg.ping) {
              reply = { id: id, ping: {} };
            } else if (msg && msg.presence) {
              reply = { id: id, presence: { presence: { "local-1": { user: "1", client: "local-1" } } } };
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
          if (fake.readyState === 3) return;
          fake.readyState = 3;
          emit("close", { code: code || 1000, reason: reason || "", wasClean: true });
        },
        __emit: emit
      };
      window.__rustappCentrifugeSockets.push(fake);
      fake.__opened = false;
      function openNow() {
        if (fake.__opened) return;
        fake.__opened = true;
        fake.readyState = 1;
        emit("open", {});
      }
      fake.readyState = 1;
      setTimeout(openNow, 0);
      Object.defineProperty(fake, "onopen", {
        get: function () { return handlers.open; },
        set: function (fn) { handlers.open = fn; if (fake.readyState === 1 && fn) openNow(); }
      });
      Object.defineProperty(fake, "onmessage", {
        get: function () { return handlers.message; },
        set: function (fn) { handlers.message = fn; }
      });
      Object.defineProperty(fake, "onerror", {
        get: function () { return handlers.error; },
        set: function (fn) { handlers.error = fn; }
      });
      Object.defineProperty(fake, "onclose", {
        get: function () { return handlers.close; },
        set: function (fn) { handlers.close = fn; }
      });
      return fake;
    }
    return protocols !== undefined ? new OWS(url, protocols) : new OWS(url);
  };
  window.WebSocket.CONNECTING = 0;
  window.WebSocket.OPEN = 1;
  window.WebSocket.CLOSING = 2;
  window.WebSocket.CLOSED = 3;

  function patchLogout(store) {
    if (!store || store.__logoutPatched) return;
    store.__logoutPatched = true;
    store.logout = function () {
      clearAuth();
      goRoute("/client/auth");
    };
  }

  function patchRouter(router) {
    if (!router || router.__raNavPatched) return;
    router.__raNavPatched = true;
    router.beforeEach(function (to) {
      var path = (to && to.path) || "";
      if (path === "/profile" || path === "/app") return "/client/profile";
      return true;
    });
  }

  function lockUrls(store) {
    if (!store || !store.Urls || store.Urls.__rustappPatched) return false;
    var ws = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/connection/websocket";
    try {
      Object.defineProperty(store.Urls, "Core", {
        configurable: true, enumerable: true,
        get: function () { return location.origin; },
        set: function () {}
      });
      Object.defineProperty(store.Urls, "Court", {
        configurable: true, enumerable: true,
        get: function () { return location.origin; },
        set: function () {}
      });
      Object.defineProperty(store.Urls, "Centrifugo", {
        configurable: true, enumerable: true,
        get: function () { return ws; },
        set: function () {}
      });
      store.Urls.Images = function (path) { return publicImage(path); };
      store.Urls.__rustappPatched = true;
      return true;
    } catch (_) {
      try {
        store.Urls.Core = location.origin;
        store.Urls.Court = location.origin;
        store.Urls.Centrifugo = ws;
        store.Urls.Images = function (path) { return publicImage(path); };
        store.Urls.__rustappPatched = true;
        return true;
      } catch (__) {}
    }
    return false;
  }

  var kickAt = 0;
  var kickCount = 0;
  var kicking = false;

  function syncRouter(router) {
    if (!router || kicking) return;
    var route = router.currentRoute && router.currentRoute.value;
    if (!route) return;
    var matched = (route.matched && route.matched.length) || 0;
    if (matched) {
      kickCount = 0;
      return;
    }
    var now = Date.now();
    if (kickCount > 6 || now - kickAt < 250) return;
    kickAt = now;
    kickCount += 1;
    var dest = location.pathname || "/";
    if (dest.length > 1 && dest.slice(-1) === "/") dest = dest.slice(0, -1) || "/";
    kicking = true;
    var finish = function () { kicking = false; };
    var go = function () { return router.replace(dest); };
    if (dest === (route.path || "/")) {
      router.replace(dest === "/" ? "/pricing" : "/").then(go).catch(go).finally(finish);
    } else {
      go().catch(function () {}).finally(finish);
    }
  }

  setInterval(function () {
    try {
      var root = document.querySelector("#app");
      var app = root && root.__vue_app__;
      var pinia = app && app.config && app.config.globalProperties && app.config.globalProperties.$pinia;
      var store = pinia && pinia._s && pinia._s.get("config");
      if (store) lockUrls(store);
      var appStore = pinia && pinia._s && pinia._s.get("app");
      if (appStore) patchLogout(appStore);
      var router = app && app.config && app.config.globalProperties && app.config.globalProperties.$router;
      patchRouter(router);
      syncRouter(router);
    } catch (_) {}
  }, 50);
})();
