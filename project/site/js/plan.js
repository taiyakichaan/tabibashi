/* 旅程プランナー / 準備チェックリスト（すべてブラウザ側。保存先は localStorage） */
(function () {
  var PK = 'tj_plan', CK = 'tj_chk', init = false;
  function load(k) { try { return JSON.parse(localStorage.getItem(k) || '{}') } catch (e) { return {} } }
  function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)) } catch (e) {} }
  var PLAN = load(PK); PLAN.a = PLAN.a || {}; PLAN.days = PLAN.days || 3; PLAN.start = PLAN.start || '';
  var CHK = load(CK);
  function pad(n) { return (n < 10 ? '0' : '') + n }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] }) }
  function root() { return document.querySelector('.planner') }
  function lang() { var r = root(); return (r && r.dataset.lang) || 'ja' }
  function L(name) { var r = root(); return (r && r.dataset[name]) || '' }
  function parse(iso) { var p = (iso || '').split('-'); if (p.length !== 3) return null; var d = new Date(+p[0], +p[1] - 1, +p[2]); return isNaN(d) ? null : d }
  function addDays(d, n) { return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n) }
  function ymd(d) { return d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) }
  function hm(t) { var p = (t || '').split(':'); return (+p[0]) * 60 + (+p[1] || 0) }
  function mm(m) { m = Math.max(0, Math.min(1439, m)); return pad(Math.floor(m / 60)) + ':' + pad(m % 60) }
  function dstr(d) { try { return d.toLocaleDateString(lang() === 'zh' ? 'zh-TW' : lang() === 'en' ? 'en-US' : 'ja-JP', { month: 'numeric', day: 'numeric', weekday: 'short' }) } catch (e) { return ymd(d) } }

  function items() {
    var r = root(), out = []; if (!r) return out;
    r.querySelectorAll('.plx').forEach(function (x, i) {
      var s = x.querySelector('.daysel'); var k = s.dataset.reg + '\t' + s.dataset.sp; var a = PLAN.a[k] || {};
      out.push({ k: k, reg: s.dataset.reg, sp: s.dataset.sp, rn: s.dataset.rn || s.dataset.reg, i: i, d: a.d || 0, t: a.t || '' });
    });
    return out;
  }
  function sched() {
    var N = PLAN.days, days = [], un = [], its = items(), d;
    for (d = 0; d < N; d++) days.push([]);
    its.forEach(function (x) { if (x.d >= 1 && x.d <= N) days[x.d - 1].push(x); else un.push(x) });
    days.forEach(function (list) {
      var auto = 0;
      list.forEach(function (x) { if (x.t) { x.m = hm(x.t); x.auto = false } else { x.m = 600 + 120 * auto; auto++; x.auto = true } });
      list.sort(function (a, b) { return (a.m - b.m) || (a.i - b.i) });
    });
    return { days: days, un: un };
  }
  function fillSelects() {
    var r = root(); if (!r) return;
    r.querySelectorAll('.daysel').forEach(function (s) {
      var k = s.dataset.reg + '\t' + s.dataset.sp, a = PLAN.a[k] || {}, h = '<option value="0">' + esc(L('none')) + '</option>';
      for (var n = 1; n <= PLAN.days; n++) h += '<option value="' + n + '">' + esc(L('day').replace('{n}', n)) + '</option>';
      s.innerHTML = h; s.value = (a.d && a.d <= PLAN.days) ? String(a.d) : '0';
    });
    r.querySelectorAll('.tmsel').forEach(function (t) { var a = PLAN.a[t.dataset.reg + '\t' + t.dataset.sp] || {}; t.value = a.t || '' });
  }
  function monthGrid(y, m, inRange, has) {
    var first = new Date(y, m, 1), nd = new Date(y, m + 1, 0).getDate(), loc = lang() === 'zh' ? 'zh-TW' : lang() === 'en' ? 'en-US' : 'ja-JP', h, i;
    var title; try { title = first.toLocaleDateString(loc, { year: 'numeric', month: 'long' }) } catch (e) { title = y + '/' + (m + 1) }
    h = '<div class="mcal"><h5>' + esc(title) + '</h5><div class="wk">';
    for (i = 0; i < 7; i++) { var wd; try { wd = new Date(2023, 0, 1 + i).toLocaleDateString(loc, { weekday: 'narrow' }) } catch (e) { wd = '' } h += '<b>' + esc(wd) + '</b>' }
    for (i = 0; i < first.getDay(); i++) h += '<i class="e"></i>';
    for (i = 1; i <= nd; i++) { var key = ymd(new Date(y, m, i)); h += '<i class="' + (inRange[key] ? 'in ' : '') + (has[key] ? 'has' : '') + '">' + i + '</i>' }
    return h + '</div></div>';
  }
  function routeUrl(list) {
    var q = list.map(function (x) { return encodeURIComponent(x.sp + ' ' + x.rn) }), u = 'https://www.google.com/maps/dir/?api=1&travelmode=transit&destination=' + q[q.length - 1];
    if (q.length >= 2) u += '&origin=' + q[0];
    if (q.length >= 3) u += '&waypoints=' + q.slice(1, -1).join('%7C');
    return u;
  }
  function render() {
    var r = root(), out = document.getElementById('planout'); if (!r || !out) return;
    var S = sched(), start = parse(PLAN.start), h = '', inRange = {}, has = {}, d;
    if (start) {
      for (d = 0; d < PLAN.days; d++) { var dd = addDays(start, d); inRange[ymd(dd)] = 1; if (S.days[d].length) has[ymd(dd)] = 1 }
      var months = {}, cal = '';
      for (d = 0; d < PLAN.days; d++) { var x = addDays(start, d); months[x.getFullYear() + '-' + x.getMonth()] = [x.getFullYear(), x.getMonth()] }
      Object.keys(months).forEach(function (k) { cal += monthGrid(months[k][0], months[k][1], inRange, has) });
      h += '<div class="mcals">' + cal + '</div>';
    }
    h += '<h4 class="schedhd">' + esc(L('sched')) + '</h4><div class="days">';
    for (d = 0; d < PLAN.days; d++) {
      var list = S.days[d], title = esc(L('day').replace('{n}', d + 1)) + (start ? ' <small>' + esc(dstr(addDays(start, d))) + '</small>' : '');
      h += '<div class="dcard"><h5>' + title + '</h5>';
      if (!list.length) h += '<p class="none">' + esc(L('emptysched')) + '</p>';
      else {
        h += '<ol>' + list.map(function (x) { return '<li><time>' + mm(x.m) + (x.auto ? '<sup>*</sup>' : '') + '</time><span>' + esc(x.sp) + '<small>' + esc(x.rn) + '</small></span></li>' }).join('') + '</ol>';
        h += '<a class="route" target="_blank" rel="noopener" href="' + routeUrl(list) + '">' + esc(L('route')) + '</a>';
      }
      h += '</div>';
    }
    h += '</div>';
    if (S.un.length) h += '<div class="dcard un"><h5>' + esc(L('un')) + '</h5><ul>' + S.un.map(function (x) { return '<li>' + esc(x.sp) + '<small>' + esc(x.rn) + '</small></li>' }).join('') + '</ul></div>';
    h += '<p class="pn">' + esc(L('note')) + '</p>';
    out.innerHTML = h;
  }
  function msg(t) { var m = document.getElementById('planmsg'); if (m) { m.textContent = t || ''; if (t) setTimeout(function () { if (m.textContent === t) m.textContent = '' }, 3500) } }

  window.tjPlanSet = function (el) {
    if (el.id === 'plan-start') PLAN.start = el.value;
    else if (el.id === 'plan-days') { var n = Math.max(1, Math.min(14, parseInt(el.value, 10) || 1)); PLAN.days = n; fillSelects() }
    else {
      var k = el.dataset.reg + '\t' + el.dataset.sp, a = PLAN.a[k] || {};
      if (el.classList.contains('daysel')) a.d = parseInt(el.value, 10) || 0; else a.t = el.value || '';
      PLAN.a[k] = a;
    }
    save(PK, PLAN); render();
  };
  function icsEsc(s) { return String(s).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\n/g, '\\n') }
  window.tjPlanIcs = function () {
    var start = parse(PLAN.start); if (!start) { msg(L('needdate')); return }
    var S = sched(), ev = [], stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+/, '');
    S.days.forEach(function (list, d) {
      var day = addDays(start, d);
      list.forEach(function (x, j) {
        var s = ymd(day) + 'T' + mm(x.m).replace(':', '') + '00', e = ymd(day) + 'T' + mm(Math.min(x.m + 90, 1439)).replace(':', '') + '00';
        ev.push('BEGIN:VEVENT', 'UID:' + ymd(day) + '-' + d + '-' + j + '-' + Math.abs(hash(x.k)) + '@travel-app', 'DTSTAMP:' + stamp, 'DTSTART:' + s, 'DTEND:' + e,
          'SUMMARY:' + icsEsc(x.sp), 'LOCATION:' + icsEsc(x.sp + ' ' + x.rn),
          'DESCRIPTION:' + icsEsc(x.rn + ' / https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(x.sp + ' ' + x.rn)), 'END:VEVENT');
      });
    });
    if (!ev.length) { msg(L('emptysched')); return }
    var txt = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Taiwan Japan Journey//Trip Planner//EN', 'CALSCALE:GREGORIAN'].concat(ev, ['END:VCALENDAR']).join('\r\n');
    var blob = new Blob([txt], { type: 'text/calendar;charset=utf-8' }), a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = 'trip-' + ymd(start) + '.ics'; document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); document.body.removeChild(a) }, 500);
  };
  function hash(s) { var h = 0; for (var i = 0; i < s.length; i++) { h = ((h << 5) - h + s.charCodeAt(i)) | 0 } return h }
  window.tjPlanText = function (btn) {
    var S = sched(), start = parse(PLAN.start), o = [];
    S.days.forEach(function (list, d) {
      if (!list.length) return;
      o.push('■ ' + L('day').replace('{n}', d + 1) + (start ? ' (' + dstr(addDays(start, d)) + ')' : ''));
      list.forEach(function (x) { o.push(mm(x.m) + '  ' + x.sp + ' (' + x.rn + ')') }); o.push('');
    });
    if (S.un.length) { o.push('■ ' + L('un')); S.un.forEach(function (x) { o.push('・' + x.sp + ' (' + x.rn + ')') }) }
    var t = o.join('\n');
    function done() { if (btn && btn.dataset.ok) { var old = btn.textContent; btn.textContent = btn.dataset.ok; setTimeout(function () { btn.textContent = old }, 1800) } }
    function fb() { var a = document.createElement('textarea'); a.value = t; document.body.appendChild(a); a.select(); try { document.execCommand('copy') } catch (e) {} document.body.removeChild(a); done() }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(t).then(done, fb); else fb();
  };

  /* ---- 準備チェックリスト ---- */
  function prepUpdate() {
    var p = document.querySelector('.prep'); if (!p) return;
    var mon = parseInt((p.querySelector('.ckmonth') || {}).value, 10) || (new Date().getMonth() + 1), a = 0, b = 0;
    p.querySelectorAll('.ck').forEach(function (l) {
      var w = l.dataset.w, ok = !w || w.split(',').indexOf(String(mon)) >= 0; l.classList.toggle('hide', !ok);
      if (ok) { b++; if (l.querySelector('input').checked) a++ }
    });
    var g = p.querySelector('.ckprog'); if (g) g.textContent = (p.dataset.done || '{a} / {b}').replace('{a}', a).replace('{b}', b);
    p.querySelectorAll('.ckg').forEach(function (grp) { grp.classList.toggle('hide', !grp.querySelector('.ck:not(.hide)')) });
  }
  window.tjChk = function (el) { CHK[el.dataset.id] = el.checked ? 1 : 0; save(CK, CHK); prepUpdate() };
  window.tjPrepMonth = function () { prepUpdate() };

  function setup() {
    var r = root();
    if (r && !r.dataset.init) {
      r.dataset.init = '1';
      var s = document.getElementById('plan-start'), n = document.getElementById('plan-days');
      if (s) s.value = PLAN.start; if (n) n.value = PLAN.days;
      fillSelects(); render();
    }
    var p = document.querySelector('.prep');
    if (p && !p.dataset.init) {
      p.dataset.init = '1';
      p.querySelectorAll('.ck input').forEach(function (i) { i.checked = !!CHK[i.dataset.id] });
      prepUpdate();
    }
  }
  document.addEventListener('click', function (e) { var a = e.target.closest && e.target.closest('details.menu .mlist a'); if (a) { var d = a.closest('details'); if (d) d.removeAttribute('open') } });   // 項目を選んだらメニューを閉じる
  var tm = null;
  new MutationObserver(function () { clearTimeout(tm); tm = setTimeout(setup, 80) }).observe(document.documentElement, { childList: true, subtree: true });
  setTimeout(setup, 500);
})();

