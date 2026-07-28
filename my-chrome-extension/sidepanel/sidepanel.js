// ============================================================
// DOM 引用
// ============================================================
const bookmarkTree = document.getElementById('bookmark-tree');
const searchInput = document.getElementById('search-input');
const bulkBar = document.getElementById('bulk-bar');
const bulkCount = document.getElementById('bulk-count');
const toast = document.getElementById('sp-toast');
const modalOverlay = document.getElementById('modal-overlay');
const modalContent = document.getElementById('modal-content');
const chatPanel = document.getElementById('chat-panel');
const chatMessages = document.getElementById('chat-messages');
const chatInputEl = document.getElementById('chat-input');
const chatToggle = document.getElementById('chat-toggle');

// ============================================================
// 状态
// ============================================================
let bookmarksData = [];       // 展平的书签列表 [{ id, title, url, parentId, ... }]
let selectedIds = new Set();

// ============================================================
// Toast
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
// Modal
// ============================================================
function showModal(html) {
  modalContent.innerHTML = html;
  modalOverlay.classList.remove('hidden');
}
function hideModal() { modalOverlay.classList.add('hidden'); }
modalOverlay.addEventListener('click', (e) => {
  if (e.target === modalOverlay) hideModal();
});

// ============================================================
// 书签详情面板 (标签与备注)
// ============================================================
function showDetailPanel(node) {
  const html = `
    <h2>${escapeHtml(node.title)}</h2>
    <p style="font-size:11px;color:#9ca3af;word-break:break-all;">${escapeHtml(node.url || '(文件夹)')}</p>
    <label style="display:block;font-size:11px;color:#6b7280;margin-top:8px;">标签 (逗号分隔)</label>
    <input id="detail-tags" type="text" placeholder="react, tutorial" style="width:100%;padding:4px 6px;border:1px solid #d1d5db;border-radius:4px;font-size:12px;">
    <label style="display:block;font-size:11px;color:#6b7280;margin-top:8px;">备注</label>
    <textarea id="detail-note" rows="3" maxlength="500" placeholder="备注..." style="width:100%;padding:4px 6px;border:1px solid #d1d5db;border-radius:4px;font-size:12px;resize:vertical;"></textarea>
    <div style="display:flex;gap:8px;margin-top:10px;">
      <button id="detail-save" class="sp-btn-primary">保存</button>
      <button id="detail-cancel" class="sp-btn-small">取消</button>
    </div>
  `;
  showModal(html);

  // 加载已有 meta
  sendMessage('getBookmarkMeta', { id: node.id }).then(res => {
    document.getElementById('detail-tags').value = (res.meta?.tags || []).join(', ');
    document.getElementById('detail-note').value = res.meta?.note || '';
  });

  document.getElementById('detail-save').addEventListener('click', async () => {
    const tags = document.getElementById('detail-tags').value.split(',').map(s => s.trim()).filter(Boolean);
    const note = document.getElementById('detail-note').value;
    await sendMessage('saveBookmarkMeta', { id: node.id, tags, note });
    hideModal();
    showToast('已保存');
  });

  document.getElementById('detail-cancel').addEventListener('click', hideModal);
}

// ============================================================
// 展平书签树
// ============================================================
function flattenTree(nodes, parentTitle = '', level = 0) {
  const result = [];
  for (const node of nodes) {
    if (node.url) {
      result.push({
        id: node.id,
        title: node.title,
        url: node.url,
        parentId: node.parentId,
        parentTitle: parentTitle,
        dateAdded: node.dateAdded
      });
    }
    if (node.children) {
      result.push(...flattenTree(node.children, node.title, level + 1));
    }
  }
  return result;
}

// ============================================================
// 渲染书签树
// ============================================================
function renderTree(nodes, container) {
  container.innerHTML = '';
  for (const node of nodes) {
    const el = createTreeNode(node);
    container.appendChild(el);
  }
}

