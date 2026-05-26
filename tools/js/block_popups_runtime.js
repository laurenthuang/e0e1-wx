// ==UserScript==
// @name 拦截弹窗
// @description 在当前小程序 runtime 中拦截 showModal、showToast、alert、confirm、prompt，并支持取消注入恢复原始行为。
// @e0e1-mode runtime_toggle
// ==/UserScript==
(function registerPopupBlocker() {
  if (typeof globalThis.__e0e1RegisterRuntimeToggle !== "function") {
    throw new Error("e0e1 runtime toggle bridge unavailable");
  }

  const originals = Object.create(null);
  let enabled = false;
  let blockedCount = 0;

  function report(message) {
    if (typeof globalThis.__e0e1JsInjectionReport === "function") {
      globalThis.__e0e1JsInjectionReport(message);
    }
  }

  function interceptWxMethod(name, factory) {
    if (!globalThis.wx || typeof globalThis.wx[name] !== "function") {
      return;
    }
    if (!originals[name]) {
      originals[name] = globalThis.wx[name];
    }
    globalThis.wx[name] = factory(originals[name]);
  }

  function restoreWxMethod(name) {
    if (!globalThis.wx || typeof originals[name] !== "function") {
      return;
    }
    globalThis.wx[name] = originals[name];
  }

  globalThis.__e0e1RegisterRuntimeToggle({
    async enable() {
      if (enabled) {
        return { ok: true, enabled: true, message: "拦截弹窗已启用", log: "blocked=" + blockedCount };
      }

      interceptWxMethod("showModal", function () {
        return function (options) {
          blockedCount += 1;
          if (options && typeof options.success === "function") {
            options.success({ confirm: true, cancel: false, errMsg: "showModal:ok" });
          }
          if (options && typeof options.complete === "function") {
            options.complete({ confirm: true, cancel: false, errMsg: "showModal:ok" });
          }
          return Promise.resolve({ confirm: true, cancel: false, errMsg: "showModal:ok" });
        };
      });

      interceptWxMethod("showToast", function () {
        return function (options) {
          blockedCount += 1;
          if (options && typeof options.success === "function") {
            options.success({ errMsg: "showToast:ok" });
          }
          if (options && typeof options.complete === "function") {
            options.complete({ errMsg: "showToast:ok" });
          }
          return Promise.resolve({ errMsg: "showToast:ok" });
        };
      });

      if (typeof globalThis.alert === "function" && !originals.alert) {
        originals.alert = globalThis.alert;
        globalThis.alert = function () {
          blockedCount += 1;
        };
      }

      if (typeof globalThis.confirm === "function" && !originals.confirm) {
        originals.confirm = globalThis.confirm;
        globalThis.confirm = function () {
          blockedCount += 1;
          return true;
        };
      }

      if (typeof globalThis.prompt === "function" && !originals.prompt) {
        originals.prompt = globalThis.prompt;
        globalThis.prompt = function (_message, defaultValue) {
          blockedCount += 1;
          return typeof defaultValue === "string" ? defaultValue : "";
        };
      }

      enabled = true;
      report("拦截弹窗已启用");
      return { ok: true, enabled: true, message: "拦截弹窗已启用", log: "blocked=" + blockedCount };
    },

    async disable() {
      if (!enabled) {
        return { ok: true, enabled: false, message: "拦截弹窗已关闭", log: "blocked=" + blockedCount };
      }

      restoreWxMethod("showModal");
      restoreWxMethod("showToast");

      if (typeof originals.alert === "function") {
        globalThis.alert = originals.alert;
      }
      if (typeof originals.confirm === "function") {
        globalThis.confirm = originals.confirm;
      }
      if (typeof originals.prompt === "function") {
        globalThis.prompt = originals.prompt;
      }

      enabled = false;
      report("拦截弹窗已关闭");
      return { ok: true, enabled: false, message: "拦截弹窗已关闭", log: "blocked=" + blockedCount };
    },

    status() {
      return {
        ok: true,
        enabled: enabled,
        message: enabled ? "拦截弹窗已启用" : "拦截弹窗已关闭",
        log: "blocked=" + blockedCount,
      };
    },
  });
})();