/* 天気（Open-Meteo をブラウザから直接取得。APIキー不要。遅い・つながらないときはサーバー経由と古いデータで補う） */
(function () {
  var NM = { ja: ['晴れ','晴れ時々くもり','くもり','霧','霧雨','雨','雪','にわか雨','雷雨'], zh: ['晴','晴時多雲','陰','霧','毛毛雨','雨','雪','陣雨','雷雨'], en: ['Clear','Partly cloudy','Cloudy','Fog','Drizzle','Rain','Snow','Showers','Thunderstorm'] };
  function grp(c) {
    if (c <= 1) return 0; if (c === 2) return 1; if (c === 3) return 2; if (c === 45 || c === 48) return 3;
    if (c >= 51 && c <= 57) return 4; if (c >= 61 && c <= 67) return 5; if ((c >= 71 && c <= 77) || c === 85 || c === 86) return 6;
    if (c >= 80 && c <= 82) return 7; if (c >= 95) return 8; return 2;
  }
  var P = { 0: '<circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
    1: '<circle cx="9" cy="9" r="3"/><path d="M9 3v1.5M3 9h1.5M4.8 4.8l1 1M13.2 4.8l-1 1"/><path d="M8 20h10a3.5 3.5 0 0 0 0-7 5 5 0 0 0-9.5 1.5A3 3 0 0 0 8 20z"/>',
    2: '<path d="M7 19h11a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.3 3.3 0 0 0 7 19z"/>',
    3: '<path d="M7 14h11a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.3 3.3 0 0 0 7 14z"/><path d="M5 18h14M8 21h8"/>',
    4: '<path d="M7 14h11a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.3 3.3 0 0 0 7 14z"/><path d="M9 17v1M13 17v1M17 17v1"/>',
    5: '<path d="M7 14h11a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.3 3.3 0 0 0 7 14z"/><path d="M8 17l-1 3M12 17l-1 3M16 17l-1 3"/>',
    6: '<path d="M7 14h11a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.3 3.3 0 0 0 7 14z"/><path d="M8 18v.1M12 20v.1M16 18v.1M10 21v.1M14 17v.1"/>',
    7: '<path d="M7 14h11a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.3 3.3 0 0 0 7 14z"/><path d="M8 17l-1 3M12 17l-1 3M16 17l-1 3"/>',
    8: '<path d="M7 13h11a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.3 3.3 0 0 0 7 13z"/><path d="M12 14l-2 4h3l-2 4"/>' };
  function ic(g) { return '<svg class="wi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + P[g] + '</svg>' }
  function esc(x) { return String(x).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] }) }
  function dlabel(iso, lang) { var p = iso.split('-'), d = new Date(+p[0], +p[1] - 1, +p[2]); var w = d.getDay();
    var wk = { ja: '日月火水木金土', zh: '日一二三四五六', en: 'SunMonTueWedThuFriSat' }[lang]; var wn = lang === 'en' ? wk.substr(w * 3, 3) : wk.charAt(w);
    return (lang === 'en' ? (+p[1]) + '/' + (+p[2]) : (+p[1]) + '/' + (+p[2])) + ' ' + wn }
  function draw(el, j) {
    var lang = el.dataset.lang || 'ja', n = NM[lang] || NM.ja, c = j.current, d = j.daily, h = '';
    var g = grp(c.weather_code);
    h += '<div class="wxnow">' + ic(g) + '<div><b class="wxt">' + Math.round(c.temperature_2m) + '&deg;C</b><span class="wxs">' + esc(n[g]) + '</span></div>' +
      '<ul class="wxm"><li>' + esc(el.dataset.hum) + ' <b>' + Math.round(c.relative_humidity_2m) + '%</b></li><li>' + esc(el.dataset.wind) + ' <b>' + Math.round(c.wind_speed_10m) + ' km/h</b></li></ul></div>';
    h += '<div class="wxdays">';
    for (var i = 0; i < d.time.length; i++) {
      var gg = grp(d.weather_code[i]);
      h += '<div class="wxd' + (i === 0 ? ' today' : '') + '"><small>' + esc(dlabel(d.time[i], lang)) + '</small>' + ic(gg) + '<b>' + Math.round(d.temperature_2m_max[i]) + '&deg;</b><span>' + Math.round(d.temperature_2m_min[i]) + '&deg;</span>' +
        '<em>' + esc(el.dataset.pop) + ' ' + (d.precipitation_probability_max[i] == null ? '-' : d.precipitation_probability_max[i]) + '%</em></div>';
    }
    h += '</div>';
    el.querySelector('.wxbody').innerHTML = h;
  }
  /* 取得の流れ（原因と対策は README「天気が読み込めない問題の原因と対策」）:
     ① キャッシュ（localStorage、30分）→ ② ブラウザから Open-Meteo へ直接（12秒まで待つ・失敗したら1回だけ再試行）
     ③ 2.5秒で返らなければサーバー経由（/gradio_api/run/wx）も並行して開始し、早い方を使う
     ④ どちらも失敗したら、12時間以内の古いデータを「○時○分時点」として表示。それもなければ案内文と「もう一度読み込む」ボタン */
  var FRESH = 1800000, STALE = 43200000, KP = 'tj_wx2_', inflight = {};
  function cget(k) { try { return JSON.parse(localStorage.getItem(k) || 'null') } catch (e) { try { return JSON.parse(sessionStorage.getItem(k) || 'null') } catch (e2) { return null } } }
  function cset(k, v) { var s = JSON.stringify(v); try { localStorage.setItem(k, s) } catch (e) { try { sessionStorage.setItem(k, s) } catch (e2) {} } }
  function valid(j) { return !!(j && j.current && j.daily && j.daily.time && j.daily.time.length) }
  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms) }) }
  function timed(p, ms, ctl) { return new Promise(function (res, rej) { var t = setTimeout(function () { if (ctl) ctl.abort(); rej('timeout') }, ms); p.then(function (v) { clearTimeout(t); res(v) }, function (e) { clearTimeout(t); rej(e) }) }) }
  function direct(url, ms) {
    var ctl = ('AbortController' in window) ? new AbortController() : null;
    return timed(fetch(url, ctl ? { signal: ctl.signal } : {}).then(function (r) { if (!r.ok) throw r.status; return r.json() }).then(function (j) { if (!valid(j)) throw 'bad'; return j }), ms, ctl);
  }
  function viaServer(lat, lon, ms) {
    var api = function (p) { return new URL('gradio_api/' + p, location.href).href };
    var body = JSON.stringify({ data: [+lat, +lon] }), hd = { 'Content-Type': 'application/json' };
    var run = fetch(api('run/wx'), { method: 'POST', headers: hd, body: body }).then(function (r) { if (!r.ok) throw r.status; return r.json() })
      .then(function (j) { return JSON.parse(j.data[0]) })
      .catch(function () {          // run が使えない環境: 待ち行列(SSE)の call API
        return fetch(api('call/wx'), { method: 'POST', headers: hd, body: body }).then(function (r) { return r.json() })
          .then(function (j) { return fetch(api('call/wx/' + j.event_id)) }).then(function (r) { return r.text() })
          .then(function (t) { var m = t.match(/event: complete\s+data: (.*)/); if (!m) throw 0; return JSON.parse(JSON.parse(m[1])[0]) });
      });
    return timed(run.then(function (j) { if (!valid(j)) throw 'bad'; return j }), ms);
  }
  function fetchWx(lat, lon, url) {
    return new Promise(function (res, rej) {
      var done = false, pend = 0, srv = false;
      function ok(j) { if (!done) { done = true; res(j) } }
      function run(p) { pend++; p.then(ok, function () { if (--pend === 0 && srv && !done) { done = true; rej() } }) }
      function startSrv() { if (srv || done) return; srv = true; run(viaServer(lat, lon, 15000)) }
      run(direct(url, 12000).catch(function () { startSrv(); return wait(1500).then(function () { return direct(url, 10000) }) }));
      setTimeout(startSrv, 2500);
    });
  }
  function fmtT(t) { var d = new Date(t); return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + d.getHours() + ':' + ('0' + d.getMinutes()).slice(-2) }
  function sameAll(el) { var r = []; document.querySelectorAll('.wx').forEach(function (e) { if (e.dataset.lat === el.dataset.lat && e.dataset.lon === el.dataset.lon) r.push(e) }); if (r.indexOf(el) < 0) r.push(el); return r }
  function show(el, j, t, stale) {
    draw(el, j); el.removeAttribute('data-fail');
    if (stale) el.querySelector('.wxbody').insertAdjacentHTML('afterbegin', '<p class="wxold">' + esc((el.dataset.asof || '{t}').replace('{t}', fmtT(t))) + '</p>');
  }
  function fail(el) {
    var b = el.querySelector('.wxbody'); if (!b) return; el.setAttribute('data-fail', '1');
    b.innerHTML = '<p class="wxload">' + esc(el.dataset.err || '') + '</p>' + (el.dataset.retry ? '<p class="wxre"><button type="button" class="wxretry">' + esc(el.dataset.retry) + '</button></p>' : '');
    var btn = b.querySelector('.wxretry'); if (btn) btn.onclick = function () { b.innerHTML = '<p class="wxload">…</p>'; load(el, true) };
  }
  function load(el, force) {
    var lat = el.dataset.lat, lon = el.dataset.lon, key = KP + lat + '_' + lon, now = Date.now();
    if (!lat || !lon) return;
    var c = cget(key), has = !!(c && valid(c.j));
    if (has && now - c.t < FRESH && !force) { show(el, c.j, c.t, false); return }
    var old = has && now - c.t < STALE;
    var url = 'https://api.open-meteo.com/v1/forecast?latitude=' + encodeURIComponent(lat) + '&longitude=' + encodeURIComponent(lon) +
      '&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto&forecast_days=14';
    var p = inflight[key] || (inflight[key] = fetchWx(lat, lon, url));          // 同じ地点の同時リクエストは1つにまとめる
    p.then(function (j) {
      delete inflight[key];
      var t = j._t ? j._t * 1000 : Date.now();                                  // サーバーが古いデータを返した場合は "_t"（取得時刻）
      var best = (has && c.t > t) ? c : { t: t, j: j };
      if (best.j === j) cset(key, best);
      sameAll(el).forEach(function (e) { show(e, best.j, best.t, Date.now() - best.t > FRESH) });   // 取得中に画面が描き直されても、表示中の枠に反映
    }, function () {
      delete inflight[key];
      sameAll(el).forEach(function (e) { if (old) show(e, c.j, c.t, true); else fail(e) });
    });
  }
  function wxSetup() { document.querySelectorAll('.wx:not([data-init])').forEach(function (el) { el.dataset.init = '1'; load(el) }) }
  window.addEventListener('online', function () { document.querySelectorAll('.wx[data-fail]').forEach(function (el) { load(el, true) }) });   // 回線が戻ったら自動で再取得
  var t2 = null;
  new MutationObserver(function () { clearTimeout(t2); t2 = setTimeout(wxSetup, 80) }).observe(document.documentElement, { childList: true, subtree: true });
  setTimeout(wxSetup, 500);
})();