function createTreeNode(node) {
  const wrapper = document.createElement('div');
  wrapper.className = 'tree-node';
  wrapper.dataset.id = node.id;

  const row = document.createElement('div');
  row.className = 'tree-row';
  row.dataset.id = node.id;
  row.dataset.title = (node.title || '').toLowerCase();
  row.dataset.url = (node.url || '').toLowerCase();

  // 展开/折叠箭头
  const hasChildren = node.children && node.children.length > 0;
  const toggle = document.createElement('span');
  toggle.className = 'tree-toggle' + (hasChildren ? '' : ' empty');
  toggle.textContent = hasChildren ? '▸' : '';
  toggle.addEventListener('click', (e) => {
    e.stopPropagation();
    const children = wrapper.querySelector(':scope > .tree-children');
    if (children) {
      children.classList.toggle('collapsed');
      toggle.textContent = children.classList.contains('collapsed') ? '▸' : '▾';
    }
  });
  row.appendChild(toggle);

  // 图标
  const icon = document.createElement('span');
  icon.className = 'tree-icon';
  icon.textContent = node.url ? '🔖' : '📁';
  row.appendChild(icon);

  // Checkbox (多选)
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.className = 'tree-checkbox';
  cb.addEventListener('click', (e) => e.stopPropagation());
  cb.addEventListener('change', () => {
    if (cb.checked) selectedIds.add(node.id);
    else selectedIds.delete(node.id);
    updateBulkBar();
  });
  row.appendChild(cb);

  // 标题
  const title = document.createElement('span');
  title.className = 'tree-title' + (node.url ? '' : ' folder');
  title.textContent = node.title || '(无标题)';
  row.appendChild(title);

  // URL 片段
  if (node.url) {
    const urlSpan = document.createElement('span');
    urlSpan.className = 'tree-url';
    try { urlSpan.textContent = new URL(node.url).hostname; } catch (_) {}
    row.appendChild(urlSpan);
  }

  // 右键菜单
  row.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    showContextMenu(e.clientX, e.clientY, node);
  });

  // 单击选中
  row.addEventListener('click', () => {
    document.querySelectorAll('.tree-row.selected').forEach(r => r.classList.remove('selected'));
    row.classList.add('selected');
    if (node.url) showDetailPanel(node);
  });

  wrapper.appendChild(row);

  // 子节点
  if (hasChildren) {
    const childrenContainer = document.createElement('div');
    childrenContainer.className = 'tree-children collapsed';
    toggle.textContent = '▸';
    for (const child of node.children) {
      childrenContainer.appendChild(createTreeNode(child));
    }
    wrapper.appendChild(childrenContainer);
  }

  return wrapper;
}

// ============================================================
// 右键菜单
// ============================================================
function showContextMenu(x, y, node) {
  // 移除旧菜单
  document.querySelector('.sp-context-menu')?.remove();

  const menu = document.createElement('div');
  menu.className = 'sp-context-menu';
  menu.style.cssText = `position:fixed;left:${x}px;top:${y}px;z-index:300;background:#fff;border:1px solid #e5e7eb;border-radius:6px;padding:4px 0;box-shadow:0 4px 12px rgba(0,0,0,0.1);min-width:140px;`;

  const items = [
    { label: '在新标签页打开', action: () => node.url && chrome.tabs.create({ url: node.url }) },
    { label: '复制 URL', action: () => node.url && navigator.clipboard.writeText(node.url).then(() => showToast('已复制')) },
    { label: '重命名', action: () => renameBookmark(node) },
    { label: '删除', action: () => deleteBookmarks([node.id]) },
  ];

  if (!node.url) {
    // 文件夹专用
    items.length = 0;
    items.push({ label: '展开全部', action: () => expandAll(node.id) });
    items.push({ label: '折叠全部', action: () => collapseAll(node.id) });
    items.push({ label: '删除文件夹', action: () => deleteBookmarks([node.id]) });
  }

  for (const item of items) {
    const el = document.createElement('div');
    el.className = 'ctx-item';
    el.style.cssText = 'padding:6px 12px;cursor:pointer;font-size:12px;';
    el.textContent = item.label;
    el.addEventListener('mouseenter', () => el.style.background = '#f3f4f6');
    el.addEventListener('mouseleave', () => el.style.background = '');
    el.addEventListener('click', () => { item.action(); menu.remove(); });
    menu.appendChild(el);
  }

  document.body.appendChild(menu);
  document.addEventListener('click', () => menu.remove(), { once: true });
}

// ============================================================
// 批量操作栏
// ============================================================
function updateBulkBar() {
  const count = selectedIds.size;
  if (count > 0) {
    bulkBar.classList.remove('hidden');
    bulkCount.textContent = `选中 ${count} 项`;
  } else {
    bulkBar.classList.add('hidden');
  }
}

