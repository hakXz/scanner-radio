#!/usr/bin/env python3

import http.server, urllib.request, threading, webbrowser, json, time, re, gzip, io

try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

PORT = 8765

channels = []
channels_lock = threading.Lock()
status_cache = {}
status_lock = threading.Lock()

FETCH_URL = "https://www.broadcastify.com/listen/mid/8"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.broadcastify.com/",
    "Origin": "https://www.broadcastify.com",
    "Accept": "*/*",
}


def _get_html():
    if HAS_REQUESTS:
        r = _requests.get(FETCH_URL, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.broadcastify.com/",
        }, timeout=15)
        r.raise_for_status()
        return r.text
    else:
        hdrs = dict(HEADERS)
        hdrs["Accept-Encoding"] = "gzip, deflate"
        req = urllib.request.Request(FETCH_URL, headers=hdrs)
        resp = urllib.request.urlopen(req, timeout=15)
        raw = resp.read()
        if resp.headers.get("Content-Encoding", "") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="ignore")


def fetch_channels():
    try:
        html = _get_html()
        print(f"[fetch] HTML boyutu: {len(html)} karakter")

        all_feeds = re.findall(r'/listen/feed/(\d+)', html)
        print(f"[fetch] Ham feed linkleri: {len(all_feeds)}")

        results = []
        seen = set()

        if HAS_BS4:
            soup = BeautifulSoup(html, "html.parser")
            for row in soup.select("tr"):
                a = row.find("a", href=re.compile(r"^/listen/feed/\d+$"))
                if not a:
                    continue
                fid = int(re.search(r"\d+", a["href"]).group())
                name = a.get_text(strip=True)
                tds = row.find_all("td")
                genre, listeners, status = "Unknown", 0, "unknown"
                if len(tds) >= 3:
                    genre = tds[2].get_text(strip=True) or "Unknown"
                if len(tds) >= 4:
                    m = re.search(r"\d+", tds[3].get_text())
                    listeners = int(m.group()) if m else 0
                st_el = row.find(string=re.compile(r"Online|Offline", re.I))
                if st_el:
                    status = "online" if "online" in st_el.lower() else "offline"
                if fid not in seen and len(name) >= 2:
                    seen.add(fid)
                    results.append({"id": fid, "name": name, "genre": genre,
                                    "listeners": listeners, "status": status})
        else:
            tr_pat = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
            for tr_m in tr_pat.finditer(html):
                tr = tr_m.group(1)
                fa = re.search(r'href="/listen/feed/(\d+)"[^>]*>\s*([^<]+?)\s*</a>', tr)
                if not fa:
                    continue
                fid = int(fa.group(1))
                name = fa.group(2).strip()
                tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
                def td_text(s): return re.sub(r"<[^>]+>", "", s).strip()
                genre, listeners, status = "Unknown", 0, "unknown"
                if len(tds) >= 3:
                    genre = td_text(tds[2]) or "Unknown"
                if len(tds) >= 4:
                    m = re.search(r"\d+", td_text(tds[3]))
                    listeners = int(m.group()) if m else 0
                st = re.search(r"(Online|Offline)", tr, re.IGNORECASE)
                if st:
                    status = st.group(1).lower()
                if fid not in seen and len(name) >= 2:
                    seen.add(fid)
                    results.append({"id": fid, "name": name, "genre": genre,
                                    "listeners": listeners, "status": status})

        print(f"[fetch] {len(results)} kanal bulundu ({'BeautifulSoup' if HAS_BS4 else 'regex'})")
        if results:
            print(f"[fetch] Ilk 3: {[c['name'] for c in results[:3]]}")
        return results

    except Exception as e:
        import traceback
        print(f"[fetch] HATA: {e}")
        traceback.print_exc()
        return []


def stream_urls(feed_id):
    return [
        f"https://broadcastify.cdnstream1.com/{feed_id}",
        f"https://audio.broadcastify.com/{feed_id}",
        f"https://broadcastify.cdnstream1.com/tunein/{feed_id}",
    ]


def check_feed(feed_id):
    for url in stream_urls(feed_id):
        try:
            req = urllib.request.Request(url, headers=HEADERS, method="HEAD")
            resp = urllib.request.urlopen(req, timeout=5)
            ct = resp.headers.get("Content-Type", "")
            if resp.status == 200 and any(x in ct for x in ("audio", "mpeg", "octet", "ogg")):
                return {"ok": True, "url": url, "checked": time.time()}
        except Exception:
            pass
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            resp = urllib.request.urlopen(req, timeout=5)
            resp.read(1)
            resp.close()
            return {"ok": True, "url": url, "checked": time.time()}
        except Exception:
            pass
    return {"ok": False, "url": None, "checked": time.time()}


