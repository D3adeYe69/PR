import os
import socket
import sys
import mimetypes
import threading
import time
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json


def build_http_response(status_code: int, reason: str, headers: dict, body: bytes) -> bytes:
    lines = [f"HTTP/1.1 {status_code} {reason}\r\n"]
    for key, value in headers.items():
        lines.append(f"{key}: {value}\r\n")
    lines.append("\r\n")
    header_bytes = "".join(lines).encode("iso-8859-1")
    return header_bytes + body


def http_date(ts: float | None = None) -> str:
    # RFC 7231 format
    import email.utils
    return email.utils.formatdate(ts, usegmt=True)


def is_safe_path(base: Path, target: Path) -> bool:
    try:
        base_resolved = base.resolve()
        target_resolved = target.resolve()
        return str(target_resolved).startswith(str(base_resolved))
    except Exception:
        return False


def generate_directory_listing(root: Path, directory: Path, request_path: str, counters: dict) -> bytes:
    entries = []
    # Add parent link if not at root
    if directory != root:
        parent_path = os.path.normpath(os.path.join(request_path, ".."))
        entries.append(f'<li><a href="{parent_path if parent_path.endswith("/") else parent_path + "/"}">..</a></li>')
    
    for entry in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        name = entry.name + ("/" if entry.is_dir() else "")
        href = request_path.rstrip("/") + "/" + entry.name
        
        # Add counter display for files
        counter_text = ""
        if entry.is_file():
            file_path = str(entry.relative_to(root))
            count = counters.get(file_path, 0)
            counter_text = f" <span style='color: #666; font-size: 0.9em'>({count} requests)</span>"
        
        entries.append(f'<li><a href="{href}">{name}</a>{counter_text}</li>')
    
    body = f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Index of {request_path}</title>
    <style>body{{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:800px;margin:2rem auto;padding:0 1rem}} li{{margin:0.25rem 0}}</style>
  </head>
  <body>
    <h1>Index of {request_path}</h1>
    <ul>
      {''.join(entries)}
    </ul>
  </body>
