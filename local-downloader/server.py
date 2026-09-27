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
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST, PORT = "127.0.0.1", 8765
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONFIG_PATH = HERE / "config.json"
PARABOLIC_DIR = Path(r"C:\Program Files\Nickvision Parabolic\Release")

PLATFORMS = ("facebook", "instagram", "threads", "youtube", "other")
HANDLERS = ("site", "parabolic", "ytdlp")

DEFAULT_CONFIG = {
    "download_dir": str(Path.home() / "Videos" / "VideoVault"),
    # 每個平台用哪種方式下載：site = 開啟下載網站、parabolic = 交給 Parabolic、ytdlp = 背景全自動
    "handlers": {
        "facebook": "site",
        "instagram": "site",
        "threads": "site",
        "youtube": "parabolic",
        "other": "ytdlp",
    },
    "parabolic_exe": str(PARABOLIC_DIR / "Nickvision.Parabolic.WinUI.exe"),
    "ytdlp_exe": "",            # 空白 = 自動尋找（PATH → Parabolic 內附）
    "cookies_from_browser": "",  # IG/FB 需要登入時可填 firefox / edge / chrome
    "concurrency": 2,
}

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------- config
def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text("utf-8"))
            handlers = {**cfg["handlers"], **saved.pop("handlers", {})}
            cfg.update(saved)
            cfg["handlers"] = handlers
        except (OSError, ValueError) as e:
            print(f"[warn] config.json 讀取失敗，使用預設值：{e}")
    return cfg


def save_config(new: dict) -> dict:
    cfg = load_config()
    for key in ("download_dir", "parabolic_exe", "ytdlp_exe", "cookies_from_browser"):
        if key in new:
            cfg[key] = str(new[key]).strip()
    if "concurrency" in new:
        cfg["concurrency"] = max(1, min(6, int(new["concurrency"])))
    for p, h in (new.get("handlers") or {}).items():
        if p in PLATFORMS and h in HANDLERS:
            cfg["handlers"][p] = h
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    return cfg


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


def tool_status(cfg: dict) -> dict:
    ytdlp = find_ytdlp(cfg)
    version = None
    if ytdlp:
        try:
            version = subprocess.run([ytdlp, "--version"], capture_output=True, text=True,
                                     timeout=15, creationflags=NO_WINDOW).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
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
               "status": "queued", "progress": 0, "message": "排隊中", "file": None, "createdAt": time.time()}
        with JOBS_LOCK:
            JOBS[job["id"]] = job
        JOB_QUEUE.put(job["id"])
        created.append(job)
    return created


# ---------------------------------------------------------------- other actions
def open_parabolic(url: str) -> str:
    cfg = load_config()
    exe = cfg["parabolic_exe"]
    if not Path(exe).is_file():
        raise FileNotFoundError(f"找不到 Parabolic：{exe}")
    # Parabolic 會讀取啟動參數中的網址；即使沒吃到參數，網頁端也已把網址放進剪貼簿，新增下載視窗會自動帶入
    subprocess.Popen([exe, url], cwd=str(Path(exe).parent))
    return "已開啟 Parabolic"


def open_folder(sub: str | None = None) -> None:
    cfg = load_config()
    path = Path(cfg["download_dir"])
    if sub in PLATFORMS:
        path = path / sub
    path.mkdir(parents=True, exist_ok=True)
    os.startfile(str(path))  # type: ignore[attr-defined]


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
            self.send_json({"config": cfg, "tools": tool_status(cfg)})
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
                self.send_json({"config": cfg, "tools": tool_status(cfg)})
            elif path == "/api/ytdlp":
                self.send_json({"jobs": enqueue(body.get("items") or [])})
            elif path == "/api/parabolic":
                if not valid_url(body.get("url", "")):
                    raise ValueError("網址格式不正確")
                self.send_json({"message": open_parabolic(body["url"])})
            elif path == "/api/open-folder":
                open_folder(body.get("platform"))
                self.send_json({"ok": True})
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
