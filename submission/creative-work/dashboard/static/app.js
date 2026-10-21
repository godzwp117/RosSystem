'use strict';
const $ = (id) => document.getElementById(id);
let CURRENT = null;      // 当前装载的证据
let CURRENT_MODE = 'UNAVAILABLE';

function setBadge(el, text, cls) {
  el.textContent = text;
  el.className = 'badge ' + cls;
}
function escapeHtml(s) {
  return String(s == null ? '—' : s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function node(id, cls, title, text) {
  const el = $(id);
  el.className = 'node' + (el.classList.contains('wide') ? ' wide' : '') + ' ' + cls;
  el.querySelector('h3').textContent = title;
  el.querySelector('p').textContent = text;
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || ('HTTP ' + res.status));
  return body;
}

// ---------------------------------------------------------------- 环境
async function refreshHealth() {
  const h = await api('/api/health');
  const rt = h.runtime;
  const ctrl = h.controller;
  if (ctrl.status === 'RUNNING') {
    setBadge($('mode-badge'), 'RUNNING · ' + ctrl.mode, 'badge-running');
    CURRENT_MODE = 'RUNNING';
  } else if (!rt.online_possible) {
    setBadge($('mode-badge'), 'UNAVAILABLE（在线不可用）', 'badge-fail');
    CURRENT_MODE = 'UNAVAILABLE';
  } else {
    setBadge($('mode-badge'), 'ONLINE 就绪', 'badge-online');
    CURRENT_MODE = 'ONLINE';
  }
  setBadge($('env-badge'), rt.docker_available ? 'docker ✓' : 'docker ✗',
           rt.docker_available ? 'badge-online' : 'badge-fail');

  const warn = $('online-warn');
  if (!rt.online_possible) {
    warn.textContent = '在线实验不可用：' + rt.online_blocked_reasons.join('；') +
      '。可点击「离线回放」查看已归档的真实实验证据。';
    $('btn-start').disabled = true;
  } else {
    warn.textContent = '';
    $('btn-start').disabled = ctrl.status === 'RUNNING';
  }
  $('s-mode').textContent = CURRENT_MODE === 'UNAVAILABLE' ? '在线不可用' : CURRENT_MODE;
  return h;
}

// ---------------------------------------------------------------- run 列表
async function loadRuns() {
  const { runs } = await api('/api/runs');
  const sel = $('run-select');
  sel.innerHTML = '';
  runs.forEach(r => {
    const o = document.createElement('option');
    o.value = r.path;
    o.textContent = `${r.run_id}  [${r.kind}]`;
    sel.appendChild(o);
  });
  if (!runs.length) {
    const o = document.createElement('option');
    o.textContent = '（无可用证据）'; o.disabled = true; sel.appendChild(o);
  }
}

// ---------------------------------------------------------------- 渲染证据
function renderM3(m3) {
  const tb = $('m3-table').querySelector('tbody');
  tb.innerHTML = '';
  if (!m3) {
    $('m3-meta').textContent = '（无 M3 证据）';
    return;
  }
  $('m3-meta').textContent =
    `${m3.checks} checks / ${m3.failures} failures / ${m3.verdict}` +
    (m3.claims_checked ? ' · claims_checked=true' : '');
  (m3.scenarios || []).forEach(s => {
    const tr = document.createElement('tr');
    const goal = s.navsim_goals;
    const verdict = s.cid === 'ON06'
      ? (s.planner_outcome === 'PLANNER_RESULT_TIMEOUT' ? 'TIMEOUT（非 BLOCK）' : '—')
      : (goal > 0 ? '已执行' : '未执行');
    tr.innerHTML = `
      <td>${escapeHtml(s.cid)}</td>
      <td>${escapeHtml(s.adapter_decision)}</td>
      <td>${escapeHtml(s.planner_outcome)}</td>
      <td class="${s.gateway_arrivals ? 'ok' : ''}">${s.gateway_arrivals}</td>
      <td>${escapeHtml((s.gateway_decisions || []).map(d => d.decision).join(',') || '无')}</td>
      <td class="${goal ? 'ok' : ''}">${goal}</td>
      <td>${escapeHtml(verdict)}</td>`;
    tb.appendChild(tr);
  });
}

function renderTimeoutComparison(replay) {
  const box = $('timeout-compare');
  box.innerHTML = '';
  if (!replay || !replay.timeout_comparison) return;
  replay.timeout_comparison.forEach(row => {
    const d = document.createElement('div');
    d.className = 'stat';
    d.innerHTML = `
      <label>${escapeHtml(row.label)}</label>
      <strong class="mono">${escapeHtml(row.run_id)}</strong>
      <p class="mono" style="color:#8b949e;font-size:11px">${escapeHtml(row.tested_code_sha)}</p>
      <p>Planner: <b>${escapeHtml(row.planner)}</b><br>
         Gateway 到达: <b>${row.gateway_arrivals}</b>　决策: <b>${escapeHtml(row.gateway_decision || '无')}</b><br>
         NavSim Goal: <b>${row.navsim_goals}</b></p>`;
    box.appendChild(d);
  });
}

function renderFacts(f) {
  CURRENT = f;
  const tc = f.tested_commit || {};
  $('s-sha').textContent = (tc.tested_code_sha || tc.hardened_tested_code_sha ||
    tc.final_tested_code_sha || '未记录');
  $('s-run').textContent = tc.run_id || (f.replay && f.replay.run_id) || '—';

  const ctrl = f.controlled && f.controlled.facts ? f.controlled.facts.scenarios : {};
  const on01 = ctrl.ON01 || {}, on05 = ctrl.ON05 || {};
  $('s-stack').textContent =
    `Gateway 审计 ${on01.gateway_arrivals != null ? on01.gateway_arrivals : '—'} 到达 / ` +
    `NavSim Goal ${on01.navsim_goals != null ? on01.navsim_goals : '—'}`;

  // 三模块
  const three = f.three_real;
  if (three) {
    const byName = {};
    (three.modules || []).forEach(m => byName[m.module] = m);
    const m1 = byName.comm_risk || {}, m2 = byName.identity_trust || {}, m3 = byName.task_risk || {};
    node('n-m1', m1.status === 'UNKNOWN' ? 'warn' : 'info', 'M1 通信风险',
         `${m1.mode || ''} · ${m1.status || '—'} · schema ${m1.schema_ok}`);
    node('n-m2', m2.status === 'AUTHORIZED' ? 'warn' : 'info', 'M2 身份可信',
         `${m2.mode || ''} · ${m2.status || '—'}（历史解释，非当前请求身份）`);
    node('n-m3', m3.status === 'ALLOW_RECOMMENDED' ? 'info' : 'info', 'M3 任务风险',
         `${m3.mode || ''} · ${m3.status || '—'}（建议，非权威）`);
  } else if (f.replay && f.replay.modules) {
    const m = f.replay.modules;
    node('n-m1', 'info', 'M1 通信风险', m.m1 || '—');
    node('n-m2', 'warn', 'M2 身份可信', m.m2 || '—');
    node('n-m3', 'info', 'M3 任务风险', m.m3 || '—');
  }

  // F0 / Planner / Gateway / NavSim
  if (three) {
    const blocked = three.decision === 'ADAPTER_BLOCK';
    node('n-f0', blocked ? 'bad' : 'ok', 'F0 可信证据核验（STRICT）',
         `${three.decision} / ${three.reason_code || ''}`);
    node('n-planner', blocked ? 'bad' : 'info', 'Planner',
         blocked ? '未提交（F0 阻断）' : '已提交');
  }
  if (f.controlled) {
    const s01 = on01, s05 = on05;
    node('n-gateway', s05.gateway_decisions && s05.gateway_decisions.length ? 'warn' : 'ok',
         'SecurityGateway · TaskPolicy（权威）',
         `ON-01 ${s01.gateway_decisions || '—'} / ON-05 ${s05.gateway_decisions || '—'}（独立阻断）`);
    node('n-navsim', (s01.navsim_goals || 0) > 0 ? 'ok' : 'warn',
         'NavigationSim（recorded_only）',
         `ON-01 Goal ${s01.navsim_goals != null ? s01.navsim_goals : '—'} / ON-05 Goal ${s05.navsim_goals != null ? s05.navsim_goals : '—'}`);
    $('s-stack').textContent =
      `Gateway 到达 ${s01.gateway_arrivals != null ? s01.gateway_arrivals : '—'} / Goal ${s01.navsim_goals != null ? s01.navsim_goals : '—'}`;
  }

  renderM3(f.m3);
  $('footer-src').textContent = '证据来源：' + (f.run_path || '—');

  // DDS
  const dds = f.dds_enforce;
  const note = $('s-note');
  note.textContent = dds
    ? `DDS Enforce（独立实验，域绑定）：${dds.passed}/${dds.total} 通过 · 来源 ${dds.source}`
    : '未见 DDS Enforce 证据（该项为独立实验，可能不在本 run 内）。';
}

async function loadEvidence(path) {
  try {
    const facts = await api('/api/run?path=' + encodeURIComponent(path));
    renderFacts(facts);
    if (CURRENT_MODE !== 'RUNNING') {
      setBadge($('mode-badge'), 'REPLAY / 历史证据回放', 'badge-replay');
      CURRENT_MODE = 'REPLAY';
      $('s-mode').textContent = 'REPLAY（读取已归档证据，非本次在线运行）';
    }
  } catch (e) {
    $('s-note').textContent = '装载失败：' + e.message;
  }
}

async function loadReplay() {
  try {
    const r = await api('/api/replay');
    renderTimeoutComparison(r);
    const facts = await api('/api/run?path=' + encodeURIComponent(
      'submission/creative-work/replay'));
    renderFacts(facts);
    setBadge($('mode-badge'), 'REPLAY / 历史证据回放', 'badge-replay');
    CURRENT_MODE = 'REPLAY';
    $('s-mode').textContent = 'REPLAY（离线，不含 ROS 2 运行）';
    $('s-note').textContent = '离线回放：展示已归档真实证据，不代表本次重新执行。';
  } catch (e) {
    $('s-note').textContent = '回放装载失败：' + e.message;
  }
}

// ---------------------------------------------------------------- 运行
async function startRun() {
  const mode = $('mode-select').value;
  $('btn-start').disabled = true;
  try {
    const r = await api('/api/run/start', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ mode })
    });
    $('run-log').textContent = '已启动：' + r.mode + ' · run_id ' + r.run_id +
      '\n日志：' + r.log_path;
    setBadge($('mode-badge'), 'RUNNING · ' + r.mode, 'badge-running');
    pollStatus();
  } catch (e) {
    $('run-log').textContent = '启动失败：' + e.message;
    $('btn-start').disabled = false;
  }
}

