"""
tinyio_server.py — the random-delay server, written in asyncio STYLE on top of
our own tinyio loop. Compare it with asyncio_server.py: the application code
is almost line-for-line the same. Only the import changes.

Protocol: each request is one line ("c3-r1\n"). The server waits a random
delay and replies "c3-r1 done after 2.31s\n". Every request gets its own Task,
so a short request on a connection can finish before a long one.

Run:  python3 tinyio_server.py            (trace on: shows loop internals)
      python3 tinyio_server.py --quiet    (only application messages)
Then: python3 tinyio_client.py
"""

import argparse
import random
import socket

import tinyio
from tinyio import create_task, gather, log, sleep, sock_accept, sock_recv, sock_sendall

ARGS = None
STATS = {"clients": 0, "requests": 0, "in_flight": 0, "max_in_flight": 0}


async def handle_request(conn, cid, request):
    delay = random.uniform(ARGS.min, ARGS.max)
    STATS["requests"] += 1
    STATS["in_flight"] += 1
    STATS["max_in_flight"] = max(STATS["max_in_flight"], STATS["in_flight"])
    log("app", f"client {cid}: got {request:<7} -> reply in {delay:.2f}s "
               f"(in flight: {STATS['in_flight']})")

    await sleep(delay)          # looks like blocking code; really a timer + Future

    await sock_sendall(conn, f"{request} done after {delay:.2f}s\n".encode())
    STATS["in_flight"] -= 1
    log("app", f"client {cid}: reply  {request:<7} sent "
               f"(in flight: {STATS['in_flight']})")


async def handle_client(conn, addr, cid):
    log("app", f"client {cid}: connected from port {addr[1]} (fd {conn.fileno()})")
    buf, pending = b"", []
    try:
        while True:
            data = await sock_recv(conn, 4096)      # pauses only THIS task
            if not data:                            # b"" = client finished sending
                break
            buf += data
            while b"\n" in buf:                     # one line = one request
                line, buf = buf.split(b"\n", 1)
                request = line.decode(errors="replace").strip()
                if request:
                    # Don't await here: start the request and keep reading.
                    pending.append(create_task(handle_request(conn, cid, request),
                                               name=f"req {request}"))
        await gather(*pending)                      # finish replies before closing
    except OSError as exc:
        log("app", f"client {cid}: connection error {exc}")
    finally:
        conn.close()
        log("app", f"client {cid}: closed")


async def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((ARGS.host, ARGS.port))
    server.listen(1024)
    server.setblocking(False)
    log("app", f"tinyio server on {ARGS.host}:{ARGS.port} (listener fd {server.fileno()}), "
               f"delay {ARGS.min}–{ARGS.max}s, single thread")

    while True:
        conn, addr = await sock_accept(server)     # pauses main until a client comes
        STATS["clients"] += 1
        create_task(handle_client(conn, addr, STATS["clients"]),
                    name=f"client {STATS['clients']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--min", type=float, default=0.5)
    p.add_argument("--max", type=float, default=3.0)
    p.add_argument("--quiet", action="store_true", help="hide loop/task/future trace")
    ARGS = p.parse_args()
    tinyio.TRACE = not ARGS.quiet
    try:
        tinyio.run(main())
    except KeyboardInterrupt:
        loop = tinyio.get_loop()
        print()
        log("app", f"stopped. clients: {STATS['clients']}, requests: {STATS['requests']}, "
                   f"most in flight: {STATS['max_in_flight']}, "
                   f"epoll_wait calls: {loop.stats['epoll_wait']}, "
                   f"callbacks run: {loop.stats['callbacks']}")