/* エリアページの旅行予算（エリアの一般的な価格帯 × 日数・人数・ホテルのグレード。すべてブラウザ側で計算） */
(function () {
  var KEY = 'tj_bgt';
  function ld() { try { return JSON.parse(localStorage.getItem(KEY) || '{}') } catch (e) { return {} } }
  function sv(o) { try { localStorage.setItem(KEY, JSON.stringify(o)) } catch (e) {} }
  function fmt(x, c) { var n = Math.round(x).toLocaleString('en-US'); return { JPY: n + '円', TWD: 'NT$' + n, USD: '$' + n, EUR: '€' + n }[c] }
  function calc(b) {
    var R = JSON.parse(b.dataset.rates), loc = b.dataset.loc, lang = b.dataset.lang, c = lang === 'ja' ? 'JPY' : lang === 'zh' ? 'TWD' : ((b.querySelector('.bg-cur') || {}).value || 'USD');
    var d = Math.max(1, Math.min(30, parseInt(b.querySelector('.bg-d').value) || 1)), p = Math.max(1, Math.min(12, parseInt(b.querySelector('.bg-p').value) || 1)), g = parseFloat(b.querySelector('.bg-g').value) || 1;
    var nights = Math.max(0, d - 1), rooms = Math.ceil(p / 2), k = function (x) { return x / R[loc] * R[c] };
    var v = { hotel: k(rooms * nights * (+b.dataset.h) * g), food: k(p * d * (+b.dataset.f)), trans: k(p * d * (+b.dataset.t)), sight: k(p * d * (+b.dataset.s)) };
    v.buf = (v.hotel + v.food + v.trans + v.sight) * 0.1;
    var tot = v.hotel + v.food + v.trans + v.sight + v.buf, bar = '';
    var col = { hotel: '#0b1c1d', food: '#14484a', trans: '#5b8f8a', sight: '#c7a15a', buf: '#d9cdb0' };
    ['hotel', 'food', 'trans', 'sight', 'buf'].forEach(function (key) {
      var r = b.querySelector('tr[data-k=' + key + ']'), sh = tot ? v[key] / tot : 0;
      r.querySelector('.p').textContent = Math.round(sh * 100) + '%'; r.querySelector('.v').textContent = fmt(v[key], c);
      bar += '<i style="width:' + (sh * 100).toFixed(1) + '%;background:' + col[key] + '"></i>';
    });
    b.querySelector('.bbar').innerHTML = bar;
    b.querySelector('.bt-all').textContent = fmt(tot, c); b.querySelector('.bt-pp').textContent = fmt(tot / p, c); b.querySelector('.bt-pd').textContent = fmt(tot / p / d, c);
    b.querySelector('.bt-as').textContent = b.dataset.assume.replace('{d}', d).replace('{n}', nights).replace('{p}', p).replace('{r}', rooms);
    var s = ld(); s.d = d; s.p = p; s.g = g; s.c = c === 'EUR' ? 'EUR' : 'USD'; sv(s);
  }
  window.tjBgt = function (el) { var b = el.closest('.bgt'); if (b) calc(b) };
  function setup() {
    document.querySelectorAll('.bgt:not([data-init])').forEach(function (b) {
      b.dataset.init = '1'; var s = ld();
      if (s.d) b.querySelector('.bg-d').value = s.d; if (s.p) b.querySelector('.bg-p').value = s.p; if (s.g) b.querySelector('.bg-g').value = String(s.g);
      var c = b.querySelector('.bg-cur'); if (c && s.c) c.value = s.c;
      b.querySelectorAll('input,select').forEach(function (e) { e.addEventListener('input', function () { calc(b) }); e.addEventListener('change', function () { calc(b) }) });
      calc(b);
    });
  }
  var t3 = null; new MutationObserver(function () { clearTimeout(t3); t3 = setTimeout(setup, 80) }).observe(document.documentElement, { childList: true, subtree: true });
  setTimeout(setup, 500);
})();

