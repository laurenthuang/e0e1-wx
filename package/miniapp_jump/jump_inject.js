// 摘要：注入小程序运行时，只弹出微信确认框并在用户确认后跳转到指定 AppID。
(function () {
  if (window.__miniappJumpNavigator) {
    return;
  }

  function buildResult(appId, path, ok, status, message, error) {
    return {
      ok: !!ok,
      status: String(status || (ok ? "success" : "failed")),
      action: "navigate_to_mini_program",
      appId: String(appId || ""),
      path: normalizePath(path),
      message: String(message || ""),
      error: String(error || ""),
    };
  }

  function normalizeAppId(appId) {
    return String(appId || "").trim();
  }

  function normalizePath(path) {
    return String(path || "").trim().replace(/^\/+/, "");
  }

  function addCandidate(candidates, frame) {
    // 只收集可直接调用微信跳转和确认框能力的运行时 frame。
    try {
      if (!frame || candidates.indexOf(frame) >= 0) {
        return;
      }
      if (!frame.wx || typeof frame.wx.navigateToMiniProgram !== "function") {
        return;
      }
      if (typeof frame.wx.showModal !== "function") {
        return;
      }
      if (!frame.__wxConfig && typeof frame.getCurrentPages !== "function") {
        return;
      }
      candidates.push(frame);
    } catch (error) {}
  }

  function collectCandidateFrames() {
    // 遍历窗口层级以找到真实小程序上下文，不修改任何小程序方法。
    var candidates = [];
    var visited = [];

    function visit(frame, depth) {
      try {
        if (!frame || visited.indexOf(frame) >= 0 || depth > 3) {
          return;
        }
        visited.push(frame);
        addCandidate(candidates, frame);
        if (frame.frames) {
          for (var index = 0; index < frame.frames.length; index += 1) {
            visit(frame.frames[index], depth + 1);
          }
        }
      } catch (error) {}
    }

    visit(window, 0);
    try {
      if (window.parent && window.parent !== window) {
        visit(window.parent, 0);
      }
    } catch (error) {}
    return candidates;
  }

  function currentRoute(frame) {
    // 读取当前页面路径，仅用于展示准备状态。
    try {
      var pages = typeof frame.getCurrentPages === "function" ? frame.getCurrentPages() || [] : [];
      if (!pages.length) {
        return "";
      }
      var current = pages[pages.length - 1];
      return String(current.route || current.__route__ || "");
    } catch (error) {
      return "";
    }
  }

  function frameScore(frame) {
    // 根据微信能力和当前页面信息选择最可能的 appservice frame。
    try {
      var score = 0;
      if (frame.wx && typeof frame.wx.navigateToMiniProgram === "function") {
        score += 2;
      }
      if (frame.wx && typeof frame.wx.showModal === "function") {
        score += 2;
      }
      if (frame.__wxConfig) {
        score += 2;
      }
      if (typeof frame.getCurrentPages === "function") {
        var pages = frame.getCurrentPages() || [];
        if (pages.length > 0) {
          score += 10;
        }
        if (currentRoute(frame)) {
          score += 5;
        }
      }
      return score;
    } catch (error) {
      return 0;
    }
  }

  function detectFrame() {
    // 自动选择当前可用的小程序运行时 frame。
    var candidates = collectCandidateFrames();
    var bestFrame = null;
    var bestScore = 0;
    candidates.forEach(function (frame) {
      var score = frameScore(frame);
      if (score > bestScore) {
        bestScore = score;
        bestFrame = frame;
      }
    });
    if (bestFrame) {
      return bestFrame;
    }
    throw new Error("未检测到可用的小程序运行环境");
  }

  function textOfError(error) {
    // 把微信回调或异常对象转成稳定文本。
    if (!error) {
      return "";
    }
    if (typeof error === "string") {
      return error;
    }
    return String(error.errMsg || error.message || error);
  }

  function isTapGestureFailureText(errorText) {
    // 判断微信是否拒绝了非用户 TAP 手势触发的小程序跳转。
    return String(errorText || "").indexOf("can only be invoked by user TAP gesture") >= 0;
  }

  function failureMessage(errorText) {
    // 将微信跳转失败文本转换为界面可读的中文原因。
    var text = String(errorText || "");
    if (!text) {
      return "小程序跳转失败";
    }
    if (text.indexOf("invalid appid") >= 0) {
      return "AppID 无效或小程序不存在";
    }
    if (text.indexOf("not released") >= 0) {
      return "目标小程序未发布";
    }
    if (text.indexOf("not found") >= 0 || text.indexOf("path") >= 0) {
      return "页面路径错误";
    }
    if (text.indexOf("cancel") >= 0) {
      return "用户取消跳转";
    }
    if (isTapGestureFailureText(text)) {
      return "当前触发不满足微信用户手势限制，请重新发起跳转并在确认框中点击立即跳转";
    }
    return "小程序跳转失败";
  }

  function callNavigateToMiniProgram(frame, appId, path) {
    // 调用微信原生跨小程序跳转接口，并统一回调为 Promise。
    return new Promise(function (resolve) {
      try {
        if (!frame || !frame.wx || typeof frame.wx.navigateToMiniProgram !== "function") {
          resolve(
            buildResult(
              appId,
              path,
              false,
              "failed",
              "wx.navigateToMiniProgram 不可用",
              "wx.navigateToMiniProgram not available"
            )
          );
          return;
        }
        var normalizedPath = normalizePath(path);
        var options = {
          appId: appId,
          envVersion: "release",
          success: function () {
            resolve(buildResult(appId, normalizedPath, true, "success", "小程序跳转完成", ""));
          },
          fail: function (error) {
            var errorText = textOfError(error);
            var cancelled = errorText.indexOf("cancel") >= 0;
            resolve(
              buildResult(
                appId,
                normalizedPath,
                false,
                cancelled ? "cancelled" : "failed",
                failureMessage(errorText),
                errorText
              )
            );
          },
        };
        if (normalizedPath) {
          options.path = normalizedPath;
        }
        frame.wx.navigateToMiniProgram(options);
      } catch (error) {
        var errorText = textOfError(error);
        resolve(buildResult(appId, path, false, "failed", failureMessage(errorText), errorText));
      }
    });
  }

  function clearPendingNavigation(pending) {
    // 清理当前待确认任务，不还原任何 Hook，因为本脚本不接管小程序方法。
    var navigatorState = window.__miniappJumpNavigator;
    if (navigatorState && (!pending || navigatorState._pending === pending)) {
      navigatorState._pending = null;
    }
  }

  function triggerPendingNavigation(pending, appId, path, message, triggerFrame) {
    // 用户确认后执行一次目标跳转，完成后立即清理待处理状态。
    if (!pending || pending.handled || window.__miniappJumpNavigator._pending !== pending) {
      return false;
    }
    pending.handled = true;
    window.__miniappJumpNavigator._state = buildResult(appId, pending.path, false, "executing", message, "");
    callNavigateToMiniProgram(triggerFrame || pending.frame, appId, pending.path).then(function (result) {
      if (window.__miniappJumpNavigator._pending !== pending) {
        return;
      }
      clearPendingNavigation(pending);
      window.__miniappJumpNavigator._state = result;
    });
    return true;
  }

  function showNativeJumpPrompt(frame, pending) {
    // 弹出微信原生确认框；用户取消或弹框失败时不保留任何接管状态。
    try {
      if (!frame || !frame.wx || typeof frame.wx.showModal !== "function") {
        return buildResult(pending.appId, pending.path, false, "failed", "wx.showModal 不可用", "wx.showModal not available");
      }
      frame.wx.showModal({
        title: "跨小程序跳转",
        content: "确认后跳转到目标小程序",
        confirmText: "立即跳转",
        cancelText: "取消",
        success: function (result) {
          if (result && result.confirm) {
            triggerPendingNavigation(
              pending,
              pending.appId,
              pending.path,
              "检测到微信原生确认，正在跳转小程序",
              frame
            );
            return;
          }
          if (window.__miniappJumpNavigator._pending === pending && !pending.handled) {
            clearPendingNavigation(pending);
            window.__miniappJumpNavigator._state = buildResult(
              pending.appId,
              pending.path,
              false,
              "cancelled",
              "用户取消跳转",
              ""
            );
          }
        },
        fail: function (error) {
          if (window.__miniappJumpNavigator._pending === pending && !pending.handled) {
            clearPendingNavigation(pending);
            window.__miniappJumpNavigator._state = buildResult(
              pending.appId,
              pending.path,
              false,
              "failed",
              "微信确认框打开失败",
              textOfError(error)
            );
          }
        },
      });
      return buildResult(
        pending.appId,
        pending.path,
        false,
        "waiting_tap",
        "已弹出微信确认框，请在小程序内确认跳转",
        ""
      );
    } catch (error) {
      var errorText = textOfError(error);
      clearPendingNavigation(pending);
      return buildResult(pending.appId, pending.path, false, "failed", "微信确认框打开失败", errorText);
    }
  }

  function prepareNavigateToMiniProgram(appId, path) {
    // 创建单次待确认任务并立即弹出确认框。
    var normalizedAppId = normalizeAppId(appId);
    var normalizedPath = normalizePath(path);
    if (!normalizedAppId) {
      return buildResult("", normalizedPath, false, "failed", "目标 AppID 不能为空", "appid is empty");
    }
    try {
      var frame = detectFrame();
      var pending = {
        appId: normalizedAppId,
        path: normalizedPath,
        frame: frame,
        route: currentRoute(frame),
        handled: false,
      };
      window.__miniappJumpNavigator._pending = pending;
      return showNativeJumpPrompt(frame, pending);
    } catch (error) {
      var errorText = textOfError(error);
      return buildResult(normalizedAppId, normalizedPath, false, "failed", "小程序跳转准备失败", errorText);
    }
  }

  function currentState() {
    // 返回当前跳转状态，供 Python 侧轮询。
    var state = window.__miniappJumpNavigator._state;
    if (state && typeof state === "object") {
      return state;
    }
    return buildResult("", "", false, "failed", "未找到待处理跳转任务", "no pending navigation");
  }

  window.__miniappJumpNavigator = {
    _pending: null,
    _state: null,

    prepareNavigateToMiniProgramJson: function (appId, path) {
      var result = prepareNavigateToMiniProgram(appId, path);
      window.__miniappJumpNavigator._state = result;
      return Promise.resolve(JSON.stringify(result));
    },

    pollNavigationResultJson: function () {
      return Promise.resolve(JSON.stringify(currentState()));
    },

    cancelPendingNavigationJson: function () {
      var current = currentState();
      clearPendingNavigation(window.__miniappJumpNavigator._pending);
      var result = buildResult(current.appId, current.path, false, "cancelled", "小程序跳转任务已取消", "");
      window.__miniappJumpNavigator._state = result;
      return Promise.resolve(JSON.stringify(result));
    },

    navigateToMiniProgramJson: function (appId, path) {
      return this.prepareNavigateToMiniProgramJson(appId, path);
    },
  };
})();
