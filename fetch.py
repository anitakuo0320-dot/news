"""
每日新聞抓取腳本
=================
流程：抓 RSS → 過濾舊聞 → 合併重複報導 → 分類 → 打分數 → 翻譯與摘要 → 存成 JSON

執行方式：
    pip install feedparser
    python fetch.py

AI 摘要（選用）：
    在 GitHub Actions 裡，程式會用內建的 GITHUB_TOKEN 呼叫 GitHub Models（免費額度），
    不需要另外申請 API key。AI 失敗時會自動退回「機器翻譯 + 原文摘要」，頁面照常產生。
"""

import concurrent.futures
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser

# ---------- 基本設定 ----------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "docs" / "data"   # 網頁放在 docs/，GitHub Pages 從這裡發布
TAIPEI = ZoneInfo("Asia/Taipei")
MAX_AGE_HOURS = 36          # 超過這個時間的新聞不收
KEEP_DAYS = 30              # data/ 資料夾最多保留幾天
USER_AGENT = "Mozilla/5.0 (compatible; news-desk/1.0; +https://github.com/)"

AI_MODEL = os.environ.get("NEWS_AI_MODEL", "openai/gpt-4o-mini")
# GitHub Models 有新舊兩個網址，依序嘗試
AI_URLS = ["https://models.github.ai/inference/chat/completions",
           "https://models.inference.ai.azure.com/chat/completions"]
AI_BATCH = 15               # 每次丟給 AI 幾則
AI_MAX_ITEMS = 200          # 每天最多讓 AI 處理幾則（免費額度有上限）
MAX_ITEMS = 200             # 每天最多保留幾則（依重要性排序），10 分鐘看得完的量

# ---------- 分類用的關鍵字 ----------
# 地區：標題或摘要出現這些字，就加上這個地區標籤（不分大小寫）
REGION_KEYWORDS = {
    "us": ["u.s.", "US", "america", "washington", "trump", "biden", "Fed", "federal reserve", "wall street",
           "congress", "senate", "white house", "midterm", "democrats", "republicans", "gop", "nasdaq", "s&p", "dow", "treasury", "美國", "美股", "聯準會", "川普", "華府"],
    "europe": ["europe", "EU", "e.u.", "eurozone", "ecb", "brussels", "germany", "german", "france", "french",
               "UK", "britain", "british", "london", "italy", "italian", "spain", "spanish", "poland", "polish", "netherlands", "dutch", "swiss", "sweden", "norway",
               "brexit", "macron", "merz", "starmer", "russia", "russian", "moscow", "kremlin", "putin", "ukraine", "nato", "歐洲", "歐盟", "德國", "法國", "英國", "烏克蘭"],
    "china": ["china", "chinese", "beijing", "xi jinping", "yuan", "hong kong", "shanghai", "shenzhen", "pboc",
              "中國", "大陸", "北京", "習近平", "人民幣", "香港", "陸股"],
    "japan": ["japan", "japanese", "tokyo", "boj", "bank of japan", "yen", "nikkei", "takaichi", "日本", "日圓", "日銀", "東京", "日経"],
    "asia": ["taiwan", "taipei", "tsmc", "korea", "seoul", "pyongyang", "india", "modi", "singapore", "indonesia", "vietnam", "asean",
             "australia", "philippines", "malaysia", "thailand", "台灣", "台股", "台積電", "韓國", "印度", "新加坡", "東南亞", "賴清德"],
    "mideast": ["middle east", "israel", "gaza", "iran", "saudi", "uae", "dubai", "qatar", "opec", "lebanon",
                "syria", "yemen", "egypt", "turkey", "中東", "以色列", "伊朗", "沙烏地", "加薩"],
    "latam": ["latin america", "brazil", "mexico", "argentina", "chile", "colombia", "peru", "venezuela",
              "milei", "lula", "sheinbaum", "巴西", "墨西哥", "阿根廷", "拉美", "委內瑞拉"],
}

