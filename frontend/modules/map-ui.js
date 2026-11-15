/** Hide the unavailable map entry without touching unrelated page logic. */
(function () {
  "use strict";

  function hideMapUi() {
    document.querySelectorAll("a, button, [role='tab'], li, span").forEach(function (el) {
      if (el.children && el.children.length > 3) return;
      const href = String((el.getAttribute && el.getAttribute("href")) || "").toLowerCase();
      const text = String(el.textContent || "").replace(/\s+/g, " ").trim();
      if (/^карта$/i.test(text) || /^map$/i.test(text) || /^live map$/i.test(text) || /^live-карта$/i.test(text) || /\/map(?:\/|$|\?)/.test(href)) {
        const node = el.closest("li") || el;
        node.style.setProperty("display", "none", "important");
        node.setAttribute("data-checkapp-hide", "1");
      }
    });
  }

  window.addEventListener("load", hideMapUi, { once: true });
  document.addEventListener("checkapp-route-changed", hideMapUi);
})();
