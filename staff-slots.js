/* Keep the original staff cards and only extend their own grid to 20 places. */
(() => {
  "use strict";
  const CAPACITY = 20;
  const SLOT_CLASS = "checkapp-native-staff-slot";

  function isStaffRoute() {
    return /\/settings\/clients(?:\/|$)/.test(location.pathname);
  }

  function warningNode() {
    return Array.from(document.querySelectorAll("h1,h2,h3,h4,strong,b,div,p"))
      .find((el) => (el.textContent || "").trim() === "Ответственный подход к правам доступа");
  }

  function findNativeGrid() {
    const warning = warningNode();
    if (!warning) return null;
    const warningTop = warning.getBoundingClientRect().top;
    const candidates = Array.from(document.querySelectorAll("div")).filter((el) => {
      const rect = el.getBoundingClientRect();
      const cards = Array.from(el.children).filter((child) => child instanceof HTMLElement);
      if (cards.length < 2 || cards.length > CAPACITY || rect.width < 280 || rect.top >= warningTop || rect.bottom > warningTop + 8) return false;
      const imageCards = cards.filter((card) => card.querySelector("img")).length;
      return imageCards > 0 && !/Ответственный подход/.test(el.textContent || "");
    });
    candidates.sort((a, b) => {
      const ai = a.querySelectorAll("img").length;
      const bi = b.querySelectorAll("img").length;
      return bi - ai || b.children.length - a.children.length || b.getBoundingClientRect().top - a.getBoundingClientRect().top;
    });
    return candidates[0] || null;
  }

  function extendNativeGrid() {
    if (!isStaffRoute()) return;
    // Remove the old custom grid if this script is loaded after an SPA update.
    const old = document.getElementById("checkapp-staff-capacity");
    if (old) old.remove();

    const grid = findNativeGrid();
    if (!grid) return;
    grid.querySelectorAll(`.${SLOT_CLASS}`).forEach((slot) => slot.remove());
    const cards = Array.from(grid.children).filter((child) => child instanceof HTMLElement);
    if (!cards.length || cards.length >= CAPACITY) return;
    // The SPA already renders one blank native card. Clone it so every added
    // place has precisely the same design, dimensions and background.
    const blank = cards.find((card) => !card.querySelector("img") && !(card.textContent || "").trim()) || cards[cards.length - 1];
    const missing = CAPACITY - cards.length;
    for (let i = 0; i < missing; i += 1) {
      const slot = blank.cloneNode(true);
      slot.classList.add(SLOT_CLASS);
      slot.setAttribute("aria-hidden", "true");
      grid.appendChild(slot);
    }
  }

  let scheduled = false;
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      extendNativeGrid();
    });
  }
  window.addEventListener("popstate", schedule);
  window.addEventListener("hashchange", schedule);
  new MutationObserver((records) => {
    const grid = findNativeGrid();
    if (!grid || records.some((record) => !grid.contains(record.target))) schedule();
  }).observe(document.documentElement, { childList: true, subtree: true });
  schedule();
})();