document.getElementById('bulk-delete').addEventListener('click', () => {
  deleteBookmarks([...selectedIds]);
});

document.getElementById('bulk-open').addEventListener('click', () => {
  for (const id of selectedIds) {
    const bm = findBookmarkById(id);
    if (bm && bm.url) chrome.tabs.create({ url: bm.url, active: false });
  }
});

document.getElementById('bulk-move').addEventListener('click', () => {
  showFolderPicker('选择目标文件夹', async (targetId) => {
    await moveBookmarks([...selectedIds], targetId);
  });
});

// ============================================================
// 书签操作（通过消息代理到 Service Worker）
// ============================================================
async function sendMessage(action, payload = {}) {
  return chrome.runtime.sendMessage({ action, ...payload });
}

function findBookmarkById(id) {
  return bookmarksData.find(b => b.id === id);
}

async function deleteBookmarks(ids) {
  if (!ids.length) return;
  if (!confirm(`确认删除 ${ids.length} 个书签？`)) return;
  try {
    const result = await sendMessage('deleteBookmarks', { ids });
    if (result.success) { showToast('已删除'); loadBookmarks(); }
  } catch (e) { showToast('删除失败'); }
}

async function moveBookmarks(ids, targetId) {
  try {
    const result = await sendMessage('moveBookmarks', { ids, parentId: targetId });
    if (result.success) { showToast('已移动'); loadBookmarks(); }
  } catch (e) { showToast('移动失败'); }
}

async function renameBookmark(node) {
  const newName = prompt('新名称:', node.title);
  if (!newName || newName === node.title) return;
  try {
    await sendMessage('renameBookmark', { id: node.id, title: newName });
    showToast('已重命名');
    loadBookmarks();
  } catch (e) { showToast('重命名失败'); }
}

async function expandAll(folderId) {
  const el = document.querySelector(`[data-id="${folderId}"]`);
  if (!el) return;
  el.querySelectorAll('.tree-children').forEach(c => c.classList.remove('collapsed'));
  el.querySelectorAll('.tree-toggle').forEach(t => { if (!t.classList.contains('empty')) t.textContent = '▾'; });
}

async function collapseAll(folderId) {
  const el = document.querySelector(`[data-id="${folderId}"]`);
  if (!el) return;
  el.querySelectorAll('.tree-children').forEach(c => c.classList.add('collapsed'));
  el.querySelectorAll('.tree-toggle').forEach(t => { if (!t.classList.contains('empty')) t.textContent = '▸'; });
}

// ============================================================
// 搜索过滤
// ============================================================
searchInput.addEventListener('input', () => {
  const query = searchInput.value.trim().toLowerCase();
  const rows = bookmarkTree.querySelectorAll('.tree-row');
  if (!query) {
    rows.forEach(r => { r.classList.remove('search-hidden', 'search-match'); });
    // 恢复折叠状态和箭头图标
    bookmarkTree.querySelectorAll('.tree-children').forEach(c => c.classList.add('collapsed'));
    bookmarkTree.querySelectorAll('.tree-toggle:not(.empty)').forEach(t => t.textContent = '▸');
    return;
  }
  rows.forEach(r => {
    const title = r.dataset.title || '';
    const url = r.dataset.url || '';
    if (title.includes(query) || url.includes(query)) {
      r.classList.remove('search-hidden');
      r.classList.add('search-match');
      // 展开所有祖先
      let parent = r.closest('.tree-children');
      while (parent) {
        parent.classList.remove('collapsed');
        const nodeEl = parent.closest('.tree-node');
        if (nodeEl) {
          const toggle = nodeEl.querySelector(':scope > .tree-row .tree-toggle');
          if (toggle) toggle.textContent = '▾';
        }
        parent = parent.parentElement?.closest('.tree-children');
      }
    } else {
      r.classList.add('search-hidden');
      r.classList.remove('search-match');
    }
  });
});

