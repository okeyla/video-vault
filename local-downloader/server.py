"""VideoVault 本地下載站。

只用 Python 標準函式庫：
    python server.py            # 啟動並開啟瀏覽器 http://127.0.0.1:8765
    python server.py --no-open  # 只啟動

負責網頁做不到的事：啟動 Parabolic、執行 yt-dlp、開啟下載資料夾。
影片清單本身由網頁直接向 GitHub 讀寫。
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST, PORT = "127.0.0.1", 8765
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONFIG_PATH = HERE / "config.json"
PARABOLIC_DIR = Path(r"C:\Program Files\Nickvision Parabolic\Release")

PLATFORMS = ("facebook", "instagram", "threads", "youtube", "other")
SOURCE_TYPES = ("site", "parabolic", "ytdlp")
STATS_PATH = HERE / "stats.json"


def _site(sid, platform, name, url, input_sel="", button_sel="", enabled=True):
    return {"id": sid, "platform": platform, "name": name, "type": "site", "url": url,
            "input": input_sel, "button": button_sel, "enabled": enabled, "builtin": True}


def _tool(platform, kind, enabled=True):
    name = {"ytdlp": "yt-dlp 全自動", "parabolic": "Parabolic"}[kind]
    return {"id": kind, "platform": platform, "name": name, "type": kind, "url": "",
            "input": "", "button": "", "enabled": enabled, "builtin": True}


# 下載來源：每個平台依序排列，排在前面的優先使用（開啟「自動排序」時改依成功率排序）
# 預設停用的是已驗證可連線的備用站，需要時到「下載來源」啟用
DEFAULT_SOURCES = [
    _site("fdown", "facebook", "fdown.net", "https://fdown.net/", "#downloadinput", "#downloadbtn"),
    _site("snapsave", "facebook", "SnapSave", "https://snapsave.app/", "#url", "#send", False),
    _site("fdownloader", "facebook", "FDownloader", "https://fdownloader.net/", "#s_input", "button.btn-red", False),
    _tool("facebook", "ytdlp"),
    _site("saveclip", "instagram", "SaveClip", "https://saveclip.app/zh-tw9", "#s_input", "#search-form button"),
    _site("fastdl", "instagram", "FastDL", "https://fastdl.app/", "#search-form-input", "#searchFormButton", False),
    _site("sssinstagram", "instagram", "SSSInstagram", "https://sssinstagram.com/", "#input", ".form__submit", False),
    _tool("instagram", "ytdlp"),
    _site("threadsdownloader", "threads", "ThreadsDownloader", "https://www.threadsdownloader.com/", "#postUrl", "#loadVideos"),
    _site("threadster", "threads", "Threadster", "https://threadster.app/", "#url", "button[type=submit]", False),
    _site("savethr", "threads", "SaveThr", "https://savethr.com/", "#floating_outlined", "#submit-btn", False),
    _tool("threads", "ytdlp"),
    _tool("youtube", "parabolic"),
    _tool("youtube", "ytdlp"),
    _tool("other", "ytdlp"),
    _site("original", "other", "開啟原網址", "{url}"),
]

DEFAULT_CONFIG = {
    "download_dir": str(Path.home() / "Videos" / "VideoVault"),
    "sources": DEFAULT_SOURCES,
    "auto_rank": True,           # 依成功率與連線狀態自動排序
    "parabolic_exe": str(PARABOLIC_DIR / "Nickvision.Parabolic.WinUI.exe"),
    "ytdlp_exe": "",            # 空白 = 自動尋找（PATH → Parabolic 內附）
    "cookies_from_browser": "",  # IG/FB 需要登入時可填 firefox / edge / chrome
    "concurrency": 2,
    "collect_downloads": True,   # 網站下載完成後，把影片從瀏覽器「下載」資料夾搬進 download_dir
}

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FILE_LOCK = threading.Lock()


# ---------------------------------------------------------------- config
def source_key(src: dict) -> str:
    return f"{src['platform']}/{src['id']}"


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if not CONFIG_PATH.exists():
        return cfg
    try:
        saved = json.loads(CONFIG_PATH.read_text("utf-8"))
    except (OSError, ValueError) as e:
        print(f"[warn] config.json 讀取失敗，使用預設值：{e}")
        return cfg
    handlers = saved.pop("handlers", None)
    cfg.update(saved)
    if "sources" not in saved and handlers:
        # 舊版設定（每平台一種方式）→ 把當時選的方式排到最前面
        for p, h in handlers.items():
            chosen = [s for s in cfg["sources"] if s["platform"] == p and s["type"] == h]
            cfg["sources"] = chosen + [s for s in cfg["sources"] if s not in chosen]
    # 新版程式加入的內建來源，補到清單最後
    have = {source_key(s) for s in cfg["sources"]}
    cfg["sources"] += [s for s in json.loads(json.dumps(DEFAULT_SOURCES)) if source_key(s) not in have]
    return cfg


def clean_source(s: dict) -> dict | None:
    platform, kind = s.get("platform"), s.get("type")
    if platform not in PLATFORMS or kind not in SOURCE_TYPES:
        return None
    sid = re.sub(r"[^\w-]", "", str(s.get("id") or ""))[:40] or uuid.uuid4().hex[:8]
    url = str(s.get("url") or "").strip()
    if kind == "site" and not (url == "{url}" or re.match(r"^https?://\S+$", url)):
        return None
    return {"id": sid, "platform": platform, "name": str(s.get("name") or sid).strip()[:40], "type": kind,
            "url": url if kind == "site" else "", "input": str(s.get("input") or "").strip()[:200],
            "button": str(s.get("button") or "").strip()[:200], "enabled": bool(s.get("enabled", True)),
            "builtin": bool(s.get("builtin"))}


def save_config(new: dict) -> dict:
    cfg = load_config()
    for key in ("download_dir", "parabolic_exe", "ytdlp_exe", "cookies_from_browser"):
        if key in new:
            cfg[key] = str(new[key]).strip()
    if "concurrency" in new:
        cfg["concurrency"] = max(1, min(6, int(new["concurrency"])))
    for key in ("auto_rank", "collect_downloads"):
        if key in new:
            cfg[key] = bool(new[key])
    if isinstance(new.get("sources"), list):
        cleaned, seen = [], set()
        for s in new["sources"]:
            c = clean_source(s)
            if c and source_key(c) not in seen:
                seen.add(source_key(c))
                cleaned.append(c)
        cfg["sources"] = cleaned
    with FILE_LOCK:
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    return cfg


# ---------------------------------------------------------------- 成功率統計
def load_stats() -> dict:
    try:
        return json.loads(STATS_PATH.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def record_stat(key: str, ok: bool) -> dict:
    with FILE_LOCK:
        stats = load_stats()
        st = stats.setdefault(key, {"ok": 0, "fail": 0, "recent": "", "lastAt": None})
        st["ok" if ok else "fail"] += 1
        st["recent"] = (st["recent"] + ("1" if ok else "0"))[-20:]  # 最近 20 次，1 = 成功
        st["lastAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        STATS_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=2), "utf-8")
    return stats


# ---------------------------------------------------------------- 連線檢查
HEALTH: dict[str, dict] = {}
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"


def check_site(url: str) -> dict:
    started = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            code = res.status
    except urllib.error.HTTPError as e:
        code = e.code
        # Cloudflare 驗證頁：網站本身正常，只是擋程式
        if e.headers.get("cf-mitigated") == "challenge" or (
                code in (403, 503) and "cloudflare" in str(e.headers.get("server", "")).lower()):
            return {"state": "up", "code": code, "ms": int((time.time() - started) * 1000), "note": "有機器人驗證"}
    except (urllib.error.URLError, OSError) as e:
        return {"state": "down", "code": None, "ms": None, "note": str(getattr(e, "reason", e))[:80]}
    ms = int((time.time() - started) * 1000)
    return {"state": "up" if code < 500 else "down", "code": code, "ms": ms, "note": ""}


def check_health() -> dict:
    cfg = load_config()
    sites = {s["url"] for s in cfg["sources"] if s["type"] == "site" and s["url"].startswith("http")}
    results: dict[str, dict] = {}
    threads = [threading.Thread(target=lambda u=u: results.__setitem__(u, check_site(u))) for u in sites]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    checked = time.strftime("%H:%M")
    HEALTH.clear()
    HEALTH.update({u: {**r, "checkedAt": checked} for u, r in results.items()})
    return HEALTH


def find_ytdlp(cfg: dict) -> str | None:
    for cand in (cfg.get("ytdlp_exe"), shutil.which("yt-dlp"), str(PARABOLIC_DIR / "yt-dlp.exe")):
        if cand and Path(cand).is_file():
            return cand
    return None


def find_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return str(Path(found).parent)
    if (PARABOLIC_DIR / "ffmpeg.exe").is_file():
        return str(PARABOLIC_DIR)
    return None


VERSION_CACHE: dict[str, str | None] = {}


def tool_status(cfg: dict) -> dict:
    ytdlp = find_ytdlp(cfg)
    version = None
    if ytdlp:
        # yt-dlp 啟動要一兩秒，版本號只查一次
        if ytdlp not in VERSION_CACHE:
            try:
                VERSION_CACHE[ytdlp] = subprocess.run([ytdlp, "--version"], capture_output=True, text=True,
                                                      timeout=15, creationflags=NO_WINDOW).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                VERSION_CACHE[ytdlp] = None
        version = VERSION_CACHE[ytdlp]
    return {
        "ytdlp": ytdlp,
        "ytdlp_version": version,
        "ffmpeg": find_ffmpeg(),
        "parabolic": cfg["parabolic_exe"] if Path(cfg["parabolic_exe"]).is_file() else None,
    }


def valid_url(url: str) -> bool:
    return bool(re.match(r"^https?://[^\s]+$", url or ""))


# ---------------------------------------------------------------- yt-dlp jobs
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
JOB_QUEUE: "queue.Queue[str]" = queue.Queue()
PROGRESS_RE = re.compile(r"VVPROG\s+([\d.]+)%")


def set_job(job_id: str, **kw):
    with JOBS_LOCK:
        JOBS[job_id].update(kw)


def run_ytdlp(job: dict):
    cfg = load_config()
    ytdlp = find_ytdlp(cfg)
    if not ytdlp:
        set_job(job["id"], status="error", message="找不到 yt-dlp")
        return
    out_dir = Path(cfg["download_dir"]) / job["platform"]
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        ytdlp,
        "-P", str(out_dir),
        "-o", "%(upload_date>%Y-%m-%d)s %(title).80B [%(id)s].%(ext)s",
        "-f", "bv*+ba/b",
        "--merge-output-format", "mp4",
        "--no-playlist", "--newline", "--progress",
        "--progress-template", "download:VVPROG %(progress._percent_str)s",
        "--print", "after_move:VVFILE %(filepath)s",
        "--encoding", "utf-8",
    ]
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        cmd += ["--ffmpeg-location", ffmpeg]
    if cfg.get("cookies_from_browser"):
        cmd += ["--cookies-from-browser", cfg["cookies_from_browser"]]
    cmd += ["--", job["url"]]

    set_job(job["id"], status="running", message="下載中")
    tail: list[str] = []
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                creationflags=NO_WINDOW)
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            m = PROGRESS_RE.search(line)
            if m:
                set_job(job["id"], progress=float(m.group(1)))
            elif line.startswith("VVFILE "):
                set_job(job["id"], file=line[7:])
            else:
                tail = (tail + [line])[-8:]
        proc.wait()
    except OSError as e:
        set_job(job["id"], status="error", message=str(e))
        return

    record_stat(f"{job['platform']}/ytdlp", proc.returncode == 0)
    if proc.returncode == 0:
        set_job(job["id"], status="done", progress=100, message="完成")
    else:
        err = next((l for l in reversed(tail) if "ERROR" in l), tail[-1] if tail else "未知錯誤")
        set_job(job["id"], status="error", message=err[:300])


def worker():
    while True:
        job_id = JOB_QUEUE.get()
        with JOBS_LOCK:
            job = dict(JOBS[job_id])
        try:
            run_ytdlp(job)
        except Exception as e:  # noqa: BLE001 - 單一工作失敗不能讓 worker 死掉
            set_job(job_id, status="error", message=repr(e))
        finally:
            JOB_QUEUE.task_done()


def enqueue(items: list[dict]) -> list[dict]:
    created = []
    for it in items:
        url = str(it.get("url", ""))
        if not valid_url(url):
            continue
        platform = it.get("platform") if it.get("platform") in PLATFORMS else "other"
        job = {"id": uuid.uuid4().hex[:10], "itemId": it.get("id"), "url": url, "platform": platform,
               "status": "queued", "progress": 0, "message": "排隊中", "file": None, "createdAt": time.time(),
               "kind": "ytdlp"}
        with JOBS_LOCK:
            JOBS[job["id"]] = job
        JOB_QUEUE.put(job["id"])
        created.append(job)
    return created


# ---------------------------------------------------------------- 自動歸檔（瀏覽器下載 → VideoVault）
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".3gp"}
PARTIAL_EXT = {".crdownload", ".part", ".partial", ".download", ".tmp"}
CLAIMED: set[str] = set()


def _stamp(f: Path) -> float:
    st = f.stat()
    return max(st.st_mtime, st.st_ctime)


def unique_path(target: Path) -> Path:
    if not target.exists():
        return target
    for i in range(2, 1000):
        cand = target.with_name(f"{target.stem} ({i}){target.suffix}")
        if not cand.exists():
            return cand
    return target.with_name(f"{target.stem} {uuid.uuid4().hex[:6]}{target.suffix}")


def collect_worker(job_id: str, since: float, platform: str):
    """等瀏覽器下載完成，把 since 之後出現的影片搬到 download_dir/<平台>/。"""
    src_dir = browser_downloads_dir()
    dest_dir = Path(load_config()["download_dir"]) / platform
    started = time.time()
    last_sizes: dict[str, int] = {}
    while time.time() - started < 600:
        try:
            files = [f for f in src_dir.iterdir() if f.is_file() and _stamp(f) >= since - 2]
        except OSError as e:
            set_job(job_id, status="error", message=f"讀不到下載資料夾：{e}")
            return
        partial = [f for f in files if f.suffix.lower() in PARTIAL_EXT]
        videos = [f for f in files if f.suffix.lower() in VIDEO_EXT and str(f) not in CLAIMED]
        sizes = {str(f): f.stat().st_size for f in videos}
        stable = videos and sizes == last_sizes and all(sizes.values())
        last_sizes = sizes
        if stable and not partial:
            dest_dir.mkdir(parents=True, exist_ok=True)
            moved = []
            for f in videos:
                CLAIMED.add(str(f))
                try:
                    target = unique_path(dest_dir / f.name)
                    shutil.move(str(f), str(target))
                    moved.append(target)
                except OSError as e:
                    set_job(job_id, status="error", message=f"搬移失敗（檔案可能還在使用中）：{e}")
                    return
            set_job(job_id, status="done", progress=100, file=str(moved[0]),
                    message=f"已搬到 {dest_dir}" + (f"（共 {len(moved)} 個檔案）" if len(moved) > 1 else ""))
            return
        if partial:
            set_job(job_id, status="running", message="等待瀏覽器下載完成…")
        elif not videos and time.time() - started > 45:
            set_job(job_id, status="error",
                    message=f"在 {src_dir} 找不到剛下載的影片（可能存到別處，或網站下載的不是影片檔）")
            return
        else:
            set_job(job_id, status="running", message="尋找剛下載的影片…")
        time.sleep(1.5)
    set_job(job_id, status="error", message="等太久了（超過 10 分鐘），請手動搬移")


def start_collect(body: dict) -> dict:
    platform = body.get("platform") if body.get("platform") in PLATFORMS else "other"
    job = {"id": uuid.uuid4().hex[:10], "itemId": body.get("id"), "url": str(body.get("url", "")),
           "platform": platform, "status": "running", "progress": 0, "message": "尋找剛下載的影片…",
           "file": None, "createdAt": time.time(), "kind": "collect"}
    with JOBS_LOCK:
        JOBS[job["id"]] = job
    since = float(body.get("since") or time.time() - 600)
    threading.Thread(target=collect_worker, args=(job["id"], since, platform), daemon=True).start()
    return job


# ---------------------------------------------------------------- other actions
def open_parabolic(url: str) -> str:
    cfg = load_config()
    exe = cfg["parabolic_exe"]
    if not Path(exe).is_file():
        raise FileNotFoundError(f"找不到 Parabolic：{exe}")
    # Parabolic 會讀取啟動參數中的網址；即使沒吃到參數，網頁端也已把網址放進剪貼簿，新增下載視窗會自動帶入
    subprocess.Popen([exe, url], cwd=str(Path(exe).parent))
    return "已開啟 Parabolic"


def browser_downloads_dir() -> Path:
    """Windows 的「下載」資料夾（使用者可能搬到別的磁碟，所以向系統查詢）。"""
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

        folder_id = GUID(0x374DE290, 0x123F, 0x4565, (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
        buf = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(buf)) == 0:
            path = Path(buf.value)
            ctypes.windll.ole32.CoTaskMemFree(buf)
            return path
    except (OSError, AttributeError):
        pass
    return Path.home() / "Downloads"


def explorer_windows() -> set:
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return set()
    user32 = ctypes.windll.user32
    out = set()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value == "CabinetWClass" and user32.IsWindowVisible(hwnd):
            out.add(hwnd)
        return True

    user32.EnumWindows(each, 0)
    return out


def bring_explorer_to_front(folder: Path, before: set, timeout: float = 3.0) -> None:
    """背景程式開的視窗會被 Windows 放在後面；找到該檔案總管視窗並拉到最前面。
    優先找「新開的」檔案總管視窗；資料夾已開著時，改用視窗標題比對。"""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return
    user32 = ctypes.windll.user32
    title = folder.name.lower()
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value == "CabinetWClass" and user32.IsWindowVisible(hwnd):
            text = ctypes.create_unicode_buffer(260)
            user32.GetWindowTextW(hwnd, text, 260)
            if hwnd not in before or text.value.lower().startswith(title):
                found.append(hwnd)
        return True

    deadline = time.time() + timeout
    while time.time() < deadline and not found:
        user32.EnumWindows(each, 0)
        if not found:
            time.sleep(0.15)
    if not found:
        return
    hwnd = found[0]
    # 模擬按一下 Alt，Windows 才允許背景程式切換前景視窗
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)


def open_folder(which: str | None = None, sub: str | None = None) -> str:
    if which == "browser":
        path = browser_downloads_dir()
    else:
        path = Path(load_config()["download_dir"])
        if sub in PLATFORMS:
            path = path / sub
        path.mkdir(parents=True, exist_ok=True)
    before = explorer_windows()
    os.startfile(str(path))  # type: ignore[attr-defined]
    threading.Thread(target=bring_explorer_to_front, args=(path, before), daemon=True).start()
    return str(path)


# ---------------------------------------------------------------- HTTP
STATIC = {
    "/": (HERE / "index.html", "text/html; charset=utf-8"),
    "/index.html": (HERE / "index.html", "text/html; charset=utf-8"),
    "/common.js": (ROOT / "common.js", "text/javascript; charset=utf-8"),
    "/style.css": (ROOT / "style.css", "text/css; charset=utf-8"),
    "/icon.svg": (ROOT / "icon.svg", "image/svg+xml"),
}
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}


class Handler(BaseHTTPRequestHandler):
    server_version = "VideoVault/1.0"

    def log_message(self, fmt, *args):  # 安靜一點，只記錯誤
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)

    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def guard(self) -> bool:
        # 防止其他網站（或 DNS rebinding）偷偷呼叫本機 API
        if self.headers.get("Host") not in ALLOWED_HOSTS:
            self.send_error(403)
            return False
        if self.path.startswith("/api/") and self.headers.get("X-VideoVault") != "1":
            self.send_error(403)
            return False
        return True

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}") if length else {}

    def do_GET(self):
        if not self.guard():
            return
        path = self.path.split("?", 1)[0]
        if path in STATIC:
            file, ctype = STATIC[path]
            data = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        elif path == "/api/config":
            cfg = load_config()
            self.send_json({"config": cfg, "tools": tool_status(cfg), "stats": load_stats(), "health": HEALTH})
        elif path == "/api/jobs":
            with JOBS_LOCK:
                self.send_json({"jobs": sorted(JOBS.values(), key=lambda j: j["createdAt"])})
        else:
            self.send_error(404)

    def do_POST(self):
        if not self.guard():
            return
        path = self.path.split("?", 1)[0]
        try:
            body = self.read_json()
            if path == "/api/config":
                cfg = save_config(body)
                self.send_json({"config": cfg, "tools": tool_status(cfg), "stats": load_stats(), "health": HEALTH})
            elif path == "/api/stats":
                key = str(body.get("key", ""))
                if not re.match(r"^[a-z]+/[\w-]+$", key):
                    raise ValueError("來源代號不正確")
                self.send_json({"stats": record_stat(key, bool(body.get("ok")))})
            elif path == "/api/stats/reset":
                with FILE_LOCK:
                    stats = load_stats()
                    stats.pop(str(body.get("key", "")), None)
                    STATS_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=2), "utf-8")
                self.send_json({"stats": stats})
            elif path == "/api/health":
                self.send_json({"health": check_health()})
            elif path == "/api/collect":
                self.send_json({"job": start_collect(body)})
            elif path == "/api/ytdlp":
                self.send_json({"jobs": enqueue(body.get("items") or [])})
            elif path == "/api/parabolic":
                if not valid_url(body.get("url", "")):
                    raise ValueError("網址格式不正確")
                self.send_json({"message": open_parabolic(body["url"])})
            elif path == "/api/open-folder":
                self.send_json({"path": open_folder(body.get("which"), body.get("platform"))})
            elif path == "/api/jobs/clear":
                with JOBS_LOCK:
                    for k in [k for k, j in JOBS.items() if j["status"] in ("done", "error")]:
                        del JOBS[k]
                self.send_json({"ok": True})
            else:
                self.send_error(404)
        except Exception as e:  # noqa: BLE001
            self.send_json({"error": str(e)}, 400)


def main():
    cfg = load_config()
    for _ in range(max(1, int(cfg.get("concurrency", 2)))):
        threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=check_health, daemon=True).start()
    try:
        httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        print(f"連接埠 {PORT} 已被使用，可能已經啟動過了。直接開啟瀏覽器。")
        webbrowser.open(f"http://{HOST}:{PORT}/")
        return
    url = f"http://{HOST}:{PORT}/"
    print(f"VideoVault 本地下載站：{url}")
    print(f"下載資料夾：{cfg['download_dir']}")
    print("關閉這個視窗即可停止。")
    if "--no-open" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
