# Fetch 10 URLs at the same time with raw epoll: one thread, no asyncio, no threads.
#
# Same idea as the socketpair example, but each "socket a" is now a TCP connection
# to a web server, and each one goes through 3 states:
#
#   CONNECTING --(EPOLLOUT: writable = connected)--> send the HTTP request
#   READING    --(EPOLLIN:  readable = data came)--> recv() a chunk
#   DONE       --(recv returned b'' = server closed)--> unregister + close
#
# Usage:
#   python3 fetch_10_urls.py                      # uses the URLS list below
#   python3 fetch_10_urls.py http://example.com http://neverssl.com ...
#   python3 fetch_10_urls.py --compare            # also time the one-by-one blocking version
#
# Only plain http:// is supported (HTTPS needs a TLS handshake step on top of this).
import errno
import select
import socket
import sys
import time
from urllib.parse import urlsplit

# Default: the local test server (run slow_server.py first). Each URL makes the
# server wait a different amount of time before answering.
DELAYS = [1.0, 0.3, 0.8, 0.5, 1.2, 0.2, 0.9, 0.4, 0.7, 0.6]
URLS = [f"http://127.0.0.1:8000/delay/{d}?id={i}" for i, d in enumerate(DELAYS)]

# Real websites over plain HTTP (many will answer "301 Moved" to https, which is still a
# complete, successful HTTP exchange):
# URLS = ["http://example.com", "http://neverssl.com", "http://info.cern.ch", ...]

T0 = time.monotonic()


def log(msg):
    print(f"[{time.monotonic() - T0:5.2f}s] {msg}")


def parse(url):
    u = urlsplit(url)
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    return u.hostname, u.port or 80, path


def start_connection(url):
    """Create a non-blocking TCP socket and START connecting (returns immediately)."""
    host, port, path = parse(url)
    ip = socket.gethostbyname(host)        # DNS lookup: blocking, but quick (resolve before the loop)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setblocking(False)                # like a.setblocking(False) in the socketpair example
    rc = sock.connect_ex((ip, port))       # non-blocking connect: doesn't wait for the handshake
    log(f"fd {sock.fileno()}: connect to {host}:{port} started -> {errno.errorcode.get(rc, 'OK (0)')}")
    request = (f"GET {path} HTTP/1.1\r\n"
               f"Host: {host}\r\n"
               f"User-Agent: epoll-demo\r\n"
               f"Connection: close\r\n\r\n").encode()   # 'close' = server ends the connection when done
    return sock, request


def fetch_all_with_epoll(urls):
    ep = select.epoll()                    # 1. create the epoll instance (once)
    conns = {}                             # fd -> everything we know about that connection

    for url in urls:
        sock, request = start_connection(url)
        # 2. register: "wake me when this socket is WRITABLE" = the TCP connection is ready
        ep.register(sock.fileno(), select.EPOLLOUT)
        conns[sock.fileno()] = {"url": url, "sock": sock, "request": request,
                                "state": "CONNECTING", "data": b""}

    wakeups = 0
    while conns:                           # loop until every connection is finished
        events = ep.poll(10.0)             # 3. sleep until at least one socket has news
        wakeups += 1
        if not events:
            for c in conns.values():
                log(f"TIMEOUT {c['url']}")
            break

        for fd, ev in events:
            c = conns[fd]
            sock = c["sock"]

            if c["state"] == "CONNECTING":
                # Writable (or error) means the connect attempt finished. Did it succeed?
                err = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if err:
                    log(f"fd {fd}: connect FAILED: {errno.errorcode.get(err, err)}  {c['url']}")
                    ep.unregister(fd); sock.close(); del conns[fd]
                    continue
                sock.send(c["request"])    # small request: fits in the kernel send buffer at once
                ep.modify(fd, select.EPOLLIN)   # now: "wake me when the response arrives"
                c["state"] = "READING"
                log(f"fd {fd}: connected, sent GET, now waiting for the response")

            elif c["state"] == "READING":
                try:
                    chunk = sock.recv(65536)   # never blocks: epoll said there is something to read
                except ConnectionError as e:
                    log(f"fd {fd}: connection error {e!r}")
                    chunk = b""
                if chunk:
                    c["data"] += chunk         # a response can arrive in several pieces
                else:                          # b'' = the server closed the connection: response complete
                    status = c["data"].split(b"\r\n", 1)[0].decode(errors="replace")
                    log(f"fd {fd}: DONE  {status}  ({len(c['data'])} bytes)  {c['url']}")
                    ep.unregister(fd)
                    sock.close()
                    del conns[fd]

    ep.close()
    return wakeups


def fetch_one_blocking(url):
    """The old way, for comparison: one URL at a time, each call waits."""
    host, port, path = parse(url)
    with socket.create_connection((host, port)) as s:   # blocking connect
        s.sendall(f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
        data = b""
        while chunk := s.recv(65536):                     # blocking recv
            data += chunk
    return data


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    urls = args or URLS

    print(f"--- epoll: {len(urls)} URLs at once, one thread ---")
    T0 = time.monotonic()
    wakeups = fetch_all_with_epoll(urls)
    total = time.monotonic() - T0
    print(f"--- all done in {total:.2f}s, epoll woke the thread {wakeups} times ---")

    if "--compare" in sys.argv:
        print("\n--- blocking: one URL after another ---")
        t = time.monotonic()
        for url in urls:
            status = fetch_one_blocking(url).split(b"\r\n", 1)[0].decode()
            print(f"[{time.monotonic() - t:5.2f}s] {status}  {url}")
        print(f"--- blocking version took {time.monotonic() - t:.2f}s vs {total:.2f}s with epoll ---")