// ============================================================
// 文件夹选择器 (弹窗)
// ============================================================
function showFolderPicker(title, callback) {
  showModal(`<h2>${title}</h2><div class="folder-list" style="max-height:250px;overflow-y:auto;">加载中...</div><button id="modal-cancel" class="sp-btn-small" style="margin-top:8px;">取消</button>`);
  modalContent.querySelector('#modal-cancel')?.addEventListener('click', hideModal);

  chrome.bookmarks.getTree().then(tree => {
    const folders = [];
    function collectFolders(nodes) {
      for (const n of nodes) {
        if (!n.url) folders.push({ id: n.id, title: n.title });
        if (n.children) collectFolders(n.children);
      }
    }
    collectFolders(tree);
    const list = modalContent.querySelector('.folder-list');
    list.innerHTML = folders.map(f =>
      `<div class="folder-option" data-id="${f.id}" style="padding:6px 8px;cursor:pointer;border-radius:4px;">📁 ${f.title}</div>`
    ).join('');
    list.querySelectorAll('.folder-option').forEach(opt => {
      opt.addEventListener('click', () => { hideModal(); callback(opt.dataset.id); });
    });
  });
}

// ============================================================
// 初始化
// ============================================================
async function loadBookmarks() {
  try {
    const tree = await chrome.bookmarks.getTree();
    bookmarksData = flattenTree(tree);
    renderTree(tree, bookmarkTree);
  } catch (e) {
    console.error('Failed to load bookmarks', e);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  loadBookmarks();
});

// ============================================================
// 工具函数
// ============================================================
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ============================================================
// 文件夹健康检查 (M9)
// ============================================================
function runFolderHealthCheck() {
  const issues = [];
  const allFolders = [];

  function scan(nodes, depth = 0) {
    for (const n of nodes) {
      if (!n.url) {
        const bookmarkCount = (n.children || []).filter(c => c.url).length;
        const folderCount = (n.children || []).filter(c => !c.url).length;
        allFolders.push({ id: n.id, title: n.title, depth, bookmarkCount, folderCount, totalChildren: (n.children || []).length });

        if (bookmarkCount === 0 && folderCount === 0) {
          issues.push({ id: n.id, title: n.title, type: '空文件夹', severity: 'low' });
        }
        if (depth >= 4) {
          issues.push({ id: n.id, title: n.title, type: '层级过深', severity: 'medium', depth });
        }
        if (bookmarkCount > 50) {
          issues.push({ id: n.id, title: n.title, type: '书签过多 (' + bookmarkCount + '个)', severity: 'medium' });
        }
        if (n.children) scan(n.children, depth + 1);
      }
    }
  }

  chrome.bookmarks.getTree().then(tree => {
    scan(tree);

    const html = `
      <h2>文件夹健康检查</h2>
      ${issues.length === 0 ? '<p>所有文件夹状态良好 ✅</p>' : `
        <p>发现 ${issues.length} 个问题:</p>
        <div style="max-height:300px;overflow-y:auto;">
          ${issues.map(issue => `
            <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #f3f4f6;font-size:12px;">
              <span>${issue.type === '空文件夹' ? '📭' : issue.type === '层级过深' ? '📎' : '📊'}</span>
              <span style="flex:1;">${escapeHtml(issue.title)}</span>
              <span style="color:${issue.severity === 'low' ? '#9ca3af' : '#f59e0b'};">${issue.type}${issue.depth ? ' (深度' + issue.depth + ')' : ''}</span>
              ${issue.type === '空文件夹'
                ? `<button class="sp-btn-small sp-btn-danger fix-delete-folder" data-id="${issue.id}">删除</button>`
                : ''}
            </div>
          `).join('')}
        </div>
      `}
      <button id="modal-cancel" class="sp-btn-small" style="margin-top:8px;">关闭</button>
    `;
    showModal(html);

    modalContent.querySelectorAll('.fix-delete-folder').forEach(btn => {
      btn.addEventListener('click', async () => {
        await sendMessage('deleteBookmarks', { ids: [btn.dataset.id] });
        hideModal();
        showToast('已删除空文件夹');
        loadBookmarks();
      });
    });

    document.getElementById('modal-cancel')?.addEventListener('click', hideModal);
  });
}

