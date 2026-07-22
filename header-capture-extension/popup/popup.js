/**
 * popup.js — Popup 交互逻辑与剪贴板复制
 *
 * 功能：
 *   1. 从 Service Worker 加载配置并回填表单
 *   2. 从 Service Worker 加载捕获记录并渲染卡片列表
 *   3. 单条复制（Apifox 格式：Key: Value\n）
 *   4. 全部复制（每条记录带 URL 注释行）
 *   5. 清空记录
 *   6. 保存配置
 */

// ============================================================
// DOM 引用
// ============================================================
const captureList = document.getElementById('capture-list');
const emptyState = document.getElementById('empty-state');
const captureCount = document.getElementById('capture-count');
const copyAllBtn = document.getElementById('copy-all-btn');
const clearBtn = document.getElementById('clear-btn');
const settingsToggle = document.getElementById('settings-toggle');
const settingsPanel = document.getElementById('settings-panel');
const urlPatternsInput = document.getElementById('url-patterns-input');
const headerFieldsInput = document.getElementById('header-fields-input');
const saveBtn = document.getElementById('save-btn');
const toast = document.getElementById('toast');

// Inject Tab DOM 引用
const tabCapture = document.getElementById('tab-capture');
const tabInject = document.getElementById('tab-inject');
const panelCapture = document.getElementById('panel-capture');
const panelInject = document.getElementById('panel-inject');
const injectRulesList = document.getElementById('inject-rules-list');
const addRuleBtn = document.getElementById('add-rule-btn');
const injectSaveBtn = document.getElementById('inject-save-btn');

document.addEventListener('DOMContentLoaded', init);

// ============================================================
// 初始化
// ============================================================
async function init() {
  await loadSettings();
  await loadCaptures();
}

// ============================================================
// Inject 状态管理
// ============================================================
let injectRules = [];

/** 从 storage 加载注入规则到本地编辑状态 */
async function loadInjectRules() {
  try {
    const response = await chrome.runtime.sendMessage({ action: 'getSettings' });
    injectRules = (response.settings.injectRules || []).map(r => ({
      id: r.id,
      pattern: r.pattern,
      headers: r.headers.map(h => ({ name: h.name, value: h.value }))
    }));
    renderInjectRules();
  } catch (err) {
    injectRules = [];
    renderInjectRules();
  }
}

// ============================================================
// Inject 规则渲染
// ============================================================
function renderInjectRules() {
  injectRulesList.innerHTML = '';

  if (injectRules.length === 0) {
    injectRulesList.innerHTML = '<div class="empty-state"><p>暂无注入规则</p><p class="hint">点击下方按钮添加</p></div>';
    return;
  }

  injectRules.forEach((rule, ri) => {
    const card = createInjectRuleCard(rule, ri);
    injectRulesList.appendChild(card);
  });
}

function createInjectRuleCard(rule, ri) {
  const card = document.createElement('div');
  card.className = 'inject-rule-card';

  card.innerHTML = `
    <div class="inject-rule-header">
      <span class="inject-rule-label">规则 #${ri + 1}</span>
      <button class="btn-icon" data-action="delete-rule" data-ri="${ri}" title="删除规则">&#x2715;</button>
    </div>
    <input class="pattern-input"
           type="text"
           placeholder="*.example.com/api/*"
           value="${escapeHtml(rule.pattern)}"
           data-ri="${ri}"
           data-field="pattern">
    <div class="inject-headers-label">Headers</div>
    <div class="inject-headers-rows" data-ri="${ri}">
      ${rule.headers.map((h, hi) => `
        <div class="inject-header-row">
          <input class="key-input"
                 type="text"
                 placeholder="Header-Name"
                 value="${escapeHtml(h.name)}"
                 data-ri="${ri}"
                 data-hi="${hi}"
                 data-field="name">
          <input class="val-input"
                 type="text"
                 placeholder="Value"
                 value="${escapeHtml(h.value)}"
                 data-ri="${ri}"
                 data-hi="${hi}"
                 data-field="value">
          <button class="btn-icon" data-action="delete-header" data-ri="${ri}" data-hi="${hi}" title="删除">&#x2715;</button>
        </div>
      `).join('')}
    </div>
    <button class="btn-add-header" data-action="add-header" data-ri="${ri}">+ 添加 Header</button>
  `;

  return card;
}