async function stopRun() {
  try {
    const r = await api('/api/run/stop', { method: 'POST' });
    $('run-log').textContent += '\n' + r.message;
  } catch (e) {
    $('run-log').textContent += '\n停止失败：' + e.message;
  }
}

let POLL = null;
function pollStatus() {
  if (POLL) clearInterval(POLL);
  POLL = setInterval(async () => {
    try {
      const s = await api('/api/run/status');
      if (s.log_tail) $('run-log').textContent = s.log_tail;
      if (s.status !== 'RUNNING') {
        clearInterval(POLL); POLL = null;
        $('btn-start').disabled = !(await refreshHealth()).runtime.online_possible;
        if (s.status === 'DONE') {
          $('run-log').textContent += '\n\n✔ 实验完成（exit 0）。请点击「装载证据」查看结果。';
        } else if (s.status === 'FAIL') {
          $('run-log').textContent += '\n\n✘ ' + (s.error || '实验失败');
          setBadge($('mode-badge'), 'FAIL', 'badge-fail');
        }
      }
    } catch (e) { /* 保持静默，下次轮询再试 */ }
  }, 2000);
}

// ---------------------------------------------------------------- 启动
window.addEventListener('DOMContentLoaded', async () => {
  $('btn-load').onclick = () => {
    const p = $('run-select').value;
    if (p) loadEvidence(p);
  };
  $('btn-replay').onclick = loadReplay;
  $('btn-start').onclick = startRun;
  $('btn-stop').onclick = stopRun;
  await refreshHealth();
  await loadRuns();
  renderTimeoutComparison(await api('/api/replay').catch(() => null));
  const runs = await api('/api/runs').catch(() => ({runs: []}));
  const primary = runs.runs.find(r => r.kind === 'ONLINE_EVIDENCE');
  if (primary) loadEvidence(primary.path);
  else loadReplay();
});
