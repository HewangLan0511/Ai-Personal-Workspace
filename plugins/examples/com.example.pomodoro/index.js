/* 番茄钟示例插件（阶段9，docs/plugin-dev-guide.md 的参照实现）。
 *
 * 能力调用一律走宿主桥（pw.call），信封见契约 3.2.7：
 *   pw.call(api, method, payload) → Promise<data>
 * 本插件用到：data.set/data.get（data:own）、ui.notify（ui:widget）。
 */
(function () {
  'use strict';

  var reqSeq = 0;
  var pending = {};

  function call(api, method, payload) {
    return new Promise(function (resolve, reject) {
      var id = ++reqSeq;
      pending[id] = { resolve: resolve, reject: reject };
      window.parent.postMessage(
        { __pwPlugin: true, reqId: id, api: api, method: method, payload: payload || {} },
        '*'
      );
    });
  }

  // 宿主应答分发
  window.addEventListener('message', function (ev) {
    var data = ev.data || {};
    if (data.__pwPlugin !== true || data.reqId === undefined) return;
    var p = pending[data.reqId];
    if (!p) return;
    delete pending[data.reqId];
    if (data.ok) p.resolve(data.data);
    else p.reject(new Error((data.error && data.error.message) || 'api failed'));
  });

  // 崩溃上报：宿主收到后调 plugin_crash → PLUGIN_ERROR + 审计
  window.onerror = function (msg) {
    window.parent.postMessage(
      { __pwPlugin: true, crash: { reason: String(msg) } },
      '*'
    );
  };

  // 就绪上报（宿主 10s 超时判据）
  window.parent.postMessage({ __pwPlugin: true, ready: true }, '*');

  // ---- 番茄钟本体 ----
  var TOTAL = 25 * 60;
  var remain = TOTAL;
  var timer = null;
  var running = false;

  var clockEl = document.getElementById('clock');
  var toggleEl = document.getElementById('toggle');
  var cyclesEl = document.getElementById('cycles');

  function render() {
    var m = Math.floor(remain / 60);
    var s = remain % 60;
    clockEl.textContent = (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }

  function loadCycles() {
    return call('data', 'get', { key: 'cycles' })
      .then(function (res) {
        var v = res && res.value;
        return typeof v === 'number' ? v : parseInt(v, 10) || 0;
      })
      .catch(function () { return 0; });
  }

  function saveCycles(n) {
    return call('data', 'set', { key: 'cycles', value: n });
  }

  function onTick() {
    remain -= 1;
    if (remain <= 0) {
      stop();
      remain = TOTAL;
      render();
      loadCycles()
        .then(function (n) {
          var next = n + 1;
          cyclesEl.textContent = '今日完成 ' + next + ' 个';
          return saveCycles(next);
        })
        .then(function () {
          return call('ui', 'notify', { title: '番茄钟', body: '一个番茄完成，休息一下吧' });
        })
        .catch(function () { /* 审计已记录，静默 */ });
      return;
    }
    render();
  }

  function start() {
    running = true;
    toggleEl.textContent = '暂停';
    timer = window.setInterval(onTick, 1000);
  }

  function stop() {
    running = false;
    toggleEl.textContent = '开始';
    if (timer) window.clearInterval(timer);
    timer = null;
  }

  toggleEl.addEventListener('click', function () {
    running ? stop() : start();
  });

  document.getElementById('reset').addEventListener('click', function () {
    stop();
    remain = TOTAL;
    render();
  });

  loadCycles().then(function (n) {
    cyclesEl.textContent = '今日完成 ' + n + ' 个';
  });
  render();
})();