// ============================================================
// Inject 事件代理
// ============================================================
injectRulesList.addEventListener('click', (e) => {
  const target = e.target;

  // 删除规则
  if (target.dataset.action === 'delete-rule') {
    const ri = parseInt(target.dataset.ri);
    injectRules.splice(ri, 1);
    renderInjectRules();
    return;
  }

  // 删除 Header
  if (target.dataset.action === 'delete-header') {
    const ri = parseInt(target.dataset.ri);
    const hi = parseInt(target.dataset.hi);
    if (injectRules[ri].headers.length > 1) {
      injectRules[ri].headers.splice(hi, 1);
      renderInjectRules();
    }
    return;
  }

  // 添加 Header
  if (target.dataset.action === 'add-header') {
    const ri = parseInt(target.dataset.ri);
    injectRules[ri].headers.push({ name: '', value: '' });
    renderInjectRules();
    return;
  }
});

injectRulesList.addEventListener('input', (e) => {
  const target = e.target;
  if (!target.dataset.ri) return;

  const ri = parseInt(target.dataset.ri);
  const field = target.dataset.field;

  if (field === 'pattern') {
    injectRules[ri].pattern = target.value;
  } else if (field === 'name' || field === 'value') {
    const hi = parseInt(target.dataset.hi);
    if (injectRules[ri] && injectRules[ri].headers[hi]) {
      injectRules[ri].headers[hi][field] = target.value;
    }
  }
});

// ============================================================
// 添加规则
// ============================================================
addRuleBtn.addEventListener('click', () => {
  const maxId = injectRules.reduce((max, r) => Math.max(max, r.id || 0), 0);
  injectRules.push({
    id: maxId + 1,
    pattern: '',
    headers: [{ name: '', value: '' }]
  });
  renderInjectRules();
});

// ============================================================
// 保存注入规则
// ============================================================
injectSaveBtn.addEventListener('click', async () => {
  const validRules = injectRules
    .filter(r => r.pattern.trim())
    .map((r, i) => ({
      id: i + 1,
      pattern: r.pattern.trim(),
      headers: r.headers.filter(h => h.name.trim())
    }));

  const finalRules = validRules.filter(r => r.headers.length > 0);

  try {
    await chrome.runtime.sendMessage({
      action: 'saveSettings',
      settings: { injectRules: finalRules }
    });
    injectRules = finalRules.map(r => ({
      id: r.id,
      pattern: r.pattern,
      headers: r.headers.map(h => ({ name: h.name, value: h.value }))
    }));
    renderInjectRules();
    showToast('注入规则已保存');
  } catch (err) {
    showToast('保存失败: ' + (err.message || '未知错误'));
  }
});

// ============================================================
// Tab 切换
// ============================================================
tabCapture.addEventListener('click', () => {
  tabCapture.classList.add('active');
  tabInject.classList.remove('active');
  panelCapture.classList.remove('hidden');
  panelInject.classList.add('hidden');
});

tabInject.addEventListener('click', () => {
  tabInject.classList.add('active');
  tabCapture.classList.remove('active');
  panelInject.classList.remove('hidden');
  panelCapture.classList.add('hidden');
  loadInjectRules();
});

// ============================================================
// Toast 提示
// ============================================================
function showToast(msg, duration = 2000) {
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), duration);
}

// ============================================================
// Step 2: loadSettings — 从 Service Worker 加载并回填配置表单
// ============================================================
async function loadSettings() {
  try {
    const response = await chrome.runtime.sendMessage({ action: 'getSettings' });
    const s = response.settings;
    urlPatternsInput.value = (s.urlPatterns || []).join('\n');
    headerFieldsInput.value = (s.headerFields || []).join(', ');
  } catch (err) {
    // Service Worker 未就绪时静默使用默认空值
    console.warn('Failed to load settings:', err);
  }
}

// ============================================================
// Step 3: loadCaptures — 加载捕获记录并渲染列表
// ============================================================
async function loadCaptures() {
  try {
    const response = await chrome.runtime.sendMessage({ action: 'getCaptures' });
    const captures = response.captures || [];
    renderCaptures(captures);
  } catch (err) {
    console.warn('Failed to load captures:', err);
    renderCaptures([]);
  }
}

