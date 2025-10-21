import os
import socket
import sys
import mimetypes
import threading
import time
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor


def build_http_response(status_code: int, reason: str, headers: dict, body: bytes) -> bytes:
    lines = [f"HTTP/1.1 {status_code} {reason}\r\n"]
    for key, value in headers.items():
        lines.append(f"{key}: {value}\r\n")
    lines.append("\r\n")
    header_bytes = "".join(lines).encode("iso-8859-1")
    return header_bytes + body


def http_date(ts: float | None = None) -> str:
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
    if directory != root:
        parent_path = os.path.normpath(os.path.join(request_path, ".."))
        entries.append(f'<li><a href="{parent_path if parent_path.endswith("/") else parent_path + "/"}">..</a></li>')
    
    for entry in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        name = entry.name + ("/" if entry.is_dir() else "")
        href = request_path.rstrip("/") + "/" + entry.name
        
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


def handle_request_naive(conn: socket.socket, client_addr, root_dir: Path, counters: dict, simulate_work: bool = False):
    """Handle request with naive counter (race condition)"""
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

        if simulate_work:
            time.sleep(1.0)

        if fs_target.is_dir():
            index_file = fs_target / "index.html"
            if index_file.exists():
                fs_target = index_file
            else:
                if not is_safe_path(root_dir, fs_target):
                    response = build_http_response(403, "Forbidden", {"Date": http_date(), "Connection": "close"}, b"")
                    conn.sendall(response)
                    return
                
                # NAIVE COUNTER UPDATE (RACE CONDITION)
                dir_path = str(fs_target.relative_to(root_dir))
                # Add VERY aggressive delays to force thread interlacing and make race condition visible
                print(f"Thread {threading.current_thread().name}: Reading counter for directory {dir_path}")
                time.sleep(0.5)  # Longer delay before reading
                current_count = counters.get(dir_path, 0)
                print(f"Thread {threading.current_thread().name}: Read count {current_count} for {dir_path}")
                time.sleep(0.5)  # Longer delay before incrementing
                new_count = current_count + 1
                print(f"Thread {threading.current_thread().name}: Calculated new count {new_count} for {dir_path}")
                time.sleep(0.5)  # Longer delay before writing
                counters[dir_path] = new_count
                print(f"Thread {threading.current_thread().name}: Wrote count {new_count} for {dir_path}")
                
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

        # NAIVE COUNTER UPDATE (RACE CONDITION)
        file_path = str(fs_target.relative_to(root_dir))
        # Add VERY aggressive delays to force thread interlacing and make race condition visible
        print(f"Thread {threading.current_thread().name}: Reading counter for {file_path}")
        time.sleep(0.5)  # Longer delay before reading
        current_count = counters.get(file_path, 0)
        print(f"Thread {threading.current_thread().name}: Read count {current_count} for {file_path}")
        time.sleep(0.5)  # Longer delay before incrementing
        new_count = current_count + 1
        print(f"Thread {threading.current_thread().name}: Calculated new count {new_count} for {file_path}")
        time.sleep(0.5)  # Longer delay before writing
        counters[file_path] = new_count
        print(f"Thread {threading.current_thread().name}: Wrote count {new_count} for {file_path}")

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


def run_server_naive(root: str, port: int, max_threads: int = 10, simulate_work: bool = False):
    """Run server with naive counter (demonstrates race condition)"""
    root_dir = Path(root)
    root_dir.mkdir(parents=True, exist_ok=True)
    
    # Shared counter WITHOUT lock (race condition)
    counters = {}
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        s.listen(5)
        print(f"Serving {root_dir} on 0.0.0.0:{port} (NAIVE COUNTER - RACE CONDITION)")
        if simulate_work:
            print("Simulating 1s work per request")
        
        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            while True:
                conn, addr = s.accept()
                executor.submit(handle_request_naive, conn, addr, root_dir, counters, simulate_work)


def main():
    if len(sys.argv) < 2:
        print("Usage: python server_race_demo.py <content_dir> [port] [max_threads] [--simulate-work]", file=sys.stderr)
        sys.exit(1)
    
    content_dir = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    max_threads = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != "--simulate-work" else 10
    simulate_work = "--simulate-work" in sys.argv
    
    run_server_naive(content_dir, port, max_threads, simulate_work)


if __name__ == "__main__":
    mimetypes.init()
    mimetypes.add_type("text/html", ".html")
    mimetypes.add_type("image/png", ".png")
    mimetypes.add_type("application/pdf", ".pdf")
    main()
