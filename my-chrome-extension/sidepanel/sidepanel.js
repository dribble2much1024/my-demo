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