// ============================================================
// 书签统计面板 (M10)
// ============================================================
document.getElementById('stats-btn').addEventListener('click', async () => {
  const tree = await chrome.bookmarks.getTree();
  let totalBookmarks = 0;
  let totalFolders = 0;
  const domainCounts = {};
  const folderSizes = [];
  const recentBookmarks = [];
  const weekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;

  function scan(nodes) {
    for (const n of nodes) {
      if (n.url) {
        totalBookmarks++;
        try { domainCounts[new URL(n.url).hostname] = (domainCounts[new URL(n.url).hostname] || 0) + 1; } catch (_) {}
        if (n.dateAdded && n.dateAdded > weekAgo) recentBookmarks.push(n);
      } else {
        totalFolders++;
        const bmCount = (n.children || []).filter(c => c.url).length;
        if (bmCount > 0) folderSizes.push({ title: n.title, count: bmCount });
      }
      if (n.children) scan(n.children);
    }
  }
  scan(tree);

  folderSizes.sort((a, b) => b.count - a.count);
  const topDomains = Object.entries(domainCounts).sort((a, b) => b[1] - a[1]).slice(0, 5);
  const topFolders = folderSizes.slice(0, 10);

  const maxFolderSize = topFolders[0]?.count || 1;
  const folderBars = topFolders.map(f => {
    const pct = Math.round(f.count / maxFolderSize * 100);
    return `<div style="margin:2px 0;"><span style="font-size:11px;">${escapeHtml(f.title)}</span>
      <div style="height:6px;background:#e5e7eb;border-radius:3px;margin-top:2px;">
        <div style="height:100%;width:${pct}%;background:#3b82f6;border-radius:3px;"></div>
      </div><span style="font-size:10px;color:#9ca3af;">${f.count} 个</span></div>`;
  }).join('');

  const html = `
    <h2>书签统计</h2>
    <div style="display:flex;gap:12px;margin-bottom:12px;">
      <div style="flex:1;text-align:center;background:#f3f4f6;border-radius:8px;padding:8px;">
        <div style="font-size:22px;font-weight:700;">${totalBookmarks}</div>
        <div style="font-size:11px;color:#6b7280;">书签总数</div>
      </div>
      <div style="flex:1;text-align:center;background:#f3f4f6;border-radius:8px;padding:8px;">
        <div style="font-size:22px;font-weight:700;">${totalFolders}</div>
        <div style="font-size:11px;color:#6b7280;">文件夹</div>
      </div>
    </div>
    <h3 style="font-size:12px;margin:8px 0;">📊 文件夹书签分布 (Top 10)</h3>
    ${folderBars}
    <h3 style="font-size:12px;margin:8px 0;">🌐 域名 Top 5</h3>
    ${topDomains.map(([domain, count], i) =>
      `<div style="font-size:11px;padding:2px 0;">${i + 1}. ${domain} (${count})</div>`
    ).join('')}
    <h3 style="font-size:12px;margin:8px 0;">🆕 最近 7 天添加 (${recentBookmarks.length})</h3>
    <div style="max-height:120px;overflow-y:auto;font-size:11px;color:#6b7280;">
      ${recentBookmarks.slice(0, 15).map(b =>
        `<div style="padding:2px 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">🔖 ${escapeHtml(b.title)}</div>`
      ).join('')}
    </div>
    <button id="health-check-btn" class="sp-btn-small" style="margin-top:8px;">🔍 文件夹健康检查</button>
    <button id="modal-cancel" class="sp-btn-small" style="margin-top:8px;">关闭</button>
  `;
  showModal(html);

  document.getElementById('health-check-btn')?.addEventListener('click', () => {
    hideModal();
    runFolderHealthCheck();
  });

  document.getElementById('modal-cancel')?.addEventListener('click', hideModal);
});

// ============================================================
// 监听快捷键聚焦搜索
// ============================================================
chrome.runtime.onMessage.addListener((message) => {
  if (message.action === 'focusSearch') {
    searchInput.focus();
  }
});

// ============================================================
// LLM 对话
// ============================================================
chatToggle.addEventListener('click', () => {
  chatPanel.classList.toggle('collapsed');
  chatToggle.textContent = chatPanel.classList.contains('collapsed') ? '+' : '−';
});

