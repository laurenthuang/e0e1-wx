// ==UserScript==
// @name 测试注入脚本
// @description 默认测试用 JS，用于验证 e0e1 JS 注入链路是否可用。
// @match *
// @run-at document-start
// ==/UserScript==

(function () {
  "use strict";

  // 写入一个无侵入的全局标记，便于在 DevTools 控制台确认是否已注入。
  var marker = {
    name: "e0e1-test-injection",
    injectedAt: new Date().toISOString(),
  };

  globalThis.__e0e1TestInjection = marker;
  console.log("[e0e1] 测试注入脚本已执行", marker);

  // 小程序环境优先用 wx.showModal，普通 JS Runtime 回退到 alert。
  if (globalThis.wx && typeof globalThis.wx.showModal === "function") {
    globalThis.wx.showModal({
      title: "e0e1 JS注入测试",
      content: "测试注入脚本已执行",
      showCancel: false,
    });
  } else if (typeof globalThis.alert === "function") {
    globalThis.alert("e0e1 JS注入测试：测试注入脚本已执行");
  }
})();
