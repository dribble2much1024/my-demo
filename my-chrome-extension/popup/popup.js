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

document.addEventListener('DOMContentLoaded', init);

// ============================================================
// 初始化
// ============================================================
async function init() {
  await loadLlmConfig();
  await loadSettings();
  await loadCaptures();
}

// ============================================================
// Toast 提示
// ============================================================
function showToast(msg, duration = 2000) {
  toast.textContent = msg;
  toast.classList.remove('hidden');
  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
    toast.classList.add('hidden');
  }, duration);
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

// ============================================================
// Tab 切换
// ============================================================
const tabHeader = document.getElementById('tab-header');
const tabBookmark = document.getElementById('tab-bookmark');
const tabSummary = document.getElementById('tab-summary');
const tabLlm = document.getElementById('tab-llm');
const panelHeader = document.getElementById('panel-header');
const panelBookmark = document.getElementById('panel-bookmark');
const panelSummary = document.getElementById('panel-summary');
const panelLlm = document.getElementById('panel-llm');

const tabs = [
  { btn: tabHeader, panel: panelHeader },
  { btn: tabBookmark, panel: panelBookmark, onShow: loadBookmarkStats },
  { btn: tabSummary, panel: panelSummary },
  { btn: tabLlm, panel: panelLlm, onShow: loadLlmConfig }
];

function activateTab(activeBtn) {
  for (const t of tabs) {
    const isActive = t.btn === activeBtn;
    t.btn.classList.toggle('active', isActive);
    t.panel.classList.toggle('active', isActive);
    if (isActive && t.onShow) t.onShow();
  }
}

for (const t of tabs) {
  t.btn.addEventListener('click', () => activateTab(t.btn));
}

// ============================================================
// 书签管理入口
// ============================================================
document.getElementById('open-sidepanel-btn').addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  await chrome.sidePanel.open({ windowId: tab.windowId });
  window.close();
});

// ============================================================
// 页面总结入口
// ============================================================
document.getElementById('open-summary-btn').addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  await chrome.storage.local.set({ sidepanelView: 'summary' });
  await chrome.sidePanel.open({ windowId: tab.windowId });
  chrome.runtime.sendMessage({ action: 'switchToSummary' }).catch(() => {});
  window.close();
});

async function loadBookmarkStats() {
  try {
    const tree = await chrome.bookmarks.getTree();
    let total = 0;
    let folders = 0;
    function count(node) {
      if (node.url) total++;
      else folders++;
      if (node.children) node.children.forEach(count);
    }
    if (tree[0] && tree[0].children) tree[0].children.forEach(count);
    document.getElementById('stat-total').textContent = total;
    document.getElementById('stat-folders').textContent = folders;
    document.getElementById('bookmark-stat').textContent = total;
  } catch (e) {
    console.warn('Failed to load bookmark stats', e);
  }
}

// ============================================================
// LLM 配置
// ============================================================
const llmEndpoint = document.getElementById('llm-endpoint');
const llmApikey = document.getElementById('llm-apikey');
const llmModel = document.getElementById('llm-model');
const llmSaveBtn = document.getElementById('llm-save-btn');

async function loadLlmConfig() {
  try {
    const data = await chrome.storage.local.get('llmConfig');
    if (data.llmConfig) {
      llmEndpoint.value = data.llmConfig.endpoint || '';
      llmApikey.value = data.llmConfig.apiKey || '';
      llmModel.value = data.llmConfig.model || '';
    }
  } catch (e) { /* ignore */ }
}

llmSaveBtn.addEventListener('click', async () => {
  await chrome.storage.local.set({
    llmConfig: {
      endpoint: llmEndpoint.value.trim(),
      apiKey: llmApikey.value.trim(),
      model: llmModel.value.trim()
    }
  });
  showToast('LLM 配置已保存');
});