function addChatMessage(role, content, planActions) {
  const div = document.createElement('div');
  div.className = 'chat-msg ' + role;
  div.textContent = role === 'user' ? content : '';
  if (role === 'assistant') {
    if (planActions) {
      div.innerHTML = '<p>' + escapeHtml(content) + '</p>';
      for (const op of planActions) {
        const item = document.createElement('div');
        item.className = 'plan-item';
        item.textContent = describeOperation(op);
        div.appendChild(item);
      }
      const btnGroup = document.createElement('div');
      btnGroup.className = 'chat-action-btns';
      const execBtn = document.createElement('button');
      execBtn.className = 'sp-btn-primary';
      execBtn.textContent = '执行';
      execBtn.addEventListener('click', () => executePlan(planActions));
      const cancelBtn = document.createElement('button');
      cancelBtn.className = 'sp-btn-small';
      cancelBtn.textContent = '取消';
      cancelBtn.addEventListener('click', () => addChatMessage('assistant', '已取消'));
      btnGroup.appendChild(execBtn);
      btnGroup.appendChild(cancelBtn);
      div.appendChild(btnGroup);
    } else {
      div.textContent = content;
    }
  }
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function describeOperation(op) {
  switch (op.type) {
    case 'createFolder': return '📁 创建文件夹: ' + op.title;
    case 'move': return '→ 移动 ' + (op.bookmarkIds?.length || 0) + ' 个书签';
    case 'rename': return '✏ 重命名书签 → ' + op.newTitle;
    case 'delete': return '🗑 删除 ' + (op.bookmarkIds?.length || 0) + ' 个书签';
    default: return JSON.stringify(op);
  }
}

async function executePlan(plan) {
  try {
    const res = await sendMessage('executePlan', { plan });
    if (res.success) {
      addChatMessage('assistant', '完成: ' + res.executed + '/' + res.total + ' 个操作已执行');
      loadBookmarks();
    } else {
      addChatMessage('assistant', '执行失败: ' + res.error);
    }
  } catch (e) {
    addChatMessage('assistant', '执行出错: ' + e.message);
  }
}

document.getElementById('chat-send').addEventListener('click', async () => {
  const msg = chatInputEl.value.trim();
  if (!msg) return;
  addChatMessage('user', msg);
  chatInputEl.value = '';

  addChatMessage('assistant', '分析中...');
  try {
    const res = await sendMessage('llmChat', { userMessage: msg });
    chatMessages.lastChild?.remove();

    if (res.error) {
      addChatMessage('assistant', '错误: ' + res.error);
    } else if (res.plan) {
      addChatMessage('assistant', res.plan.explanation || '建议以下操作:', res.plan.operations);
    }
  } catch (e) {
    chatMessages.lastChild?.remove();
    addChatMessage('assistant', '请求失败: ' + e.message);
  }
});

// 回车发送
chatInputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    document.getElementById('chat-send').click();
  }
});

// ============================================================
// 智能分类按钮
// ============================================================
document.getElementById('smart-classify-btn').addEventListener('click', async () => {
  showModal('<h2>正在分析书签...</h2><div id="classify-progress">准备中...</div>');
  try {
    const res = await sendMessage('smartClassify');
    if (res.error) {
      showModal('<h2>分类失败</h2><p>' + escapeHtml(res.error) + '</p><button id="modal-cancel" class="sp-btn-small">关闭</button>');
      modalContent.querySelector('#modal-cancel')?.addEventListener('click', hideModal);
      return;
    }
    if (res.suggestions) {
      renderClassifyPreview(res.suggestions);
    }
  } catch (e) {
    showModal('<h2>分类失败</h2><p>' + escapeHtml(e.message) + '</p><button id="modal-cancel" class="sp-btn-small">关闭</button>');
    modalContent.querySelector('#modal-cancel')?.addEventListener('click', hideModal);
  }
});

