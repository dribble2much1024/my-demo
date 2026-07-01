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