function tjGo(reg){window.tjSpin&&tjSpin(1);var t=document.querySelector('#bridge textarea,#bridge input');if(!t)return;var d=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(t),'value');d.set.call(t,'region\t'+reg+'\t'+Date.now());t.dispatchEvent(new Event('input',{bubbles:true}));}
/* 国・言語を切り替えると、同じ要素のまま data-j だけ書き換わることがある。属性の中身が変わったら読み直す（以前は最初に読んだ国のデータを使い続けていた） */
function tjCatData(box){var p=box.querySelector('.cpanels');if(!p)return null;var j=p.getAttribute('data-j');if(p._j!==j){p._j=j;try{p._d=JSON.parse(j)}catch(e){p._d=null}}return p._d}
function tjCatRender(box){
  var D=tjCatData(box),res=box.querySelector('.cres'),cur=box.querySelector('.cchip.on');
  if(!D||!res)return; res.textContent=''; if(!cur)return;
  var k=cur.getAttribute('data-k'),rows=(D.c[k]||[]).slice(),R=D.r,mode=(box.querySelector('.csort .on')||{}).dataset.s||'n',lang=D.lang;
  var cmp=function(a,b){var x=R[a[0]],y=R[b[0]];
    if(mode==='n')return (y[2]-x[2])||(b[1]-a[1]);
    if(lang==='ja')return x[1]<y[1]?-1:x[1]>y[1]?1:0;
    return x[0].localeCompare(y[0],lang==='zh'?'zh-Hant-u-co-zhuyin':'en')};
  rows.sort(cmp);
  var h=document.createElement('div');h.className='cph';h.textContent=cur.textContent;var em=document.createElement('em');em.textContent=rows.length;h.appendChild(em);res.appendChild(h);
  var g=document.createElement('div');g.className='cgrid';
  rows.forEach(function(r){var info=R[r[0]],a=document.createElement('a');a.className='ccard';a.href='#';
    if(info[3]){a.style.backgroundImage='linear-gradient(180deg,rgba(7,15,17,.28),rgba(7,15,17,.86)),url("'+info[3]+'")';a.style.backgroundPosition='0 0,'+info[4]+'% '+info[5]+'%';}
    a.onclick=function(e){e.preventDefault();tjGo(r[0]);};
    var hd=document.createElement('div');hd.className='chd';var b=document.createElement('b');b.textContent=info[0];var n=document.createElement('em');n.textContent=r[1];hd.appendChild(b);hd.appendChild(n);a.appendChild(hd);
    var ul=document.createElement('ul');r[2].forEach(function(s){var li=document.createElement('li');li.textContent=s[0];if(s[1]){var sp=document.createElement('span');sp.className='en';sp.textContent=s[1];li.appendChild(sp)}ul.appendChild(li)});a.appendChild(ul);
    var go=document.createElement('span');go.className='cgo';go.textContent='→';a.appendChild(go);g.appendChild(a)});
  res.appendChild(g);
}
function tjCat(b){
  var box=b.closest('#catbox'); if(!box) return; var on=b.classList.contains('on');
  box.querySelectorAll('.cchip').forEach(function(x){x.classList.remove('on')});
  if(!on)b.classList.add('on');
  tjCatRender(box);
  if(!on){  /* カテゴリのカードを押したら、結果（エリアカード）の位置まで移動する。固定ヘッダーの高さ分だけ上に余白を取る */
    var r=box.querySelector('.cres .cph')||box.querySelector('.csort');
    if(r){var tb=document.getElementById('topbar'),off=(tb?tb.getBoundingClientRect().bottom:60)+10;
      window.scrollTo({top:r.getBoundingClientRect().top+window.scrollY-off,behavior:'smooth'});}
  }
}
function tjCatSort(b){var box=b.closest('#catbox');box.querySelectorAll('.csort button').forEach(function(x){x.classList.remove('on')});b.classList.add('on');tjCatRender(box)}

