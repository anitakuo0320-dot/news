// 全球財經政治日報：前端
// 讀取 data/ 裡的 JSON，畫出今日重點、篩選列與新聞列表。
// 已讀、收藏、深淺色都只存在這台裝置的瀏覽器裡。

const REGIONS = { us: '美國', europe: '歐洲', china: '中國', japan: '日本', asia: '亞太', mideast: '中東', latam: '拉美', global: '全球' };
const TOPICS = { macro: '總經央行', markets: '市場', tech: '科技 AI', energy: '能源', geopolitics: '地緣政治', policy: '政策監管' };

const state = {
  days: [],
  day: null,          // 當天的資料
  regions: new Set(), // 空的代表全部
  topics: new Set(),
  query: '',
  view: 'all',        // all | unread | saved
  sort: 'score',
  open: new Set(),
};

// ---------- 瀏覽器儲存（失敗也不影響使用） ----------
const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (e) { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) {}
  },
};
let readMap = store.get('nd-read', {});     // { id: 時間戳 }
let savedMap = store.get('nd-saved', {});   // { id: 新聞內容 }

function pruneRead() {
  const limit = Date.now() - 40 * 86400000;
  for (const id in readMap) if (readMap[id] < limit) delete readMap[id];
  store.set('nd-read', readMap);
}

// ---------- 小工具 ----------
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u) ? u : '#');