# 主題：至少命中一個主題才會收錄（擋掉體育、娛樂等雜訊）
TOPIC_KEYWORDS = {
    "macro": ["inflation", "interest rate", "rate cut", "rate hike", "central bank", "Fed", "ecb", "boj", "gdp",
              "recession", "jobs report", "unemployment", "economy", "economic", "cpi", "bond", "yield", "monetary",
              "fiscal", "debt", "deficit", "budget", "通膨", "利率", "降息", "升息", "央行", "經濟", "gdp", "公債", "殖利率", "景氣", "財政"],
    "markets": ["stock", "shares", "market", "investor", "nasdaq", "s&p", "dow", "index", "ipo", "earnings", "profit",
                "revenue", "dollar", "currency", "gold", "bitcoin", "crypto", "fund", "venture", "private equity",
                "merger", "acquisition", "deal", "valuation", "bank", "股", "指數", "財報", "營收", "獲利", "匯率", "美元",
                "黃金", "併購", "創投", "基金", "比特幣", "加權", "上市"],
    "tech": ["AI", "a.i.", "artificial intelligence", "chip", "semiconductor", "nvidia", "tsmc", "data center",
             "datacenter", "openai", "cloud", "gpu", "tech", "software", "fintech", "robot", "quantum",
             "人工智慧", "晶片", "半導體", "輝達", "台積電", "資料中心", "伺服器", "科技", "金融科技"],
    "energy": ["oil", "gas", "lng", "opec", "energy", "power grid", "electricity", "renewable", "solar", "wind power",
               "nuclear", "battery", "climate", "carbon", "crude", "石油", "原油", "天然氣", "能源", "電力", "再生能源",
               "太陽能", "風電", "核電", "電池", "碳"],
    "geopolitics": ["war", "military", "missile", "sanction", "tariff", "trade war", "election", "president",
                    "prime minister", "minister", "government", "parliament", "congress", "senate", "summit",
                    "diplomat", "ceasefire", "attack", "nato", "coup", "protest", "vote", "midterm", "democrat",
                    "republican", "戰爭", "軍", "飛彈", "制裁", "關稅", "選舉", "總統", "總理", "首相", "政府", "國會",
                    "峰會", "外交", "停火", "抗議", "立法院", "政黨"],
    "policy": ["regulation", "regulator", "law", "bill", "antitrust", "SEC", "policy", "court", "ruling", "ban",
               "subsidy", "tax", "legislation", "compliance", "監管", "法案", "法規", "政策", "法院", "禁令", "補貼",
               "稅", "金管會", "反壟斷"],
}

# 這些字出現時直接排除（體育、娛樂、生活）
EXCLUDE_KEYWORDS = ["football", "soccer", "cricket", "tennis", "nba", "nfl", "premier league", "world cup",
                    "olympic", "recipe", "celebrity", "movie review", "horoscope", "球賽", "職棒", "星座",
                    # 央行例行統計公告，資訊量低
                    "held by the bank of japan", "collateral accepted", "time-series data", "statistical release",
                    "outstanding amount", "monthly report on", "minutes of the monetary policy meeting of"]

# 主題的重要性權重，用來排「今日重點」
TOPIC_WEIGHT = {"macro": 3, "geopolitics": 3, "markets": 2, "energy": 2, "tech": 2, "policy": 1}

STOPWORDS = set("""a an the of to in on for and or with at by from as is are was were be been it its this that
after before over into amid says said say new will could would may might than more most about up down out not no
how why what who when where which his her their they he she we you your our us vs""".split())


# ---------- 小工具 ----------
def log(*args):
    print(*args, file=sys.stderr, flush=True)


