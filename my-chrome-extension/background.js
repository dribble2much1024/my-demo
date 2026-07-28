/**
 * 将 glob 通配符模式转为 RegExp
 * *  → .*
 * .  → \\.
 * 首尾包裹 ^...$
 */
function globToRegex(pattern) {
  const escaped = pattern
    .replace(/[.+^${}()|[\]\\]/g, '\\$&')
    .replace(/\*/g, '.*');
  return new RegExp('^' + escaped + '$');
}

/**
 * 按白名单过滤请求头，返回匹配的键值对
 * 匹配规则：大小写不敏感。至少命中一个白名单字段才返回非空结果
 * @param {chrome.webRequest.HttpHeader[]} requestHeaders
 * @param {string[]} fieldWhitelist
 * @returns {Record<string, string>}
 */
function filterHeaders(requestHeaders, fieldWhitelist) {
  if (!fieldWhitelist || fieldWhitelist.length === 0) return {};

  const lowerWhitelist = fieldWhitelist.map(f => f.toLowerCase());
  const result = {};
  for (const h of requestHeaders) {
    if (lowerWhitelist.includes(h.name.toLowerCase())) {
      result[h.name] = h.value;
    }
  }
  return result;
}

function uuid() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
  });
}

// ============================================================
// 快照管理
// ============================================================
async function createSnapshot(operation, affectedIds) {
  try {
    const tree = await chrome.bookmarks.getTree();
    const data = await chrome.storage.local.get('snapshots');
    let snapshots = data.snapshots || [];

    const snapshot = {
      id: 'snap_' + Date.now(),
      timestamp: Date.now(),
      operation,
      affectedIds,
      tree
    };

    snapshots.push(snapshot);
    if (snapshots.length > 20) snapshots = snapshots.slice(snapshots.length - 20);

    await chrome.storage.local.set({ snapshots });
  } catch (err) {
    console.error('createSnapshot failed:', err);
  }
}

/** 去重 key: URL + headers 的序列化值 */
function dedupKey(url, headers) {
  return url + '|' + JSON.stringify(headers);
}

/** 清理 dedupMap 中超过 5 秒的旧条目，防止 Map 无限增长 */
function pruneDedupMap(now) {
  for (const [key, timestamp] of dedupMap) {
    if (now - timestamp > 5000) {
      dedupMap.delete(key);
    }
  }
}

// 内存缓存 — Service Worker 生命周期内有效
let cachedSettings = {
  urlPatterns: [],
  headerFields: [],
  bufferSize: 50
};
const dedupMap = new Map(); // key → timestamp
let writeQueue = Promise.resolve(); // 串行化 storage 写入以防止竞态条件

/** 缓存的已编译正则，避免每次请求都重新编译 glob → RegExp */
let compiledPatterns = [];

/** 将 URL 匹配模式编译为正则，settings 变更时调用 */
function compilePatterns(patterns) {
  compiledPatterns = patterns.map(p => globToRegex(p));
}

async function loadSettings() {
  const data = await chrome.storage.local.get('settings');
  if (data.settings) {
    cachedSettings = { ...cachedSettings, ...data.settings };
  }
}

/**
 * 将捕获记录推入环形缓冲区
 * 去重：同一 URL + 相同 headers 5 秒内不重复记录
 * 满容：自动淘汰最旧记录
 */
async function pushCapture(capture) {
  const key = dedupKey(capture.url, capture.headers);
  const now = Date.now();

  pruneDedupMap(now);

  if (dedupMap.has(key) && (now - dedupMap.get(key)) < 5000) {
    return; // 5 秒内重复，跳过
  }
  dedupMap.set(key, now);

  // 串行化写入，避免并发请求导致的竞态条件
  writeQueue = writeQueue.then(async () => {
    const data = await chrome.storage.local.get('captures');
    let captures = data.captures || [];

    captures.push(capture);

    // 环形缓冲：只保留最近 bufferSize 条
    if (captures.length > cachedSettings.bufferSize) {
      captures = captures.slice(captures.length - cachedSettings.bufferSize);
    }

    await chrome.storage.local.set({ captures });
  }).catch(err => {
    console.error('pushCapture: storage write failed', err);
  });

  return writeQueue;
}