function timeLabel(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const diff = (Date.now() - d) / 3600000;
  if (diff < 1) return `${Math.max(1, Math.round(diff * 60))} 分鐘前`;
  if (diff < 24) return `${Math.round(diff)} 小時前`;
  return d.toLocaleString('zh-TW', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Taipei' });
}

const titleOf = (it) => it.title_zh || it.title;
const hasOrig = (it) => it.title_zh && it.title_zh !== it.title;

// ---------- 載入資料 ----------
async function loadJSON(path) {
  const res = await fetch(path, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`${path} ${res.status}`);
  return res.json();
}

async function init() {
  pruneRead();
  try {
    state.days = (await loadJSON('data/index.json')).days || [];
  } catch (e) {
    $('meta').textContent = '還沒有資料，等第一次自動抓取完成後再來看看。';
    return;
  }
  $('daySelect').innerHTML = state.days
    .slice(0, 7)
    .map((d, i) => `<option value="${esc(d)}">${i === 0 ? '今天 ' : ''}${esc(d.slice(5).replace('-', '/'))}</option>`)
    .join('');
  const fromHash = location.hash.slice(1);
  await loadDay(state.days.includes(fromHash) ? fromHash : state.days[0]);
}

async function loadDay(date) {
  if (!date) return;
  $('meta').textContent = '載入中…';
  try {
    state.day = await loadJSON(`data/${date}.json`);
  } catch (e) {
    $('meta').textContent = `${date} 的資料讀取失敗`;
    return;
  }
  state.open.clear();
  $('daySelect').value = date;
  history.replaceState(null, '', date === state.days[0] ? location.pathname : `#${date}`);
  const idx = state.days.indexOf(date);
  $('prevDay').disabled = idx >= Math.min(6, state.days.length - 1);
  $('nextDay').disabled = idx <= 0;
  renderMeta();
  renderTop();
  renderChips();
  renderList();
  renderSources();
  window.scrollTo({ top: 0 });
}

// ---------- 畫面 ----------
function renderMeta() {
  const d = state.day;
  const [y, m, dd] = d.date.split('-');
  const week = '日一二三四五六'[new Date(`${d.date}T12:00:00+08:00`).getDay()];
  const mode = d.ai ? 'AI 摘要' : '機器翻譯';
  $('meta').textContent = `${y} 年 ${+m} 月 ${+dd} 日 星期${week} · ${d.items.length} 則 · ${mode} · ${d.generated_at.slice(11, 16)} 更新`;
}

function tagsHTML(it) {
  return it.regions.map((r) => `<span class="tag">${esc(REGIONS[r] || r)}</span>`).join('');
}

function renderTop() {
  const byId = Object.fromEntries(state.day.items.map((it) => [it.id, it]));
  const top = (state.day.top || []).map((id) => byId[id]).filter(Boolean);
  $('topSection').hidden = top.length === 0;
  $('topList').innerHTML = top
    .map((it) => `
      <li data-id="${esc(it.id)}">
        <div class="t">${esc(titleOf(it))}</div>
        <div class="w">${esc(it.why || it.summary_zh || it.summary || '')}</div>
      </li>`)
    .join('');
}

function renderChips() {
  const items = state.day.items;
  const count = (key, val) => items.filter((it) => it[key].includes(val)).length;
  const chip = (group, key, label, n) =>
    `<button class="chip${state[group].has(key) ? ' on' : ''}" data-group="${group}" data-key="${key}">${esc(label)}<span class="n">${n}</span></button>`;
  const allChip = (group, label) => `<button class="chip${state[group].size === 0 ? ' on' : ''}" data-group="${group}" data-key="">${label}</button>`;
  $('regionChips').innerHTML = allChip('regions', '全部地區') +
    Object.entries(REGIONS).map(([k, v]) => [k, v, count('regions', k)]).filter((x) => x[2]).map(([k, v, n]) => chip('regions', k, v, n)).join('');
  $('topicChips').innerHTML = allChip('topics', '全部主題') +
    Object.entries(TOPICS).map(([k, v]) => [k, v, count('topics', k)]).filter((x) => x[2]).map(([k, v, n]) => chip('topics', k, v, n)).join('');
}

function filtered() {
  const q = state.query.trim().toLowerCase();
  let items = state.view === 'saved' ? Object.values(savedMap) : state.day.items;
  items = items.filter((it) => {
    if (state.regions.size && !it.regions.some((r) => state.regions.has(r))) return false;
    if (state.topics.size && !it.topics.some((t) => state.topics.has(t))) return false;
    if (state.view === 'unread' && readMap[it.id]) return false;
    if (q) {
      const hay = [it.title, it.title_zh, it.summary, it.summary_zh, it.why, ...it.sources.map((s) => s.name)].join(' ').toLowerCase();
      if (!q.split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    return true;
  });
  const byTime = (a, b) => (b.time || '').localeCompare(a.time || '');
  items.sort(state.sort === 'time' || state.view === 'saved' ? byTime : (a, b) => b.score - a.score);
  return items;
}

function cardHTML(it) {
  const open = state.open.has(it.id);
  const src = it.sources.length > 1
    ? `<span class="multi">${it.sources.length} 家報導</span>`
    : `<span>${esc(it.sources[0].name)}</span>`;
  const summary = it.summary_zh || it.summary;
  return `
    <li class="card${readMap[it.id] ? ' read' : ''}${savedMap[it.id] ? ' saved' : ''}" data-id="${esc(it.id)}">
      <button class="card-head" aria-expanded="${open}">
        <div class="card-meta">${tagsHTML(it)}${src}<span>·</span><span>${esc(timeLabel(it.time))}</span></div>
        <div class="card-title">${esc(titleOf(it))}</div>
        ${hasOrig(it) ? `<div class="card-orig">${esc(it.title)}</div>` : ''}
      </button>
      <div class="card-body"${open ? '' : ' hidden'}>
        ${summary ? `<p class="summary">${esc(summary)}</p>` : ''}
        ${it.why ? `<p class="why"><b>為什麼重要</b>${esc(it.why)}</p>` : ''}
        ${it.summary_zh && it.summary && it.summary_zh !== it.summary ? `<p class="orig-summary">${esc(it.summary)}</p>` : ''}
        <ul class="links">${it.sources.map((s) => `<li><a href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener">${esc(s.name)} ↗</a></li>`).join('')}</ul>
        <div class="actions">
          <button data-act="save" class="${savedMap[it.id] ? 'on' : ''}">${savedMap[it.id] ? '★ 已收藏' : '☆ 收藏'}</button>
          <button data-act="unread">${readMap[it.id] ? '標為未讀' : '標為已讀'}</button>
        </div>
      </div>
    </li>`;
}

function renderList() {
  const items = filtered();
  const total = state.view === 'saved' ? Object.keys(savedMap).length : state.day.items.length;
  const unread = state.day.items.filter((it) => !readMap[it.id]).length;
  $('count').textContent = state.view === 'saved'
    ? `收藏 ${items.length} 則`
    : `顯示 ${items.length} / ${total} 則 · 未讀 ${unread}`;
  $('list').innerHTML = items.map(cardHTML).join('');
  $('empty').hidden = items.length > 0;
}

function renderSources() {
  const list = state.day.sources || [];
  const bad = list.filter((s) => !s.ok);
  $('sourceSummary').textContent = `來源狀態：${list.length - bad.length}/${list.length} 成功${bad.length ? `，${bad.length} 個今天抓不到` : ''}`;
  $('sourceList').innerHTML = list
    .map((s) => `<li class="${s.ok ? '' : 'bad'}">${esc(s.name)}：${s.ok ? `${s.count} 則` : `失敗（${esc(s.error)}）`}</li>`)
    .join('');
}

function findItem(id) {
  return state.day.items.find((it) => it.id === id) || savedMap[id];
}

function rerenderCard(id) {
  const old = document.querySelector(`.card[data-id="${CSS.escape(id)}"]`);
  const it = findItem(id);
  if (old && it) old.outerHTML = cardHTML(it);
}

// ---------- 互動 ----------
$('list').addEventListener('click', (e) => {
  const card = e.target.closest('.card');
  if (!card) return;
  const id = card.dataset.id;
  const act = e.target.closest('[data-act]')?.dataset.act;
  if (act === 'save') {
    if (savedMap[id]) delete savedMap[id];
    else savedMap[id] = findItem(id);
    store.set('nd-saved', savedMap);
    return state.view === 'saved' ? renderList() : rerenderCard(id);
  }
  if (act === 'unread') {
    if (readMap[id]) delete readMap[id];
    else readMap[id] = Date.now();
    store.set('nd-read', readMap);
    return rerenderCard(id);
  }
  if (e.target.closest('.card-head')) {
    if (state.open.has(id)) state.open.delete(id);
    else {
      state.open.add(id);
      readMap[id] = Date.now();   // 點開就算讀過
      store.set('nd-read', readMap);
    }
    rerenderCard(id);
  }
});

$('topList').addEventListener('click', (e) => {
  const li = e.target.closest('li');
  if (!li) return;
  const id = li.dataset.id;
  state.regions.clear(); state.topics.clear(); state.query = ''; $('search').value = '';
  setSeg('view', 'all');
  state.open.add(id);
  readMap[id] = Date.now();
  store.set('nd-read', readMap);
  renderChips();
  renderList();
  document.querySelector(`.card[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
});

function onChip(e) {
  const btn = e.target.closest('.chip');
  if (!btn) return;
  const set = state[btn.dataset.group];
  const key = btn.dataset.key;
  if (!key) set.clear();
  else if (set.has(key)) set.delete(key);
  else set.add(key);
  renderChips();
  renderList();
}
$('regionChips').addEventListener('click', onChip);
$('topicChips').addEventListener('click', onChip);

let searchTimer;
$('search').addEventListener('input', (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.query = e.target.value; renderList(); }, 150);
});

function setSeg(name, value) {
  state[name] = value;
  document.querySelectorAll(`[data-${name}]`).forEach((b) => b.classList.toggle('on', b.dataset[name] === value));
}
document.querySelectorAll('[data-view]').forEach((b) => b.addEventListener('click', () => { setSeg('view', b.dataset.view); renderList(); }));
document.querySelectorAll('[data-sort]').forEach((b) => b.addEventListener('click', () => { setSeg('sort', b.dataset.sort); renderList(); }));

$('daySelect').addEventListener('change', (e) => loadDay(e.target.value));
$('prevDay').addEventListener('click', () => loadDay(state.days[state.days.indexOf(state.day.date) + 1]));
$('nextDay').addEventListener('click', () => loadDay(state.days[state.days.indexOf(state.day.date) - 1]));

$('themeBtn').addEventListener('click', () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  root.dataset.theme = dark ? 'light' : 'dark';
  try { localStorage.setItem('nd-theme', root.dataset.theme); } catch (e) {}
});

$('markAllRead').addEventListener('click', () => {
  filtered().forEach((it) => { readMap[it.id] = readMap[it.id] || Date.now(); });
  store.set('nd-read', readMap);
  renderList();
});

init();