def clean_text(raw):
    """去掉 HTML 標籤、多餘空白"""
    text = html.unescape(raw or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def first_sentences(text, max_chars=280):
    """取前幾句當作摘要，避免轉載全文"""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    for mark in [". ", "。", "! ", "? "]:
        pos = cut.rfind(mark)
        if pos > max_chars * 0.5:
            return cut[: pos + 1].strip()
    return cut.rstrip() + "…"


def has_cjk(text):
    return bool(re.search(r"[一-鿿]", text or ""))


def has_kana(text):
    return bool(re.search(r"[぀-ヿ]", text or ""))


def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ---------- 第 1 步：抓取 ----------
def fetch_source(src):
    """抓一個來源，回傳 (新聞列表, 狀態)。任何錯誤都只影響這個來源。"""
    status = {"name": src["name"], "region": src["region"], "ok": False, "count": 0, "error": ""}
    try:
        raw = http_get(src["url"])
        items = parse_cnyes(raw, src) if src.get("type") == "cnyes" else parse_rss(raw, src)
        items = items[: src.get("limit", 20)]
        status["ok"] = len(items) > 0
        status["count"] = len(items)
        if not items:
            status["error"] = "沒有新內容"
        return items, status
    except Exception as exc:  # 網路錯誤、被擋、格式壞掉都在這裡接住
        status["error"] = str(exc)[:120]
        return [], status


def parse_rss(raw, src):
    feed = feedparser.parse(raw.lstrip())   # 有些網站在 XML 前面多了空白行，會讓解析失敗
    if feed.bozo and not feed.entries:
        raise ValueError(f"RSS 格式錯誤：{feed.bozo_exception}")
    items = []
    for entry in feed.entries:
        title = clean_text(entry.get("title", ""))
        link = entry.get("link", "")
        if not title or not link:
            continue
        # Google News 的標題結尾會加「 - 媒體名」，去掉
        if "news.google.com" in src["url"]:
            title = re.sub(r"\s+-\s+[^-]{2,40}$", "", title)
        summary = clean_text(entry.get("summary", ""))
        if "news.google.com" in src["url"] or summary.lower().startswith(title.lower()[:30]):
            summary = ""  # Google News 的摘要只是標題重複，不要
        published = None
        for key in ("published_parsed", "updated_parsed"):
            if entry.get(key):
                published = datetime(*entry[key][:6], tzinfo=timezone.utc)
                break
        items.append(make_item(src, title, link, summary, published))
    return items


def parse_cnyes(raw, src):
    data = json.loads(raw)
    items = []
    for row in data.get("items", {}).get("data", []):
        title = clean_text(row.get("title", ""))
        link = f"https://news.cnyes.com/news/id/{row.get('newsId')}"
        summary = clean_text(row.get("summary", ""))
        ts = row.get("publishAt")
        published = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
        items.append(make_item(src, title, link, summary, published))
    return items


def make_item(src, title, link, summary, published):
    return {
        "title": title,
        "link": link,
        "summary": first_sentences(summary),
        "published": published,
        "source": src["name"],
        "source_region": src["region"],
        "institution": bool(src.get("institution")),
    }


# ---------- 第 2 步：合併同一事件 ----------
def title_tokens(title):
    if has_cjk(title) or has_kana(title):
        chars = re.sub(r"[^一-鿿぀-ヿ0-9a-zA-Z]", "", title)
        return {chars[i : i + 2] for i in range(len(chars) - 1)}  # 中文用兩字一組比對
    words = re.findall(r"[a-z0-9$%]+", title.lower())
    words = [w[:-1] if w.endswith("s") and len(w) > 4 else w for w in words]  # democrats → democrat
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def similar(a, b):
    if not a or not b:
        return False
    inter = len(a & b)
    jaccard = inter / len(a | b)
    return jaccard >= 0.5 or (inter >= 4 and jaccard >= 0.3)


def cluster_items(items):
    """把不同媒體報導同一件事的新聞合併成一則"""
    clusters = []
    for item in items:
        tokens = title_tokens(item["title"])
        for cluster in clusters:
            if similar(tokens, cluster["tokens"]):
                if item["source"] not in {s["name"] for s in cluster["sources"]}:
                    cluster["sources"].append({"name": item["source"], "url": item["link"], "title": item["title"]})
                cluster["tokens"] |= tokens
                if not cluster["summary"] and item["summary"]:
                    cluster["summary"] = item["summary"]
                if item["institution"]:
                    cluster["institution"] = True
                break
        else:
            clusters.append({
                "title": item["title"],
                "summary": item["summary"],
                "published": item["published"],
                "source_region": item["source_region"],
                "institution": item["institution"],
                "tokens": tokens,
                "sources": [{"name": item["source"], "url": item["link"], "title": item["title"]}],
            })
    return clusters


# ---------- 第 3 步：分類與打分數 ----------
_PATTERNS = {}


def keyword_pattern(word):
    """把關鍵字轉成正規表示式：英文要整個字比對（war 不會誤中 award），含大寫的字分大小寫（US 不會誤中 us）"""
    if word not in _PATTERNS:
        if re.search(r"[\u3040-\u9fff]", word):
            _PATTERNS[word] = re.compile(re.escape(word))           # 中日文直接比對
        else:
            flags = 0 if any(ch.isupper() for ch in word) else re.IGNORECASE
            _PATTERNS[word] = re.compile(r"(?<![A-Za-z0-9])" + re.escape(word) + r"(?:s|es)?(?![A-Za-z0-9])", flags)
    return _PATTERNS[word]


def match_keywords(text, table):
    return [key for key, words in table.items() if any(keyword_pattern(w).search(text) for w in words)]


def classify(cluster):
    text = cluster["title"] + " " + cluster["summary"]
    regions = match_keywords(text, REGION_KEYWORDS)
    if not regions:
        regions = [cluster["source_region"]]
    topics = match_keywords(text, TOPIC_KEYWORDS)
    if cluster["institution"] and "macro" not in topics:
        topics.append("macro")
    cluster["regions"] = regions[:3]
    cluster["topics"] = topics[:3]


def score(cluster, now):
    s = len(cluster["sources"]) * 3                      # 越多家媒體報導越重要
    s += max(TOPIC_WEIGHT.get(t, 0) for t in cluster["topics"]) if cluster["topics"] else 0
    if cluster["institution"]:
        s += 2                                           # 央行、IMF 等官方發布
    if cluster["published"]:
        hours = (now - cluster["published"]).total_seconds() / 3600
        s += max(0, 3 - hours / 8)                       # 越新越前面
    return round(s, 2)


# ---------- 第 4 步：AI 摘要（GitHub Models，免費） ----------
AI_SYSTEM = """你是台灣的財經政治新聞編輯，讀者是關注創投、家族辦公室、金融科技、AI 資料中心、能源轉型與地緣政治的大學生。
請用台灣慣用的繁體中文（例如：川普、輝達、聯準會、晶片、資料中心）。
對每則新聞輸出：
- t：中文標題，精簡、不誇張
- s：中文摘要，最多 3 句，只根據提供的內容，不要編造數字
- w：「為什麼重要」1 句，從資本市場、產業或政經角度切入
- r：地區，從 us, europe, china, japan, asia, mideast, latam, global 選 1~2 個
- p：主題，從 macro, markets, tech, energy, geopolitics, policy 選 1~2 個
- k：若是體育、娛樂、社會八卦等與財經政治無關的新聞填 false，否則 true
只輸出 JSON：{"items": {"<id>": {"t":..., "s":..., "w":..., "r":[...], "p":[...], "k":true}}}"""


def ai_call(token, messages, max_tokens=3500):
    errors = []
    for url in AI_URLS:
        model = AI_MODEL if "github.ai" in url else AI_MODEL.split("/")[-1]  # 舊網址的模型名稱不帶 openai/
        try:
            result = ai_call_url(url, model, token, messages, max_tokens)
            if AI_URLS[0] != url:          # 記住能用的網址，之後直接用
                AI_URLS.remove(url)
                AI_URLS.insert(0, url)
            return result
        except Exception as exc:
            errors.append(f"{url.split('/')[2]} → {exc}")
    raise RuntimeError("；".join(errors))


def ai_call_url(url, model, token, messages, max_tokens):
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                raw = resp.read().decode("utf-8", "replace")
            try:
                content = json.loads(raw)["choices"][0]["message"]["content"]
            except Exception:
                raise ValueError(f"AI 回應不是預期格式：{raw[:300]}")
            return parse_json_loose(content)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:   # 太頻繁，等一下再試
                time.sleep(20 * (attempt + 1))
                continue
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"HTTP {exc.code}：{detail}")
    return {}