def channel_watcher():
    global channels
    fetched = fetch_channels()
    if fetched:
        with channels_lock:
            channels = fetched
        print(f"[init] {len(fetched)} kanal yuklendi.")

    while True:
        fetched = fetch_channels()
        if fetched:
            with channels_lock:
                old_ids = {c["id"] for c in channels}
                new_ids = {c["id"] for c in fetched}
                added = new_ids - old_ids
                removed = old_ids - new_ids
                if added or removed:
                    print(f"Kanal guncellendi: +{len(added)} -{len(removed)}")
                    channels = fetched

        with channels_lock:
            current_ids = [c["id"] for c in channels]

        for fid in current_ids:
            result = check_feed(fid)
            with status_lock:
                status_cache[fid] = result

        time.sleep(300)


HTML = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<title>LA Scanner Radio</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: sans-serif; background: #1a1a1a; color: #ccc; display: flex; height: 100vh; overflow: hidden; }

  #sidebar { width: 280px; min-width: 280px; background: #111; display: flex; flex-direction: column; border-right: 1px solid #222; }
  #top { padding: 12px; border-bottom: 1px solid #222; display: flex; flex-direction: column; gap: 7px; }
  #top h2 { color: #fff; font-size: 14px; }

  #search-row { display: flex; gap: 6px; }
  #search { flex: 1; background: #1e1e1e; border: 1px solid #2a2a2a; color: #ccc; padding: 6px 9px; border-radius: 4px; font-size: 13px; outline: none; }
  #search:focus { border-color: #444; }

  #refreshbtn { background: #1e1e1e; border: 1px solid #2a2a2a; color: #888; border-radius: 4px; padding: 0 9px; cursor: pointer; font-size: 15px; }
  #refreshbtn:hover { color: #ccc; border-color: #444; }
  #refreshbtn.spinning { animation: spin 0.6s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  #filters { display: flex; gap: 4px; flex-wrap: wrap; }
  .fb { padding: 2px 8px; font-size: 11px; border-radius: 3px; border: 1px solid #2a2a2a; background: transparent; color: #666; cursor: pointer; }
  .fb:hover { color: #aaa; }
  .fb.on { background: #2a2a2a; color: #ddd; }

  #syncbar { font-size: 11px; color: #555; padding: 0 2px; min-height: 16px; }
  #syncbar.active { color: #4a9; }

  #list { overflow-y: auto; flex: 1; }
  .item { padding: 9px 12px; cursor: pointer; border-bottom: 1px solid #1a1a1a; display: flex; align-items: center; gap: 9px; }
  .item:hover { background: #181818; }
  .item.active { background: #1a2a1a; border-left: 3px solid #4a9; padding-left: 9px; }

  .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; transition: background 0.3s; }
  .dot.on { background: #4a9; box-shadow: 0 0 4px #4a9; }
  .dot.off { background: #444; }
  .dot.unknown { background: #555; }

  .iname { font-size: 13px; color: #ccc; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .item.active .iname { color: #fff; }
  .imeta { font-size: 11px; color: #444; margin-top: 1px; }

  #main { flex: 1; display: flex; flex-direction: column; }
  #nowbar { padding: 10px 16px; background: #0f0f0f; border-bottom: 1px solid #222; font-size: 13px; color: #555; display: flex; align-items: center; gap: 10px; }
  #nowbar span { color: #bbb; flex: 1; }

  .badge { font-size: 11px; padding: 2px 8px; border-radius: 3px; }
  .badge.playing { background: #1a3a1a; color: #4a9; }
  .badge.loading { background: #2a2a1a; color: #aa4; }
  .badge.stopped { background: #222; color: #555; }
  .badge.error   { background: #3a1a1a; color: #a44; }

  #player-area { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; }
  #empty { color: #333; font-size: 14px; text-align: center; line-height: 2; }
  #controls { display: none; flex-direction: column; align-items: center; gap: 12px; width: 100%; max-width: 360px; padding: 0 20px; }

  #playbtn { width: 52px; height: 52px; border-radius: 50%; border: 2px solid #4a9; background: transparent; color: #4a9; cursor: pointer; font-size: 20px; display: flex; align-items: center; justify-content: center; }
  #playbtn:hover { background: rgba(68,170,153,.1); }

  #vol-row { display: flex; align-items: center; gap: 10px; width: 100%; }
  #vol-row span { color: #555; font-size: 13px; }
  #vol { flex: 1; accent-color: #4a9; }

  #errbox { color: #a44; font-size: 13px; text-align: center; display: none; line-height: 1.8; }

  #list::-webkit-scrollbar { width: 4px; }
  #list::-webkit-scrollbar-thumb { background: #222; border-radius: 2px; }
</style>
</head>
<body>

<div id="sidebar">
  <div id="top">
    <h2>📻 LA Scanner Radio</h2>
    <div id="search-row">
      <input id="search" placeholder="Ara..." oninput="render()">
      <button id="refreshbtn" onclick="manualRefresh()" title="Yenile">↻</button>
    </div>
    <div id="filters">
      <button class="fb on" onclick="setF('all',this)">Tumu</button>
      <button class="fb" onclick="setF('Public Safety',this)">Guvenlik</button>
      <button class="fb" onclick="setF('Amateur Radio',this)">Amator</button>
      <button class="fb" onclick="setF('Rail',this)">Demiryolu</button>
      <button class="fb" onclick="setF('Other',this)">Diger</button>
    </div>
    <div id="syncbar"></div>
  </div>
  <div id="list"></div>
</div>

<div id="main">
  <div id="nowbar">
    <span id="nowtitle">Kanal secilmedi</span>
    <span class="badge stopped" id="badge">DURDURULDU</span>
  </div>
  <div id="player-area">
    <div id="empty">Sol taraftan bir kanal secin</div>
    <div id="controls">
      <button id="playbtn" onclick="togglePlay()">▶</button>
      <div id="vol-row">
        <span>🔈</span>
        <input type="range" id="vol" min="0" max="1" step="0.02" value="0.8" oninput="audio.volume=+this.value">
        <span>🔊</span>
      </div>
    </div>
    <div id="errbox">Baglanti kurulamadi.<br>Kanal cevrimdisi veya sunucu yanit vermiyor.</div>
  </div>
</div>

<audio id="audio"></audio>

<script>
const audio = document.getElementById('audio');
audio.volume = 0.8;

let allChannels = [];
let current = null;
let playing = false;
let filter = 'all';
let statuses = {};

function dotClass(id) {
  if (!(id in statuses)) return 'unknown';
  return statuses[id].ok ? 'on' : 'off';
}

function setF(f, btn) {
  filter = f;
  document.querySelectorAll('.fb').forEach(b => b.classList.remove('on'));
  btn.classList.add('on');
  render();
}

function render() {
  const q = document.getElementById('search').value.toLowerCase();
  const list = document.getElementById('list');
  list.innerHTML = '';
  allChannels
    .filter(c => filter === 'all' || c.genre === filter)
    .filter(c => !q || c.name.toLowerCase().includes(q))
    .forEach(c => {
      const el = document.createElement('div');
      el.className = 'item' + (current && current.id === c.id ? ' active' : '');
      el.innerHTML =
        `<div class="dot ${dotClass(c.id)}" id="dot-${c.id}"></div>` +
        `<div style="flex:1;min-width:0">` +
        `<div class="iname">${c.name}</div>` +
        `<div class="imeta">${c.genre}${c.listeners ? ' · ' + c.listeners + ' dinleyici' : ''}</div></div>`;
      el.onclick = () => select(c);
      list.appendChild(el);
    });
}

function updateDots() {
  document.querySelectorAll('.dot[id^="dot-"]').forEach(el => {
    const id = parseInt(el.id.replace('dot-', ''));
    el.className = 'dot ' + dotClass(id);
  });
}

function setBadge(cls, text) {
  const b = document.getElementById('badge');
  b.className = 'badge ' + cls;
  b.textContent = text;
}

function setSyncBar(text, active) {
  const el = document.getElementById('syncbar');
  el.textContent = text;
  el.className = active ? 'active' : '';
}

function select(c) {
  current = c;
  document.getElementById('nowtitle').textContent = c.name;
  document.getElementById('empty').style.display = 'none';
  document.getElementById('errbox').style.display = 'none';
  document.getElementById('controls').style.display = 'flex';
  render();
  startPlay();
}

function startPlay() {
  setBadge('loading', 'BAGLANILIYOR');
  audio.src = `/stream?id=${current.id}`;
  audio.play().catch(showErr);
}

function togglePlay() {
  if (!current) return;
  if (playing) {
    audio.pause();
    audio.src = '';
    playing = false;
    document.getElementById('playbtn').textContent = '▶';
    setBadge('stopped', 'DURDURULDU');
  } else {
    startPlay();
  }
}

function showErr() {
  setBadge('error', 'HATA');
  document.getElementById('errbox').style.display = 'block';
  playing = false;
  document.getElementById('playbtn').textContent = '▶';
}

audio.addEventListener('playing', () => {
  playing = true;
  setBadge('playing', 'YAYIN');
  document.getElementById('playbtn').textContent = '⏸';
  document.getElementById('errbox').style.display = 'none';
});
audio.addEventListener('error', showErr);
audio.addEventListener('waiting', () => setBadge('loading', 'TAMPON'));
audio.addEventListener('stalled', () => setBadge('loading', 'TAMPON'));

function fetchChannels() {
  return fetch('/channels').then(r => r.json());
}

function fetchStatus() {
  return fetch('/status').then(r => r.json());
}

function applyChannels(data) {
  if (!data || !data.length) return;
  const oldIds = new Set(allChannels.map(c => c.id));
  const newIds = new Set(data.map(c => c.id));
  const changed = [...newIds].some(id => !oldIds.has(id)) || [...oldIds].some(id => !newIds.has(id));
  if (changed || !allChannels.length) {
    allChannels = data;
    render();
  }
}

function manualRefresh() {
  const btn = document.getElementById('refreshbtn');
  btn.classList.add('spinning');
  setSyncBar('guncelleniyor...', true);
  Promise.all([fetchChannels(), fetchStatus()])
    .then(([ch, st]) => {
      applyChannels(ch);
      statuses = st;
      updateDots();
      setSyncBar('guncellendi ✓', true);
      setTimeout(() => setSyncBar('', false), 2000);
    })
    .catch(() => setSyncBar('hata', false))
    .finally(() => btn.classList.remove('spinning'));
}

function pollAll() {
  Promise.all([fetchChannels(), fetchStatus()])
    .then(([ch, st]) => {
      applyChannels(ch);
      statuses = st;
      updateDots();
    })
    .catch(() => {});
}

pollAll();
setInterval(pollAll, 5000);
</script>
</body>
</html>
"""


class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, *args):
        pass

    def do_GET(self):
        try:
            if self.path == '/':
                self._html()
            elif self.path == '/channels':
                self._channels()
            elif self.path == '/status':
                self._status()
            elif self.path.startswith('/stream'):
                self._stream()
            else:
                self.send_response(404)
                self.end_headers()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def _html(self):
        body = HTML.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _channels(self):
        with channels_lock:
            data = list(channels)
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def _status(self):
        with status_lock:
            snap = {str(k): {"ok": v["ok"], "url": v["url"]} for k, v in status_cache.items()}
        body = json.dumps(snap).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def _stream(self):
        try:
            feed_id = int(self.path.split('id=')[1].split('&')[0])
        except (IndexError, ValueError):
            self.send_response(400)
            self.end_headers()
            return

        with status_lock:
            cached = status_cache.get(feed_id)

        urls_to_try = []
        if cached and cached.get("url"):
            urls_to_try.append(cached["url"])
        for u in stream_urls(feed_id):
            if u not in urls_to_try:
                urls_to_try.append(u)

        for url in urls_to_try:
            try:
                req = urllib.request.Request(url, headers=HEADERS)
                resp = urllib.request.urlopen(req, timeout=10)
                ct = resp.headers.get('Content-Type', 'audio/mpeg')

                self.send_response(200)
                self.send_header('Content-Type', ct)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()

                with status_lock:
                    status_cache[feed_id] = {"ok": True, "url": url, "checked": time.time()}

                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                return

            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return
            except Exception:
                continue

        with status_lock:
            status_cache[feed_id] = {"ok": False, "url": None, "checked": time.time()}
        try:
            self.send_response(502)
            self.end_headers()
        except Exception:
            pass


if __name__ == '__main__':
    t = threading.Thread(target=channel_watcher, daemon=True)
    t.start()

    server = http.server.ThreadingHTTPServer(('localhost', PORT), Handler)
    print(f'http://localhost:{PORT}')
    threading.Timer(1.2, lambda: webbrowser.open(f'http://localhost:{PORT}')).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
