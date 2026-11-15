/**
 * Local notification cleanup. Loaded separately from the API bridge.
 */
(function () {
  "use strict";

  function isBadToast(el) {
    if (!el || el.nodeType !== 1) return false;
    const text = String(el.textContent || "").replace(/\s+/g, " ").trim();
    return Boolean(text) && /unhandled-exception|Ошибка подключения к серверу авторизации|переподключаемся|Нет соединения с сервисом|No connection to the service|network-error|Мы уже получили сигнал|уже получили сигнал о проблеме|Не удалось подключиться к серверу событий|Failed to connect to the event server/i.test(text);
  }

  function sweep(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll(".notification,[class*='notification'],[class*='n-message'],[class*='n-notification'],[class*='runtime'],[class*='toast']").forEach(function (el) {
      if (!isBadToast(el)) return;
      const box = el.closest(".notification,[class*='notification'],[class*='runtime'],[class*='toast']") || el;
      try { box.remove(); } catch (_) { box.style.display = "none"; }
    });
  }

  let pending = false;
  function schedule() {
    if (pending) return;
    pending = true;
    setTimeout(function () {
      pending = false;
      sweep(document);
    }, 500);
  }

  window.addEventListener("load", function () {
    sweep(document);
    new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true });
  }, { once: true });
})();
