# Fetch 10 URLs SYNCHRONOUSLY: one URL at a time, every call waits until it's done.
# Same raw sockets as fetch_10_urls.py, but no epoll, no non-blocking, no state machine.
#
# Usage:
#   python3 sync_fetch_10_urls.py                       # uses the URLS list below (run slow_server.py first)
#   python3 sync_fetch_10_urls.py http://example.com http://neverssl.com ...
import socket
import sys
import time
from urllib.parse import urlsplit

DELAYS = [1.0, 0.3, 0.8, 0.5, 1.2, 0.2, 0.9, 0.4, 0.7, 0.6]
URLS = [f"http://127.0.0.1:8000/delay/{d}?id={i}" for i, d in enumerate(DELAYS)]

T0 = time.monotonic()


def log(msg):
    print(f"[{time.monotonic() - T0:5.2f}s] {msg}")


def fetch(url):
    u = urlsplit(url)
    host, port = u.hostname, u.port or 80
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")

    ip = socket.gethostbyname(host)            # 1. DNS lookup        (waits)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)   # blocking by default

    sock.connect((ip, port))                   # 2. TCP handshake     (waits until connected)
    log(f"fd {sock.fileno()}: connected to {host}:{port}")

    request = (f"GET {path} HTTP/1.1\r\n"
               f"Host: {host}\r\n"
               f"User-Agent: sync-demo\r\n"
               f"Connection: close\r\n\r\n").encode()
    sock.sendall(request)                      # 3. send the request  (waits until all bytes are handed to the kernel)
    log(f"fd {sock.fileno()}: sent GET, now waiting for the response...")

    data = b""
    while True:
        chunk = sock.recv(65536)               # 4. read              (thread SLEEPS here until data arrives)
        if not chunk:                          #    b'' = server closed the connection: response complete
            break
        data += chunk

    sock.close()                               # 5. close; the fd number is free again
    return data


if __name__ == "__main__":
    urls = sys.argv[1:] or URLS
    print(f"--- synchronous: {len(urls)} URLs, one after another ---")
    T0 = time.monotonic()
    for url in urls:
        start = time.monotonic()
        try:
            data = fetch(url)
            status = data.split(b"\r\n", 1)[0].decode(errors="replace")
            log(f"DONE  {status}  ({len(data)} bytes, took {time.monotonic() - start:.2f}s)  {url}")
        except OSError as e:                   # e.g. ConnectionRefusedError, DNS failure
            log(f"FAILED {e!r}  {url}")
    print(f"--- all done in {time.monotonic() - T0:.2f}s ---")