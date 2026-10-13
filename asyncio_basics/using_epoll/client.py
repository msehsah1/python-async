"""
epoll_clients.py — fire many clients at epoll_server.py at the same moment.

Each client connects, sends all its requests at once ("c3-r1", "c3-r2", ...),
then waits for the replies. Every reply says how long the server delayed it.

What to look for in the output:
  * Wall time ≈ the LONGEST single delay, not the SUM of all delays.
    The server is one thread, yet it waits on all requests at the same time.
  * "overtook" markers: a later request answered before an earlier one from the
    same client, because its random delay was shorter. Replies come back in
    the order they finish, not the order they were sent.

Run:  python3 epoll_clients.py
      python3 epoll_clients.py --clients 50 --requests 3
"""

import argparse
import socket
import threading
import time


def run_client(i, n_requests, host, port, barrier, t0, results, lock):
    sock = socket.create_connection((host, port))
    barrier.wait()                                  # everyone starts together

    pending = {}                                    # request id -> send time
    for j in range(1, n_requests + 1):
        rid = f"c{i}-r{j}"
        pending[rid] = time.monotonic()
        sock.sendall(f"{rid}\n".encode())

    buf = b""
    while pending:
        data = sock.recv(4096)
        if not data:
            with lock:
                print(f"client {i}: server closed the connection early")
            break
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            text = line.decode()
            rid = text.split()[0]
            server_delay = float(text.rsplit(" ", 1)[1].rstrip("s"))
            sent_at = pending.pop(rid)
            now = time.monotonic()
            # Did an earlier request from this client get overtaken?
            earlier = [r for r in pending if int(r.split("-r")[1]) < int(rid.split("-r")[1])]
            note = f"   <- overtook {', '.join(earlier)}" if earlier else ""
            with lock:
                results.append((rid, server_delay, now - sent_at))
                print(f"[{now - t0[0]:6.2f}s] client {i:<3} got: {text}{note}", flush=True)
    sock.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--clients", type=int, default=10)
    p.add_argument("--requests", type=int, default=2, help="requests per client")
    args = p.parse_args()

    t0 = [0.0]
    results, lock = [], threading.Lock()
    # The barrier releases all clients at once and records the start time.
    barrier = threading.Barrier(args.clients,
                                action=lambda: t0.__setitem__(0, time.monotonic()))

    print(f"Starting {args.clients} clients x {args.requests} requests "
          f"= {args.clients * args.requests} requests at once\n")
    threads = [threading.Thread(target=run_client,
                                args=(i, args.requests, args.host, args.port,
                                      barrier, t0, results, lock))
               for i in range(1, args.clients + 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.monotonic() - t0[0]

    if not results:
        return
    total = sum(d for _, d, _ in results)
    longest = max(d for _, d, _ in results)
    print(f"\n{len(results)} replies received in {wall:.2f}s of wall time")
    print(f"  sum of every server delay : {total:6.2f}s   (time if served one by one)")
    print(f"  longest single delay      : {longest:6.2f}s   (best possible with full concurrency)")
    print(f"  speedup vs one-by-one     : {total / wall:6.1f}x  from a single-threaded server")


if __name__ == "__main__":
    main()