def parse_json_loose(text):
    """AI 有時會在 JSON 外面包 ```json ... ```，這裡把它剝掉"""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise ValueError(f"AI 回傳內容無法解析：{text[:200]}")


def ai_enrich(clusters, token):
    """回傳成功處理的數量；失敗的那批會留給機器翻譯"""
    done = 0
    targets = clusters[:AI_MAX_ITEMS]
    for start in range(0, len(targets), AI_BATCH):
        batch = targets[start : start + AI_BATCH]
        lines = [{"id": str(start + i), "title": c["title"], "text": c["summary"][:300]} for i, c in enumerate(batch)]
        try:
            result = ai_call(token, [
                {"role": "system", "content": AI_SYSTEM},
                {"role": "user", "content": json.dumps(lines, ensure_ascii=False)},
            ]).get("items", {})
        except Exception as exc:
            log(f"  AI 第 {start // AI_BATCH + 1} 批失敗：{exc}")
            if start == 0:
                return 0   # 第一批就失敗，多半是權限或額度問題，直接放棄
            continue
        for i, c in enumerate(batch):
            r = result.get(str(start + i))
            if not isinstance(r, dict) or not r.get("t"):
                continue
            c["title_zh"] = r["t"].strip()
            c["summary_zh"] = (r.get("s") or "").strip()
            c["why"] = (r.get("w") or "").strip()
            regions = [x for x in r.get("r", []) if x in REGION_KEYWORDS or x == "global"]
            topics = [x for x in r.get("p", []) if x in TOPIC_KEYWORDS]
            if regions:
                c["regions"] = regions[:2]
            if topics:
                c["topics"] = topics[:2]
            c["relevant"] = r.get("k", True) is not False
            c["ai"] = True
            done += 1
        log(f"  AI 已處理 {done}/{len(targets)}")
        time.sleep(4)  # 免費額度每分鐘有上限
    return done


