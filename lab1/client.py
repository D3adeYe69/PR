import os
import socket
import sys
from pathlib import Path


def recv_all(sock: socket.socket, timeout: float = 3.0) -> bytes:
    sock.settimeout(timeout)
    chunks: list[bytes] = []
    while True:
        try:
            data = sock.recv(4096)
        except TimeoutError:
            break
        except Exception:
            break
        if not data:
            break
        chunks.append(data)
    return b"".join(chunks)


def parse_response(raw: bytes):
    try:
        header_raw, body = raw.split(b"\r\n\r\n", 1)
    except ValueError:
        return (0, {}, raw)
    header_text = header_raw.decode("iso-8859-1", errors="replace")
    lines = header_text.split("\r\n")
    status_line = lines[0] if lines else ""
    parts = status_line.split()
    status = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return (status, headers, body)


def main():
    if len(sys.argv) != 5:
        print("Usage: python client.py server_host server_port url_path directory", file=sys.stderr)
        sys.exit(1)
    host = sys.argv[1]
    port = int(sys.argv[2])
    path = sys.argv[3]
    outdir = Path(sys.argv[4])
    if not path.startswith("/"):
        path = "/" + path

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((host, port))
        request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode("iso-8859-1")
        sock.sendall(request)
        raw = recv_all(sock, timeout=5.0)

    status, headers, body = parse_response(raw)
    ctype = headers.get("content-type", "")
    if status != 200:
        print(body.decode("utf-8", errors="replace"))
        sys.exit(1)

    if ctype.startswith("text/html"):
        print(body.decode("utf-8", errors="replace"))
    elif ctype.startswith("image/png"):
        outdir.mkdir(parents=True, exist_ok=True)
        filename = Path(path).name or "image.png"
        target = outdir / (filename if filename.lower().endswith(".png") else filename + ".png")
        with open(target, "wb") as f:
            f.write(body)
        print(str(target))
    elif ctype.startswith("application/pdf"):
        outdir.mkdir(parents=True, exist_ok=True)
        filename = Path(path).name or "file.pdf"
        target = outdir / (filename if filename.lower().endswith(".pdf") else filename + ".pdf")
        with open(target, "wb") as f:
            f.write(body)
        print(str(target))
    else:
        # Unknown content type -> print status line
        print(f"Unsupported content-type: {ctype}")


if __name__ == "__main__":
    main()


