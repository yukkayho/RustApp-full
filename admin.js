(function () {
  const TOKEN_KEY = "access_token";
  const searchTimers = {};
  let manageProject = null;
  let confirmCb = null;
  let projectsCache = {};
  let openDropdown = null;
  let me = { is_owner: false, id: 0 };
  let auditTab = "admin";
  let auditProjects = [];

  function $(id) { return document.getElementById(id); }

  function token() {
    let t = localStorage.getItem(TOKEN_KEY) || localStorage.getItem("token") || "";
    try { t = JSON.parse(t); } catch (_) {}
    return String(t || "").replace(/^"|"$/g, "");
  }

  function setToken(t) {
    localStorage.setItem(TOKEN_KEY, JSON.stringify(t));
    localStorage.setItem("token", JSON.stringify(t));
  }

  function toast(msg, err) {
    const el = document.createElement("div");
    el.className = "toast" + (err ? " err" : "");
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(function () { el.remove(); }, 3200);
  }

  function rub(k) { return (Number(k || 0) / 100).toFixed(2) + " ₽"; }
  function esc(s) {
    return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function escAttr(s) { return esc(s).replace(/'/g, "&#39;"); }

  function planLabel(slug) {
    const s = String(slug || "base").toLowerCase();
    if (s === "plus") return "Plus";
    if (s === "enterprise") return "Enterprise";
    return "Base";
  }

  function statusBadge(p) {
    const st = String((p && p.status) || "active");
    const label = (p && p.status_label) || st;
    const icon = st === "blocked" ? "🔒" : ((st === "frozen" || st === "expired") ? "❄️" : (st === "trial" ? "⏳" : "🟢"));
    return '<span class="status-badge ' + esc(st) + '">' + icon + " " + esc(label) + "</span>";
  }

  function skeletonHtml() {
    return '<div class="skeleton"></div>';
  }

  function num(v) { return Number(v || 0); }

  function fmtN(v) {
    return num(v).toLocaleString("ru-RU");
  }

  function pct(part, whole) {
    if (!whole) return 0;
    return Math.max(0, Math.min(100, Math.round((part / whole) * 100)));
  }

  function ringSegments(cx, cy, r, stroke, parts) {
    var total = 0;
    parts.forEach(function (p) { total += p.n; });
    var circ = 2 * Math.PI * r;
    var html = '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none" stroke="rgba(255,255,255,.07)" stroke-width="' + stroke + '"/>';
    if (!total) return html;
    var acc = 0;
    html += '<g transform="rotate(-90 ' + cx + ' ' + cy + ')">';
    parts.forEach(function (p) {
      if (!p.n) return;
      var len = (p.n / total) * circ;
      html += '<circle class="ring-seg" cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none" stroke="' + p.color + '" stroke-width="' + stroke + '" data-len="' + len.toFixed(2) + '" data-gap="' + (circ - len).toFixed(2) + '" data-off="' + (-acc).toFixed(2) + '" stroke-dasharray="0 ' + circ.toFixed(2) + '" stroke-dashoffset="' + (-acc).toFixed(2) + '" stroke-linecap="butt"/>';
      acc += len;
    });
    html += "</g>";
    return html;
  }

  function ticksSvg(cx, cy, r, count) {
    var html = '<g class="ring-spin">';
    for (var i = 0; i < count; i++) {
      var a = (i / count) * Math.PI * 2;
      var inner = r - (i % 4 === 0 ? 7 : 3);
      var x1 = cx + Math.cos(a) * inner;
      var y1 = cy + Math.sin(a) * inner;
      var x2 = cx + Math.cos(a) * (r + 5);
      var y2 = cy + Math.sin(a) * (r + 5);
      html += '<line x1="' + x1.toFixed(1) + '" y1="' + y1.toFixed(1) + '" x2="' + x2.toFixed(1) + '" y2="' + y2.toFixed(1) + '" stroke="rgba(255,255,255,.2)" stroke-width="' + (i % 4 === 0 ? 1.4 : 0.7) + '"/>';
    }
    html += "</g>";
    return html;
  }

  function gaugeSvg(value, max, color) {
    var p = max ? Math.max(0, Math.min(1, value / max)) : 0;
    var len = 138.2;
    var dash = (p * len).toFixed(1);
    return '<svg viewBox="0 0 120 86" aria-hidden="true">' +
      '<path d="M14 72 A46 46 0 0 1 106 72" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="10" stroke-linecap="round"/>' +
      '<path class="gauge-fill" data-gauge="' + dash + '" d="M14 72 A46 46 0 0 1 106 72" fill="none" stroke="' + color + '" stroke-width="10" stroke-linecap="round" stroke-dasharray="0 ' + len + '"/>' +
      "</svg>";
  }

  function animateNums(root) {
    if (!root) return;
    root.querySelectorAll("[data-count]").forEach(function (el) {
      var to = num(el.getAttribute("data-count"));
      var suffix = el.getAttribute("data-suffix") || "";
      if (el._countAnim) cancelAnimationFrame(el._countAnim);
      el.textContent = "0" + suffix;
      var start = performance.now();
      function tick(now) {
        var t = Math.min(1, (now - start) / 860);
        var e = 1 - Math.pow(1 - t, 3);
        el.textContent = Math.round(to * e).toLocaleString("ru-RU") + suffix;
        if (t < 1) el._countAnim = requestAnimationFrame(tick);
        else el._countAnim = 0;
      }
      el._countAnim = requestAnimationFrame(tick);
    });
  }

  function animateGauges(root) {
    if (!root) return;
    root.querySelectorAll(".gauge-fill").forEach(function (el) {
      var to = num(el.getAttribute("data-gauge"));
      if (el._gAnim) cancelAnimationFrame(el._gAnim);
      el.style.strokeDasharray = "0 138.2";
      var start = performance.now();
      function tick(now) {
        var t = Math.min(1, (now - start) / 900);
        var e = 1 - Math.pow(1 - t, 3);
        el.style.strokeDasharray = (to * e).toFixed(1) + " 138.2";
        if (t < 1) el._gAnim = requestAnimationFrame(tick);
        else el._gAnim = 0;
      }
      el._gAnim = requestAnimationFrame(tick);
    });
  }

  function animateRings(root) {
    if (!root) return;
    root.querySelectorAll(".ring-seg").forEach(function (el) {
      var len = num(el.getAttribute("data-len"));
      var gap = num(el.getAttribute("data-gap"));
      var full = len + gap;
      if (el._rAnim) cancelAnimationFrame(el._rAnim);
      el.setAttribute("stroke-dasharray", "0 " + full);
      var start = performance.now();
      function tick(now) {
        var t = Math.min(1, (now - start) / 920);
        var e = 1 - Math.pow(1 - t, 3);
        el.setAttribute("stroke-dasharray", (len * e).toFixed(2) + " " + (full - len * e).toFixed(2));
        if (t < 1) el._rAnim = requestAnimationFrame(tick);
        else el._rAnim = 0;
      }
      el._rAnim = requestAnimationFrame(tick);
    });
  }

  function restartCssAnim(el) {
    if (!el) return;
    el.style.animation = "none";
    void el.offsetWidth;
    el.style.animation = "";
  }

  function replayMotion(el) {
    if (!el) return;
    if (el._motionUntil && Date.now() < el._motionUntil) return;
    el._motionUntil = Date.now() + 900;
    animateNums(el);
    animateGauges(el);
    animateRings(el);
    el.querySelectorAll(".sky-bar, .track i, .spectrum").forEach(restartCssAnim);
  }

  function bindDashMotion(root) {
    if (!root) return;
    root.querySelectorAll(".dash-core, .dash-dials, .dash-rail, .dash-sky, .dash-pulse, .dial, .sky-col, .spectrum-meta > div, .pulse-row").forEach(function (el) {
      el.addEventListener("mouseenter", function () { replayMotion(el); });
    });
  }

  async function api(path, opts) {
    opts = opts || {};
    const headers = Object.assign({ "Content-Type": "application/json", Accept: "application/json" }, opts.headers || {});
    const t = token();
    if (t) headers.Authorization = "Bearer " + t;
    const res = await fetch(path, Object.assign({}, opts, { headers: headers }));
    const ct = (res.headers.get("Content-Type") || "").toLowerCase();
    const raw = await res.text();
    let data = {};
    try { data = raw ? JSON.parse(raw) : {}; } catch (_) {}
    if (res.status === 401 || res.status === 403) throw new Error("forbidden");
    if (!ct.includes("json") || (raw && raw.trim().charAt(0) !== "{")) {
      throw new Error("Сервер вернул HTML вместо данных. Перезапустите start.bat и обновите страницу (Ctrl+F5).");
    }
    if (!res.ok) {
      const msg = data.message || data.error || "";
      if (/project blocked|заблокирован/i.test(String(msg))) throw new Error("Проект заблокирован");
      if (/not found/i.test(String(msg))) throw new Error("Данные не найдены");
      if (res.status >= 500) throw new Error("Сервер временно недоступен. Попробуйте позже.");
      throw new Error(msg && !/^(HTTP|Axios|Prisma|Internal)/i.test(msg) ? msg : "Не удалось выполнить действие");
    }
    return data;
  }

  function apiQ(path, q) {
    if (!q) return path;
    return path + "?q=" + encodeURIComponent(q);
  }

  function confirmDialog(title, text) {
    return new Promise(function (resolve) {
      confirmCb = resolve;
      $("confirm-title").textContent = title;
      $("confirm-text").textContent = text;
      $("confirm-modal").classList.remove("hidden");
    });
  }

  function closeDropdowns() {
    document.querySelectorAll(".dropdown.open").forEach(function (el) { el.classList.remove("open"); });
    openDropdown = null;
  }

  document.addEventListener("click", function (e) {
    if (!e.target.closest(".dropdown")) closeDropdowns();
  });

  async function login(email, password) {
    const res = await fetch("/auth/classic/sign-in", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ email: email, password: password }),
    });
    if (!res.ok) throw new Error("Неверный email или пароль");
    const tok = await res.json();
    setToken(typeof tok === "string" ? tok : tok.token || tok.access_token || "");
    await api("/admin/api/stats");
  }

  let presenceTimer = null;
  let chatPeekTimer = null;
  let chatAudioUnlockBound = false;

  function showLogin() {
    $("login-screen").classList.remove("hidden");
    $("app-shell").classList.add("hidden");
    clearInterval(presenceTimer);
    clearInterval(chatPeekTimer);
    stopChatPoll();
  }

  function showApp() {
    $("login-screen").classList.add("hidden");
    $("app-shell").classList.remove("hidden");
    paintChrome();
    tickClock();
    startPresence();
    if (!chatAudioUnlockBound) {
      chatAudioUnlockBound = true;
      document.addEventListener("pointerdown", unlockChatAudio);
    }
  }

  async function refreshAdminPresence() {
    if ($("app-shell").classList.contains("hidden") || document.hidden) return;
    try {
      await api("/admin/api/me");
      if (!document.querySelector('.page[data-page="admins"]:not(.hidden)')) return;
      const data = await api("/admin/api/admins");
      (data.admins || []).forEach(function (a) {
        const el = document.querySelector('.presence[data-admin="' + a.id + '"]');
        if (!el) return;
        el.classList.toggle("on", !!a.online);
        el.title = a.online ? "Онлайн" : "Оффлайн";
      });
    } catch (_) {}
  }

  function startPresence() {
    clearInterval(presenceTimer);
    clearInterval(chatPeekTimer);
    refreshAdminPresence();
    peekChatBadge();
    presenceTimer = setInterval(refreshAdminPresence, 20000);
    chatPeekTimer = setInterval(peekChatBadge, 3000);
  }

  function paintChrome() {
    var who = $("admin-who");
    if (who) who.textContent = me.email || me.name || "Админ";
    var role = $("admin-role");
    if (role) role.textContent = me.is_owner ? "Владелец" : "Администратор";
  }

  function tickClock() {
    var el = $("admin-clock");
    if (!el) return;
    el.textContent = new Date().toLocaleString("ru-RU", {
      weekday: "short",
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function setPage(name) {
    document.querySelectorAll(".nav-btn").forEach(function (b) {
      b.classList.toggle("active", b.dataset.page === name);
    });
    document.querySelectorAll(".page").forEach(function (p) {
      p.classList.toggle("hidden", p.dataset.page !== name);
    });
    var titles = {
      dashboard: { t: "Обзор платформы", k: "Живые цифры" },
      users: { t: "Пользователи", k: "Аккаунты" },
      projects: { t: "Проекты", k: "Площадки" },
      admins: { t: "Администраторы", k: "Доступ" },
      chat: { t: "Чат админов", k: "Голос · скрины · видео" },
      audit: { t: "Журнал аудита", k: "История" },
      transactions: { t: "Транзакции", k: "Платежи" },
      ips: { t: "IP серверов", k: "Сеть" },
    };
    var meta = titles[name] || { t: "Админка", k: "Панель" };
    $("page-title").textContent = meta.t;
    var kicker = $("page-kicker");
    if (kicker) kicker.textContent = meta.k;
    if (name === "dashboard") loadStats();
    if (name === "users") loadUsers($("users-search").value.trim());
    if (name === "projects") loadProjects($("projects-search").value.trim());
    if (name === "admins") loadAdmins();
    if (name === "chat") startChat();
    else stopChatPoll();
    if (name === "audit") loadAudit();
    if (name === "transactions") loadTransactions();
    if (name === "ips") loadIps($("ips-search").value.trim());
  }

  function debounceSearch(key, fn, ms) {
    clearTimeout(searchTimers[key]);
    searchTimers[key] = setTimeout(fn, ms || 250);
  }

  async function loadStats() {
    $("stats-grid").innerHTML = skeletonHtml();
    try {
      const s = await api("/admin/api/stats");
      const users = num(s.users);
      const projects = num(s.projects);
      const servers = num(s.servers);
      const paired = num(s.paired_servers);
      const online = num(s.online_servers);
      const active = num(s.active_projects);
      const frozen = num(s.frozen_projects);
      const blocked = num(s.blocked_projects);
      const checks = num(s.checks);
      const reports = num(s.reports);
      const users7 = num(s.users_7d);
      const projects7 = num(s.projects_7d);
      const mix = [
        { n: active, color: "#8bc94e", label: "Активные" },
        { n: frozen, color: "#2b88f5", label: "Заморозка" },
        { n: blocked, color: "#ff5031", label: "Блок" },
      ];
      const mixTotal = active + frozen + blocked || 1;
      const flex = function (n) { return Math.max(n ? 1 : 0, Math.round((n / mixTotal) * 1000)); };
      const incidentMax = Math.max(checks, reports, 1);
      const sky = [
        { n: users, label: "Люди", color: "#fc7113" },
        { n: projects, label: "Проекты", color: "#fc7113" },
        { n: servers, label: "Серверы", color: "#f0b132" },
        { n: checks, label: "Проверки", color: "#8bc94e" },
        { n: reports, label: "Репорты", color: "#2b88f5" },
        { n: users7, label: "За 7 дней", color: "#c084fc" },
      ];
      const skyMax = Math.max.apply(null, sky.map(function (x) { return x.n; }).concat([1]));
      const html =
        '<div class="dash-hero">' +
          '<div class="dash-core">' +
            '<div class="core-wrap">' +
              '<svg class="core-svg" viewBox="0 0 240 240" aria-hidden="true">' +
                ticksSvg(120, 120, 108, 48) +
                ringSegments(120, 120, 86, 18, mix) +
                '<circle cx="120" cy="120" r="68" fill="none" stroke="rgba(252,113,19,.18)" stroke-width="1.5" stroke-dasharray="3 7"/>' +
              "</svg>" +
              '<div class="core-center"><div class="n" data-count="' + projects + '">0</div><div class="l">проектов</div></div>' +
            "</div>" +
            '<div class="core-legend">' + mix.map(function (p) {
              return '<span class="leg"><i style="background:' + p.color + '"></i>' + p.label + ' · <b data-count="' + p.n + '">0</b></span>';
            }).join("") + "</div>" +
          "</div>" +
          '<div class="dash-dials">' +
            '<div class="dial">' + gaugeSvg(users7, Math.max(users, 1), "#fc7113") +
              '<div class="n" data-count="' + users + '">0</div><div class="l">Пользователи</div>' +
              '<div class="sub">+' + fmtN(users7) + " за 7 дней</div></div>" +
            '<div class="dial">' + gaugeSvg(checks, Math.max(checks + reports, 1), "#8bc94e") +
              '<div class="n" data-count="' + checks + '">0</div><div class="l">Проверки</div>' +
              '<div class="sub">' + pct(checks, checks + reports) + "% от инцидентов</div></div>" +
            '<div class="dial">' + gaugeSvg(paired, Math.max(servers, 1), "#2b88f5") +
              '<div class="n" data-count="' + servers + '">0</div><div class="l">Серверы</div>' +
              '<div class="sub">' + fmtN(paired) + " в паре · " + fmtN(online) + " онлайн</div></div>" +
          "</div>" +
        "</div>" +
        '<div class="dash-rail">' +
          '<div class="rail-head"><h3>Состав проектов</h3><span>активные · заморозка · блок</span></div>' +
          '<div class="spectrum">' +
            '<b style="flex:' + flex(active) + ';background:#8bc94e"></b>' +
            '<b style="flex:' + flex(frozen) + ';background:#2b88f5"></b>' +
            '<b style="flex:' + flex(blocked) + ';background:#ff5031"></b>' +
          "</div>" +
          '<div class="spectrum-meta">' +
            '<div><div class="n" data-count="' + active + '">0</div><div class="l">Активны · ' + pct(active, mixTotal) + "%</div></div>" +
            '<div><div class="n" data-count="' + frozen + '">0</div><div class="l">Заморозка · ' + pct(frozen, mixTotal) + "%</div></div>" +
            '<div><div class="n" data-count="' + blocked + '">0</div><div class="l">Блок · ' + pct(blocked, mixTotal) + "%</div></div>" +
          "</div>" +
        "</div>" +
        '<div class="dash-split">' +
          '<div class="dash-sky">' +
            '<div class="rail-head"><h3>Масштаб</h3><span>сравнение объёмов</span></div>' +
            '<div class="skyline">' + sky.map(function (x, i) {
              var ratio = skyMax ? Math.sqrt(x.n / skyMax) : 0;
              var h = x.n ? Math.max(22, Math.round(ratio * 118)) : 8;
              return '<div class="sky-col"><div class="sky-bar" style="height:' + h + "px;--bar:" + x.color + ";animation-delay:" + (i * 70) + 'ms"></div><span>' + x.label + '<br><b data-count="' + x.n + '">0</b></span></div>';
            }).join("") + "</div>" +
          "</div>" +
          '<div class="dash-pulse">' +
            '<div class="rail-head"><h3>Нагрузка</h3><span>доля от базы</span></div>' +
            '<div class="pulse-row"><span class="l">В паре</span><div class="track"><i style="--w:' + pct(paired, servers) + '%;background:#2b88f5"></i></div><span class="n" data-count="' + pct(paired, servers) + '" data-suffix="%">0%</span></div>' +
            '<div class="pulse-row"><span class="l">Онлайн</span><div class="track"><i style="--w:' + pct(online, servers) + '%;background:#8bc94e"></i></div><span class="n" data-count="' + pct(online, servers) + '" data-suffix="%">0%</span></div>' +
            '<div class="pulse-row"><span class="l">Новые люди</span><div class="track"><i style="--w:' + pct(users7, users) + '%;background:#fc7113"></i></div><span class="n" data-count="' + pct(users7, users) + '" data-suffix="%">0%</span></div>' +
            '<div class="pulse-row"><span class="l">Новые проекты</span><div class="track"><i style="--w:' + pct(projects7, projects) + '%;background:#f0b132"></i></div><span class="n" data-count="' + pct(projects7, projects) + '" data-suffix="%">0%</span></div>' +
            '<div class="pulse-row"><span class="l">Репорты</span><div class="track"><i style="--w:' + pct(reports, incidentMax) + '%;background:#c084fc"></i></div><span class="n" data-count="' + reports + '">0</span></div>' +
          "</div>" +
        "</div>";
      $("stats-grid").innerHTML = html;
      replayMotion($("stats-grid"));
      bindDashMotion($("stats-grid"));
    } catch (e) {
      $("stats-grid").innerHTML = '<div class="empty">' + esc(e.message || "Нет данных") + "</div>";
    }
  }

  async function loadUsers(q) {
    $("users-table").innerHTML = skeletonHtml();
    try {
    const data = await api(apiQ("/admin/api/users", q));
    const rows = data.users || [];
    $("users-table").innerHTML = rows.length ? (
      "<table><thead><tr><th>ID</th><th>Email</th><th>Имя</th><th>Проектов</th><th>Блокировка</th><th>Регистрация</th><th></th></tr></thead><tbody>" +
      rows.map(function (u) {
        return "<tr><td>" + u.id + "</td><td>" + esc(u.email) + "</td><td>" + esc(u.name) + "</td><td>" +
          u.projects_count + "</td><td>" +
          (u.account_blocked ? '<span class="status-badge blocked">🔒 BLOCKED</span>' : (u.projects_blocked ? '<span class="status-badge blocked">🔒 Новые проекты</span>' : "—")) +
          "</td><td>" + esc(u.created_at_fmt || "") +
          '</td><td><button class="btn-primary" data-user="' + u.id + '">Открыть</button></td></tr>';
      }).join("") + "</tbody></table>"
    ) : '<div class="empty">Пользователи не найдены</div>';
    $("users-table").querySelectorAll("button[data-user]").forEach(function (btn) {
      btn.onclick = function () { openUser(Number(btn.dataset.user)); };
    });
    } catch (e) {
      $("users-table").innerHTML = '<div class="empty">' + esc(e.message || "Пользователи не найдены") + "</div>";
    }
  }

  async function fetchProject(pid) {
    pid = Number(pid);
    if (!pid) throw new Error("Некорректный ID проекта");
    try {
      const p = await api("/admin/api/projects/" + pid);
      projectsCache[pid] = p;
      return p;
    } catch (err) {
      if (projectsCache[pid]) return projectsCache[pid];
      try {
        const data = await api("/admin/api/projects?q=" + pid);
        const found = (data.projects || []).find(function (p) { return Number(p.id) === pid; });
        if (found) {
          projectsCache[pid] = found;
          return found;
        }
      } catch (_) {}
      throw new Error(err.message || ("Проект #" + pid + " не найден"));
    }
  }

  async function loadProjects(q) {
    $("projects-table").innerHTML = skeletonHtml();
    try {
    const data = await api(apiQ("/admin/api/projects", q));
    const rows = data.projects || [];
    rows.forEach(function (p) { projectsCache[p.id] = p; });
    $("projects-table").innerHTML = rows.length ? (
      "<table><thead><tr><th>ID</th><th>Название</th><th>Владелец</th><th>Тариф</th><th>Баланс</th><th>Подписка</th><th>IP:PORT</th><th>Статус</th><th></th></tr></thead><tbody>" +
      rows.map(function (p) {
        return "<tr><td>" + p.id + "</td><td>" + esc(p.name) + "<br><small class='hint'>" + esc(p.domain) + "</small></td><td>" +
          esc(p.owner_email) + "<br><small>#" + p.owner_user_id + "</small></td><td>" + esc(planLabel(p.plan)) +
          "</td><td>" + rub(p.balance) + "</td><td><small>" + esc(p.paid_until_fmt || p.trial_ends_fmt || "—") +
          (p.is_trial && p.trial_ends_fmt ? " · пробный" : "") +
          "</small></td><td>" + esc(p.server_ip || "—") + "</td><td>" + statusBadge(p) +
          '</td><td><button class="secondary manage-btn" data-manage="' + p.id + '">Управление</button></td></tr>';
      }).join("") + "</tbody></table>"
    ) : '<div class="empty">Проекты не найдены</div>';
    $("projects-table").querySelectorAll("button[data-manage]").forEach(function (btn) {
      btn.onclick = function () { openProjectManage(Number(btn.dataset.manage)); };
    });
    } catch (e) {
      $("projects-table").innerHTML = '<div class="empty">' + esc(e.message || "Проекты не найдены") + "</div>";
    }
  }

  async function loadIps(q) {
    $("ips-table").innerHTML = skeletonHtml();
    try {
    const data = await api(apiQ("/admin/api/server-ips", q));
    const rows = data.items || data.data || data.results || [];
    $("ips-table").innerHTML = rows.length ? (
      "<table><thead><tr><th>Название</th><th>Адрес</th><th>IP</th><th>Порт</th><th>Статус</th><th>Проект</th><th>Пользователь</th><th>IP заблокирован</th><th></th></tr></thead><tbody>" +
      rows.map(function (r) {
        const addr = r.endpoint || r.address || (r.server_ip && r.port ? (r.server_ip + ":" + r.port) : (r.server_ip || ""));
        const st = r.connected ? "online" : (r.status || "offline");
        return "<tr><td>" + esc(r.name || r.server_name || "—") + "</td><td><code>" + esc(addr || "—") +
          "</code></td><td><code>" + esc(r.ip || r.server_ip || "—") + "</code></td><td>" + esc(r.port || "—") +
          "</td><td>" + (st === "online" ? '<span class="status-badge ok">online</span>' : '<span class="status-badge">offline</span>') +
          "</td><td>" + esc(r.project_name || "—") +
          (r.project_id ? " (#" + r.project_id + ")" : "") + "</td><td>" + esc(r.owner_email || "—") +
          (r.owner_user_id ? "<br><small>#" + r.owner_user_id + "</small>" : "") +
          "</td><td>" + (r.ip_blocked ? "Да" : "Нет") +
          '</td><td><div class="actions">' +
          (r.ip_blocked
            ? '<button class="ok" data-ip-act="unblock" data-ip="' + escAttr(r.ip || r.server_ip) + '">Разблок IP</button>'
            : '<button class="danger" data-ip-act="block" data-ip="' + escAttr(r.ip || r.server_ip) + '">Блок IP</button>') +
          (r.project_id ? '<button class="secondary" data-manage="' + r.project_id + '">Проект</button>' : "") +
          "</div></td></tr>";
      }).join("") + "</tbody></table>"
    ) : '<div class="empty">IP не найдены</div>';
    $("ips-table").querySelectorAll("button[data-ip-act]").forEach(function (btn) {
      btn.onclick = async function () {
        const ip = btn.dataset.ip;
        const act = btn.dataset.ipAct;
        if (act === "block") {
          const ok = await confirmDialog("Блокировка IP", "Заблокировать IP " + ip + " глобально?");
          if (!ok) return;
        }
        try {
          await api("/admin/api/server-ips/" + encodeURIComponent(ip) + "/" + act, {
            method: "POST",
            body: JSON.stringify({ reason: "admin panel" }),
          });
          toast(act === "block" ? "IP заблокирован" : "IP разблокирован");
          loadIps($("ips-search").value.trim());
        } catch (e) { toast(e.message, true); }
      };
    });
    $("ips-table").querySelectorAll("button[data-manage]").forEach(function (btn) {
      btn.onclick = function () { openProjectManage(Number(btn.dataset.manage)); };
    });
    } catch (e) {
      $("ips-table").innerHTML = '<div class="empty">' + esc(e.message || "Не удалось загрузить IP") + "</div>";
    }
  }

  async function openUser(uid) {
    $("user-modal-body").innerHTML = skeletonHtml();
    $("user-modal").classList.remove("hidden");
    const u = await api("/admin/api/users/" + uid);
    $("user-modal").dataset.uid = String(uid);
    $("user-modal-title").textContent = "Пользователь #" + u.id;

    $("user-modal-body").innerHTML =
      '<div class="info-grid">' +
      '<div class="info-card"><div class="label">Email</div><div class="value">' + esc(u.email) + '</div></div>' +
      '<div class="info-card"><div class="label">Имя</div><div class="value">' + esc(u.name) + '</div></div>' +
      '<div class="info-card"><div class="label">Регистрация</div><div class="value">' + esc(u.created_at_fmt || "—") + '</div></div>' +
      '<div class="info-card"><div class="label">Статус аккаунта</div><div class="value">' +
      (u.account_blocked ? '<span class="status-badge blocked">🔒 BLOCKED</span>' : "ACTIVE") + '</div></div></div>' +

      '<div class="section-card"><h4>Блокировка</h4>' +
      (u.account_blocked
        ? '<button class="secondary" id="user-unblock-btn">Разблокировать аккаунт</button>'
        : '<button class="danger" id="user-block-btn">Заблокировать аккаунт</button>') +
      '<p class="hint">Заблокированный пользователь не может входить, создавать проекты и пользоваться API.</p></div>' +

      '<div class="section-card"><h4>Проекты пользователя</h4>' +
      (u.projects && u.projects.length ? u.projects.map(function (p) {
        return '<div class="project-row"><div><strong>#' + p.id + " " + esc(p.name) + '</strong><br>' +
          statusBadge(p) + ' · ' + rub(p.balance) + ' · ' + esc(planLabel(p.plan)) +
          (p.paid_until_fmt ? " · до " + esc(p.paid_until_fmt) : (p.trial_ends_fmt ? " · тест до " + esc(p.trial_ends_fmt) : "")) +
          '</div><button class="secondary" data-open-project="' + p.id + '">Управление</button></div>';
      }).join("") : '<p class="empty">Нет проектов</p>') + '</div>' +

      '<div class="section-card"><h4>IP адреса пользователя</h4>' +
      (u.ips && u.ips.length ? (
        "<table><tr><th>IP</th><th>Первый вход</th><th>Последний</th><th>Хитов</th><th></th></tr>" +
        u.ips.map(function (ip) {
          return "<tr><td>" + esc(ip.ip) + (ip.ip_blocked ? ' <span class="status-badge blocked">blocked</span>' : "") +
            "</td><td>" + esc(ip.first_seen_fmt) + "</td><td>" + esc(ip.last_seen_fmt) + "</td><td>" + ip.hits +
            '</td><td>' + (ip.ip_blocked
              ? '<button class="secondary" data-user-ip-act="unblock" data-user-ip="' + escAttr(ip.ip) + '">Разблок. IP</button>'
              : '<button class="danger" data-user-ip-act="block" data-user-ip="' + escAttr(ip.ip) + '">Блок. IP</button>') +
            "</td></tr>";
        }).join("") + "</table>"
      ) : "<p class='empty'>Нет данных</p>") + '</div>' +

      '<div class="section-card"><h4>Редактирование</h4>' +
      '<label>Никнейм</label><input id="edit-name" value="' + escAttr(u.name) + '">' +
      '<label>Email</label><input id="edit-email" value="' + escAttr(u.email) + '">' +
      '<label>Новый пароль</label><input id="edit-password" type="password" placeholder="оставьте пустым">' +
      '</div>';

    $("user-modal-body").querySelectorAll("button[data-open-project]").forEach(function (btn) {
      btn.onclick = function () { openProjectManage(Number(btn.dataset.openProject)); };
    });
    const blockBtn = $("user-block-btn");
    if (blockBtn) {
      blockBtn.onclick = async function () {
        const ok = await confirmDialog("Блокировка", "Заблокировать пользователя #" + uid + "?");
        if (!ok) return;
        try {
          await api("/admin/api/users/" + uid + "/block", { method: "POST", body: JSON.stringify({ reason: "admin panel" }) });
          toast("Пользователь заблокирован");
          openUser(uid);
          loadUsers($("users-search").value.trim());
        } catch (e) { toast(e.message, true); }
      };
    }
    const unblockBtn = $("user-unblock-btn");
    if (unblockBtn) {
      unblockBtn.onclick = async function () {
        if (unblockBtn.dataset.loading === "1") return;
        unblockBtn.dataset.loading = "1";
        const prev = unblockBtn.textContent;
        unblockBtn.disabled = true;
        unblockBtn.textContent = "Разблокировка...";
        try {
          await api("/admin/api/users/" + uid + "/unblock", { method: "POST", body: "{}" });
          toast("Пользователь разблокирован");
          // Optimistic UI — don't freeze on full modal rebuild
          const statusCard = $("user-modal-body").querySelector(".info-card .value");
          const cards = $("user-modal-body").querySelectorAll(".info-card");
          cards.forEach(function (card) {
            if (/Статус аккаунта/i.test(String(card.textContent || ""))) {
              const v = card.querySelector(".value");
              if (v) v.innerHTML = "ACTIVE";
            }
          });
          const blockWrap = unblockBtn.parentElement;
          if (blockWrap) {
            unblockBtn.outerHTML = '<button class="danger" id="user-block-btn">Заблокировать аккаунт</button>';
            const nb = $("user-block-btn");
            if (nb) {
              nb.onclick = async function () {
                const ok = await confirmDialog("Блокировка", "Заблокировать пользователя #" + uid + "?");
                if (!ok) return;
                try {
                  await api("/admin/api/users/" + uid + "/block", { method: "POST", body: JSON.stringify({ reason: "admin panel" }) });
                  toast("Пользователь заблокирован");
                  openUser(uid);
                  loadUsers($("users-search").value.trim());
                } catch (e) { toast(e.message, true); }
              };
            }
          }
          // Refresh lists in background — do not await before unlocking UI
          Promise.resolve().then(function () {
            loadUsers($("users-search").value.trim());
          });
        } catch (e) {
          toast(e.message, true);
          unblockBtn.disabled = false;
          unblockBtn.textContent = prev;
          unblockBtn.dataset.loading = "0";
        }
      };
    }
    $("user-modal-body").querySelectorAll("button[data-user-ip]").forEach(function (btn) {
      btn.onclick = async function () {
        const ip = btn.dataset.userIp;
        const act = btn.dataset.userIpAct;
        if (act === "block") {
          const ok = await confirmDialog("Блокировка IP пользователя", "Заблокировать IP " + ip + "? Новые аккаунты с этим IP будут BLOCKED.");
          if (!ok) return;
        }
        try {
          await api("/admin/api/user-ips/" + encodeURIComponent(ip) + "/" + act, {
            method: "POST",
            body: JSON.stringify({ reason: "admin panel" }),
          });
          toast(act === "block" ? "User IP заблокирован" : "User IP разблокирован");
          openUser(uid);
        } catch (e) { toast(e.message, true); }
      };
    });
  }

  async function saveUserModal() {
    const uid = $("user-modal").dataset.uid;
    const name = $("edit-name").value.trim();
    const email = $("edit-email").value.trim();
    const password = $("edit-password").value;
    try {
      const body = {};
      if (name) body.name = name;
      if (email) body.email = email;
      if (password) body.password = password;
      await api("/admin/api/users/" + uid, { method: "PUT", body: JSON.stringify(body) });
      toast("Пользователь обновлён");
      $("user-modal").classList.add("hidden");
      loadUsers($("users-search").value.trim());
    } catch (e) { toast(e.message, true); }
  }

  async function deleteUserModal() {
    const uid = $("user-modal").dataset.uid;
    const ok = await confirmDialog("Удаление пользователя", "Удалить пользователя #" + uid + "? Это действие необратимо.");
    if (!ok) return;
    try {
      await api("/admin/api/users/" + uid, { method: "DELETE" });
      toast("Пользователь удалён");
      $("user-modal").classList.add("hidden");
      loadUsers($("users-search").value.trim());
      loadStats();
    } catch (e) { toast(e.message, true); }
  }

  function renderProjectModal(p) {
    manageProject = p;
    $("project-modal-title").textContent = "Проект #" + p.id + " — " + (p.name || "");
    const blocked = p.status === "blocked";
    const canUnfreeze = !blocked && (p.status === "frozen" || p.admin_frozen);
    const subEnd = p.paid_until_fmt || p.trial_ends_fmt || "—";

    $("project-modal-body").innerHTML =
      '<div class="info-grid">' +
      '<div class="info-card"><div class="label">Статус</div><div class="value">' + statusBadge(p) + '</div></div>' +
      '<div class="info-card"><div class="label">Тариф</div><div class="value">' + esc(planLabel(p.plan)) + '</div></div>' +
      '<div class="info-card"><div class="label">Баланс проекта</div><div class="value">' + rub(p.balance) + '</div></div>' +
      '<div class="info-card"><div class="label">Подписка до</div><div class="value">' + esc(subEnd) + '</div></div>' +
      '<div class="info-card"><div class="label">Владелец</div><div class="value">' + esc(p.owner_email) + ' #' + p.owner_user_id + '</div></div>' +
      '<div class="info-card"><div class="label">IP:PORT сервера</div><div class="value">' + esc(p.server_ip || p.server_endpoint || "—") + '</div></div>' +
      '</div>' +

      '<div class="section-card inline-form">' +
      '<h4>Название проекта</h4>' +
      '<label>Текущее название</label><input id="proj-edit-name" value="' + escAttr(p.name) + '">' +
      '<button class="secondary" id="proj-save-name">Сохранить название</button>' +
      '</div>' +

      '<div class="tabs">' +
      '<button class="tab-btn active" data-tab="balance">Баланс</button>' +
      '<button class="tab-btn" data-tab="subscription">Подписка</button>' +
      '<button class="tab-btn" data-tab="actions">Действия</button>' +
      '</div>' +

      '<div class="tab-panel" data-tab-panel="balance">' +
      '<div class="section-card inline-form">' +
      '<h4>Баланс проекта #' + p.id + '</h4>' +
      '<p class="hint">Текущий баланс: <strong>' + rub(p.balance) + '</strong></p>' +
      '<label>Сумма (в рублях)</label><input id="proj-balance-amount" type="number" step="0.01" placeholder="100">' +
      '<label>Причина</label><input id="proj-balance-reason" placeholder="admin adjustment">' +
      '<div class="inline-actions">' +
      '<button class="ok" id="proj-balance-add">+ Начислить</button>' +
      '<button class="danger" id="proj-balance-sub">− Списать</button>' +
      '</div></div></div>' +

      '<div class="tab-panel hidden" data-tab-panel="subscription">' +
      '<div class="section-card inline-form">' +
      '<h4>Подписка проекта</h4>' +
      '<p class="hint">Статус: ' + statusBadge(p) + ' · Тариф: ' + esc(planLabel(p.plan)) + ' · До: ' + esc(subEnd) + '</p>' +
      '<label>Тариф</label><select id="proj-sub-plan"><option value="plus">Plus</option><option value="enterprise">Enterprise</option><option value="base">Base (тест)</option></select>' +
      '<label>Срок (дней от текущего момента)</label><input id="proj-sub-days" type="number" min="1" max="3650" value="30">' +
      '<p class="hint">Дата окончания = сейчас + указанное количество дней. Сохраняется в paid_until.</p>' +
      '<button class="btn-primary" id="proj-sub-grant">Выдать подписку</button>' +
      (blocked ? '<p class="hint">Проект заблокирован — подписка продлится, но блокировка останется до «Разблокировать».</p>' : '') +
      '</div></div>' +

      '<div class="tab-panel hidden" data-tab-panel="actions">' +
      '<div class="section-card">' +
      '<h4>Действия администратора</h4>' +
      '<div class="inline-actions" style="flex-direction:column;align-items:stretch">' +
      (canUnfreeze ? '<button class="secondary" data-proj-act="unfreeze">❄️ Разморозить</button>' : '') +
      (!blocked ? '<button class="secondary" data-proj-act="freeze">❄️ Заморозить</button>' : '') +
      (!blocked ? '<button class="danger" data-proj-act="block">🔒 Заблокировать проект</button>' : '<button class="ok" data-proj-act="unblock">🔓 Разблокировать проект</button>') +
      '<button class="danger" data-proj-act="delete">🗑 Удалить проект</button>' +
      '</div></div></div>';

    $("project-modal-body").querySelectorAll(".tab-btn").forEach(function (btn) {
      btn.onclick = function () {
        $("project-modal-body").querySelectorAll(".tab-btn").forEach(function (b) { b.classList.remove("active"); });
        btn.classList.add("active");
        $("project-modal-body").querySelectorAll(".tab-panel").forEach(function (panel) {
          panel.classList.toggle("hidden", panel.dataset.tabPanel !== btn.dataset.tab);
        });
      };
    });

    var balAdd = $("proj-balance-add");
    var balSub = $("proj-balance-sub");
    var subGrant = $("proj-sub-grant");
    var subPlan = $("proj-sub-plan");
    if (balAdd) balAdd.onclick = function () { changeProjectBalance(1); };
    if (balSub) balSub.onclick = function () { changeProjectBalance(-1); };
    if (subGrant) subGrant.onclick = grantProjectSubscription;
    $("project-modal-body").querySelectorAll("[data-proj-act]").forEach(function (btn) {
      btn.onclick = function () { projectAction(btn.dataset.projAct); };
    });
    if (subPlan) {
      subPlan.onchange = function () {
        if (subPlan.value === "base") $("proj-sub-days").value = "7";
        else if (Number($("proj-sub-days").value) === 7) $("proj-sub-days").value = "30";
      };
    }
    var saveName = $("proj-save-name");
    if (saveName) saveName.onclick = saveProjectName;
  }

  async function saveProjectName() {
    if (!manageProject) return;
    const name = $("proj-edit-name").value.trim();
    if (!name) { toast("Укажите название", true); return; }
    try {
      await api("/admin/api/projects/" + manageProject.id, {
        method: "PUT",
        body: JSON.stringify({ name: name }),
      });
      toast("Название обновлено");
      var fresh = await fetchProject(manageProject.id);
      renderProjectModal(fresh);
      loadProjects($("projects-search").value.trim());
    } catch (e) { toast(e.message, true); }
  }

  async function openProjectManage(pid) {
    var modal = $("project-modal");
    var body = $("project-modal-body");
    if (!modal || !body) {
      toast("Обновите страницу админки (Ctrl+F5)", true);
      return;
    }
    modal.classList.remove("hidden");
    body.innerHTML = skeletonHtml();
    try {
      var p = await fetchProject(pid);
      renderProjectModal(p);
    } catch (e) {
      toast(e.message || "Не удалось загрузить проект", true);
      modal.classList.add("hidden");
    }
  }

  async function changeProjectBalance(sign) {
    if (!manageProject) return;
    const rubles = parseFloat($("proj-balance-amount").value);
    if (isNaN(rubles) || rubles <= 0) { toast("Укажите сумму", true); return; }
    const amount = Math.round(rubles * 100) * sign;
    const reason = $("proj-balance-reason").value.trim() || "admin adjustment";
    try {
      await api("/admin/api/project-balance", {
        method: "POST",
        body: JSON.stringify({
          project_id: manageProject.id,
          projectId: manageProject.id,
          amount: amount,
          comment: reason,
        }),
      });
      toast(sign > 0 ? "Баланс начислен" : "Баланс списан");
      var fresh = await fetchProject(manageProject.id);
      renderProjectModal(fresh);
      loadProjects($("projects-search").value.trim());
    } catch (e) { toast(e.message, true); }
  }

  async function grantProjectSubscription() {
    if (!manageProject) return;
    const plan = $("proj-sub-plan").value;
    const days = parseInt($("proj-sub-days").value, 10);
    if (!days || days < 1) { toast("Укажите срок в днях", true); return; }
    try {
      const out = await api("/admin/api/subscription", {
        method: "POST",
        body: JSON.stringify({ project_id: manageProject.id, plan: plan, days: days }),
      });
      toast("Подписка выдана до " + (out.paid_until_fmt || out.trial_ends_fmt || "—"));
      var fresh = await fetchProject(manageProject.id);
      renderProjectModal(fresh);
      loadProjects($("projects-search").value.trim());
      loadStats();
    } catch (e) { toast(e.message, true); }
  }

  async function projectAction(action) {
    if (!manageProject) return;
    const pid = manageProject.id;
    const labels = {
      freeze: ["Заморозка", "Заморозить проект #" + pid + "?"],
      unfreeze: ["Разморозка", "Разморозить проект #" + pid + "?"],
      block: ["Блокировка", "Заблокировать проект #" + pid + "? Новые проекты этого пользователя также будут блокироваться."],
      unblock: ["Разблокировка", "Разблокировать проект #" + pid + " и разрешить новые проекты?"],
      delete: ["Удаление", "Удалить проект #" + pid + "? Это действие необратимо."],
    };
    if (labels[action]) {
      const ok = await confirmDialog(labels[action][0], labels[action][1]);
      if (!ok) return;
    }
    try {
      if (action === "delete") {
        await api("/admin/api/projects/" + pid, { method: "DELETE" });
        toast("Проект удалён");
        $("project-modal").classList.add("hidden");
        loadProjects($("projects-search").value.trim());
        loadStats();
      } else {
        const actBtn = document.querySelector('[data-proj-act="' + action + '"]');
        if (actBtn) {
          actBtn.disabled = true;
          actBtn.dataset._prev = actBtn.textContent;
          actBtn.textContent = "...";
        }
        await api("/admin/api/projects/" + pid + "/" + action, { method: "POST", body: "{}" });
        toast("Готово");
        var fresh = await fetchProject(pid);
        renderProjectModal(fresh);
        // Refresh tables async — do not block modal update
        setTimeout(function () {
          loadProjects($("projects-search").value.trim());
          loadStats();
        }, 0);
      }
    } catch (e) {
      toast(e.message, true);
      const actBtn = document.querySelector('[data-proj-act="' + action + '"]');
      if (actBtn) {
        actBtn.disabled = false;
        if (actBtn.dataset._prev) actBtn.textContent = actBtn.dataset._prev;
      }
    }
  }

  document.querySelectorAll(".nav-btn[data-page]").forEach(function (btn) {
    btn.onclick = function () { setPage(btn.dataset.page); };
  });
  document.querySelectorAll("#audit-tabs .tab-btn").forEach(function (btn) {
    btn.onclick = function () {
      auditTab = btn.dataset.audit || "admin";
      document.querySelectorAll("#audit-tabs .tab-btn").forEach(function (b) {
        b.classList.toggle("active", b === btn);
      });
      loadAudit();
    };
  });

  $("login-form").onsubmit = async function (e) {
    e.preventDefault();
    try {
      await login($("login-email").value.trim(), $("login-password").value);
      try { me = await api("/admin/api/me") || me; } catch (_) {}
      showApp();
      setPage("dashboard");
    } catch (err) {
      toast(err.message || "Ошибка входа", true);
    }
  };

  $("logout-btn").onclick = function () {
    localStorage.removeItem(TOKEN_KEY);
    showLogin();
  };

  $("save-user-btn").onclick = saveUserModal;
  $("delete-user-btn").onclick = deleteUserModal;
  $("close-user-modal").onclick = function () { $("user-modal").classList.add("hidden"); };
  $("close-project-modal").onclick = function () { $("project-modal").classList.add("hidden"); };

  $("confirm-cancel").onclick = function () {
    $("confirm-modal").classList.add("hidden");
    if (confirmCb) confirmCb(false);
    confirmCb = null;
  };
  $("confirm-ok").onclick = function () {
    $("confirm-modal").classList.add("hidden");
    if (confirmCb) confirmCb(true);
    confirmCb = null;
  };

  $("users-search").oninput = function () {
    debounceSearch("users", function () { loadUsers($("users-search").value.trim()); });
  };
  async function loadAdmins() {
    $("admins-table").innerHTML = skeletonHtml();
    try {
      const data = await api("/admin/api/admins");
      me.is_owner = !!(data.is_owner);
      const rows = data.admins || [];
      $("admins-toolbar").innerHTML = me.is_owner
        ? '<div class="inline-form" style="max-width:420px"><label>Добавить администратора по email</label><div class="inline-actions"><input id="admin-email" type="email" placeholder="user@email.com"><button class="btn-primary" id="admin-add-btn">Добавить</button></div><p class="hint">Пользователь должен уже быть зарегистрирован на сайте. Главный администратор: pcigru@gmail.com</p></div>'
        : '<p class="hint">Администраторы имеют те же права, что и главный администратор, кроме управления списком администраторов.</p>';
      $("admins-table").innerHTML = rows.length ? (
        "<table><thead><tr><th>ID</th><th class=\"presence-col\"></th><th>Email</th><th>Имя</th><th>Роль</th><th></th></tr></thead><tbody>" +
        rows.map(function (a) {
          const canDel = me.is_owner && !a.is_owner;
          const on = !!a.online;
          return "<tr><td>" + a.id + '</td><td class="presence-col"><span class="presence' + (on ? " on" : "") + '" data-admin="' + a.id + '" title="' + (on ? "Онлайн" : "Оффлайн") + '"></span></td><td>' + esc(a.email) + "</td><td>" + esc(a.name) + "</td><td>" +
            esc(a.role_label || a.role) + "</td><td>" +
            (canDel ? '<button class="danger" data-del-admin="' + a.id + '">Удалить</button>' : "—") +
            "</td></tr>";
        }).join("") + "</tbody></table>"
      ) : '<div class="empty">Администраторы не найдены</div>';
      const addBtn = $("admin-add-btn");
      if (addBtn) {
        addBtn.onclick = async function () {
          try {
            await api("/admin/api/admins", { method: "POST", body: JSON.stringify({ email: $("admin-email").value.trim() }) });
            toast("Администратор добавлен");
            loadAdmins();
          } catch (err) {
            toast(err.message || "Ошибка", true);
          }
        };
      }
      $("admins-table").querySelectorAll("button[data-del-admin]").forEach(function (btn) {
        btn.onclick = async function () {
          const ok = await confirmDialog("Удаление", "Снять права администратора?");
          if (!ok) return;
          try {
            await api("/admin/api/admins/" + btn.dataset.delAdmin, { method: "DELETE" });
            toast("Администратор удалён");
            loadAdmins();
          } catch (err) {
            toast(err.message || "Ошибка", true);
          }
        };
      });
    } catch (e) {
      $("admins-toolbar").innerHTML = "";
      $("admins-table").innerHTML = '<div class="empty">' + esc(e.message || "Не удалось загрузить администраторов") + "</div>";
    }
  }

  function auditEventLabel(ev) {
    const map = {
      "admin.platform.add": "Добавил администратора",
      "admin.platform.remove": "Удалил администратора",
      "admin.platform.role": "Изменил роль администратора",
      "admin.user.update": "Изменил пользователя",
      "admin.user.delete": "Удалил пользователя",
      "admin.user.block": "Заблокировал пользователя",
      "admin.user.unblock": "Разблокировал пользователя",
      "admin.project.update": "Изменил проект",
      "admin.project.delete": "Удалил проект",
      "admin.project.freeze": "Заморозил проект",
      "admin.project.unfreeze": "Разморозил проект",
      "admin.project.block": "Заблокировал проект",
      "admin.project.unblock": "Разблокировал проект",
      "admin.project.balance": "Изменил баланс",
      "admin.project.subscription": "Выдал подписку",
      "settings.edit": "Изменил настройки",
      "webhook.save": "Изменил вебхуки",
      "mute.create": "Выдал мут",
      "mute.delete": "Снял мут",
      "ban.create": "Выдал бан",
      "ban.delete": "Снял бан",
      "staff_edit": "Изменил сотрудника",
      "staff_delete": "Удалил сотрудника",
      "project.freeze": "Заморозка проекта",
      "tariff.discard_trial": "Завершил пробный период",
    };
    return map[ev] || ev;
  }

  async function loadAudit() {
    $("audit-table").innerHTML = skeletonHtml();
    try {
      const pid = ($("audit-project") && $("audit-project").value) || "";
      const qs = "?category=" + encodeURIComponent(auditTab) + (pid ? "&project_id=" + encodeURIComponent(pid) : "");
      const data = await api("/admin/api/audit" + qs);
      auditProjects = data.projects || auditProjects;
      if (auditTab === "projects") {
        $("audit-toolbar").innerHTML = '<label>Проект</label><select id="audit-project" style="max-width:280px"><option value="">Все проекты</option>' +
          auditProjects.map(function (p) {
            return '<option value="' + p.id + '"' + (String(p.id) === String(pid) ? " selected" : "") + ">#" + p.id + " " + esc(p.name) + "</option>";
          }).join("") + "</select>";
        $("audit-project").onchange = function () { loadAudit(); };
      } else {
        $("audit-toolbar").innerHTML = "";
      }
      const rows = data.items || [];
      $("audit-table").innerHTML = rows.length ? (
        "<table><thead><tr><th>Когда</th><th>Кто</th><th>Действие</th><th>Объект</th><th>Проект</th></tr></thead><tbody>" +
        rows.map(function (r) {
          return "<tr><td><small>" + esc(r.created_at ? new Date(r.created_at).toLocaleString("ru-RU") : "") +
            "</small></td><td>" + esc(r.actor_name || r.actor_email || r.actor) +
            "</td><td>" + esc(auditEventLabel(r.event)) +
            "</td><td>" + esc(r.object || "") +
            "</td><td>" + (r.project_id ? ("#" + r.project_id) : "—") + "</td></tr>";
        }).join("") + "</tbody></table>"
      ) : '<div class="empty">Записей нет</div>';
    } catch (e) {
      $("audit-toolbar").innerHTML = "";
      $("audit-table").innerHTML = '<div class="empty">' + esc(e.message || "Не удалось загрузить журнал") + "</div>";
    }
  }

  let txProjectId = "";
  async function loadTransactions() {
    try {
      const projectsRes = await api("/admin/api/projects");
      const projects = projectsRes.projects || [];
      const pid = txProjectId || "";
      $("tx-toolbar").innerHTML = '<label>Проект</label><select id="tx-project" style="max-width:320px"><option value="">Все проекты</option>' +
        projects.map(function (p) {
          return '<option value="' + p.id + '"' + (String(p.id) === String(pid) ? " selected" : "") + ">#" + p.id + " " + esc(p.name || "") + "</option>";
        }).join("") + "</select>";
      $("tx-project").onchange = function () {
        txProjectId = this.value;
        loadTransactions();
      };
      $("tx-table").innerHTML = skeletonHtml();
      const data = await api("/admin/api/transactions" + (pid ? ("?project_id=" + encodeURIComponent(pid)) : ""));
      const rows = data.items || data.data || data.results || [];
      if (!rows.length) {
        $("tx-table").innerHTML = '<div class="empty">Транзакций нет</div>';
        return;
      }
      $("tx-table").innerHTML = "<table><thead><tr><th>ID</th><th>Проект</th><th>Тип</th><th>Сумма</th><th>Валюта</th><th>Статус</th><th>Пользователь</th><th>Дата</th><th>Дополнительно</th></tr></thead><tbody>" +
        rows.map(function (r) {
          const extra = r.extra && typeof r.extra === "object" ? JSON.stringify(r.extra) : (r.comment || r.reason || "");
          const rawAmt = Number(r.amount || 0);
          const amt = (Math.abs(rawAmt) >= 1000 ? (rawAmt / 100) : rawAmt).toFixed(2);
          return "<tr><td>" + esc(r.id) + "</td><td>" + esc(r.project_name || r.project || ("#" + (r.project_id || ""))) +
            "</td><td>" + esc(r.type || r.reason || "") +
            "</td><td>" + esc(amt) +
            "</td><td>" + esc(r.currency || "RUB") +
            "</td><td>" + esc(r.status || "success") +
            "</td><td>" + esc(r.actor_name || "—") +
            "</td><td><small>" + esc(r.created_at ? new Date(r.created_at).toLocaleString("ru-RU") : "") + "</small></td>" +
            "<td><small>" + esc(extra).slice(0, 180) + "</small></td></tr>";
        }).join("") + "</tbody></table>";
    } catch (e) {
      $("tx-table").innerHTML = '<div class="empty">' + esc(e.message || "Не удалось загрузить транзакции") + "</div>";
    }
  }

  let chatTimer = null;
  let chatLastId = 0;
  let chatSeenId = Number(localStorage.getItem("admin_chat_seen") || 0) || 0;
  let chatPending = null;
  let chatReplyTo = null;
  let chatRec = null;
  let chatRecChunks = [];
  let chatRecStream = null;
  let chatRecStarted = 0;
  let chatRecTick = null;
  let chatRecSend = false;
  let chatReady = false;
  let chatAdmins = [];
  let chatMentionList = [];
  let chatMentionIdx = 0;
  let chatSoundOn = localStorage.getItem("admin_chat_sound") !== "0";
  let chatAudioCtx = null;
  let chatSoundPrimed = false;
  let chatSoundLast = chatSeenId;

  function chatOpen() {
    return !!document.querySelector('.page[data-page="chat"]:not(.hidden)');
  }

  function stopChatPoll() {
    clearInterval(chatTimer);
    chatTimer = null;
  }

  function fmtChatTime(ms) {
    if (!ms) return "";
    return new Date(ms).toLocaleString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  }

  function fmtDur(ms) {
    var s = Math.max(0, Math.round(Number(ms || 0) / 1000));
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }

  function initials(name, email) {
    var s = String(name || email || "A").trim();
    return (s.charAt(0) || "A").toUpperCase();
  }

  function setChatBadge(n) {
    var el = $("chat-badge");
    if (!el) return;
    if (n > 0) {
      el.textContent = n > 99 ? "99+" : String(n);
      el.classList.remove("hidden");
    } else {
      el.classList.add("hidden");
    }
  }

  function chatHandle(a) {
    var name = String((a && (a.name || a.user_name)) || "").trim();
    if (name) return name.replace(/\s+/g, "");
    var email = String((a && (a.email || a.user_email)) || "");
    return email.split("@")[0] || "";
  }

  function mentionsMe(m) {
    var myId = Number(me.id || 0);
    if (!myId) return false;
    var ids = m && m.mentions;
    if (Array.isArray(ids) && ids.some(function (id) { return Number(id) === myId; })) return true;
    var handle = chatHandle(me);
    if (!handle) return false;
    var re = new RegExp("(^|\\s)@" + handle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "(?=\\s|$|[.,!?])", "i");
    return re.test(String((m && m.text) || ""));
  }

  function formatChatText(text) {
    var s = String(text || "");
    var re = /(@[A-Za-zА-Яа-яЁё0-9_.-]{2,40})/g;
    var out = "";
    var last = 0;
    var m;
    while ((m = re.exec(s))) {
      out += esc(s.slice(last, m.index));
      out += '<span class="chat-tag">' + esc(m[1]) + "</span>";
      last = m.index + m[1].length;
    }
    out += esc(s.slice(last));
    return out;
  }

  function collectMentions(text) {
    var tags = String(text || "").match(/@([A-Za-zА-Яа-яЁё0-9_.-]{2,40})/g) || [];
    if (!tags.length) return [];
    var ids = [];
    (chatAdmins || []).forEach(function (a) {
      var h = "@" + chatHandle(a);
      var hit = tags.some(function (t) { return t.toLowerCase() === h.toLowerCase(); });
      if (hit && Number(a.id)) ids.push(Number(a.id));
    });
    return ids;
  }

  function unlockChatAudio() {
    try {
      var Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      if (!chatAudioCtx) chatAudioCtx = new Ctx();
      if (chatAudioCtx.state === "suspended") chatAudioCtx.resume();
    } catch (_) {}
  }

  function playChatPing(mentioned) {
    if (!chatSoundOn) return;
    unlockChatAudio();
    if (!chatAudioCtx) return;
    var ctx = chatAudioCtx;
    var now = ctx.currentTime;
    function tone(freq, start, dur, gain) {
      var o = ctx.createOscillator();
      var g = ctx.createGain();
      o.type = "sine";
      o.frequency.setValueAtTime(freq, now + start);
      g.gain.setValueAtTime(0.0001, now + start);
      g.gain.exponentialRampToValueAtTime(gain, now + start + 0.018);
      g.gain.exponentialRampToValueAtTime(0.0001, now + start + dur);
      o.connect(g);
      g.connect(ctx.destination);
      o.start(now + start);
      o.stop(now + start + dur + 0.02);
    }
    if (mentioned) {
      tone(880, 0, 0.12, 0.09);
      tone(1175, 0.13, 0.16, 0.1);
    } else {
      tone(740, 0, 0.09, 0.045);
      tone(980, 0.1, 0.1, 0.04);
    }
  }

  function paintSoundBtn() {
    var btn = $("chat-sound");
    if (!btn) return;
    btn.textContent = chatSoundOn ? "🔔" : "🔕";
    btn.classList.toggle("muted", !chatSoundOn);
    btn.setAttribute("aria-pressed", chatSoundOn ? "true" : "false");
    btn.title = chatSoundOn ? "Звук включён" : "Звук выключен";
  }

  async function peekChatBadge() {
    try {
      const data = await api("/admin/api/chat/peek");
      const last = Number(data.last_id || 0);
      if (chatOpen()) {
        chatSeenId = Math.max(chatSeenId, last);
        localStorage.setItem("admin_chat_seen", String(chatSeenId));
        setChatBadge(0);
        chatSoundLast = Math.max(chatSoundLast, last);
        chatSoundPrimed = true;
        return;
      }
      setChatBadge(Math.max(0, last - chatSeenId));
      if (!chatSoundPrimed) {
        chatSoundLast = last;
        chatSoundPrimed = true;
      } else if (chatSoundOn && last > chatSoundLast && Number(data.last_user_id || 0) !== Number(me.id || 0)) {
        var tagged = Array.isArray(data.mentions) && data.mentions.some(function (id) { return Number(id) === Number(me.id); });
        playChatPing(tagged);
      }
      chatSoundLast = Math.max(chatSoundLast, last);
    } catch (_) {}
  }

  function chatQuoteLabel(kind, text) {
    var t = String(text || "").trim();
    if (t) return t;
    kind = String(kind || "text");
    if (kind === "image") return "Фото";
    if (kind === "video") return "Видео";
    if (kind === "audio") return "Голосовое";
    if (kind === "file") return "Файл";
    return "Сообщение";
  }

  function setReply(m) {
    if (!m || !m.id) return;
    chatReplyTo = {
      id: Number(m.id),
      user_name: m.user_name || m.user_email || "Админ",
      text: chatQuoteLabel(m.kind, m.text),
      kind: m.kind || "text",
    };
    $("chat-reply-name").textContent = "Ответ · " + chatReplyTo.user_name;
    $("chat-reply-text").textContent = chatReplyTo.text;
    $("chat-reply").classList.remove("hidden");
    try { $("chat-text").focus(); } catch (_) {}
  }

  function clearReply() {
    chatReplyTo = null;
    $("chat-reply").classList.add("hidden");
  }

  function jumpToMsg(id) {
    var row = document.querySelector('.chat-row[data-mid="' + id + '"]');
    if (!row) return;
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    row.classList.add("flash");
    setTimeout(function () { row.classList.remove("flash"); }, 1200);
  }

  function mediaHtml(m) {
    var url = escAttr(m.file_url || "");
    var kind = String(m.kind || "file");
    if (kind === "image") {
      return '<img src="' + url + '" alt="" data-lite="img">';
    }
    if (kind === "video") {
      return '<video src="' + url + '" controls preload="metadata" data-lite="video"></video>';
    }
    if (kind === "audio") {
      return '<audio src="' + url + '" controls preload="metadata"></audio>' +
        (m.duration_ms ? '<div class="hint" style="margin:0">Голосовое · ' + fmtDur(m.duration_ms) + "</div>" : "");
    }
    if (url) {
      return '<a class="chat-file" href="' + url + '" target="_blank" rel="noreferrer">Файл · ' + esc(m.file_name || "вложение") + "</a>";
    }
    return "";
  }

  function chatBubble(m) {
    var mine = Number(m.user_id) === Number(me.id);
    var canDel = mine || me.is_owner;
    var pinged = !mine && mentionsMe(m);
    var quote = "";
    if (Number(m.reply_to) > 0) {
      quote = '<button class="chat-quote" type="button" data-jump="' + m.reply_to + '"><strong>' +
        esc(m.reply_name || "Админ") + "</strong><span>" + esc(chatQuoteLabel(m.reply_kind, m.reply_text)) + "</span></button>";
    }
    return '<div class="chat-row' + (mine ? " mine" : "") + (pinged ? " pinged" : "") + '" data-mid="' + m.id + '">' +
      '<div class="chat-ava">' + esc(initials(m.user_name, m.user_email)) +
        '<span class="presence' + (m.online ? " on" : "") + '"></span></div>' +
      '<div class="chat-bubble">' +
        '<div class="chat-meta"><strong>' + esc(m.user_name || m.user_email || "Админ") + "</strong><time>" +
        esc(fmtChatTime(m.created_at)) + "</time>" +
        '<span class="chat-act"><button class="chat-del" data-reply-msg="' + m.id + '" type="button">ответить</button>' +
        (canDel ? '<button class="chat-del" data-del-msg="' + m.id + '" type="button">удалить</button>' : "") +
        "</span></div>" +
        quote +
        mediaHtml(m) +
        (m.text ? "<p>" + formatChatText(m.text) + "</p>" : "") +
      "</div></div>";
  }

  function bindChatLog() {
    var log = $("chat-log");
    if (!log) return;
    log.querySelectorAll("[data-del-msg]").forEach(function (btn) {
      btn.onclick = async function () {
        try {
          await api("/admin/api/chat/" + btn.dataset.delMsg, { method: "DELETE" });
          var row = log.querySelector('[data-mid="' + btn.dataset.delMsg + '"]');
          if (row) row.remove();
        } catch (e) { toast(e.message, true); }
      };
    });
    log.querySelectorAll("[data-reply-msg]").forEach(function (btn) {
      btn.onclick = function () {
        var row = log.querySelector('[data-mid="' + btn.dataset.replyMsg + '"]');
        var name = "";
        var text = "";
        var kind = "text";
        if (row) {
          var strong = row.querySelector(".chat-meta strong");
          var p = row.querySelector(".chat-bubble > p");
          name = strong ? strong.textContent : "";
          text = p ? p.textContent : "";
          if (row.querySelector("img")) kind = "image";
          else if (row.querySelector("video")) kind = "video";
          else if (row.querySelector("audio")) kind = "audio";
        }
        setReply({ id: btn.dataset.replyMsg, user_name: name, text: text, kind: kind });
      };
    });
    log.querySelectorAll("[data-jump]").forEach(function (btn) {
      btn.onclick = function (ev) {
        ev.preventDefault();
        jumpToMsg(btn.getAttribute("data-jump"));
      };
    });
    log.querySelectorAll("[data-lite]").forEach(function (el) {
      el.onclick = function (ev) {
        if (el.tagName === "VIDEO" && ev.target === el) {
          /* allow controls; still open on dbl? skip video lightbox except images */
        }
        if (el.getAttribute("data-lite") !== "img") return;
        ev.preventDefault();
        $("chat-lite-body").innerHTML = '<img src="' + escAttr(el.getAttribute("src")) + '" alt="">';
        $("chat-lightbox").classList.remove("hidden");
      };
    });
  }

  function appendChat(rows, reset) {
    var log = $("chat-log");
    if (!log) return;
    var nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
    if (reset) log.innerHTML = "";
    if (!rows.length && reset) {
      log.innerHTML = '<div class="empty">Пока тихо. Напишите первым, киньте скрин или запишите голосовое.</div>';
      return;
    }
    if (reset && log.querySelector(".empty")) log.innerHTML = "";
    var empty = log.querySelector(".empty");
    if (empty && rows.length) empty.remove();
    var incoming = [];
    rows.forEach(function (m) {
      if (log.querySelector('[data-mid="' + m.id + '"]')) return;
      incoming.push(m);
      log.insertAdjacentHTML("beforeend", chatBubble(m));
      chatLastId = Math.max(chatLastId, Number(m.id) || 0);
    });
    bindChatLog();
    if (reset || nearBottom) log.scrollTop = log.scrollHeight;
    if (!reset && incoming.length) {
      var fromOther = incoming.filter(function (m) { return Number(m.user_id) !== Number(me.id); });
      if (fromOther.length) playChatPing(fromOther.some(mentionsMe));
    }
  }

  async function pullChat(reset) {
    try {
      const data = await api("/admin/api/chat?after=" + (reset ? 0 : chatLastId) + "&limit=" + (reset ? 100 : 50));
      const rows = data.messages || [];
      appendChat(rows, !!reset);
      if (chatOpen()) {
        chatSeenId = Math.max(chatSeenId, chatLastId);
        localStorage.setItem("admin_chat_seen", String(chatSeenId));
        setChatBadge(0);
      }
    } catch (e) {
      if (reset) $("chat-log").innerHTML = '<div class="empty">' + esc(e.message || "Чат недоступен") + "</div>";
    }
  }

  async function loadChatAdmins() {
    try {
      const data = await api("/admin/api/admins");
      chatAdmins = data.admins || [];
    } catch (_) {}
  }

  function startChat() {
    wireChat();
    paintSoundBtn();
    loadChatAdmins();
    stopChatPoll();
    if (!chatLastId) pullChat(true);
    else pullChat(false);
    chatTimer = setInterval(function () { pullChat(false); }, 2200);
  }

  async function apiForm(path, form) {
    const headers = { Accept: "application/json" };
    const t = token();
    if (t) headers.Authorization = "Bearer " + t;
    const res = await fetch(path, { method: "POST", headers: headers, body: form });
    const raw = await res.text();
    let data = {};
    try { data = raw ? JSON.parse(raw) : {}; } catch (_) {}
    if (!res.ok) throw new Error(data.message || "Не удалось отправить");
    return data;
  }

  function clearPending() {
    chatPending = null;
    $("chat-preview").classList.add("hidden");
    $("chat-preview").innerHTML = "";
    $("chat-file").value = "";
  }

  function showPending(file, kind) {
    chatPending = { file: file, kind: kind || "" };
    var box = $("chat-preview");
    box.classList.remove("hidden");
    var url = URL.createObjectURL(file);
    var preview = "";
    if ((file.type || "").indexOf("image/") === 0) preview = '<img src="' + url + '" alt="">';
    else if ((file.type || "").indexOf("video/") === 0) preview = '<video src="' + url + '" muted></video>';
    else preview = "<span>Вложение</span>";
    box.innerHTML = preview + "<span>" + esc(file.name || "файл") + "</span>" +
      '<button class="secondary" type="button" id="chat-preview-x">Убрать</button>';
    $("chat-preview-x").onclick = clearPending;
  }

  async function sendChat() {
    var text = ($("chat-text").value || "").trim();
    if (chatPending && chatPending.file) {
      var form = new FormData();
      if (text) form.append("text", text);
      if (chatPending.kind) form.append("kind", chatPending.kind);
      if (chatReplyTo && chatReplyTo.id) form.append("reply_to", String(chatReplyTo.id));
      var tagged = collectMentions(text);
      if (tagged.length) form.append("mentions", JSON.stringify(tagged));
      form.append("file", chatPending.file, chatPending.file.name || "file");
      try {
        const out = await apiForm("/admin/api/chat", form);
        $("chat-text").value = "";
        clearPending();
        clearReply();
        hideMentions();
        if (out.message) appendChat([out.message], false);
      } catch (e) { toast(e.message, true); }
      return;
    }
    if (!text) return;
    try {
      const body = { text: text };
      if (chatReplyTo && chatReplyTo.id) body.reply_to = chatReplyTo.id;
      var tagged = collectMentions(text);
      if (tagged.length) body.mentions = tagged;
      const out = await api("/admin/api/chat", { method: "POST", body: JSON.stringify(body) });
      $("chat-text").value = "";
      clearReply();
      hideMentions();
      if (out.message) appendChat([out.message], false);
    } catch (e) { toast(e.message, true); }
  }

  function recStamp() {
    $("chat-rec-time").textContent = fmtDur(Date.now() - chatRecStarted);
  }

  function stopRecTracks() {
    if (chatRecStream) {
      chatRecStream.getTracks().forEach(function (t) { try { t.stop(); } catch (_) {} });
      chatRecStream = null;
    }
    clearInterval(chatRecTick);
    $("chat-rec").classList.add("hidden");
    $("chat-mic").classList.remove("live");
  }

  async function startVoice() {
    if (chatRec) return;
    try {
      chatRecStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (_) {
      toast("Нет доступа к микрофону", true);
      return;
    }
    var mime = "";
    if (window.MediaRecorder && MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) mime = "audio/webm;codecs=opus";
    else if (window.MediaRecorder && MediaRecorder.isTypeSupported("audio/webm")) mime = "audio/webm";
    chatRecChunks = [];
    try {
      chatRec = mime ? new MediaRecorder(chatRecStream, { mimeType: mime }) : new MediaRecorder(chatRecStream);
    } catch (e) {
      stopRecTracks();
      toast("Запись голоса недоступна в этом браузере", true);
      return;
    }
    chatRec.ondataavailable = function (e) { if (e.data && e.data.size) chatRecChunks.push(e.data); };
    chatRec.onstop = async function () {
      var rec = chatRec;
      chatRec = null;
      var blob = new Blob(chatRecChunks, { type: (rec && rec.mimeType) || "audio/webm" });
      var dur = Date.now() - chatRecStarted;
      stopRecTracks();
      if (!chatRecSend || blob.size < 600) return;
      var form = new FormData();
      form.append("kind", "audio");
      form.append("duration_ms", String(dur));
      if (chatReplyTo && chatReplyTo.id) form.append("reply_to", String(chatReplyTo.id));
      form.append("file", blob, "voice.webm");
      try {
        const out = await apiForm("/admin/api/chat", form);
        clearReply();
        if (out.message) appendChat([out.message], false);
      } catch (e) { toast(e.message, true); }
    };
    chatRecSend = false;
    chatRecStarted = Date.now();
    chatRec.start();
    $("chat-rec").classList.remove("hidden");
    $("chat-mic").classList.add("live");
    recStamp();
    chatRecTick = setInterval(recStamp, 250);
  }

  function finishVoice(send) {
    chatRecSend = !!send;
    if (chatRec && chatRec.state !== "inactive") chatRec.stop();
    else stopRecTracks();
  }

  function mentionQuery(ta) {
    var pos = ta.selectionStart;
    var before = ta.value.slice(0, pos);
    var m = before.match(/(^|[\s])@([A-Za-zА-Яа-яЁё0-9_.-]*)$/);
    return m ? m[2] : null;
  }

  function hideMentions() {
    chatMentionList = [];
    var box = $("chat-mentions");
    if (box) {
      box.classList.add("hidden");
      box.innerHTML = "";
    }
  }

  function paintMentions() {
    var box = $("chat-mentions");
    if (!box) return;
    if (!chatMentionList.length) {
      hideMentions();
      return;
    }
    if (chatMentionIdx < 0) chatMentionIdx = 0;
    if (chatMentionIdx >= chatMentionList.length) chatMentionIdx = chatMentionList.length - 1;
    box.innerHTML = chatMentionList.map(function (a, i) {
      return '<button type="button" data-mention-i="' + i + '" class="' + (i === chatMentionIdx ? "active" : "") + '">' +
        '<span class="handle">@' + esc(chatHandle(a)) + "</span>" +
        "<em>" + esc(a.name || a.email || "") + (a.online ? " · онлайн" : "") + "</em></button>";
    }).join("");
    box.classList.remove("hidden");
    box.querySelectorAll("[data-mention-i]").forEach(function (btn) {
      btn.onmousedown = function (e) { e.preventDefault(); };
      btn.onclick = function () { insertMention(chatMentionList[Number(btn.dataset.mentionI)]); };
    });
  }

  function refreshMentions() {
    var ta = $("chat-text");
    var q = mentionQuery(ta);
    if (q == null) {
      hideMentions();
      return;
    }
    var needle = String(q || "").toLowerCase();
    chatMentionList = (chatAdmins || []).filter(function (a) {
      if (Number(a.id) === Number(me.id)) return false;
      var hay = (chatHandle(a) + " " + (a.name || "") + " " + (a.email || "")).toLowerCase();
      return !needle || hay.indexOf(needle) >= 0;
    }).slice(0, 8);
    chatMentionIdx = 0;
    paintMentions();
  }

  function insertMention(admin) {
    if (!admin) return;
    var ta = $("chat-text");
    var pos = ta.selectionStart;
    var val = ta.value;
    var before = val.slice(0, pos);
    var at = before.lastIndexOf("@");
    if (at < 0) return;
    var handle = chatHandle(admin);
    var next = val.slice(pos).replace(/^[A-Za-zА-Яа-яЁё0-9_.-]*/, "");
    ta.value = before.slice(0, at) + "@" + handle + " " + next;
    var caret = at + handle.length + 2;
    ta.focus();
    ta.setSelectionRange(caret, caret);
    hideMentions();
  }

  function wireChat() {
    if (chatReady) return;
    chatReady = true;
    paintSoundBtn();
    $("chat-send").onclick = sendChat;
    $("chat-attach").onclick = function () { $("chat-file").click(); };
    $("chat-file").onchange = function () {
      var f = this.files && this.files[0];
      if (f) showPending(f, (f.type || "").indexOf("image/") === 0 ? "image" : ((f.type || "").indexOf("video/") === 0 ? "video" : ((f.type || "").indexOf("audio/") === 0 ? "audio" : "file")));
    };
    $("chat-sound").onclick = function () {
      chatSoundOn = !chatSoundOn;
      localStorage.setItem("admin_chat_sound", chatSoundOn ? "1" : "0");
      paintSoundBtn();
      unlockChatAudio();
      if (chatSoundOn) playChatPing(false);
    };
    $("chat-text").addEventListener("input", refreshMentions);
    $("chat-text").addEventListener("keydown", function (e) {
      if (chatMentionList.length && !e.altKey && !e.metaKey) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          chatMentionIdx = (chatMentionIdx + 1) % chatMentionList.length;
          paintMentions();
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          chatMentionIdx = (chatMentionIdx - 1 + chatMentionList.length) % chatMentionList.length;
          paintMentions();
          return;
        }
        if (e.key === "Tab" || e.key === "Enter") {
          e.preventDefault();
          e.stopPropagation();
          insertMention(chatMentionList[chatMentionIdx]);
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          hideMentions();
          return;
        }
      }
      if (e.shiftKey || e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.isComposing || e.keyCode === 229) return;
      var send = e.key === "Enter" || e.key === "NumpadEnter" || e.code === "Enter" || e.code === "NumpadEnter" || e.which === 13 || e.keyCode === 13;
      if (!send) return;
      e.preventDefault();
      e.stopPropagation();
      hideMentions();
      sendChat();
    }, true);
    $("chat-reply-x").onclick = clearReply;
    $("chat-mic").onclick = function () {
      if (chatRec) finishVoice(true);
      else startVoice();
    };
    $("chat-rec-cancel").onclick = function () { finishVoice(false); };
    $("chat-rec-send").onclick = function () { finishVoice(true); };
    $("chat-lite-close").onclick = function () { $("chat-lightbox").classList.add("hidden"); };
    $("chat-lightbox").onclick = function (e) {
      if (e.target === $("chat-lightbox")) $("chat-lightbox").classList.add("hidden");
    };
    var shell = $("chat-shell");
    shell.addEventListener("paste", function (e) {
      var items = e.clipboardData && e.clipboardData.items;
      if (!items) return;
      for (var i = 0; i < items.length; i++) {
        if (items[i].type.indexOf("image/") === 0) {
          var f = items[i].getAsFile();
          if (f) {
            e.preventDefault();
            showPending(new File([f], "screenshot.png", { type: f.type || "image/png" }), "image");
          }
          return;
        }
      }
    });
    shell.addEventListener("dragover", function (e) { e.preventDefault(); });
    shell.addEventListener("drop", function (e) {
      e.preventDefault();
      var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) showPending(f);
    });
  }

  $("projects-search").oninput = function () {
    debounceSearch("projects", function () { loadProjects($("projects-search").value.trim()); });
  };
  $("ips-search").oninput = function () {
    debounceSearch("ips", function () { loadIps($("ips-search").value.trim()); });
  };

  setInterval(tickClock, 15000);
  tickClock();

  (async function init() {
    if (!token()) { showLogin(); return; }
    try {
      await api("/admin/api/stats");
      try { me = await api("/admin/api/me") || me; } catch (_) {}
      showApp();
      setPage("dashboard");
    } catch (_) {
      showLogin();
    }
  })();
})();
