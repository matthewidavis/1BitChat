"""
BitNet Chat Server - manages llama-server, serves the chat UI, and
optionally exposes an OpenAI-compatible API on the LAN with per-NIC
allow-list and optional Bearer-token auth.
"""
import http.server
import ipaddress
import json
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import psutil

UI_HOST = "127.0.0.1"
UI_PORT = 3000
LLAMA_HOST = "127.0.0.1"
LLAMA_PORT = 8080

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
    UI_DIR = Path(sys._MEIPASS) / "chat-ui"
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    UI_DIR = Path(__file__).resolve().parent

SETTINGS_PATH = BASE_DIR / "1bitchat_settings.json"

MODELS = {
    "bitnet-2b": {
        "path": "models/BitNet-b1.58-2B-4T/ggml-model-i2_s.gguf",
        "template": "llama3",
        "context": 4096,
        "label": "BitNet b1.58-2B-4T",
        "params": "2.4B",
        "url": "https://huggingface.co/microsoft/BitNet-b1.58-2B-4T-gguf/resolve/main/ggml-model-i2_s.gguf",
    },
    "falcon-10b": {
        "path": "models/Falcon3-10B-Instruct-1.58bit/ggml-model-i2_s.gguf",
        "template": None,
        "context": 32768,
        "label": "Falcon3-10B-Instruct-1.58bit",
        "params": "10B",
        "url": "https://huggingface.co/tiiuae/Falcon3-10B-Instruct-1.58bit-GGUF/resolve/main/ggml-model-i2_s.gguf",
    },
}

DEFAULT_SETTINGS = {
    "api_enabled": False,
    "api_port": 8080,
    "api_key": "",
    "allowed_ips": [],
    "default_model": "bitnet-2b",
}

llama_proc = None
current_model = None
server_ready = False
settings = dict(DEFAULT_SETTINGS)
proxy = None  # ApiProxy instance or None

# Per-model download state: {status: idle|downloading|done|error|canceled,
#                            done: bytes, total: bytes, error: str|None}
download_state = {mid: {"status": "idle", "done": 0, "total": 0, "error": None} for mid in MODELS}
download_cancels = {mid: threading.Event() for mid in MODELS}
download_threads = {}


# --- Settings persistence ---

def load_settings():
    global settings
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH) as f:
                loaded = json.load(f)
            settings = {**DEFAULT_SETTINGS, **loaded}
        except Exception:
            settings = dict(DEFAULT_SETTINGS)
    else:
        settings = dict(DEFAULT_SETTINGS)


def save_settings():
    try:
        with open(SETTINGS_PATH, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"Failed to save settings: {e}")


# --- Model downloads ---

def download_model(model_id):
    if model_id not in MODELS:
        return
    url = MODELS[model_id].get("url")
    if not url:
        download_state[model_id] = {"status": "error", "done": 0, "total": 0, "error": "No download URL"}
        return

    target = BASE_DIR / MODELS[model_id]["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")

    cancel = download_cancels[model_id]
    cancel.clear()
    download_state[model_id] = {"status": "downloading", "done": 0, "total": 0, "error": None}

    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "1BitChat/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            download_state[model_id]["total"] = total
            done = 0
            with open(partial, "wb") as f:
                while True:
                    if cancel.is_set():
                        download_state[model_id]["status"] = "canceled"
                        try: partial.unlink(missing_ok=True)
                        except Exception: pass
                        return
                    chunk = resp.read(1 << 20)  # 1 MB
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    download_state[model_id]["done"] = done
        partial.replace(target)
        download_state[model_id]["status"] = "done"
    except Exception as e:
        download_state[model_id]["status"] = "error"
        download_state[model_id]["error"] = str(e)
        try: partial.unlink(missing_ok=True)
        except Exception: pass


def start_download(model_id):
    if model_id not in MODELS:
        return False, "Unknown model"
    t = download_threads.get(model_id)
    if t and t.is_alive():
        return False, "Already downloading"
    if (BASE_DIR / MODELS[model_id]["path"]).exists():
        download_state[model_id]["status"] = "done"
        return False, "Already installed"
    t = threading.Thread(target=download_model, args=(model_id,), daemon=True)
    download_threads[model_id] = t
    t.start()
    return True, "ok"


def cancel_download(model_id):
    if model_id in download_cancels:
        download_cancels[model_id].set()


# --- NIC enumeration ---

def list_nics():
    """Return IPv4 NICs (including loopback and link-local) with friendly names."""
    out = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        for a in addrs:
            if a.family != socket.AF_INET:
                continue
            ip = a.address
            try:
                ip_obj = ipaddress.IPv4Address(ip)
            except ValueError:
                continue
            is_up = stats.get(name).isup if name in stats else True
            out.append({
                "nic": name,
                "ip": ip,
                "loopback": ip_obj.is_loopback,
                "link_local": ip_obj.is_link_local,
                "up": is_up,
            })
    return out


