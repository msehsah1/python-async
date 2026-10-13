"""
tinyio_client.py — many clients in ONE thread, using the same tinyio loop.

The earlier epoll_clients.py needed one OS thread per client. Here every client
is a coroutine wrapped in a Task, and one event loop drives them all, exactly
like an asyncio client would.

Run:  python3 tinyio_client.py                       (3 clients x 2 requests)
      python3 tinyio_client.py --clients 200 --requests 3
      python3 tinyio_client.py --trace               (show loop internals too)
Works against tinyio_server.py and asyncio_server.py.
"""

import argparse
import socket
import time

import tinyio
from tinyio import create_task, gather, log, sock_connect, sock_recv, sock_sendall


async def client(i, n_requests, host, port, t0):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setblocking(False)
    await sock_connect(sock, (host, port))

    pending = {}
    for j in range(1, n_requests + 1):          # send all requests at once
        rid = f"c{i}-r{j}"
        pending[rid] = time.monotonic()
        await sock_sendall(sock, f"{rid}\n".encode())

    results, buf = [], b""
    while pending:
        data = await sock_recv(sock, 4096)      # pauses only this client's task
        if not data:
            log("client", f"client {i}: server closed early")
            break
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            text = line.decode()
            rid = text.split()[0]
            delay = float(text.rsplit(" ", 1)[1].rstrip("s"))
            pending.pop(rid)
            earlier = [r for r in pending if int(r.split("-r")[1]) < int(rid.split("-r")[1])]
            note = f"   <- overtook {', '.join(earlier)}" if earlier else ""
            if not QUIET_REPLIES:
                log("client", f"[{time.monotonic() - t0:5.2f}s] client {i} got: {text}{note}")
            results.append(delay)
    sock.close()
    return results


async def main(args):
    t0 = time.monotonic()
    log("client", f"{args.clients} clients x {args.requests} requests, all in ONE thread")
    tasks = [create_task(client(i, args.requests, args.host, args.port, t0), name=f"client {i}")
             for i in range(1, args.clients + 1)]
    per_client = await gather(*tasks)
    wall = time.monotonic() - t0

    delays = [d for r in per_client for d in r]
    loop = tinyio.get_loop()
    print()
    print(f"{len(delays)} replies in {wall:.2f}s of wall time")
    print(f"  sum of every server delay : {sum(delays):7.2f}s  (if served one by one)")
    print(f"  longest single delay      : {max(delays):7.2f}s  (best possible)")
    print(f"  client side: 1 thread, {loop.stats['epoll_wait']} epoll_wait calls, "
          f"{loop.stats['callbacks']} callbacks run")


QUIET_REPLIES = False

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--clients", type=int, default=3)
    p.add_argument("--requests", type=int, default=2)
    p.add_argument("--trace", action="store_true", help="show loop/task/future internals")
    args = p.parse_args()
    tinyio.TRACE = args.trace
    QUIET_REPLIES = args.clients * args.requests > 60   # keep big runs readable
    tinyio.run(main(args))