def ai_pick_top(clusters, token):
    """請 AI 從分數最高的 40 則中挑 5 則今日重點"""
    candidates = [c for c in clusters[:40]]
    lines = [{"id": str(i), "title": c.get("title_zh") or c["title"], "sources": len(c["sources"])}
             for i, c in enumerate(candidates)]
    prompt = ("以下是今天的新聞。請挑出對「全球資本市場與地緣政治」影響最大的 5 則，避免同一事件重複，"
              "地區盡量分散。只輸出 JSON：{\"top\": [\"id\", ...]}\n" + json.dumps(lines, ensure_ascii=False))
    result = ai_call(token, [{"role": "user", "content": prompt}], max_tokens=200)
    ids = [int(x) for x in result.get("top", []) if str(x).isdigit() and int(x) < len(candidates)]
    return [candidates[i]["id"] for i in ids[:5]]


# ---------- 第 4 步（備案）：機器翻譯 ----------
_TRANSLATE_FAILS = [0]   # 連續失敗次數；太多次就停止翻譯，避免整個流程卡住


def _gtx(texts):
    """管道 1：translate.googleapis.com，用換行把多則接在一起翻"""
    joined = "\n".join(t.replace("\n", " ") for t in texts)
    body = urllib.parse.urlencode({"q": joined}).encode()
    url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=zh-TW&dt=t"
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    out = "".join(seg[0] for seg in data[0] if seg and seg[0]).split("\n")
    return [x.strip() for x in out]