/* スライドショーの2枚目以降は「出番の少し前」に1枚ずつ読み込む。
   以前は表示1.5秒後に全枚数(最大16枚・約4MB)を一斉に読み込んでいたため、次のページ遷移の通信と帯域を取り合って遅くなっていた。 */
setInterval(function(){
  var now=Date.now(),busy=window.tjBusy&&now-window.tjBusy<8000;
  document.querySelectorAll('.slide[data-bg]').forEach(function(e){
    if(!e._t0)e._t0=now;
    var d=(parseFloat(e.style.animationDelay)||0)*1000,lead=busy?800:3500;      /* ページ遷移中は直前まで待つ */
    if(now-e._t0>=d-lead){e.style.backgroundImage='url("'+e.getAttribute('data-bg')+'")';e.removeAttribute('data-bg')}
  });
},500);

/* ヘッダーの実際の高さを --tb に反映（スマホで本文の開始位置・1ページ目の配置に使う） */
(function () {
  var t = null;
  function m() { var b = document.getElementById('topbar'); if (!b || !b.offsetHeight) return; var v = b.offsetHeight + 'px'; if (document.documentElement.style.getPropertyValue('--tb') !== v) document.documentElement.style.setProperty('--tb', v) }
  new MutationObserver(function () { clearTimeout(t); t = setTimeout(m, 60) }).observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener('resize', m); setTimeout(m, 400);
})();

