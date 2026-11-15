/* Render the project team as exactly twenty places: real members first,
   then neutral empty cards.  This is kept separate from the vendor SPA. */
(() => {
  "use strict";
  const CAPACITY = 20;
  const STYLE_ID = "checkapp-staff-capacity-style";
  const ROOT_ID = "checkapp-staff-capacity";

  const esc = (value) => String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/\"/g, "&quot;").replace(/'/g, "&#039;");

  function isStaffRoute() {
    return /\/settings\/clients(?:\/|$)/.test(location.pathname);
  }

  function addStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      #${ROOT_ID}{display:grid;grid-template-columns:repeat(auto-fill,minmax(134px,1fr));gap:10px;margin:12px 0 28px;max-width:100%;}
      #${ROOT_ID} .ca-staff-card{position:relative;min-height:122px;border-radius:5px;background:#181818;box-sizing:border-box;padding:20px 12px 12px;text-align:center;overflow:hidden;}
      #${ROOT_ID} .ca-staff-card.ca-owner{background:linear-gradient(135deg,#1d3042,#17202c);}
      #${ROOT_ID} .ca-staff-card.ca-staff{cursor:default;}
      #${ROOT_ID} .ca-staff-card.ca-empty{background:#191919;min-height:122px;}
      #${ROOT_ID} .ca-staff-avatar{display:block;width:48px;height:48px;border-radius:50%;object-fit:cover;background:#303030;margin:0 auto 8px;}
      #${ROOT_ID} .ca-staff-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#f6f6f6;font-weight:700;font-size:14px;line-height:18px;}
      #${ROOT_ID} .ca-staff-tag{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#8c96a5;font-size:13px;line-height:17px;}
      #${ROOT_ID} .ca-staff-crown{position:absolute;top:10px;left:10px;color:#f7c766;font-size:17px;line-height:17px;}
      #${ROOT_ID} .ca-staff-empty-dot{width:48px;height:48px;border-radius:50%;background:#303030;margin:18px auto;opacity:.7;}
    `;
    document.head.appendChild(style);
  }

  function textIs(el, text) {
    return (el && (el.textContent || "").trim() === text);
  }

  function findWarning() {
    return Array.from(document.querySelectorAll("h1,h2,h3,h4,strong,b,div,p"))
      .find((el) => textIs(el, "Ответственный подход к правам доступа"));
  }

  function findNativeGrid(warning) {
    if (!warning) return null;
    const warningTop = warning.getBoundingClientRect().top;
    const scope = warning.parentElement;
    if (!scope) return null;
    const candidates = Array.from(scope.querySelectorAll("div")).filter((el) => {
      const rect = el.getBoundingClientRect();
      const children = Array.from(el.children);
      const images = el.querySelectorAll("img").length;
      return images > 0 && children.length >= 2 && children.length <= CAPACITY + 2 &&
        rect.top < warningTop && rect.bottom <= warningTop + 8 &&
        !/Ответственный подход/.test(el.textContent || "");
    });
    candidates.sort((a, b) => b.querySelectorAll("img").length - a.querySelectorAll("img").length ||
      b.children.length - a.children.length);
    return candidates[0] || null;
  }

  async function loadMembers() {
    const slug = (location.pathname.split("/").filter(Boolean)[0] || "").trim();
    if (!slug) return [];
    const response = await fetch(`/project/${encodeURIComponent(slug)}/clients`, { credentials: "same-origin" });
    if (!response.ok) throw new Error("staff request failed");
    const payload = await response.json();
    const rows = Array.isArray(payload && payload.active) ? payload.active : [];
    return rows.slice(0, CAPACITY);
  }

  function memberCard(row) {
    const client = row && row.client && typeof row.client === "object" ? row.client : (row || {});
    const name = client.name || client.username || client.tag || "Сотрудник";
    const tag = client.tag || client.username || "";
    const avatar = client.avatar || "/local/image-1024.jpg";
    const owner = !!(row && row.is_owner);
    return `<div class="ca-staff-card ca-staff${owner ? " ca-owner" : ""}">
      ${owner ? '<span class="ca-staff-crown" aria-label="Владелец">♛</span>' : ""}
      <img class="ca-staff-avatar" src="${esc(avatar)}" alt="">
      <div class="ca-staff-name" title="${esc(name)}">${esc(name)}</div>
      <div class="ca-staff-tag" title="${esc(tag)}">${tag ? "@" + esc(String(tag).replace(/^@+/, "")) : ""}</div>
    </div>`;
  }

  function emptyCard() {
    return '<div class="ca-staff-card ca-empty" aria-label="Свободное место"><div class="ca-staff-empty-dot"></div></div>';
  }

  async function render() {
    if (!isStaffRoute()) return;
    const warning = findWarning();
    if (!warning) return;
    let root = document.getElementById(ROOT_ID);
    if (!root) {
      root = document.createElement("div");
      root.id = ROOT_ID;
      const nativeGrid = findNativeGrid(warning);
      if (nativeGrid) nativeGrid.style.display = "none";
      warning.parentElement.insertBefore(root, warning);
    }
    try {
      const members = await loadMembers();
      root.innerHTML = members.map(memberCard).join("") + Array.from({ length: Math.max(0, CAPACITY - members.length) }, emptyCard).join("");
    } catch (_) {
      root.innerHTML = Array.from({ length: CAPACITY }, emptyCard).join("");
    }
  }

  let timer = 0;
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(render, 120);
  }
  addStyle();
  window.addEventListener("popstate", schedule);
  window.addEventListener("hashchange", schedule);
  new MutationObserver((records) => {
    const root = document.getElementById(ROOT_ID);
    // Updating our own twenty cards also mutates the DOM.  Ignore those
    // mutations so a render cannot schedule another render forever.
    if (records.some((record) => !root || (record.target !== root && !root.contains(record.target)))) schedule();
  }).observe(document.documentElement, { childList: true, subtree: true });
  schedule();
})();