function renderClassifyPreview(suggestions) {
  const foldersHtml = suggestions.map(s => {
    let itemsHtml = '';
    for (const id of s.bookmarkIds) {
      const bm = findBookmarkById(id);
      if (bm) itemsHtml += '<li>' + escapeHtml(bm.title) + '</li>';
    }
    return '<details style="margin:4px 0;">' +
      '<summary>📁 ' + escapeHtml(s.folderName) + ' (' + s.bookmarkIds.length + ')</summary>' +
      '<ul style="font-size:11px;color:#6b7280;padding-left:16px;">' + itemsHtml + '</ul>' +
      '</details>';
  }).join('');

  const html =
    '<h2>智能分类建议</h2>' +
    '<div style="max-height:300px;overflow-y:auto;margin:8px 0;">' + foldersHtml + '</div>' +
    '<div style="display:flex;gap:8px;margin-top:12px;">' +
    '<button id="classify-exec" class="sp-btn-primary">确认执行</button>' +
    '<button id="classify-cancel" class="sp-btn-small">取消</button>' +
    '</div>';
  showModal(html);

  document.getElementById('classify-cancel').addEventListener('click', hideModal);
  document.getElementById('classify-exec').addEventListener('click', async () => {
    hideModal();
    showToast('正在执行分类...');

    const operations = [];
    const tree = await chrome.bookmarks.getTree();
    const otherBookmarks = tree[1]?.id || '';

    for (const s of suggestions) {
      const folder = await chrome.bookmarks.create({ parentId: otherBookmarks, title: s.folderName });
      if (s.bookmarkIds.length > 0) {
        operations.push({ type: 'move', bookmarkIds: s.bookmarkIds, parentId: folder.id });
      }
    }

    if (operations.length > 0) {
      await executePlan(operations);
    } else {
      showToast('无需执行任何操作');
    }
    loadBookmarks();
  });
}

// ============================================================
// 清理书签按钮
// ============================================================
document.getElementById('clean-btn').addEventListener('click', async () => {
  showModal('<h2>正在扫描书签...</h2><div id="clean-progress">检测失效链接中...</div>');
  try {
    const res = await sendMessage('cleanBookmarks');

    const deadCount = res.deadLinks?.length || 0;
    const dupCount = res.duplicates?.length || 0;

    if (deadCount === 0 && dupCount === 0) {
      showModal('<h2>清理结果</h2><p>未发现失效或重复书签 ✅</p><button id="modal-cancel" class="sp-btn-small">关闭</button>');
      modalContent.querySelector('#modal-cancel')?.addEventListener('click', hideModal);
      return;
    }

    renderCleanupPreview(res);
  } catch (e) {
    showModal('<h2>扫描失败</h2><p>' + escapeHtml(e.message) + '</p><button id="modal-cancel" class="sp-btn-small">关闭</button>');
    modalContent.querySelector('#modal-cancel')?.addEventListener('click', hideModal);
  }
});

function renderCleanupPreview(result) {
  const { deadLinks, duplicates, llmSuggestions } = result;

  let deadHtml = '';
  if (deadLinks.length > 0) {
    deadHtml = '<h3>❌ 失效链接 (' + deadLinks.length + ')</h3>';
    for (const d of deadLinks) {
      const suggestion = llmSuggestions?.deadSuggestions?.find(s => s.id === d.id);
      deadHtml +=
        '<div style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:12px;">' +
        '<input type="checkbox" class="clean-dead-cb" data-id="' + d.id + '" checked>' +
        '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escapeHtml(d.title) + '</span>' +
        '<span style="color:#9ca3af;">' + (d.status || '超时') + '</span>' +
        (suggestion ? '<span style="color:#3b82f6;font-size:11px;">建议: ' + escapeHtml(suggestion.suggestion) + '</span>' : '') +
        '</div>';
    }
  }

  let dupHtml = '';
  if (duplicates.length > 0) {
    dupHtml = '<h3>⚠ 重复书签 (' + duplicates.length + ' 组)</h3>';
    duplicates.forEach((group, gi) => {
      const keepId = llmSuggestions?.dupReview?.find(r => r.groupId === gi)?.keepId || group.recommended;
      dupHtml += '<p style="font-size:11px;color:#6b7280;margin-top:4px;">重复组 #' + (gi + 1) + ':</p>';
      for (const item of group.items) {
        const isKeep = item.id === keepId;
        dupHtml +=
          '<div style="display:flex;align-items:center;gap:8px;padding:2px 0;font-size:12px;">' +
          '<input type="checkbox" class="clean-dup-cb" data-id="' + item.id + '" ' + (isKeep ? '' : 'checked') + '>' +
          '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escapeHtml(item.title) + '</span>' +
          '<span style="color:#9ca3af;font-size:11px;">' + (isKeep ? '保留' : '建议删除') + '</span>' +
          '</div>';
      }
    });
  }

  const html =
    '<h2>清理预览</h2>' +
    '<div style="max-height:350px;overflow-y:auto;">' + deadHtml + dupHtml + '</div>' +
    '<div style="display:flex;gap:8px;margin-top:12px;">' +
    '<button id="clean-exec" class="sp-btn-primary">确认清理</button>' +
    '<button id="clean-cancel" class="sp-btn-small">取消</button>' +
    '</div>';
  showModal(html);

  document.getElementById('clean-cancel').addEventListener('click', hideModal);
  document.getElementById('clean-exec').addEventListener('click', async () => {
    const toDelete = [];
    modalContent.querySelectorAll('.clean-dead-cb:checked, .clean-dup-cb:checked').forEach(cb => toDelete.push(cb.dataset.id));
    if (toDelete.length === 0) { hideModal(); return; }
    if (!confirm('确认删除 ' + toDelete.length + ' 个书签？')) return;
    try {
      await sendMessage('deleteBookmarks', { ids: toDelete });
      hideModal();
      showToast('已清理 ' + toDelete.length + ' 个书签');
      loadBookmarks();
    } catch (e) {
      showToast('清理失败');
    }
  });
}