</html>
""".encode("utf-8")
    return body


def guess_content_type(path: Path) -> str | None:
    ctype, _ = mimetypes.guess_type(str(path))
    return ctype


class RateLimiter:
    def __init__(self, max_requests: int = 5, window_seconds: int = 1):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.clients = defaultdict(list)  # IP -> list of timestamps
        self.lock = threading.Lock()
    
    def is_allowed(self, client_ip: str) -> bool:
        with self.lock:
            now = time.time()
            # Clean old requests outside the window
            self.clients[client_ip] = [
                timestamp for timestamp in self.clients[client_ip]
                if now - timestamp < self.window_seconds
            ]
            
            # Check if under limit
            if len(self.clients[client_ip]) < self.max_requests:
                self.clients[client_ip].append(now)
                return True
            return False


def handle_request(conn: socket.socket, client_addr, root_dir: Path, counters: dict, counters_lock: threading.Lock, rate_limiter: RateLimiter, simulate_work: bool = False):
    client_ip = client_addr[0]
    
    try:
        conn.settimeout(5.0)
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 65536:
            try:
                chunk = conn.recv(4096)
            except (socket.timeout, TimeoutError):
                return
            if not chunk:
                break
            data += chunk
        if not data:
            return
        
        # Check rate limiting
        if not rate_limiter.is_allowed(client_ip):
            response = build_http_response(429, "Too Many Requests", {
                "Date": http_date(),
                "Connection": "close",
                "Content-Type": "text/plain; charset=utf-8",
            }, b"Rate limit exceeded. Try again later.")
            conn.sendall(response)
            return
        
        try:
            header = data.split(b"\r\n\r\n", 1)[0].decode("iso-8859-1", errors="replace")
        except Exception:
            header = ""
        lines = header.split("\r\n")
        if not lines:
            return
        request_line = lines[0]
        parts = request_line.split()
        if len(parts) < 3:
            response = build_http_response(400, "Bad Request", {"Date": http_date(), "Connection": "close"}, b"Bad Request")
            conn.sendall(response)
            return
        method, raw_path, _ = parts
        if method != "GET":
            response = build_http_response(405, "Method Not Allowed", {
                "Date": http_date(),
                "Connection": "close",
                "Allow": "GET",
                "Content-Type": "text/plain; charset=utf-8",
            }, b"Method Not Allowed")
            conn.sendall(response)
            return

        # Normalize path
        path = raw_path.split("?", 1)[0]
        if path.startswith("http://") or path.startswith("https://"):
            try:
                from urllib.parse import urlparse
                path = urlparse(path).path
            except Exception:
                path = "/"
        if not path.startswith("/"):
            path = "/" + path
        fs_target = (root_dir / path.lstrip("/"))

        # Simulate work if requested
        if simulate_work:
            time.sleep(1.0)

        # If directory, try to serve index.html; otherwise generate listing
        if fs_target.is_dir():
            index_file = fs_target / "index.html"
            if index_file.exists():
                fs_target = index_file
            else:
                if not is_safe_path(root_dir, fs_target):
                    response = build_http_response(403, "Forbidden", {"Date": http_date(), "Connection": "close"}, b"")
                    conn.sendall(response)
                    return
                
                # Update counter for directory listing
                dir_path = str(fs_target.relative_to(root_dir))
                with counters_lock:
                    counters[dir_path] = counters.get(dir_path, 0) + 1
                
                body = generate_directory_listing(root_dir, fs_target, path if path.endswith("/") else path + "/", counters)
                headers = {
                    "Date": http_date(),
                    "Content-Type": "text/html; charset=utf-8",
                    "Content-Length": str(len(body)),
                    "Connection": "close",
                }
                response = build_http_response(200, "OK", headers, body)
                conn.sendall(response)
                return

        # Resolve and validate
        if not is_safe_path(root_dir, fs_target):
            response = build_http_response(403, "Forbidden", {"Date": http_date(), "Connection": "close"}, b"")
            conn.sendall(response)
            return

        if not fs_target.exists() or not fs_target.is_file():
            body = b"404 Not Found"
            headers = {
                "Date": http_date(),
                "Content-Type": "text/plain; charset=utf-8",
                "Content-Length": str(len(body)),
                "Connection": "close",
            }
            response = build_http_response(404, "Not Found", headers, body)
            conn.sendall(response)
            return

        ctype = guess_content_type(fs_target)
        if ctype is None or not any(ctype.startswith(p) for p in ["text/html", "image/png", "application/pdf"]):
            body = b"404 Not Found"
            headers = {
                "Date": http_date(),
                "Content-Type": "text/plain; charset=utf-8",
                "Content-Length": str(len(body)),
                "Connection": "close",
            }
            response = build_http_response(404, "Not Found", headers, body)
            conn.sendall(response)
            return

        # Update counter for file access
        file_path = str(fs_target.relative_to(root_dir))
        with counters_lock:
            counters[file_path] = counters.get(file_path, 0) + 1

        with open(fs_target, "rb") as f:
            body = f.read()
        headers = {
            "Date": http_date(),
            "Content-Type": f"{ctype}; charset=utf-8" if ctype.startswith("text/") else ctype,
            "Content-Length": str(len(body)),
            "Connection": "close",
        }
        response = build_http_response(200, "OK", headers, body)
        conn.sendall(response)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run_server(root: str, port: int, max_threads: int = 10, simulate_work: bool = False):
    root_dir = Path(root)
    root_dir.mkdir(parents=True, exist_ok=True)
    
    # Shared data structures
    counters = {}
    counters_lock = threading.Lock()
    rate_limiter = RateLimiter(max_requests=5, window_seconds=1)
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        s.listen(5)
        print(f"Serving {root_dir} on 0.0.0.0:{port} (multithreaded, max {max_threads} threads)")
        if simulate_work:
            print("Simulating 1s work per request")
        
        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            while True:
                conn, addr = s.accept()
                executor.submit(
                    handle_request, 
                    conn, 
                    addr, 
                    root_dir, 
                    counters, 
                    counters_lock, 
                    rate_limiter,
                    simulate_work
                )


def main():
    if len(sys.argv) < 2:
        print("Usage: python server_lab2.py <content_dir> [port] [max_threads] [--simulate-work]", file=sys.stderr)
        sys.exit(1)
    
    content_dir = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    max_threads = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != "--simulate-work" else 10
    simulate_work = "--simulate-work" in sys.argv
    
    run_server(content_dir, port, max_threads, simulate_work)


if __name__ == "__main__":
    mimetypes.init()
    # Ensure common types
    mimetypes.add_type("text/html", ".html")
    mimetypes.add_type("image/png", ".png")
    mimetypes.add_type("application/pdf", ".pdf")
    main()