def _dict_ext(texts):
    """管道 2：clients5.google.com，每則一個 q 參數，一次回傳多則"""
    query = urllib.parse.urlencode([("client", "dict-chrome-ex"), ("sl", "auto"), ("tl", "zh-TW")] +
                                   [("q", t) for t in texts])
    req = urllib.request.Request("https://clients5.google.com/translate_a/t?" + query,
                                 headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    out = []
    for row in data:
        while isinstance(row, list):
            row = row[0]
        out.append(str(row).strip())
    return out


_ENGINES = [_gtx, _dict_ext]


def google_translate(texts):
    """免費機器翻譯。被限流時先等一下重試，再換另一個管道。失敗就回傳 None。"""
    if _TRANSLATE_FAILS[0] >= 6:
        return None
    for engine in list(_ENGINES):
        for wait in (0, 6):
            time.sleep(wait)
            try:
                out = engine(texts)
                _TRANSLATE_FAILS[0] = 0
                if _ENGINES[0] is not engine:      # 記住能用的管道
                    _ENGINES.remove(engine)
                    _ENGINES.insert(0, engine)
                return out if len(out) == len(texts) else None
            except Exception as exc:
                log(f"  翻譯失敗（{engine.__name__}）：{str(exc)[:80]}")
    _TRANSLATE_FAILS[0] += 1
    if _TRANSLATE_FAILS[0] == 6:
        log("  翻譯一直失敗，其餘新聞先顯示原文")
    return None


def translate_batch(texts, chunk_chars=1800):
    results, chunk = [], []
    def flush():
        if not chunk:
            return
        out = google_translate(chunk)
        if out is None and _TRANSLATE_FAILS[0] < 6 and len(chunk) <= 40:  # 整批對不齊，就一則一則翻
            out = [(google_translate([t]) or [t])[0] for t in chunk]
        if out is None:
            out = list(chunk)
        results.extend(out)
        chunk.clear()
        time.sleep(0.5)
    for t in texts:
        if sum(len(x) for x in chunk) + len(t) > chunk_chars:
            flush()
        chunk.append(t)
    flush()
    return results


def load_translation_cache():
    """讀前幾天的檔案，已經翻過的標題和摘要直接沿用，重跑時不會再翻一次"""
    cache = {}
    for path in sorted(DATA_DIR.glob("20??-??-??.json"))[-3:]:
        try:
            for it in json.loads(path.read_text()).get("items", []):
                for src, dst in (("title", "title_zh"), ("summary", "summary_zh")):
                    if it.get(src) and it.get(dst) and it[dst] != it[src]:
                        cache[it[src]] = it[dst]
        except Exception:
            continue
    return cache


def fallback_translate(clusters):
    cache = load_translation_cache()
    for c in clusters:
        if c.get("ai") or has_cjk(c["title"]) and not has_kana(c["title"]):
            continue
        if c["title"] in cache:
            c["title_zh"] = cache[c["title"]]
            c["summary_zh"] = cache.get(c["summary"], "") if c["summary"] else ""
            c["cached"] = True
    todo = [c for c in clusters if not c.get("ai") and not c.get("cached")]
    need = [c for c in todo if not has_cjk(c["title"]) or has_kana(c["title"])]
    for c in todo:
        if c not in need:   # 原本就是中文
            c["title_zh"] = c["title"]
            c["summary_zh"] = c["summary"]
    if not need:
        return
    titles = translate_batch([c["title"] for c in need])
    summaries = translate_batch([c["summary"] or "-" for c in need])
    for c, t, s in zip(need, titles, summaries):
        c["title_zh"] = t if t and t != c["title"] else ""
        c["summary_zh"] = s if c["summary"] and s != "-" else ""


def pick_top_heuristic(clusters, chosen):
    finance = {"macro", "markets", "tech", "energy"}
    by_id = {c["id"]: c for c in clusters}
    picked = [by_id[i] for i in chosen]
    def ok(c, strict):
        if c in picked:
            return False
        if any(len(c["tokens"] & p["tokens"]) >= 2 for p in picked):
            return False                                  # 跟已選的是同一件事
        if strict:
            if sum(1 for p in picked if p["regions"][0] == c["regions"][0]) >= 2:
                return False                              # 同地區最多 2 則
            fin_count = sum(1 for p in picked if finance & set(p["topics"]))
            if 5 - len(picked) <= 2 - fin_count and not finance & set(c["topics"]):
                return False                              # 保留名額給財經新聞
        return True
    for strict in (True, False):
        for c in clusters:
            if len(picked) >= 5:
                break
            if ok(c, strict):
                picked.append(c)
    return [c["id"] for c in picked]


# ---------- 主程式 ----------
def main():
    now = datetime.now(timezone.utc)
    today = now.astimezone(TAIPEI).strftime("%Y-%m-%d")
    sources = [s for s in json.loads((ROOT / "sources.json").read_text())["sources"] if s.get("enabled", True)]

    log(f"抓取 {len(sources)} 個來源…")
    all_items, statuses = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        for items, status in pool.map(fetch_source, sources):
            all_items.extend(items)
            statuses.append(status)
            mark = "✓" if status["ok"] else "✗"
            log(f"  {mark} {status['name']}: {status['count']} {status['error']}")

    # 過濾太舊的新聞
    cutoff = now - timedelta(hours=MAX_AGE_HOURS)
    fresh = [i for i in all_items if i["published"] is None or i["published"] >= cutoff]
    fresh.sort(key=lambda i: i["published"] or now, reverse=True)

    clusters = cluster_items(fresh)
    for c in clusters:
        classify(c)
    clusters = [c for c in clusters
                if (c["topics"] or c["institution"]) and not match_keywords(c["title"] + " " + c["summary"], {"x": EXCLUDE_KEYWORDS})]
    for c in clusters:
        c["score"] = score(c, now)
    clusters.sort(key=lambda c: c["score"], reverse=True)
    clusters = clusters[:MAX_ITEMS]
    for i, c in enumerate(clusters):
        c["id"] = f"{today}-{i:03d}"
    log(f"共 {len(all_items)} 則 → 去重分類後 {len(clusters)} 則")

    # AI 摘要（有 GITHUB_TOKEN 才會跑）
    token = os.environ.get("GITHUB_TOKEN") if os.environ.get("NEWS_AI", "1") != "0" else None
    ai_count = 0
    top_ids = []
    if token:
        log("呼叫 GitHub Models 做摘要…")
        try:
            ai_count = ai_enrich(clusters, token)
            clusters = [c for c in clusters if c.get("relevant", True)]
            if ai_count:
                top_ids = ai_pick_top(clusters, token)
        except Exception as exc:
            log(f"AI 流程中斷：{exc}")
    log("機器翻譯其餘新聞…")
    fallback_translate(clusters)

    # 今日重點：AI 沒挑就自己挑——分數高、事件不重複、地區分散、至少 2 則財經
    valid = {c["id"] for c in clusters}
    top_ids = [i for i in top_ids if i in valid]
    if len(top_ids) < 5:
        top_ids = pick_top_heuristic(clusters, top_ids)

    out_items = []
    for c in clusters:
        out_items.append({
            "id": c["id"],
            "title": c["title"],
            "title_zh": c.get("title_zh") or "",
            "summary": c["summary"],
            "summary_zh": c.get("summary_zh") or "",
            "why": c.get("why", ""),
            "regions": c["regions"],
            "topics": c["topics"],
            "score": c["score"],
            "time": c["published"].astimezone(TAIPEI).isoformat(timespec="minutes") if c["published"] else None,
            "sources": c["sources"],
        })

    DATA_DIR.mkdir(exist_ok=True)
    day = {
        "date": today,
        "generated_at": now.astimezone(TAIPEI).isoformat(timespec="minutes"),
        "ai": ai_count > 0,
        "ai_count": ai_count,
        "top": top_ids,
        "items": out_items,
        "sources": sorted(statuses, key=lambda s: (s["ok"], s["name"])),
    }
    (DATA_DIR / f"{today}.json").write_text(json.dumps(day, ensure_ascii=False, separators=(",", ":")))

    # 清掉太舊的檔案，更新日期清單
    days = sorted((p.stem for p in DATA_DIR.glob("20??-??-??.json")), reverse=True)
    for old in days[KEEP_DAYS:]:
        (DATA_DIR / f"{old}.json").unlink()
    (DATA_DIR / "index.json").write_text(json.dumps({"days": days[:KEEP_DAYS]}, ensure_ascii=False))

    ok = sum(1 for s in statuses if s["ok"])
    log(f"完成：{today}，{len(out_items)} 則，AI 處理 {ai_count} 則，來源成功 {ok}/{len(statuses)}")


if __name__ == "__main__":
    main()
