/* 正在播放示例插件（阶段9，docs/plugin-dev-guide.md 的参照实现）。
 *
 * 演示 system:media 权限：
 *   system.mediaNow / system.mediaControl —— core 网关 → sidecar SMTC。
 * 权限声明见 manifest.json（system:media + ui:widget）。
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

  window.addEventListener('message', function (ev) {
    var data = ev.data || {};
    if (data.__pwPlugin !== true || data.reqId === undefined) return;
    var p = pending[data.reqId];
    if (!p) return;
    delete pending[data.reqId];
    if (data.ok) p.resolve(data.data);
    else p.reject(new Error((data.error && data.error.message) || 'api failed'));
  });

  window.onerror = function (msg) {
    window.parent.postMessage(
      { __pwPlugin: true, crash: { reason: String(msg) } },
      '*'
    );
  };

  window.parent.postMessage({ __pwPlugin: true, ready: true }, '*');

  var titleEl = document.getElementById('title');
  var artistEl = document.getElementById('artist');

  function refresh() {
    call('system', 'mediaNow', {})
      .then(function (info) {
        var session = info && info.session;
        if (!info || info.available === false || !session) {
          artistEl.textContent = info && info.reason ? info.reason : '暂无媒体会话';
          titleEl.textContent = '—';
          return;
        }
        titleEl.textContent = session.title || '未知曲目';
        artistEl.textContent = session.artist || '';
      })
      .catch(function (err) {
        titleEl.textContent = '读取失败';
        artistEl.textContent = String(err.message || err);
      });
  }

  document.querySelectorAll('button[data-action]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      call('system', 'mediaControl', { action: btn.getAttribute('data-action') })
        .then(refresh)
        .catch(function () { /* 越权/失败已审计 */ });
    });
  });

  document.getElementById('refresh').addEventListener('click', refresh);
  refresh();
})();
