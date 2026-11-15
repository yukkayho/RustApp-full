/**
 * Working glass dashboard from Desktop/index.html mockup.
 * Mounted on /client/profile over the Vue SPA.
 */
(function () {
  if (window.__rcDashVer === 11) return;
  window.__rcDashVer = 11;
  window.__rcDashReady = 1;

  var ICONS = ["crystal", "cobalt", "piskar", "default"];
  var state = { user: null, projects: [], sessions: [], logoData: "", avatarData: "", lang: "ru" };
  var I18N = {
    ru: {
      createProject: "Создать новый проект", profile: "Личный профиль", logout: "Выйти с аккаунта",
      createTitle: "Создать проект", createSub: "Приступим к созданию вашего проекта",
      name: "Название", link: "Ссылка", logo: "Логотип проекта",
      uploadTitle: "Загрузите логотип проекта", uploadSub: "PNG, JPEG или GIF (не более 10 МБ)",
      back: "Назад", continue: "Продолжить",
      legal: "Создавая проект, вы подтверждаете свое согласие с User Agreement и Privacy Policy",
      navProfile: "Профиль", navIntegrations: "Интеграции", navInterface: "Интерфейс", navSecurity: "Безопасность", navProjects: "Проекты",
      policy: "Политика", terms: "Соглашение",
      tabProfile: "Профиль", tabProfileDesc: "Управление вашим профилем",
      avatarTitle: "Аватар профиля", change: "изменить",
      displayName: "Отображаемое имя", username: "Имя пользователя", about: "Обо мне",
      aboutPh: "Любые подробности, например: возраст, род занятий или город",
      save: "Сохранить", close: "Закрыть",
      tabIntegrations: "Интеграции", tabIntegrationsDesc: "Подключение сторонних сервисов",
      integrationsBanner: "С помощью интеграций вы можете подключить к вашему аккаунту другие сервисы.",
      steamDesc: "привяжите Steam аккаунт", discordDesc: "привяжите Discord аккаунт", telegramDesc: "привяжите Telegram аккаунт",
      connect: "Подключить", connected: "Подключено", unavailable: "Недоступно",
      tabInterface: "Интерфейс", tabInterfaceDesc: "Настройка внешнего вида",
      animTitle: "Тема анимаций", animSub: "Плавные переходы и эффекты",
      notifTitle: "Уведомления", notifSub: "Показывать уведомления в браузере",
      soundTitle: "Звуки", soundSub: "Воспроизводить звуки интерфейса",
      langTitle: "Язык интерфейса", langSub: "выберите язык",
      bmTitle: "Кнопка Battlemetrics в профиле", bmSub: "добавляет кнопку, открывающую профиль в BM",
      chatTitle: "Подтверждать отправку в чат всех серверов", chatSub: "защищает от случайных сообщений",
      yes: "Да", no: "Нет",
      tabSecurity: "Безопасность", tabSecurityDesc: "Защита вашего аккаунта",
      twofa: "Двухфакторная аутентификация", install: "Установить", sessions: "Активные сеансы",
      session: "Сеанс", currentSession: "Текущий сеанс", now: "сейчас",
      tabProjects: "Проекты", tabProjectsDesc: "Ваши подключённые проекты",
      noProjects: "Нет проектов", owner: "Создатель", leave: "Покинуть", leaveConfirm: "Покинуть проект?",
      leaveFail: "Не удалось удалить", createFail: "Не удалось создать проект",
      sessionFail: "Не удалось закрыть сеанс", loadFail: "Ошибка загрузки"
    },
    en: {
      createProject: "Create a new project", profile: "Personal profile", logout: "Log out",
      createTitle: "Create project", createSub: "Let's set up your project",
      name: "Name", link: "Link", logo: "Project logo",
      uploadTitle: "Upload a project logo", uploadSub: "PNG, JPEG or GIF (max 10 MB)",
      back: "Back", continue: "Continue",
      legal: "By creating a project you agree to the User Agreement and Privacy Policy",
      navProfile: "Profile", navIntegrations: "Integrations", navInterface: "Interface", navSecurity: "Security", navProjects: "Projects",
      policy: "Privacy", terms: "Terms",
      tabProfile: "Profile", tabProfileDesc: "Manage your profile",
      avatarTitle: "Profile avatar", change: "change",
      displayName: "Display name", username: "Username", about: "About me",
      aboutPh: "Any details, for example: age, occupation or city",
      save: "Save", close: "Close",
      tabIntegrations: "Integrations", tabIntegrationsDesc: "Connect third-party services",
      integrationsBanner: "Use integrations to connect other services to your account.",
      steamDesc: "link your Steam account", discordDesc: "link your Discord account", telegramDesc: "link your Telegram account",
      connect: "Connect", connected: "Connected", unavailable: "Unavailable",
      tabInterface: "Interface", tabInterfaceDesc: "Appearance settings",
      animTitle: "Animation theme", animSub: "Smooth transitions and effects",
      notifTitle: "Notifications", notifSub: "Show browser notifications",
      soundTitle: "Sounds", soundSub: "Play interface sounds",
      langTitle: "Interface language", langSub: "choose a language",
      bmTitle: "Battlemetrics button in profile", bmSub: "adds a button that opens the profile in BM",
      chatTitle: "Confirm sending chat to all servers", chatSub: "protects from accidental messages",
      yes: "Yes", no: "No",
      tabSecurity: "Security", tabSecurityDesc: "Protect your account",
      twofa: "Two-factor authentication", install: "Set up", sessions: "Active sessions",
      session: "Session", currentSession: "Current session", now: "now",
      tabProjects: "Projects", tabProjectsDesc: "Your connected projects",
      noProjects: "No projects", owner: "Owner", leave: "Leave", leaveConfirm: "Leave this project?",
      leaveFail: "Could not leave", createFail: "Could not create the project",
      sessionFail: "Could not close the session", loadFail: "Failed to load"
    },
    uk: {
      createProject: "Створити новий проєкт", profile: "Особистий профіль", logout: "Вийти з акаунта",
      createTitle: "Створити проєкт", createSub: "Почнемо створення вашого проєкту",
      name: "Назва", link: "Посилання", logo: "Логотип проєкту",
      uploadTitle: "Завантажте логотип проєкту", uploadSub: "PNG, JPEG або GIF (не більше 10 МБ)",
      back: "Назад", continue: "Продовжити",
      legal: "Створюючи проєкт, ви підтверджуєте згоду з User Agreement і Privacy Policy",
      navProfile: "Профіль", navIntegrations: "Інтеграції", navInterface: "Інтерфейс", navSecurity: "Безпека", navProjects: "Проєкти",
      policy: "Політика", terms: "Угода",
      tabProfile: "Профіль", tabProfileDesc: "Керування вашим профілем",
      avatarTitle: "Аватар профілю", change: "змінити",
      displayName: "Відображуване ім'я", username: "Ім'я користувача", about: "Про мене",
      aboutPh: "Будь-які деталі, наприклад: вік, рід занять або місто",
      save: "Зберегти", close: "Закрити",
      tabIntegrations: "Інтеграції", tabIntegrationsDesc: "Підключення сторонніх сервісів",
      integrationsBanner: "За допомогою інтеграцій ви можете підключити до акаунта інші сервіси.",
      steamDesc: "прив'яжіть Steam акаунт", discordDesc: "прив'яжіть Discord акаунт", telegramDesc: "прив'яжіть Telegram акаунт",
      connect: "Підключити", connected: "Підключено", unavailable: "Недоступно",
      tabInterface: "Інтерфейс", tabInterfaceDesc: "Налаштування вигляду",
      animTitle: "Тема анімацій", animSub: "Плавні переходи та ефекти",
      notifTitle: "Сповіщення", notifSub: "Показувати сповіщення в браузері",
      soundTitle: "Звуки", soundSub: "Відтворювати звуки інтерфейсу",
      langTitle: "Мова інтерфейсу", langSub: "виберіть мову",
      bmTitle: "Кнопка Battlemetrics у профілі", bmSub: "додає кнопку, що відкриває профіль у BM",
      chatTitle: "Підтверджувати надсилання в чат усіх серверів", chatSub: "захищає від випадкових повідомлень",
      yes: "Так", no: "Ні",
      tabSecurity: "Безпека", tabSecurityDesc: "Захист вашого акаунта",
      twofa: "Двофакторна автентифікація", install: "Встановити", sessions: "Активні сеанси",
      session: "Сеанс", currentSession: "Поточний сеанс", now: "зараз",
      tabProjects: "Проєкти", tabProjectsDesc: "Ваші підключені проєкти",
      noProjects: "Немає проєктів", owner: "Власник", leave: "Покинути", leaveConfirm: "Покинути проєкт?",
      leaveFail: "Не вдалося видалити", createFail: "Не вдалося створити проєкт",
      sessionFail: "Не вдалося закрити сеанс", loadFail: "Помилка завантаження"
    }
  };

  function tr(key) {
    var lang = state.lang || localStorage.getItem("rustcheck-lang") || "ru";
    var dict = I18N[lang] || I18N.ru;
    return dict[key] || I18N.ru[key] || key;
  }

  function applyVueLocale(lang) {
    try {
      var app = document.querySelector("#app");
      var i18n = app && app.__vue_app__ && app.__vue_app__.config && app.__vue_app__.config.globalProperties && app.__vue_app__.config.globalProperties.$i18n;
      if (!i18n) return;
      var loc = (i18n.global && i18n.global.locale) || i18n.locale;
      if (loc && typeof loc === "object" && "value" in loc) loc.value = lang;
      else if (i18n.global) i18n.global.locale = lang;
      else i18n.locale = lang;
    } catch (_) {}
  }

  function applyLang(lang) {
    if (!I18N[lang]) lang = "ru";
    state.lang = lang;
    document.documentElement.lang = lang;
    try {
      localStorage.setItem("rustcheck-lang", lang);
      localStorage.setItem("locale", lang);
    } catch (_) {}
    applyVueLocale(lang);
    var dict = I18N[lang];
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      if (el.querySelector("a, svg, input, textarea, button")) return;
      var k = el.getAttribute("data-i18n");
      if (k && dict[k]) el.textContent = dict[k];
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
      var k = el.getAttribute("data-i18n-placeholder");
      if (k && dict[k]) el.setAttribute("placeholder", dict[k]);
    });
    ["rcBm", "rcConfirmChat"].forEach(function (id) {
      var drop = document.getElementById(id);
      if (!drop) return;
      var v = drop.getAttribute("data-value");
      var lab = drop.querySelector(".rc-drop-label");
      if (lab) lab.textContent = v === "0" ? dict.no : dict.yes;
    });
    renderUser();
    renderSettingsProjects();
    renderSessions();
  }

  function token() {
    try {
      var raw = localStorage.getItem("access_token") || localStorage.getItem("token") || "";
      raw = String(raw).replace(/^"+|"+$/g, "").trim();
      if (raw.toLowerCase().indexOf("bearer ") === 0) raw = raw.slice(7).trim();
      return raw;
    } catch (_) {
      return "";
    }
  }

  function headers(json) {
    var h = { Accept: "application/json" };
    if (json) h["Content-Type"] = "application/json";
    var t = token();
    if (t) h.Authorization = "Bearer " + t;
    return h;
  }

  function api(method, url, body) {
    var opts = { method: method, credentials: "include", cache: "no-store", headers: headers(body !== undefined) };
    if (body !== undefined) opts.body = JSON.stringify(body);
    return fetch(url, opts).then(function (res) {
      return res.text().then(function (text) {
        var data = text;
        try { data = text ? JSON.parse(text) : null; } catch (_) {}
        if (!res.ok) {
          var err = new Error((data && (data.detail || data.message || data.error)) || res.statusText || "error");
          err.status = res.status;
          err.data = data;
          throw err;
        }
        return data;
      });
    });
  }

  function hostLabel() {
    return (location.host || "rustcheck.cc").replace(/^www\./, "");
  }

  function initials(name) {
    var s = String(name || "?").trim();
    if (!s) return "?";
    var parts = s.split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return s.slice(0, 2).toUpperCase();
  }

  function slugify(s) {
    return String(s || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "")
      .slice(0, 32);
  }

  function displayName(user) {
    user = user || {};
    return user.name || user.nickname || (user.email && String(user.email).split("@")[0]) || "user";
  }

  function displayTag(user) {
    user = user || {};
    var tag = String(user.tag || user.username || user.login || "").replace(/^@/, "");
    if (!tag) tag = slugify(displayName(user)) || "user";
    return "@" + tag;
  }

  function avatarUrl(user) {
    user = user || {};
    var a = user.avatar || (user.google && user.google.avatar) || "";
    if (!a || a === "[object Object]") return "";
    if (/image-1024|placeholder|default-avatar/i.test(a)) return "";
    return a;
  }

  function go(path) {
    try {
      var root = document.querySelector("#app");
      var router = root && root.__vue_app__ && root.__vue_app__.config.globalProperties.$router;
      if (router) {
        router.push(path).catch(function () { location.href = path; });
        return;
      }
    } catch (_) {}
    location.href = path;
  }

  function toast(msg, danger) {
    if (msg && window.__checkappToast) window.__checkappToast(danger ? "warn" : "success", msg);
    var el = document.getElementById("rcDashToast");
    if (!el) return;
    el.textContent = msg || "";
    el.style.color = danger ? "#ef4444" : "rgba(255,255,255,.7)";
    el.style.opacity = msg ? "1" : "0";
  }

  function svgArrow() {
    return '<svg class="project-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>';
  }

  function projectIconHtml(p, i) {
    var kind = ICONS[i % ICONS.length];
    var av = p && (p.avatar || p.avatar_url);
    if (av && typeof av === "object") av = av.url || av.src;
    av = typeof av === "string" ? av : "";
    if (av && !/placeholder/i.test(av)) {
      return '<div class="project-icon ' + kind + '" style="overflow:hidden;padding:0"><img src="' + av.replace(/"/g, "") + '" alt="" style="width:100%;height:100%;object-fit:cover"></div>';
    }
    return '<div class="project-icon ' + kind + '">' + initials(p && p.name) + "</div>";
  }

  function renderProjects() {
    var list = document.getElementById("rcProjects");
    if (!list) return;
    var rows = state.projects || [];
    if (!rows.length) {
      list.innerHTML = '<div class="project-url" style="padding:8px 12px">Пока нет проектов — создайте первый</div>';
      return;
    }
    list.innerHTML = rows.map(function (p, i) {
      var domain = p.domain || p.tag || p.url || "";
      return (
        '<a href="/' + encodeURIComponent(domain) + '/players" class="project-item" data-domain="' + String(domain).replace(/"/g, "") + '">' +
          projectIconHtml(p, i) +
          '<div class="project-info">' +
            '<div class="project-name">' + (p.name || domain) + "</div>" +
            '<div class="project-url">' + hostLabel() + "/" + domain + "</div>" +
          "</div>" + svgArrow() +
        "</a>"
      );
    }).join("");
    list.querySelectorAll(".project-item").forEach(function (item, index) {
      item.style.animation = "slideUp 0.6s cubic-bezier(0.16, 1, 0.3, 1) " + index * 0.08 + "s backwards";
      item.addEventListener("click", function (e) {
        e.preventDefault();
        go("/" + item.getAttribute("data-domain") + "/players");
      });
    });
  }

  function renderSettingsProjects() {
    var box = document.getElementById("rcSettingsProjects");
    if (!box) return;
    var rows = state.projects || [];
    if (!rows.length) {
      box.innerHTML = '<div class="settings-tab-desc">' + tr("noProjects") + "</div>";
      return;
    }
    box.innerHTML = rows.map(function (p, i) {
      var kind = ICONS[i % ICONS.length];
      var domain = p.domain || p.tag || "";
      var owner = p.is_owner === true || p.role === "owner" || p.is_owner == null;
      var leaveBtn = owner
        ? '<button type="button" class="btn-leave leave-owner">' + tr("owner") + "</button>"
        : '<button type="button" class="btn-leave leave-active" data-leave="' + (p.id || "") + '">' + tr("leave") + "</button>";
      return (
        '<div class="project-row" data-id="' + (p.id || "") + '">' +
          projectIconHtml(p, i).replace('project-icon ', 'project-row-icon ') +
          '<div class="project-row-info">' +
            '<div class="project-row-name">' + (p.name || domain) + "</div>" +
            '<div class="project-row-slug">' + domain + "</div>" +
          "</div>" +
          leaveBtn +
        "</div>"
      );
    }).join("");
    box.querySelectorAll("[data-leave]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.getAttribute("data-leave");
        if (!id || !confirm(tr("leaveConfirm"))) return;
        api("DELETE", "/project/" + id).catch(function () {
          return api("POST", "/project/" + id + "/delete", {});
        }).then(function () { return reload(); }).catch(function (err) {
          toast(err.message || tr("leaveFail"), true);
        });
      });
    });
  }

  function iconStyle(kind) {
    if (kind === "crystal") return "background:linear-gradient(135deg,#1a1a2e,#16213e);color:#00d4ff";
    if (kind === "cobalt") return "background:linear-gradient(135deg,#0f3460,#16213e);color:#4da8da";
    if (kind === "piskar") return "background:linear-gradient(135deg,#1a1a2e,#2d2d44);color:#a855f7";
    return "background:linear-gradient(135deg,#1a1a1a,#2a2a2a);color:#fff";
  }

  function paintAvatar(el, user, sizeLetter) {
    if (!el) return;
    var url = state.avatarData || avatarUrl(user);
    var letter = initials(displayName(user));
    if (url) {
      el.innerHTML = '<img src="' + url.replace(/"/g, "") + '" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:50%">';
    } else {
      el.textContent = letter;
    }
  }

  function renderUser() {
    var user = state.user || {};
    var name = displayName(user);
    var tag = displayTag(user);
    document.querySelectorAll("[data-rc-name]").forEach(function (n) { n.textContent = name; });
    document.querySelectorAll("[data-rc-tag]").forEach(function (n) { n.textContent = tag; });
    paintAvatar(document.getElementById("rcAvatar"), user);
    paintAvatar(document.getElementById("rcSettingsAvatar"), user);
    paintAvatar(document.getElementById("rcProfileAvatarLg"), user);
    var nameInp = document.getElementById("rcSetName");
    var tagInp = document.getElementById("rcSetTag");
    var bioInp = document.getElementById("rcSetBio");
    if (nameInp) nameInp.value = name;
    if (tagInp) tagInp.value = tag;
    if (bioInp) bioInp.value = user.bio || user.about || "";
    var steamBtn = document.getElementById("rcSteamBtn");
    var discBtn = document.getElementById("rcDiscordBtn");
    if (steamBtn) {
      var steamOn = /^[0-9]{17}$/.test(String(user.steam_id || user.steam && user.steam.steam_id || ""));
      steamBtn.textContent = steamOn ? (state.lang === "en" ? "Unlink" : "Отвязать") : tr("connect");
      steamBtn.classList.remove("unavailable");
      steamBtn.classList.toggle("rc-unlink", steamOn);
    }
    if (discBtn) {
      var discOn = !!(user.discord && user.discord.discord_id);
      discBtn.textContent = discOn ? (state.lang === "en" ? "Unlink" : "Отвязать") : tr("connect");
      discBtn.classList.remove("unavailable");
      discBtn.classList.toggle("rc-unlink", discOn);
    }
  }

  function renderSessions() {
    var box = document.getElementById("rcSessions");
    if (!box) return;
    var rows = Array.isArray(state.sessions) ? state.sessions : [];
    if (!rows.length) {
      box.innerHTML = '<div class="session-item"><div class="session-info"><h5>' + tr("currentSession") + "</h5><span>" + tr("now") + "</span></div></div>";
      return;
    }
    box.innerHTML = rows.map(function (s) {
      var title = s.user_agent || s.browser || s.device || tr("session");
      if (title.length > 42) title = title.slice(0, 42) + "…";
      var when = s.created_at || s.time || s.last_seen || "";
      if (typeof when === "number") {
        try { when = new Date(when > 1e12 ? when : when * 1000).toLocaleString(); } catch (_) {}
      }
      return (
        '<div class="session-item">' +
          '<div class="session-info"><h5>' + title + "</h5><span>" + (when || "") + "</span></div>" +
          (s.current || s.is_current ? "" : '<button type="button" class="btn-revoke" data-sid="' + (s.id || "") + '"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>') +
        "</div>"
      );
    }).join("");
    box.querySelectorAll("[data-sid]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.getAttribute("data-sid");
        if (!id) return;
        api("DELETE", "/auth/sessions/" + id).then(function () { return reload(); }).catch(function (err) {
          toast(err.message || tr("sessionFail"), true);
        });
      });
    });
  }

  function markup() {
    var host = hostLabel();
    return (
      '<div class="dash-bg"></div><div class="dash-noise"></div>' +
      '<div class="container" id="rcDashMain">' +
        '<div class="glass-card"><div class="glow-line"></div>' +
          '<div class="profile-section">' +
            '<div class="avatar-wrapper"><div class="avatar-ring"></div><div class="avatar" id="rcAvatar">?</div></div>' +
            '<h1 class="username" data-rc-name>…</h1><p class="handle" data-rc-tag>@user</p>' +
          "</div>" +
          '<div class="projects-list" id="rcProjects"></div>' +
          '<div class="divider"></div>' +
          '<div class="actions-list">' +
            '<a href="#" class="action-item" id="rcCreateBtn">' +
              '<svg class="action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>' +
              '<span class="action-text" data-i18n="createProject">Создать новый проект</span></a>' +
            '<a href="#" class="action-item" id="rcSettingsBtn">' +
              '<svg class="action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>' +
              '<span class="action-text" data-i18n="profile">Личный профиль</span></a>' +
            '<a href="#" class="action-item danger" id="rcLogoutBtn">' +
              '<svg class="action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>' +
              '<span class="action-text" data-i18n="logout">Выйти с аккаунта</span></a>' +
          "</div><div id=\"rcDashToast\" style=\"margin-top:12px;font-size:12px;opacity:0;transition:opacity .2s\"></div>" +
        "</div></div>" +

      '<div class="modal-overlay" id="createModal"><div class="modal-card">' +
        '<div class="modal-close" id="modalClose"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></div>' +
        '<div class="modal-header"><h2 class="modal-title" data-i18n="createTitle">Создать проект</h2><p class="modal-subtitle" data-i18n="createSub">Приступим к созданию вашего проекта</p></div>' +
        '<form id="createForm">' +
          '<div class="form-group"><label class="form-label" data-i18n="name">Название</label><div class="form-input-wrapper"><input type="text" class="form-input" placeholder="Null Rust" id="projectName" required></div></div>' +
          '<div class="form-group"><label class="form-label" data-i18n="link">Ссылка</label><div class="input-with-prefix"><span class="input-prefix" id="rcHostPrefix">' + host + '/</span><input type="text" class="form-input" placeholder="nullrust" id="projectSlug" required></div></div>' +
          '<div class="form-group"><label class="form-label" data-i18n="logo">Логотип проекта</label>' +
            '<div class="upload-zone" id="uploadZone"><div class="upload-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg></div>' +
            '<div class="upload-title" data-i18n="uploadTitle">Загрузите логотип проекта</div><div class="upload-subtitle" data-i18n="uploadSub">PNG, JPEG или GIF (не более 10 МБ)</div>' +
            '<input type="file" accept="image/png,image/jpeg,image/gif" id="fileInput"></div>' +
            '<div class="upload-preview" id="uploadPreview"><img src="" alt="Preview" class="upload-preview-img" id="previewImg">' +
              '<div class="upload-preview-info"><div class="upload-preview-name" id="previewName"></div><div class="upload-preview-size" id="previewSize"></div></div>' +
              '<div class="upload-preview-remove" id="removeFile"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></div></div>' +
          "</div>" +
          '<div class="modal-footer"><button type="button" class="btn-back" id="btnBack" data-i18n="back">Назад</button><button type="submit" class="btn-continue" data-i18n="continue">Продолжить</button></div>' +
        "</form>" +
        '<p class="legal-text">Создавая проект, вы подтверждаете свое<br>согласие с <a href="#" data-legal="terms">User Agreement</a> и <a href="#" data-legal="privacy">Privacy Policy</a></p>' +
      "</div></div>" +

      '<div class="settings-overlay" id="settingsOverlay"><div class="settings-particles" id="settingsParticles"></div><div class="settings-card">' +
        '<div class="settings-sidebar">' +
          '<div class="settings-user"><div class="settings-user-avatar" id="rcSettingsAvatar">?</div>' +
            '<div class="settings-user-info"><div class="settings-user-name" data-rc-name>…</div><div class="settings-user-handle" data-rc-tag>@user</div></div></div>' +
          '<div class="settings-nav">' +
            '<div class="settings-nav-item active" data-tab="profile"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg><span data-i18n="navProfile">Профиль</span></div>' +
            '<div class="settings-nav-item" data-tab="integrations"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/></svg><span data-i18n="navIntegrations">Интеграции</span></div>' +
            '<div class="settings-nav-item" data-tab="interface"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg><span data-i18n="navInterface">Интерфейс</span></div>' +
            '<div class="settings-nav-item" data-tab="security"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg><span data-i18n="navSecurity">Безопасность</span></div>' +
            '<div class="settings-nav-item" data-tab="projects"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg><span data-i18n="navProjects">Проекты</span></div>' +
          "</div>" +
        "</div>" +
        '<div class="settings-content">' +
          '<div class="settings-tab active" id="tab-profile">' +
            '<div class="settings-tab-title" data-i18n="tabProfile">Профиль</div><div class="settings-tab-desc" data-i18n="tabProfileDesc">Управление вашим профилем</div>' +
            '<div class="profile-avatar-section"><div class="profile-avatar-lg" id="rcProfileAvatarLg">?</div>' +
              '<div class="profile-avatar-info"><h4 data-i18n="avatarTitle">Аватар профиля</h4><span id="rcChangeAvatar" style="color:#3b82f6;cursor:pointer;font-size:12px" data-i18n="change">изменить</span></div></div>' +
            '<input type="file" accept="image/png,image/jpeg,image/gif,image/webp" id="rcAvatarFile" style="display:none">' +
            '<div class="settings-field"><label data-i18n="displayName">Отображаемое имя</label><input type="text" id="rcSetName"></div>' +
            '<div class="settings-field"><label data-i18n="username">Имя пользователя</label><input type="text" id="rcSetTag"></div>' +
            '<div class="settings-field"><label data-i18n="about">Обо мне</label><textarea id="rcSetBio" data-i18n-placeholder="aboutPh" placeholder="Любые подробности, например: возраст, род занятий или город"></textarea></div>' +
            '<div class="settings-actions"><button type="button" class="btn-save" id="rcSaveProfile" data-i18n="save">Сохранить</button><button type="button" class="btn-close-settings" id="closeSettings" data-i18n="close">Закрыть</button></div>' +
          "</div>" +
          '<div class="settings-tab" id="tab-integrations">' +
            '<div class="settings-tab-title" data-i18n="tabIntegrations">Интеграции</div><div class="settings-tab-desc" data-i18n="tabIntegrationsDesc">Подключение сторонних сервисов</div>' +
            '<div class="integration-info-banner" data-i18n="integrationsBanner">С помощью интеграций вы можете подключить к вашему аккаунту другие сервисы.</div>' +
            '<div class="integration-item"><div class="integration-icon steam"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M11.979 0C5.678 0 .511 4.86.022 11.037l6.432 2.658c.545-.371 1.203-.59 1.912-.59.063 0 .125.004.188.006l2.861-4.142V8.91c0-2.495 2.028-4.524 4.524-4.524 2.494 0 4.524 2.031 4.524 4.527s-2.03 4.525-4.524 4.525h-.105l-4.076 2.911c0 .052.004.105.004.159 0 1.875-1.515 3.396-3.39 3.396-1.635 0-3.016-1.173-3.331-2.727L.436 15.27C1.862 20.307 6.486 24 11.979 24c6.627 0 11.999-5.373 11.999-12S18.605 0 11.979 0zM7.54 18.205l-1.473-.61c.262.543.714.999 1.314 1.25 1.297.539 2.793-.076 3.332-1.375.263-.63.264-1.319.005-1.949s-.75-1.121-1.377-1.383c-.624-.26-1.29-.249-1.878-.03l1.523.63c.956.4 1.409 1.5 1.009 2.455-.397.957-1.497 1.41-2.454 1.012H7.54zm8.523-9.08c-1.623 0-2.943 1.32-2.943 2.943 0 1.623 1.32 2.942 2.943 2.942 1.623 0 2.943-1.32 2.943-2.942 0-1.624-1.32-2.943-2.943-2.943zm0 3.868c-.51 0-.924-.414-.924-.924s.414-.924.924-.924.924.414.924.924-.414.924-.924.924z"/></svg></div><div class="integration-info"><div class="integration-name">Steam</div><div class="integration-desc" data-i18n="steamDesc">привяжите Steam аккаунт</div></div><button type="button" class="btn-connect" id="rcSteamBtn">Подключить</button></div>' +
            '<div class="integration-item"><div class="integration-icon discord"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M19.54 5.34A16.3 16.3 0 0 0 15.44 4l-.5 1.02a15.2 15.2 0 0 0-5.86 0L8.56 4a16.4 16.4 0 0 0-4.1 1.34C1.87 9.18 1.17 12.93 1.52 16.62a16.5 16.5 0 0 0 5.03 2.55l1.22-1.67c-.67-.25-1.31-.56-1.92-.93l.47-.36c3.7 1.72 7.72 1.72 11.38 0l.48.36c-.61.37-1.26.68-1.93.93l1.22 1.67a16.5 16.5 0 0 0 5.03-2.55c.42-4.28-.72-8-2.96-11.28ZM8.85 14.34c-1.11 0-2.02-1.03-2.02-2.29s.89-2.29 2.02-2.29c1.14 0 2.04 1.04 2.02 2.29 0 1.26-.89 2.29-2.02 2.29Zm6.3 0c-1.11 0-2.02-1.03-2.02-2.29s.89-2.29 2.02-2.29c1.14 0 2.04 1.04 2.02 2.29 0 1.26-.88 2.29-2.02 2.29Z"/></svg></div><div class="integration-info"><div class="integration-name">Discord</div><div class="integration-desc" data-i18n="discordDesc">привяжите Discord аккаунт</div></div><button type="button" class="btn-connect" id="rcDiscordBtn">Подключить</button></div>' +
            '<div class="integration-item"><div class="integration-icon telegram"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M21.6 3.2 18.4 19c-.24 1.12-.88 1.39-1.78.87l-4.87-3.59-2.35 2.26c-.26.26-.48.48-.98.48l.35-4.96 9.02-8.15c.39-.35-.09-.55-.61-.2L6.03 12.73 1.23 11.23c-1.04-.33-1.06-1.04.22-1.54L20.22 2.46c.87-.32 1.63.2 1.38.74Z"/></svg></div><div class="integration-info"><div class="integration-name">Telegram</div><div class="integration-desc" data-i18n="telegramDesc">привяжите Telegram аккаунт</div></div><button type="button" class="btn-connect unavailable" data-i18n="unavailable">Недоступно</button></div>' +
          "</div>" +
          '<div class="settings-tab" id="tab-interface">' +
            '<div class="settings-tab-title" data-i18n="tabInterface">Интерфейс</div><div class="settings-tab-desc" data-i18n="tabInterfaceDesc">Настройка внешнего вида</div>' +
            interfaceRow("Уведомления", "Показывать уведомления в браузере", "rcNotif", true, "notifTitle", "notifSub") +
            interfaceRow("Звуки", "Воспроизводить звуки интерфейса", "rcSound", false, "soundTitle", "soundSub") +
            interfaceSelect("Язык интерфейса", "выберите язык", "rcLang", [
              { v: "ru", t: "Русский" },
              { v: "en", t: "English" },
              { v: "uk", t: "Українська" }
            ], localStorage.getItem("rustcheck-lang") || "ru", "langTitle", "langSub") +
            interfaceSelect("Кнопка Battlemetrics в профиле", "добавляет кнопку, открывающую профиль в BM", "rcBm", [
              { v: "1", t: "Да", k: "yes" },
              { v: "0", t: "Нет", k: "no" }
            ], localStorage.getItem("rc-ui-rcBm") == null ? "1" : localStorage.getItem("rc-ui-rcBm"), "bmTitle", "bmSub") +
            interfaceSelect("Подтверждать отправку в чат всех серверов", "защищает от случайных сообщений", "rcConfirmChat", [
              { v: "1", t: "Да", k: "yes" },
              { v: "0", t: "Нет", k: "no" }
            ], localStorage.getItem("rc-ui-rcConfirmChat") == null ? "1" : localStorage.getItem("rc-ui-rcConfirmChat"), "chatTitle", "chatSub") +
          "</div>" +
          '<div class="settings-tab" id="tab-security">' +
            '<div class="settings-tab-title" data-i18n="tabSecurity">Безопасность</div><div class="settings-tab-desc" data-i18n="tabSecurityDesc">Защита вашего аккаунта</div>' +
            '<div class="security-section"><div class="security-header"><div class="security-section-title" data-i18n="twofa">Двухфакторная аутентификация</div><button type="button" class="btn-install-2fa" id="rc2fa" data-i18n="install">Установить</button></div></div>' +
            '<div class="security-section"><div class="security-section-title" data-i18n="sessions">Активные сеансы</div><div id="rcSessions"></div></div>' +
          "</div>" +
          '<div class="settings-tab" id="tab-projects">' +
            '<div class="settings-tab-title" data-i18n="tabProjects">Проекты</div><div class="settings-tab-desc" data-i18n="tabProjectsDesc">Ваши подключённые проекты</div>' +
            '<div id="rcSettingsProjects"></div>' +
          "</div>" +
        "</div></div></div>"
    );
  }

  function interfaceSelect(title, sub, id, options, value, titleKey, subKey) {
    var current = options.filter(function (o) { return String(o.v) === String(value); })[0] || options[0];
    var items = options.map(function (o) {
      var on = String(o.v) === String(current.v);
      return '<button type="button" class="rc-drop-item' + (on ? " active" : "") + '" data-v="' + o.v + '"' + (o.k ? ' data-i18n="' + o.k + '"' : "") + ' role="option">' + o.t + "</button>";
    }).join("");
    return (
      '<div class="interface-option"><div class="interface-option-info"><h5' + (titleKey ? ' data-i18n="' + titleKey + '"' : "") + ">" + title + "</h5><span" + (subKey ? ' data-i18n="' + subKey + '"' : "") + ">" + sub + "</span></div>" +
      '<div class="rc-drop" id="' + id + '" data-value="' + current.v + '">' +
        '<button type="button" class="rc-drop-btn" aria-haspopup="listbox">' +
          '<span class="rc-drop-label">' + current.t + "</span>" +
          '<svg class="rc-drop-chevron" viewBox="0 0 10 6" fill="none"><path d="M1 1.2L5 5l4-3.8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>' +
        "</button>" +
        '<div class="rc-drop-menu" role="listbox">' + items + "</div>" +
      "</div></div>"
    );
  }

  function openLegal(kind) {
    if (typeof window.__checkappOpenLegal === "function") window.__checkappOpenLegal(kind);
  }

  function interfaceRow(title, sub, id, on, titleKey, subKey) {
    var stored = localStorage.getItem("rc-ui-" + id);
    if (stored === "0") on = false;
    if (stored === "1") on = true;
    return (
      '<div class="interface-option"><div class="interface-option-info"><h5' + (titleKey ? ' data-i18n="' + titleKey + '"' : "") + ">" + title + "</h5><span" + (subKey ? ' data-i18n="' + subKey + '"' : "") + ">" + sub + "</span></div>" +
      '<div class="toggle-switch' + (on ? " on" : "") + '" id="' + id + '"></div></div>'
    );
  }

  function spawnParticles() {
    var box = document.getElementById("settingsParticles");
    if (!box) return;
    box.innerHTML = "";
    for (var i = 0; i < 50; i++) {
      var p = document.createElement("div");
      p.className = "settings-particle";
      var angle = Math.random() * Math.PI * 2;
      var distance = 300 + Math.random() * 400;
      p.style.left = 50 + (Math.random() - 0.5) * 10 + "%";
      p.style.top = 50 + (Math.random() - 0.5) * 10 + "%";
      p.style.setProperty("--tx", Math.cos(angle) * distance + "px");
      p.style.setProperty("--ty", Math.sin(angle) * distance + "px");
      p.style.animation = "particleAssemble " + (0.6 + Math.random() * 0.4) + "s cubic-bezier(0.22, 1, 0.36, 1) " + Math.random() * 0.3 + "s forwards";
      box.appendChild(p);
    }
    setTimeout(function () { box.innerHTML = ""; }, 1500);
  }

  function bindUi(root) {
    var modal = document.getElementById("createModal");
    var settingsOverlay = document.getElementById("settingsOverlay");
    var mainContainer = document.getElementById("rcDashMain");

    function forceShowOverlay(el, cardSel) {
      if (!el) return;
      el.classList.add("active");
      el.classList.remove("slide-out");
      el.style.setProperty("transform", "none", "important");
      el.style.setProperty("opacity", "1", "important");
      el.style.setProperty("visibility", "visible", "important");
      el.style.setProperty("pointer-events", "auto", "important");
      var card = cardSel ? el.querySelector(cardSel) : null;
      if (card) {
        card.style.setProperty("opacity", "1", "important");
        card.style.setProperty("transform", "none", "important");
        card.style.setProperty("visibility", "visible", "important");
      }
      document.body.style.overflow = "hidden";
    }
    function clearOverlayInline(el, cardSel) {
      if (!el) return;
      el.style.removeProperty("transform");
      el.style.removeProperty("opacity");
      el.style.removeProperty("visibility");
      el.style.removeProperty("pointer-events");
      var card = cardSel ? el.querySelector(cardSel) : null;
      if (card) {
        card.style.removeProperty("opacity");
        card.style.removeProperty("transform");
        card.style.removeProperty("visibility");
      }
    }
    function closeModal() {
      var card = modal.querySelector(".modal-card");
      if (card) {
        card.classList.remove("tilt-active");
        card.style.transform = "";
        card.style.boxShadow = "";
        card.style.background = "";
      }
      modal.classList.add("slide-out");
      modal.classList.remove("active");
      clearOverlayInline(modal, ".modal-card");
      setTimeout(function () {
        modal.classList.remove("slide-out");
        if (mainContainer) mainContainer.classList.remove("slide-out");
        document.body.style.overflow = "";
      }, 280);
    }
    function closeSettings() {
      settingsOverlay.classList.add("slide-out");
      settingsOverlay.classList.remove("active");
      clearOverlayInline(settingsOverlay, ".settings-card");
      var isModal = document.documentElement.classList.contains("rc-dash-modal");
      setTimeout(function () {
        settingsOverlay.classList.remove("slide-out");
        if (mainContainer) mainContainer.classList.remove("slide-out");
        document.body.style.overflow = "";
        if (isModal && window.unmountRcDash) window.unmountRcDash();
      }, 280);
    }
    function openSettings() {
      var overlay = document.getElementById("settingsOverlay") || settingsOverlay;
      if (!overlay) return;
      if (overlay.classList.contains("active")) return;
      overlay.classList.remove("slide-out");
      spawnParticles();
      forceShowOverlay(overlay, ".settings-card");
      if (mainContainer) mainContainer.classList.add("slide-out");
    }
    window.openRcDashSettings = openSettings;

    function openCreateFromUi() {
      if (!modal) return;
      modal.classList.remove("slide-out");
      forceShowOverlay(modal, ".modal-card");
      if (mainContainer) mainContainer.classList.add("slide-out");
      setTimeout(function () {
        var card = modal.querySelector(".modal-card");
        if (card) card.classList.add("tilt-active");
      }, 200);
    }
    window.openRcDashCreate = openCreateFromUi;

    document.getElementById("rcCreateBtn").addEventListener("click", function (e) {
      e.preventDefault();
      openCreateFromUi();
    });
    document.getElementById("rcSettingsBtn").addEventListener("click", function (e) {
      e.preventDefault();
      openSettings();
    });
    document.getElementById("rcLogoutBtn").addEventListener("click", function (e) {
      e.preventDefault();
      try {
        localStorage.removeItem("access_token");
        localStorage.removeItem("token");
      } catch (_) {}
      api("DELETE", "/auth/sessions").catch(function () {});
      location.replace("/client/auth");
    });
    document.getElementById("modalClose").addEventListener("click", closeModal);
    document.getElementById("btnBack").addEventListener("click", closeModal);
    document.getElementById("closeSettings").addEventListener("click", closeSettings);
    settingsOverlay.addEventListener("click", function (e) {
      if (e.target === settingsOverlay) closeSettings();
    });
    modal.addEventListener("click", function (e) { if (e.target === modal) closeModal(); });

    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      var opened = root.querySelector(".rc-drop.open");
      if (opened) {
        opened.classList.remove("open");
        var openedMenu = opened._rcMenu;
        if (openedMenu) {
          openedMenu.classList.remove("is-open");
          if (openedMenu.parentNode !== opened) opened.appendChild(openedMenu);
        }
        return;
      }
      if (settingsOverlay.classList.contains("active")) closeSettings();
      else if (modal.classList.contains("active")) closeModal();
    });

    var nameInp = document.getElementById("projectName");
    var slugInp = document.getElementById("projectSlug");
    var slugTouched = false;
    slugInp.addEventListener("input", function () { slugTouched = true; });
    nameInp.addEventListener("input", function () {
      if (!slugTouched) slugInp.value = slugify(nameInp.value);
    });

    var uploadZone = document.getElementById("uploadZone");
    var fileInput = document.getElementById("fileInput");
    var uploadPreview = document.getElementById("uploadPreview");
    uploadZone.addEventListener("click", function () { fileInput.click(); });
    fileInput.addEventListener("change", function () {
      if (fileInput.files[0]) handleFile(fileInput.files[0]);
    });
    uploadZone.addEventListener("dragover", function (e) {
      e.preventDefault();
      uploadZone.style.borderColor = "rgba(255,255,255,0.4)";
    });
    uploadZone.addEventListener("drop", function (e) {
      e.preventDefault();
      if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
    });
    document.getElementById("removeFile").addEventListener("click", function (e) {
      e.stopPropagation();
      fileInput.value = "";
      state.logoData = "";
      uploadPreview.classList.remove("active");
      uploadZone.style.display = "";
    });
    function handleFile(file) {
      if (!file.type.match(/image\/(png|jpeg|gif|webp)/)) return toast("Нужен PNG, JPEG или GIF", true);
      if (file.size > 10 * 1024 * 1024) return toast("Файл больше 10 МБ", true);
      var reader = new FileReader();
      reader.onload = function () {
        state.logoData = reader.result;
        document.getElementById("previewImg").src = reader.result;
        document.getElementById("previewName").textContent = file.name;
        document.getElementById("previewSize").textContent = (file.size / 1024).toFixed(1) + " КБ";
        uploadZone.style.display = "none";
        uploadPreview.classList.add("active");
      };
      reader.readAsDataURL(file);
    }

    document.getElementById("createForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var name = nameInp.value.trim();
      var slug = slugify(slugInp.value || name);
      if (!name || !slug) return toast("Укажите название и ссылку", true);
      var btn = e.target.querySelector(".btn-continue");
      btn.disabled = true;
      api("POST", "/project", { name: name, domain: slug, avatar: state.logoData || "" })
        .then(function (created) {
          closeModal();
          nameInp.value = "";
          slugInp.value = "";
          slugTouched = false;
          state.logoData = "";
          fileInput.value = "";
          uploadPreview.classList.remove("active");
          uploadZone.style.display = "";
          toast('Проект "' + name + '" создан');
          var domain = (created && (created.domain || created.tag)) || slug;
          return reload().then(function () { go("/" + domain + "/players"); });
        })
        .catch(function (err) {
          toast(err.message || tr("createFail"), true);
        })
        .then(function () { btn.disabled = false; });
    });

    document.querySelectorAll("#rc-dash .settings-nav-item").forEach(function (item) {
      item.addEventListener("click", function () {
        if (item.classList.contains("active")) return;
        var next = document.getElementById("tab-" + item.dataset.tab);
        var current = document.querySelector("#rc-dash .settings-tab.active");
        document.querySelectorAll("#rc-dash .settings-nav-item").forEach(function (n) { n.classList.remove("active"); });
        item.classList.add("active");
        function showNext() {
          document.querySelectorAll("#rc-dash .settings-tab").forEach(function (t) {
            t.classList.remove("active", "fade-out");
          });
          if (!next) return;
          void next.offsetWidth;
          next.classList.add("active");
        }
        if (current && current !== next) {
          current.classList.remove("active");
          current.classList.add("fade-out");
          setTimeout(showNext, 160);
        } else {
          showNext();
        }
      });
    });

    document.getElementById("rcSaveProfile").addEventListener("click", function () {
      var payload = {
        name: document.getElementById("rcSetName").value.trim(),
        tag: document.getElementById("rcSetTag").value.trim().replace(/^@/, ""),
        bio: document.getElementById("rcSetBio").value
      };
      if (state.avatarData) payload.avatar = state.avatarData;
      api("PUT", "/client/profile", payload).then(function (saved) {
        if (saved && typeof saved === "object") state.user = Object.assign({}, state.user || {}, saved);
        renderUser();
        toast("Профиль сохранён");
      }).catch(function (err) {
        toast(err.message || "Не удалось сохранить", true);
      });
    });

    document.getElementById("rcChangeAvatar").addEventListener("click", function () {
      document.getElementById("rcAvatarFile").click();
    });
    document.getElementById("rcAvatarFile").addEventListener("change", function () {
      var file = this.files && this.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function () {
        state.avatarData = reader.result;
        renderUser();
      };
      reader.readAsDataURL(file);
    });

    document.getElementById("rcSteamBtn").addEventListener("click", function () {
      if (this.classList.contains("unavailable")) return;
      if (this.classList.contains("rc-unlink")) {
        var button = this;
        button.disabled = true;
        api("DELETE", "/auth/steam-connect").then(function () { state.user.steam = null; state.user.steam_id = ""; if (state.user.integrations && state.user.integrations.steam) state.user.integrations.steam.connected = false; renderUser(); return reload(); }).catch(function (err) {
          toast(err.message || "Не удалось отвязать аккаунт", true);
        }).finally(function () { button.disabled = false; });
        return;
      }
      location.href = "/auth/steam-connect?return_url=" + encodeURIComponent(location.origin + "/client/profile");
    });
    document.getElementById("rcDiscordBtn").addEventListener("click", function () {
      if (this.classList.contains("unavailable")) return;
      if (this.classList.contains("rc-unlink")) {
        var button = this;
        button.disabled = true;
        api("DELETE", "/auth/discord-connect").then(function () { state.user.discord = null; state.user.discord_id = ""; localStorage.removeItem("ca_discord_link"); if (state.user.integrations && state.user.integrations.discord) state.user.integrations.discord.connected = false; renderUser(); return reload(); }).catch(function (err) {
          toast(err.message || "Не удалось отвязать аккаунт", true);
        }).finally(function () { button.disabled = false; });
        return;
      }
      location.href = "/auth/discord-connect?return_url=" + encodeURIComponent(location.origin + "/client/profile");
    });
    document.getElementById("rc2fa").addEventListener("click", function () {
      go("/client/profile");
      toast("Откройте безопасность в панели или подтвердите 2FA в аккаунте");
    });

    ["rcAnim", "rcNotif", "rcSound"].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("click", function () {
        el.classList.toggle("on");
        localStorage.setItem("rc-ui-" + id, el.classList.contains("on") ? "1" : "0");
      });
    });

    root.querySelectorAll("[data-legal]").forEach(function (a) {
      a.addEventListener("click", function (e) {
        e.preventDefault();
        openLegal(a.getAttribute("data-legal"));
      });
    });

    var dropLock = 0;
    function closeDrops(except) {
      root.querySelectorAll(".rc-drop").forEach(function (drop) {
        if (drop === except) return;
        drop.classList.remove("open");
        var menu = drop._rcMenu;
        if (!menu) return;
        menu.classList.remove("is-open");
        menu.style.top = "";
        menu.style.bottom = "";
        menu.style.right = "";
        menu.style.left = "";
        if (menu.parentNode !== drop) drop.appendChild(menu);
      });
    }
    function placeDropMenu(drop) {
      var btn = drop.querySelector(".rc-drop-btn");
      var menu = drop._rcMenu;
      if (!btn || !menu) return;
      var host = document.getElementById("rc-dash") || document.body;
      host.appendChild(menu);
      menu.classList.add("is-open");
      menu.style.zIndex = "1000100";
      var r = btn.getBoundingClientRect();
      var minW = Math.max(r.width + 24, 124);
      menu.style.minWidth = minW + "px";
      menu.style.left = Math.round(r.right - minW) + "px";
      menu.style.right = "auto";
      var h = menu.offsetHeight || 120;
      if (window.innerHeight - r.bottom < h + 16) {
        menu.style.top = "auto";
        menu.style.bottom = Math.round(window.innerHeight - r.top + 6) + "px";
      } else {
        menu.style.bottom = "auto";
        menu.style.top = Math.round(r.bottom + 6) + "px";
      }
    }
    root.querySelectorAll(".rc-drop").forEach(function (drop) {
      var btn = drop.querySelector(".rc-drop-btn");
      var label = drop.querySelector(".rc-drop-label");
      var menu = drop.querySelector(".rc-drop-menu");
      drop._rcMenu = menu;
      menu.addEventListener("click", function (e) { e.stopPropagation(); });
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var willOpen = !drop.classList.contains("open");
        dropLock += 1;
        closeDrops();
        if (willOpen) {
          drop.classList.add("open");
          placeDropMenu(drop);
        }
        setTimeout(function () { dropLock = Math.max(0, dropLock - 1); }, 120);
      });
      menu.querySelectorAll(".rc-drop-item").forEach(function (item) {
        item.addEventListener("click", function (e) {
          e.preventDefault();
          e.stopPropagation();
          var v = item.getAttribute("data-v");
          drop.setAttribute("data-value", v);
          label.textContent = item.textContent;
          menu.querySelectorAll(".rc-drop-item").forEach(function (n) { n.classList.remove("active"); });
          item.classList.add("active");
          if (drop.id === "rcLang") {
            applyLang(v);
          } else if (drop.id === "rcBm") {
            localStorage.setItem("rc-ui-rcBm", v);
          } else if (drop.id === "rcConfirmChat") {
            localStorage.setItem("rc-ui-rcConfirmChat", v);
          }
          closeDrops();
        });
      });
    });
    document.addEventListener("click", function (e) {
      if (dropLock) return;
      var t = e.target;
      if (t && t.closest && (t.closest(".rc-drop") || t.closest(".rc-drop-menu"))) return;
      closeDrops();
    }, true);
    var settingsPane = document.querySelector(".settings-content");
    if (settingsPane) settingsPane.addEventListener("scroll", function () { if (!dropLock) closeDrops(); });

    var modalCard = document.querySelector(".modal-card");
    var maxTilt = 15;
    var proximity = 50;
    var currentRotateX = 0;
    var currentRotateY = 0;
    var targetRotateX = 0;
    var targetRotateY = 0;
    var isTiltActive = false;
    function lerp(a, b, t) { return a + (b - a) * t; }
    function dashAlive() { return !!document.getElementById("rc-dash"); }
    function animateTilt() {
      if (!dashAlive() || !modalCard) return;
      currentRotateX = lerp(currentRotateX, targetRotateX, 0.12);
      currentRotateY = lerp(currentRotateY, targetRotateY, 0.12);
      if (modal.classList.contains("active") && modalCard.classList.contains("tilt-active")) {
        var scale = isTiltActive ? 1.02 : 1;
        modalCard.style.transform = "perspective(1000px) rotateX(" + currentRotateX + "deg) rotateY(" + currentRotateY + "deg) scale3d(" + scale + "," + scale + ",1)";
        modalCard.style.boxShadow = "0 8px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.1), " + (currentRotateY / maxTilt) * 12 + "px " + (-currentRotateX / maxTilt) * 12 + "px 50px rgba(0,0,0,0.5)";
      }
      requestAnimationFrame(animateTilt);
    }
    requestAnimationFrame(animateTilt);
    document.addEventListener("mousemove", function (e) {
      if (!dashAlive() || !modal.classList.contains("active") || !modalCard || !modalCard.classList.contains("tilt-active")) return;
      var rect = modalCard.getBoundingClientRect();
      var centerX = rect.left + rect.width / 2;
      var centerY = rect.top + rect.height / 2;
      var dx = e.clientX - centerX;
      var dy = e.clientY - centerY;
      var dist = Math.sqrt(dx * dx + dy * dy);
      var inside = e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top && e.clientY <= rect.bottom;
      if (inside) {
        var x = e.clientX - rect.left;
        var y = e.clientY - rect.top;
        targetRotateX = ((y - rect.height / 2) / (rect.height / 2)) * -maxTilt;
        targetRotateY = ((x - rect.width / 2) / (rect.width / 2)) * maxTilt;
        isTiltActive = true;
        modalCard.style.background = "radial-gradient(circle at " + (x / rect.width) * 100 + "% " + (y / rect.height) * 100 + "%, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.04) 50%, rgba(255,255,255,0.02) 100%)";
      } else if (dist < proximity + Math.max(rect.width, rect.height) / 2) {
        var pull = 1 - (dist / (proximity + Math.max(rect.width, rect.height) / 2));
        var clampedDx = Math.max(-1, Math.min(1, dx / (rect.width / 2)));
        var clampedDy = Math.max(-1, Math.min(1, dy / (rect.height / 2)));
        targetRotateX = clampedDy * -maxTilt * pull;
        targetRotateY = clampedDx * maxTilt * pull;
        isTiltActive = false;
        modalCard.style.background = "radial-gradient(circle at " + (50 + clampedDx * 30) + "% " + (50 + clampedDy * 30) + "%, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.02) 100%)";
      } else {
        targetRotateX = 0;
        targetRotateY = 0;
        isTiltActive = false;
        modalCard.style.background = "rgba(255,255,255,0.03)";
      }
    });
  }

  function reload() {
    if (!token()) {
      location.replace("/client/auth");
      return Promise.resolve();
    }
    return Promise.all([
      api("GET", "/auth/handshake").catch(function () { return api("GET", "/client"); }),
      api("GET", "/project"),
      api("GET", "/auth/sessions").catch(function () { return []; })
    ]).then(function (rows) {
      var user = rows[0];
      if (!user || user.unauthorized || user.message === "unauthorized") {
        location.replace("/client/auth");
        return;
      }
      state.user = user;
      state.projects = Array.isArray(rows[1]) ? rows[1] : (rows[1] && rows[1].projects) || [];
      state.sessions = Array.isArray(rows[2]) ? rows[2] : (rows[2] && rows[2].items) || [];
      renderUser();
      renderProjects();
      renderSettingsProjects();
      renderSessions();
    }).catch(function (err) {
      if (err && err.status === 401) location.replace("/client/auth");
      else toast(err && err.message ? err.message : tr("loadFail"), true);
    });
  }

  function wantSettingsOpen() {
    if (location.hash === "#settings" || /(?:\?|&)settings=1(?:&|$)/.test(location.search || "")) return true;
    try {
      if (sessionStorage.getItem("rc-open-settings") === "1") {
        sessionStorage.removeItem("rc-open-settings");
        return true;
      }
    } catch (_) {}
    return false;
  }

  function wantCreateOpen() {
    if (location.hash === "#create" || /(?:\?|&)create=1(?:&|$)/.test(location.search || "")) return true;
    try {
      if (sessionStorage.getItem("rc-open-create") === "1") {
        sessionStorage.removeItem("rc-open-create");
        return true;
      }
    } catch (_) {}
    return false;
  }

  function openCreateModal() {
    var modal = document.getElementById("createModal");
    var mainContainer = document.getElementById("rcDashMain");
    if (!modal) return;
    modal.classList.add("active");
    modal.classList.remove("slide-out");
    modal.style.setProperty("transform", "none", "important");
    modal.style.setProperty("opacity", "1", "important");
    modal.style.setProperty("visibility", "visible", "important");
    var card = modal.querySelector(".modal-card");
    if (card) {
      card.style.setProperty("opacity", "1", "important");
      card.style.setProperty("transform", "none", "important");
      card.classList.add("tilt-active");
    }
    if (mainContainer) mainContainer.classList.add("slide-out");
    document.body.style.overflow = "hidden";
  }
  window.openRcDashCreate = openCreateModal;

  window.mountRcDash = function (opts) {
    opts = opts || {};
    var modal = !!opts.modal;
    var existing = document.getElementById("rc-dash");
    if (existing && modal !== document.documentElement.classList.contains("rc-dash-modal")) {
      existing.remove();
      existing = null;
      document.documentElement.classList.remove("rc-dash-on", "rc-dash-modal");
    }
    document.documentElement.classList.toggle("rc-dash-on", !modal);
    document.documentElement.classList.toggle("rc-dash-modal", modal);
    document.documentElement.classList.remove("rc-profile-on");
    var leftover = document.getElementById("rc-profile-bg");
    if (leftover) leftover.remove();
    if (document.getElementById("rc-dash")) {
      if ((wantSettingsOpen() || modal) && window.openRcDashSettings) window.openRcDashSettings();
      else if (wantCreateOpen() && window.openRcDashCreate) window.openRcDashCreate();
      return;
    }
    var cssHref = "/rc-dash.css?v=15";
    if (!document.getElementById("rc-dash-css")) {
      var link = document.createElement("link");
      link.id = "rc-dash-css";
      link.rel = "stylesheet";
      link.href = cssHref;
      document.head.appendChild(link);
    } else if (document.getElementById("rc-dash-css").getAttribute("href") !== cssHref) {
      document.getElementById("rc-dash-css").href = cssHref;
    }
    var oldCrit = document.getElementById("rc-dash-critical");
    if (oldCrit) oldCrit.remove();
    if (!document.getElementById("rc-dash-critical")) {
      var crit = document.createElement("style");
      crit.id = "rc-dash-critical";
      crit.textContent =
        "#rc-dash{position:relative;z-index:99990;min-height:100vh;width:100%;overflow:hidden}" +
        "html.rc-dash-on,html.rc-dash-on body{overflow:hidden!important;background:#050505!important}" +
        "#rc-dash .dash-bg:after,#rc-dash .bg-animation::after{max-width:min(760px,100vw);max-height:min(760px,100vh)}" +
        "#rc-dash .glass-card{max-width:360px;width:100%;margin:0 auto}" +
        "#rc-dash .modal-overlay,#rc-dash .settings-overlay{position:fixed!important;inset:0!important;z-index:100001!important;" +
        "display:flex!important;justify-content:center!important;align-items:center!important;" +
        "background:rgba(5,5,5,.35)!important;transform:translateX(100%);opacity:0;visibility:hidden;pointer-events:none}" +
        "#rc-dash .modal-overlay.active,#rc-dash .settings-overlay.active{" +
        "transform:none!important;opacity:1!important;visibility:visible!important;pointer-events:auto!important}" +
        "#rc-dash .modal-overlay.active .modal-card,#rc-dash .settings-overlay.active .settings-card{" +
        "opacity:1!important;transform:none!important;visibility:visible!important}" +
        "#rc-dash .modal-card{max-width:320px;width:100%;transform:translateX(60px);opacity:0}" +
        "#rc-dash .settings-card{max-width:680px;width:100%;min-height:420px;opacity:0;transform:scale(.96)}" +
        "#rc-dash .container.slide-out{transform:translateX(-24%);opacity:0;pointer-events:none}";
      document.head.appendChild(crit);
    }
    var root = document.createElement("div");
    root.id = "rc-dash";
    root.innerHTML = markup();
    document.body.appendChild(root);
    bindUi(root);
    applyLang(localStorage.getItem("rustcheck-lang") || "ru");
    reload();
    if (wantSettingsOpen() || modal) window.openRcDashSettings();
    else if (wantCreateOpen()) openCreateModal();
  };

  window.unmountRcDash = function () {
    var el = document.getElementById("rc-dash");
    if (el) el.remove();
    document.documentElement.classList.remove("rc-dash-on", "rc-dash-modal");
    document.body.style.overflow = "";
  };
})();