def primary_lan_ip():
    """Best guess at a routable LAN IP (for display in UI)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


# --- llama-server subprocess ---

def find_llama_server():
    for c in [
        BASE_DIR / "build" / "bin" / "llama-server.exe",
        BASE_DIR / "build" / "bin" / "Release" / "llama-server.exe",
        BASE_DIR / "build" / "bin" / "llama-server",
    ]:
        if c.exists():
            return str(c)
    return None


def stop_llama():
    global llama_proc, server_ready, current_model
    server_ready = False
    if llama_proc and llama_proc.poll() is None:
        llama_proc.terminate()
        try:
            llama_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            llama_proc.kill()
    llama_proc = None
    current_model = None


def start_llama(model_id):
    global llama_proc, current_model, server_ready

    if model_id not in MODELS:
        return False, f"Unknown model: {model_id}"

    model = MODELS[model_id]
    model_path = BASE_DIR / model["path"]
    if not model_path.exists():
        return False, f"Model file not found: {model_path}"

    exe = find_llama_server()
    if not exe:
        return False, "llama-server executable not found"

    stop_llama()
    time.sleep(1)

    cmd = [
        exe,
        "-m", str(model_path),
        "-t", "4",
        "-c", str(model["context"]),
        "--host", LLAMA_HOST,
        "--port", str(LLAMA_PORT),
        "-b", "1",
        "-ngl", "0",
    ]
    if model.get("template"):
        cmd.extend(["--chat-template", model["template"]])

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW

    llama_proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    current_model = model_id

    import urllib.request
    for _ in range(60):
        time.sleep(1)
        if llama_proc.poll() is not None:
            return False, "llama-server exited unexpectedly"
        try:
            req = urllib.request.urlopen(f"http://{LLAMA_HOST}:{LLAMA_PORT}/health", timeout=2)
            if json.loads(req.read()).get("status") == "ok":
                server_ready = True
                return True, "ok"
        except Exception:
            pass
    return False, "Timed out waiting for llama-server"


# --- LAN proxy (NIC filter + optional bearer auth) ---

class ApiProxy:
    """Raw-socket HTTP/SSE proxy to llama-server with NIC allow-list + bearer auth."""

    def __init__(self, port, allowed_ips, api_key):
        self.port = port
        self.allowed_ips = set(allowed_ips)
        self.api_key = api_key
        self.sock = None
        self.thread = None
        self.stopping = False

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", self.port))
        self.sock.listen(64)
        self.thread = threading.Thread(target=self._accept_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping = True
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass

    def _accept_loop(self):
        while not self.stopping:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            local_ip = conn.getsockname()[0]
            if local_ip not in self.allowed_ips:
                self._reject(conn, 403, "NIC not permitted")
                continue
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _reject(self, conn, code, msg):
        try:
            body = json.dumps({"error": msg}).encode()
            conn.sendall(
                f"HTTP/1.1 {code} {msg}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body
            )
        except Exception:
            pass
        finally:
            try: conn.close()
            except Exception: pass

    def _handle(self, conn):
        try:
            # Read headers
            conn.settimeout(15)
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = conn.recv(4096)
                if not chunk:
                    conn.close(); return
                buf += chunk
                if len(buf) > 64 * 1024:
                    self._reject(conn, 431, "Headers too large"); return

            head, _, rest = buf.partition(b"\r\n\r\n")
            header_text = head.decode("iso-8859-1", errors="replace")

            # Bearer check
            if self.api_key:
                auth_ok = False
                for line in header_text.split("\r\n")[1:]:
                    k, _, v = line.partition(":")
                    if k.strip().lower() == "authorization":
                        token = v.strip()
                        if token.lower().startswith("bearer "):
                            token = token[7:].strip()
                        if secrets.compare_digest(token, self.api_key):
                            auth_ok = True
                        break
                if not auth_ok:
                    self._reject(conn, 401, "Unauthorized"); return

            # Connect upstream
            up = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            up.settimeout(15)
            try:
                up.connect((LLAMA_HOST, LLAMA_PORT))
            except Exception:
                self._reject(conn, 502, "Upstream unavailable"); return
            up.settimeout(None)
            conn.settimeout(None)

            # Forward what we already read
            up.sendall(head + b"\r\n\r\n" + rest)

            # Bidirectional splice
            stop = threading.Event()

            def pipe(src, dst):
                try:
                    while not stop.is_set():
                        data = src.recv(8192)
                        if not data:
                            break
                        dst.sendall(data)
                except Exception:
                    pass
                finally:
                    stop.set()
                    try: dst.shutdown(socket.SHUT_WR)
                    except Exception: pass

            t1 = threading.Thread(target=pipe, args=(conn, up), daemon=True)
            t2 = threading.Thread(target=pipe, args=(up, conn), daemon=True)
            t1.start(); t2.start()
            t1.join(); t2.join()
        except Exception:
            pass
        finally:
            try: conn.close()
            except Exception: pass


def apply_api_settings():
    """(Re)start or stop the LAN proxy according to current settings."""
    global proxy
    if proxy:
        proxy.stop()
        proxy = None
    if settings.get("api_enabled") and settings.get("allowed_ips"):
        try:
            p = ApiProxy(
                port=int(settings["api_port"]),
                allowed_ips=settings["allowed_ips"],
                api_key=settings.get("api_key", "") or "",
            )
            p.start()
            proxy = p
            print(f"API proxy listening on :{settings['api_port']} (allowed: {settings['allowed_ips']})")
        except Exception as e:
            print(f"Failed to start API proxy: {e}")


# --- UI HTTP server (localhost only) ---

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/models":
            available = {}
            for mid, m in MODELS.items():
                available[mid] = {
                    "label": m["label"],
                    "params": m["params"],
                    "context": m["context"],
                    "ready": (BASE_DIR / m["path"]).exists(),
                    "active": mid == current_model,
                    "download": download_state[mid],
                    "downloadable": bool(m.get("url")),
                    "manual_note": m.get("manual_note"),
                }
            self.send_json({"models": available, "current": current_model, "server_ready": server_ready})
            return

        if parsed.path == "/api/status":
            self.send_json({"current": current_model, "server_ready": server_ready})
            return

        if parsed.path == "/api/settings":
            self.send_json({
                "settings": settings,
                "nics": list_nics(),
                "lan_ip": primary_lan_ip(),
                "proxy_active": proxy is not None,
            })
            return

        if parsed.path == "/favicon.ico":
            self.send_response(204); self.end_headers(); return

        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if parsed.path == "/api/switch":
            model_id = body.get("model")
            if not model_id:
                self.send_json({"error": "Missing 'model' field"}, 400); return
            if model_id == current_model and server_ready:
                self.send_json({"status": "already_active"}); return
            self.send_json({"status": "switching", "model": model_id})
            settings["default_model"] = model_id
            save_settings()
            threading.Thread(target=start_llama, args=(model_id,), daemon=True).start()
            return

        if parsed.path == "/api/settings":
            updated = False
            for key in ("api_enabled", "api_port", "api_key", "allowed_ips"):
                if key in body:
                    settings[key] = body[key]
                    updated = True
            if updated:
                try:
                    settings["api_port"] = int(settings["api_port"])
                except Exception:
                    settings["api_port"] = 8080
                save_settings()
                apply_api_settings()
            self.send_json({"ok": True, "settings": settings, "proxy_active": proxy is not None})
            return

        if parsed.path == "/api/generate_key":
            settings["api_key"] = secrets.token_urlsafe(24)
            save_settings()
            if proxy:
                apply_api_settings()
            self.send_json({"api_key": settings["api_key"]})
            return

        if parsed.path == "/api/download":
            mid = body.get("model")
            ok, msg = start_download(mid)
            self.send_json({"ok": ok, "message": msg, "state": download_state.get(mid)}, 200 if ok else 400)
            return

        if parsed.path == "/api/download_cancel":
            cancel_download(body.get("model"))
            self.send_json({"ok": True})
            return

        if parsed.path == "/api/stop":
            stop_llama()
            self.send_json({"status": "stopped"})
            return

        self.send_error(404)

    def send_json(self, data, code=200):
        payload = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def log_message(self, format, *args):
        first = str(args[0]) if args else ""
        if "/api/" in first:
            return
        super().log_message(format, *args)


def main():
    load_settings()
    default_model = settings.get("default_model") or "bitnet-2b"
    threading.Thread(target=start_llama, args=(default_model,), daemon=True).start()
    apply_api_settings()

    server = http.server.HTTPServer((UI_HOST, UI_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def cleanup():
        if proxy:
            proxy.stop()
        stop_llama()
        server.shutdown()

    try:
        import webview
        window = webview.create_window(
            "1BitChat",
            f"http://{UI_HOST}:{UI_PORT}",
            width=1100, height=800,
            min_size=(600, 500),
        )
        window.events.closed += cleanup
        webview.start()
    except ImportError:
        print(f"Browser mode: open http://{UI_HOST}:{UI_PORT}")
        signal.signal(signal.SIGINT, lambda s, f: (cleanup(), sys.exit(0)))
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            cleanup()


if __name__ == "__main__":
    main()