function renderCaptures(captures) {
  // 移除旧记录（保留 emptyState）
  captureList.querySelectorAll('.capture-card').forEach(el => el.remove());

  const count = captures.length;
  captureCount.textContent = count;
  copyAllBtn.disabled = count === 0;

  if (count === 0) {
    emptyState.classList.remove('hidden');
    return;
  }

  emptyState.classList.add('hidden');

  // 倒序渲染（新记录在上）
  for (let i = captures.length - 1; i >= 0; i--) {
    const card = createCaptureCard(captures[i], i);
    captureList.appendChild(card);
  }
}

// ============================================================
// Step 4: createCaptureCard — 渲染单条记录
// ============================================================
function createCaptureCard(capture, index) {
  const card = document.createElement('div');
  card.className = 'capture-card';

  const methodClass = 'method-' + capture.method.toUpperCase();

  card.innerHTML = `
    <div class="meta">
      <span class="method-badge ${methodClass}">${escapeHtml(capture.method)}</span>
      <span class="capture-url" title="${escapeHtml(capture.url)}">${escapeHtml(truncateUrl(capture.url))}</span>
    </div>
    <div class="header-tags">
      ${Object.keys(capture.headers).map(k =>
        `<span class="header-tag">${escapeHtml(k)}</span>`
      ).join('')}
    </div>
    <div class="capture-actions">
      <button class="btn-small" data-action="copy" data-index="${index}">复制</button>
    </div>
  `;

  // 绑定复制事件
  card.querySelector('[data-action="copy"]').addEventListener('click', (e) => {
    e.stopPropagation();
    copyCapture(capture);
  });

  // 点击卡片整体也复制
  card.addEventListener('click', () => copyCapture(capture));

  return card;
}

function truncateUrl(url) {
  return url.length > 60 ? url.substring(0, 60) + '...' : url;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ============================================================
// Step 5: copyCapture — 剪贴板复制（Apifox 格式）
// ============================================================
async function copyCapture(capture) {
  // 主格式: "Key: Value\n" 逐行
  const lines = Object.entries(capture.headers).map(
    ([name, value]) => `${name}: ${value}`
  );
  const text = lines.join('\n');

  try {
    await navigator.clipboard.writeText(text);
    showToast('已复制，可直接粘贴到 Apifox 请求头');
  } catch {
    // 旧浏览器降级
    showToast('复制失败，请手动选择文本');
  }
}

// ============================================================
// Step 6: "复制全部" — 合并所有捕获记录
// ============================================================
copyAllBtn.addEventListener('click', async () => {
  try {
    const response = await chrome.runtime.sendMessage({ action: 'getCaptures' });
    const captures = response.captures || [];

    if (captures.length === 0) return;

    const allLines = captures.map(c => {
      const headerLines = Object.entries(c.headers).map(
        ([name, value]) => `${name}: ${value}`
      );
      return `# ${c.method} ${c.url}\n${headerLines.join('\n')}`;
    });

    const text = allLines.join('\n\n');

    await navigator.clipboard.writeText(text);
    showToast(`已复制 ${captures.length} 条记录`);
  } catch {
    showToast('复制失败');
  }
});

// ============================================================
// Step 7: "清空"与"保存配置"事件绑定
// ============================================================
clearBtn.addEventListener('click', async () => {
  try {
    await chrome.runtime.sendMessage({ action: 'clearCaptures' });
    await loadCaptures();
    showToast('已清空');
  } catch (err) {
    showToast('清空失败');
  }
});

saveBtn.addEventListener('click', async () => {
  try {
    const urlPatterns = urlPatternsInput.value
      .split('\n')
      .map(s => s.trim())
      .filter(s => s.length > 0);

    const headerFields = headerFieldsInput.value
      .split(',')
      .map(s => s.trim())
      .filter(s => s.length > 0);

    await chrome.runtime.sendMessage({
      action: 'saveSettings',
      settings: { urlPatterns, headerFields }
    });

    showToast('配置已保存');
  } catch (err) {
    showToast('保存失败');
  }
});

settingsToggle.addEventListener('click', () => {
  settingsPanel.classList.toggle('hidden');
});