function onBeforeSendHeaders(details) {
  // 规则为空时不拦截
  if (!cachedSettings.urlPatterns || cachedSettings.urlPatterns.length === 0) return;

  // URL 匹配
  const matched = compiledPatterns.some(re => re.test(details.url));
  if (!matched) return;

  // 过滤请求头
  const headers = filterHeaders(details.requestHeaders, cachedSettings.headerFields);
  if (Object.keys(headers).length === 0) return;

  pushCapture({
    id: uuid(),
    url: details.url,
    method: details.method,
    headers,
    timestamp: Date.now()
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message.action) {
    case 'getCaptures':
      writeQueue.then(() => chrome.storage.local.get('captures')).then(data => {
        sendResponse({ captures: data.captures || [] });
      }).catch(() => {
        sendResponse({ captures: [] });
      });
      return true; // 保持通道开启以异步响应

    case 'clearCaptures':
      writeQueue = writeQueue.then(() => chrome.storage.local.set({ captures: [] })).then(() => {
        dedupMap.clear();
        sendResponse({ success: true });
      }).catch(err => {
        sendResponse({ success: false, error: err.message });
      });
      return true;

    case 'getSettings':
      sendResponse({ settings: cachedSettings });
      return false; // 同步响应

    case 'saveSettings':
      cachedSettings = { ...cachedSettings, ...message.settings };
      compilePatterns(cachedSettings.urlPatterns);
      chrome.storage.local.set({ settings: cachedSettings }).then(() => {
        sendResponse({ success: true });
      }).catch(err => {
        sendResponse({ success: false, error: err.message });
      });
      return true;

    case 'deleteBookmarks':
      (async () => {
        try {
          for (const id of message.ids) {
            await chrome.bookmarks.remove(id);
          }
          sendResponse({ success: true });
        } catch (err) {
          sendResponse({ success: false, error: err.message });
        }
      })();
      return true;

    case 'moveBookmarks':
      (async () => {
        try {
          for (const id of message.ids) {
            await chrome.bookmarks.move(id, { parentId: message.parentId });
          }
          sendResponse({ success: true });
        } catch (err) {
          sendResponse({ success: false, error: err.message });
        }
      })();
      return true;

    case 'renameBookmark':
      (async () => {
        try {
          await chrome.bookmarks.update(message.id, { title: message.title });
          sendResponse({ success: true });
        } catch (err) {
          sendResponse({ success: false, error: err.message });
        }
      })();
      return true;

    case 'llmChat':
      (async () => {
        try {
          const data = await chrome.storage.local.get('llmConfig');
          const config = data.llmConfig;
          if (!config || !config.apiKey || !config.endpoint) {
            sendResponse({ error: '请先在 Popup 中配置 LLM API' });
            return;
          }

          const tree = await chrome.bookmarks.getTree();
          const bookmarks = [];
          function collect(nodes, parentTitle) {
            for (const n of nodes) {
              if (n.url) bookmarks.push({ id: n.id, title: n.title, url: n.url, parentTitle });
              if (n.children) collect(n.children, n.title);
            }
          }
          collect(tree, '');

          const systemPrompt = `你是一个书签管理助手。根据用户指令，分析书签列表并输出 JSON 操作计划。
可用操作:
- createFolder(parentId, title): 创建文件夹。parentId 为空则在根目录创建
- move(bookmarkIds[], parentId): 移动书签到指定文件夹
- rename(bookmarkId, newTitle): 重命名书签
- delete(bookmarkIds[]): 删除书签

输出格式:
{
  "explanation": "一句话解释你的操作逻辑",
  "operations": [
    {"type": "createFolder", "parentId": "", "title": "开发工具"},
    {"type": "move", "bookmarkIds": ["id1","id2"], "parentId": "TARGET_FOLDER_ID"},
    ...
  ]
}

注意:
- parentId 必须使用书签列表中已有的 ID
- bookmarkIds 必须是书签列表中存在的 ID
- 只输出 JSON，不要输出其他内容`;

          const userMsg = `书签列表:\n${JSON.stringify(bookmarks)}\n\n用户指令: ${message.userMessage}`;

          const response = await fetch(config.endpoint, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${config.apiKey}`
            },
            body: JSON.stringify({
              model: config.model,
              messages: [
                { role: 'system', content: systemPrompt },
                { role: 'user', content: userMsg }
              ],
              temperature: 0.3
            })
          });

          if (!response.ok) {
            const errText = await response.text();
            sendResponse({ error: `LLM API 错误 (${response.status}): ${errText.slice(0, 200)}` });
            return;
          }

          const json = await response.json();
          const content = json.choices?.[0]?.message?.content || '';
          const jsonMatch = content.match(/\{[\s\S]*\}/);
          if (!jsonMatch) {
            sendResponse({ error: 'LLM 未返回有效的 JSON 操作计划', raw: content });
            return;
          }

          const plan = JSON.parse(jsonMatch[0]);
          sendResponse({ plan });
        } catch (err) {
          sendResponse({ error: err.message });
        }
      })();
      return true;

    case 'executePlan':
      (async () => {
        try {
          await createSnapshot('LLM操作执行', []);
          const plan = message.plan;
          let executed = 0;
          for (const op of plan.operations) {
            await new Promise(r => setTimeout(r, 50));
            try {
              switch (op.type) {
                case 'createFolder': {
                  const parentId = op.parentId || undefined;
                  const created = await chrome.bookmarks.create({ parentId, title: op.title });
                  op._createdId = created.id;
                  break;
                }
                case 'move':
                  for (const id of op.bookmarkIds) {
                    await chrome.bookmarks.move(id, { parentId: op.parentId });
                  }
                  break;
                case 'rename':
                  await chrome.bookmarks.update(op.bookmarkId, { title: op.newTitle });
                  break;
                case 'delete':
                  for (const id of op.bookmarkIds) {
                    await chrome.bookmarks.remove(id);
                  }
                  break;
              }
              executed++;
            } catch (opErr) {
              console.warn('Operation failed, continuing:', op, opErr);
            }
          }
          sendResponse({ success: true, executed, total: plan.operations.length });
        } catch (err) {
          sendResponse({ success: false, error: err.message });
        }
      })();
      return true;

    case 'smartClassify':
      (async () => {
        try {
          const data = await chrome.storage.local.get('llmConfig');
          const config = data.llmConfig;
          if (!config || !config.apiKey) {
            sendResponse({ error: '请先配置 LLM API' });
            return;
          }

          const tree = await chrome.bookmarks.getTree();
          const bookmarks = [];
          function collect(nodes) {
            for (const n of nodes) {
              if (n.url) bookmarks.push({ id: n.id, title: n.title, url: n.url });
              if (n.children) collect(n.children);
            }
          }
          collect(tree);

          if (bookmarks.length === 0) {
            sendResponse({ suggestions: [], uncategorized: [] });
            return;
          }

          const batchSize = 50;
          const batches = [];
          for (let i = 0; i < bookmarks.length; i += batchSize) {
            batches.push(bookmarks.slice(i, i + batchSize));
          }

          const allSuggestions = [];
          for (let bi = 0; bi < batches.length; bi++) {
            const batch = batches[bi];

            const systemPrompt = `分析这批书签，将它们按主题分类。输出 JSON:
{
  "suggestions": [
    {"folderName": "分类名", "bookmarkIds": ["id1", "id2"]}
  ],
  "uncategorized": ["id3"]
}
folderName 使用中文，覆盖主要技术/工具/阅读/社交/购物/视频等常见分类。
只输出 JSON，不要输出其他内容。`;

            const response = await fetch(config.endpoint, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${config.apiKey}`
              },
              body: JSON.stringify({
                model: config.model,
                messages: [
                  { role: 'system', content: systemPrompt },
                  { role: 'user', content: JSON.stringify(batch) }
                ],
                temperature: 0.3
              })
            });

            if (!response.ok) throw new Error(`API error: ${response.status}`);

            const json = await response.json();
            const content = json.choices?.[0]?.message?.content || '';
            const jsonMatch = content.match(/\{[\s\S]*\}/);
            if (jsonMatch) {
              const result = JSON.parse(jsonMatch[0]);
              if (result.suggestions) allSuggestions.push(...result.suggestions);
            }
          }

          const merged = {};
          for (const s of allSuggestions) {
            if (!merged[s.folderName]) merged[s.folderName] = new Set();
            for (const id of s.bookmarkIds) merged[s.folderName].add(id);
          }
          const suggestions = Object.entries(merged).map(([folderName, ids]) => ({
            folderName, bookmarkIds: [...ids]
          }));

          sendResponse({ suggestions, uncategorized: [] });
        } catch (err) {
          sendResponse({ error: err.message });
        }
      })();
      return true;

    case 'cleanBookmarks':
      (async () => {
        try {
          const tree = await chrome.bookmarks.getTree();
          const allBookmarks = [];
          function collect(nodes) {
            for (const n of nodes) {
              if (n.url) allBookmarks.push(n);
              if (n.children) collect(n.children);
            }
          }
          collect(tree);

          const deadLinks = [];
          const duplicates = [];

          const concurrency = 8;
          for (let i = 0; i < allBookmarks.length; i += concurrency) {
            const batch = allBookmarks.slice(i, i + concurrency);
            const results = await Promise.allSettled(
              batch.map(bm =>
                fetch(bm.url, { method: 'HEAD', signal: AbortSignal.timeout(5000) })
                  .then(r => ({ id: bm.id, url: bm.url, title: bm.title, status: r.status, ok: r.ok }))
                  .catch(() => ({ id: bm.id, url: bm.url, title: bm.title, status: 0, ok: false, error: true }))
              )
            );
            for (const r of results) {
              if (r.status === 'fulfilled' && r.value && !r.value.ok) {
                deadLinks.push(r.value);
              }
            }
          }

          function normalizeUrl(url) {
            try {
              const u = new URL(url);
              u.hash = '';
              let path = u.pathname.replace(/\/$/, '');
              u.pathname = path;
              let host = u.hostname.replace(/^www\./, '');
              u.hostname = host;
              return u.toString();
            } catch (_) { return url; }
          }

          const urlMap = {};
          for (const bm of allBookmarks) {
            const norm = normalizeUrl(bm.url);
            if (!urlMap[norm]) urlMap[norm] = [];
            urlMap[norm].push(bm);
          }

          for (const [norm, group] of Object.entries(urlMap)) {
            if (group.length > 1) {
              duplicates.push({
                type: 'exact',
                items: group.map(b => ({ id: b.id, title: b.title, url: b.url })),
                recommended: group[0].id
              });
            }
          }

          let llmSuggestions = null;
          const settingsData = await chrome.storage.local.get('llmConfig');
          if (settingsData.llmConfig?.apiKey) {
            const deadForLlm = deadLinks.slice(0, 20);
            const dupForLlm = duplicates.slice(0, 10);

            if (deadForLlm.length > 0 || dupForLlm.length > 0) {
              const prompt = `分析以下书签清理候选:

失效书签: ${JSON.stringify(deadForLlm)}
重复书签组: ${JSON.stringify(dupForLlm)}

对于失效书签，尝试根据 URL 模式推测可能的替代链接。对于重复书签，判断是否语义重复并推荐保留哪个。

输出 JSON:
{
  "deadSuggestions": [{"id": "xxx", "suggestion": "可能的替代域名...", "confidence": "low|medium|high"}],
  "dupReview": [{"groupId": 0, "keepId": "xxx", "reason": "理由"}]
}
只输出 JSON。`;

              try {
                const llmConfig = settingsData.llmConfig;
                const resp = await fetch(llmConfig.endpoint, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${llmConfig.apiKey}` },
                  body: JSON.stringify({
                    model: llmConfig.model,
                    messages: [
                      { role: 'system', content: '你是一个书签清理分析工具。输出 JSON。' },
                      { role: 'user', content: prompt }
                    ],
                    temperature: 0.2
                  })
                });
                if (resp.ok) {
                  const j = await resp.json();
                  const c = j.choices?.[0]?.message?.content || '';
                  const m = c.match(/\{[\s\S]*\}/);
                  if (m) llmSuggestions = JSON.parse(m[0]);
                }
              } catch (_) { /* LLM 语义分析失败不影响主流程 */ }
            }
          }

          sendResponse({ deadLinks, duplicates, llmSuggestions });
        } catch (err) {
          sendResponse({ error: err.message });
        }
      })();
      return true;

    case 'restoreSnapshot':
      (async () => {
        try {
          const data = await chrome.storage.local.get('snapshots');
          const snapshots = data.snapshots || [];
          const snap = snapshots.find(s => s.id === message.snapshotId);
          if (!snap) {
            sendResponse({ success: false, error: '快照不存在' });
            return;
          }

          // 撤销前先创建当前状态快照，以便可重做
          await createSnapshot('撤销前状态', []);

          const currentTree = await chrome.bookmarks.getTree();
          async function removeAll(nodes) {
            for (const n of nodes) {
              if (n.children) {
                for (const child of n.children) {
                  await chrome.bookmarks.removeTree(child.id);
                }
              }
            }
          }
          await removeAll(currentTree);

          async function restoreNodes(parentId, nodes) {
            for (const n of nodes) {
              if (n.url) {
                await chrome.bookmarks.create({ parentId, title: n.title, url: n.url });
              } else if (n.children) {
                const folder = await chrome.bookmarks.create({ parentId, title: n.title });
                await restoreNodes(folder.id, n.children);
              }
            }
          }
          for (const root of snap.tree) {
            await restoreNodes(root.parentId || root.id, root.children || []);
          }

          const idx = snapshots.indexOf(snap);
          const validSnapshots = snapshots.slice(0, idx + 1);
          validSnapshots[validSnapshots.length - 1].restored = true;
          await chrome.storage.local.set({ snapshots: validSnapshots });

          sendResponse({ success: true });
        } catch (err) {
          sendResponse({ success: false, error: err.message });
        }
      })();
      return true;

    case 'restoreFromBackup':
      (async () => {
        try {
          await createSnapshot('导入备份前', []);

          const currentTree = await chrome.bookmarks.getTree();
          async function removeAll(nodes) {
            for (const n of nodes) {
              if (n.children) {
                for (const child of n.children) {
                  await chrome.bookmarks.removeTree(child.id);
                }
              }
            }
          }
          await removeAll(currentTree);

          async function restoreNodes(parentId, nodes) {
            for (const n of nodes) {
              if (n.url) {
                await chrome.bookmarks.create({ parentId, title: n.title, url: n.url });
              } else if (n.children && n.children.length > 0) {
                const folder = await chrome.bookmarks.create({ parentId, title: n.title });
                await restoreNodes(folder.id, n.children);
              }
            }
          }

          for (const root of message.backup.tree) {
            if (root.children) {
              await restoreNodes(root.parentId, root.children);
            }
          }

          if (message.backup.bookmarkMeta) {
            await chrome.storage.local.set({ bookmarkMeta: message.backup.bookmarkMeta });
          }

          sendResponse({ success: true });
        } catch (err) {
          sendResponse({ success: false, error: err.message });
        }
      })();
      return true;

    case 'saveBookmarkMeta':
      (async () => {
        try {
          const data = await chrome.storage.local.get('bookmarkMeta');
          const meta = data.bookmarkMeta || {};
          meta[message.id] = { tags: message.tags || [], note: message.note || '' };
          await chrome.storage.local.set({ bookmarkMeta: meta });
          sendResponse({ success: true });
        } catch (err) {
          sendResponse({ success: false, error: err.message });
        }
      })();
      return true;

    case 'getBookmarkMeta':
      (async () => {
        const data = await chrome.storage.local.get('bookmarkMeta');
        const meta = (data.bookmarkMeta || {})[message.id] || { tags: [], note: '' };
        sendResponse({ meta });
      })();
      return true;
  }
});

// ============================================================
// 键盘快捷键 (M11)
// ============================================================
chrome.commands.onCommand.addListener(async (command) => {
  if (command === 'open-bookmark-sidepanel') {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    await chrome.sidePanel.open({ windowId: tab.windowId });
  } else if (command === 'focus-search') {
    chrome.runtime.sendMessage({ action: 'focusSearch' }).catch(() => {});
  }
});

loadSettings().then(() => {
  compilePatterns(cachedSettings.urlPatterns);
  chrome.webRequest.onBeforeSendHeaders.addListener(
    onBeforeSendHeaders,
    { urls: ['<all_urls>'] },
    ['requestHeaders', 'extraHeaders']
  );
});
