// ==UserScript==
// @name 微信环境信息探测
// @description 采集 wx.getSystemInfoSync 等运行环境信息，并输出到弹窗、控制台和 JS 注入日志。
// @match *
// @run-at document-start
// ==/UserScript==

(function () {
  "use strict";

  // 限制复杂对象的深度和长度，避免日志页被超大对象卡住。
  function sanitize(value, depth) {
    if (depth > 4) {
      return "[MaxDepth]";
    }
    if (value === null || value === undefined) {
      return value;
    }
    var valueType = typeof value;
    if (valueType === "string") {
      return value.length > 500 ? value.slice(0, 500) + "...[truncated]" : value;
    }
    if (valueType === "number" || valueType === "boolean") {
      return value;
    }
    if (valueType === "function") {
      return "[Function " + (value.name || "anonymous") + "]";
    }
    if (Array.isArray(value)) {
      return value.slice(0, 30).map(function (item) {
        return sanitize(item, depth + 1);
      });
    }
    if (valueType === "object") {
      var output = {};
      Object.keys(value)
        .slice(0, 80)
        .forEach(function (key) {
          try {
            output[key] = sanitize(value[key], depth + 1);
          } catch (error) {
            output[key] = "[ReadError " + formatError(error) + "]";
          }
        });
      return output;
    }
    return String(value);
  }

  // 统一格式化异常，方便在日志中定位不可调用 API。
  function formatError(error) {
    if (!error) {
      return "unknown";
    }
    return String(error.stack || error.message || error);
  }

  // 安全调用同步环境函数，失败时保留错误原因。
  function safeCall(label, fn) {
    try {
      if (typeof fn !== "function") {
        return { ok: false, available: false, error: label + " 不存在" };
      }
      return { ok: true, available: true, value: sanitize(fn(), 0) };
    } catch (error) {
      return { ok: false, available: true, error: formatError(error) };
    }
  }

  // 安全读取全局对象字段，避免 getter 抛异常导致脚本中断。
  function safeRead(label, reader) {
    try {
      return { ok: true, value: sanitize(reader(), 0) };
    } catch (error) {
      return { ok: false, error: label + " 读取失败：" + formatError(error) };
    }
  }

  // 生成当前页面栈摘要，避免完整 page 实例过大。
  function currentPagesSummary() {
    if (typeof globalThis.getCurrentPages !== "function") {
      return [];
    }
    return globalThis.getCurrentPages().map(function (page, index) {
      return {
        index: index,
        route: page && page.route,
        options: sanitize(page && page.options, 0),
      };
    });
  }

  // 构建 wx API 可用性和常用同步环境函数结果。
  function buildWxReport(wxObject) {
    var syncCalls = {
      getSystemInfoSync: safeCall("wx.getSystemInfoSync", wxObject && wxObject.getSystemInfoSync),
      getDeviceInfo: safeCall("wx.getDeviceInfo", wxObject && wxObject.getDeviceInfo),
      getWindowInfo: safeCall("wx.getWindowInfo", wxObject && wxObject.getWindowInfo),
      getAppBaseInfo: safeCall("wx.getAppBaseInfo", wxObject && wxObject.getAppBaseInfo),
      getSystemSetting: safeCall("wx.getSystemSetting", wxObject && wxObject.getSystemSetting),
      getAppAuthorizeSetting: safeCall("wx.getAppAuthorizeSetting", wxObject && wxObject.getAppAuthorizeSetting),
      getAccountInfoSync: safeCall("wx.getAccountInfoSync", wxObject && wxObject.getAccountInfoSync),
      getLaunchOptionsSync: safeCall("wx.getLaunchOptionsSync", wxObject && wxObject.getLaunchOptionsSync),
      getEnterOptionsSync: safeCall("wx.getEnterOptionsSync", wxObject && wxObject.getEnterOptionsSync),
      getMenuButtonBoundingClientRect: safeCall(
        "wx.getMenuButtonBoundingClientRect",
        wxObject && wxObject.getMenuButtonBoundingClientRect
      ),
    };

    var functionNames = wxObject
      ? Object.keys(wxObject)
          .filter(function (key) {
            return typeof wxObject[key] === "function";
          })
          .sort()
          .slice(0, 200)
      : [];

    return {
      available: !!wxObject,
      functionCount: functionNames.length,
      functionNames: functionNames,
      canIUse: wxObject && typeof wxObject.canIUse === "function"
        ? {
            getSystemInfoSync: wxObject.canIUse("getSystemInfoSync"),
            getDeviceInfo: wxObject.canIUse("getDeviceInfo"),
            getWindowInfo: wxObject.canIUse("getWindowInfo"),
            getAppBaseInfo: wxObject.canIUse("getAppBaseInfo"),
            getSystemSetting: wxObject.canIUse("getSystemSetting"),
            getAccountInfoSync: wxObject.canIUse("getAccountInfoSync"),
          }
        : {},
      syncCalls: syncCalls,
    };
  }

  // 生成一份可直接写入 JS 注入日志的环境报告。
  function buildReport() {
    var wxObject = globalThis.wx;
    var appInfo = safeRead("getApp", function () {
      if (typeof globalThis.getApp !== "function") {
        return null;
      }
      var app = globalThis.getApp({ allowDefault: true });
      return {
        hasApp: !!app,
        globalDataKeys: app && app.globalData ? Object.keys(app.globalData).slice(0, 80) : [],
        globalData: app && app.globalData ? sanitize(app.globalData, 0) : null,
      };
    });

    return {
      title: "微信小程序环境信息探测",
      injectedAt: new Date().toISOString(),
      globalRuntime: {
        hasWx: !!globalThis.wx,
        hasApp: typeof globalThis.App === "function",
        hasPage: typeof globalThis.Page === "function",
        hasComponent: typeof globalThis.Component === "function",
        hasGetApp: typeof globalThis.getApp === "function",
        hasGetCurrentPages: typeof globalThis.getCurrentPages === "function",
        hasRequire: typeof globalThis.require === "function",
        hasWeixinJSBridge: !!globalThis.WeixinJSBridge,
      },
      wx: buildWxReport(wxObject),
      app: appInfo,
      pages: currentPagesSummary(),
      wxConfig: safeRead("__wxConfig", function () {
        return sanitize(globalThis.__wxConfig, 0);
      }),
    };
  }

  // 生成弹窗摘要，详细 JSON 放到日志和控制台。
  function buildPopupSummary(report) {
    var systemInfo = report.wx.syncCalls.getSystemInfoSync;
    var appBaseInfo = report.wx.syncCalls.getAppBaseInfo;
    var accountInfo = report.wx.syncCalls.getAccountInfoSync;
    var systemValue = systemInfo.ok ? systemInfo.value : {};
    var appBaseValue = appBaseInfo.ok ? appBaseInfo.value : {};
    var accountValue = accountInfo.ok ? accountInfo.value : {};
    var miniProgram = accountValue && accountValue.miniProgram ? accountValue.miniProgram : {};

    return [
      "wx：" + (report.wx.available ? "可用" : "不可用"),
      "appid：" + (miniProgram.appId || "未知"),
      "设备：" + (systemValue.brand || appBaseValue.brand || "未知") + " " + (systemValue.model || ""),
      "系统：" + (systemValue.system || "未知") + " / SDK " + (systemValue.SDKVersion || appBaseValue.SDKVersion || "未知"),
      "页面栈：" + report.pages.length,
      "完整 JSON 已写入 JS注入日志和控制台",
    ].join("\n");
  }

  // 输出到弹窗、控制台和 e0e1 注入日志。
  function emitReport(report) {
    var popupSummary = buildPopupSummary(report);
    var jsonText = JSON.stringify(report, null, 2);
    console.log("[e0e1][wx-env-probe] 微信环境信息探测", report);
    if (typeof globalThis.__e0e1JsInjectionReport === "function") {
      globalThis.__e0e1JsInjectionReport(jsonText);
    }
    if (globalThis.wx && typeof globalThis.wx.showModal === "function") {
      globalThis.wx.showModal({
        title: "环境信息探测",
        content: popupSummary,
        showCancel: false,
      });
    } else if (typeof globalThis.alert === "function") {
      globalThis.alert("环境信息探测\n" + popupSummary);
    }
  }

  emitReport(buildReport());
})();