function tjCopy(el){var q=el.getAttribute('data-q'),m=el.getAttribute('data-t');
 try{if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(q).catch(function(){})}catch(e){}
 var t=document.getElementById('tjtoast');if(!t){t=document.createElement('div');t.id='tjtoast';document.body.appendChild(t)}
 t.textContent=m;t.className='on';clearTimeout(t._h);t._h=setTimeout(function(){t.className=''},3800)}

/* ---- ページ遷移中のぐるぐるマーク ---- */
(function(){
  var tm=null,safe=null;
  function el(){var e=document.getElementById('tjspin');if(!e){e=document.createElement('div');e.id='tjspin';e.setAttribute('role','status');e.setAttribute('aria-live','polite');e.innerHTML='<i></i>';document.body.appendChild(e);}return e;}
  window.tjSpin=function(on){
    clearTimeout(tm);clearTimeout(safe);
    window.tjBusy=on?Date.now():0;
    if(on){tm=setTimeout(function(){el().classList.add('on');},120);          /* すぐ終わる処理ではちらつかせない */
           safe=setTimeout(function(){el().classList.remove('on');},20000);}   /* 万一終了を取りこぼしても消す */
    else{el().classList.remove('on');}
  };
  var IDS=['pick-tw','pick-jp','hbtn','pbtn','go','sysback','home'];
  document.addEventListener('click',function(ev){
    var t=ev.target;if(!t||!t.closest)return;
    for(var i=0;i<IDS.length;i++){if(t.closest('#'+IDS[i])){window.tjSpin(1);return;}}
  },true);
  document.addEventListener('keydown',function(ev){
    if(ev.key==='Enter'&&ev.target&&ev.target.closest&&ev.target.closest('#hsearch,#psearch'))window.tjSpin(1);
  },true);
})();