// ============================================================
// 撤销按钮
// ============================================================
document.getElementById('undo-btn').addEventListener('click', async () => {
  try {
    const data = await chrome.storage.local.get('snapshots');
    const snapshots = data.snapshots || [];
    if (snapshots.length === 0) {
      showToast('没有可撤销的操作');
      return;
    }

    const listHtml = snapshots.slice().reverse().map(s =>
      '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid #f3f4f6;">' +
      '<div>' +
      '<span style="font-size:12px;font-weight:500;">' + escapeHtml(s.operation) + '</span>' +
      '<span style="font-size:11px;color:#9ca3af;margin-left:8px;">' + new Date(s.timestamp).toLocaleString() + '</span>' +
      '</div>' +
      '<button class="sp-btn-small undo-restore-btn" data-sid="' + s.id + '">撤销</button>' +
      '</div>'
    ).join('');

    const html =
      '<h2>操作历史</h2>' +
      '<div style="max-height:300px;overflow-y:auto;">' + (listHtml || '<p>暂无记录</p>') + '</div>' +
      '<div style="display:flex;gap:8px;margin-top:12px;">' +
      '<button id="export-backup-btn" class="sp-btn-small">导出备份</button>' +
      '<button id="import-backup-btn" class="sp-btn-small">导入备份</button>' +
      '<button id="modal-cancel" class="sp-btn-small">关闭</button>' +
      '</div>';
    showModal(html);

    modalContent.querySelectorAll('.undo-restore-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const sid = btn.dataset.sid;
        const snap = snapshots.find(s => s.id === sid);
        if (!snap) return;
        if (!confirm('撤销操作 "' + snap.operation + '"？此操作将恢复书签到 ' + new Date(snap.timestamp).toLocaleString() + ' 的状态。')) return;
        try {
          await sendMessage('restoreSnapshot', { snapshotId: sid });
          hideModal();
          showToast('已撤销');
          loadBookmarks();
        } catch (e) {
          showToast('撤销失败');
        }
      });
    });

    modalContent.querySelector('#modal-cancel')?.addEventListener('click', hideModal);

    // 导出备份
    document.getElementById('export-backup-btn').addEventListener('click', async () => {
      const tree = await chrome.bookmarks.getTree();
      const storageData = await chrome.storage.local.get(['snapshots', 'bookmarkMeta']);
      const backup = { tree, snapshots: storageData.snapshots, bookmarkMeta: storageData.bookmarkMeta, exportedAt: Date.now() };
      const blob = new Blob([JSON.stringify(backup, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'bookmarks-backup-' + new Date().toISOString().slice(0, 10) + '.json';
      a.click();
      URL.revokeObjectURL(url);
      showToast('备份已下载');
    });

    // 导入备份
    document.getElementById('import-backup-btn').addEventListener('click', () => {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = '.json';
      input.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        try {
          const text = await file.text();
          const backup = JSON.parse(text);
          if (!backup.tree) throw new Error('无效的备份文件');
          await sendMessage('restoreFromBackup', { backup });
          hideModal();
          showToast('备份已恢复');
          loadBookmarks();
        } catch (err) {
          showToast('导入失败: ' + err.message);
        }
      });
      input.click();
    });
  } catch (e) {
    showToast('加载操作历史失败');
  }
});
