"""
epoll_server.py — one thread, one epoll loop, many clients, random reply delays.

Each client sends requests as lines of text ("c3-r1\n"). For every request the
server picks a random delay (default 0.5–3.0 s) and replies when it expires:

    "c3-r1 done after 2.31s\n"

The important rule: the server NEVER calls time.sleep(). A sleep would freeze
the whole loop and every other client with it. Instead, each pending reply is a
timer in a heap, and the timeout given to epoll_wait is "time until the next
timer is due". That is exactly how asyncio implements call_later()/sleep().

The three epoll calls, as in the Level 3 example:
    select.epoll()      -> epoll_create1   make the epoll instance (once)
    ep.register/modify/unregister       -> epoll_ctl       ADD / MOD / DEL interest (on change)
    ep.poll(timeout)    -> epoll_wait      sleep until ready or timeout

Run:  phoytn3 epoll_server.py              (Linux only: epoll is Linux-specific)
      python3 epoll_server.py --min 1 --max 5
Then: python3 epoll_clients.py
"""

import argparse
import heapq
import itertools
import random
import select
import socket
import time

START = time.monotonic()


def log(msg):
    print(f"[{time.monotonic() - START:7.3f}s] {msg}", flush=True)


class Conn:
    """Everything the loop knows about one client."""

    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.fd = sock.fileno()
        self.inbuf = b""        # bytes received but not yet a full line
        self.outbuf = b""       # replies waiting to be sent
        self.pending = 0        # requests whose timer hasn't fired yet
        self.writing = False    # are we currently watching EPOLLOUT?
        self.closed = False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--min", type=float, default=0.5, help="min reply delay (s)")
    p.add_argument("--max", type=float, default=3.0, help="max reply delay (s)")
    args = p.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(1024)
    server.setblocking(False)

    ep = select.epoll()                                   # epoll_create1
    ep.register(server.fileno(), select.EPOLLIN)          # epoll_ctl ADD

    conns = {}                     # fd -> Conn (epoll gives us fds, not sockets)
    timers = []                    # heap of (due_time, seq, conn, request, delay)
    seq = itertools.count()        # tie-breaker so the heap never compares Conns
    in_flight = 0                  # requests waiting for their delay to expire
    stats = {"epoll_wait": 0, "requests": 0, "replies": 0, "max_in_flight": 0}

    log(f"epoll server on {args.host}:{args.port}, "
        f"reply delay {args.min}–{args.max}s, single thread")

    # ---- helpers ------------------------------------------------------------

    def set_writing(c, on):
        """Watch EPOLLOUT only while there is something to send."""
        if c.writing != on:
            mask = select.EPOLLIN | (select.EPOLLOUT if on else 0)
            ep.modify(c.fd, mask)                         # epoll_ctl MOD
            c.writing = on

    def close(c, why):
        nonlocal in_flight
        if c.closed:
            return
        c.closed = True                 # timers still in the heap will skip it
        in_flight -= c.pending
        ep.unregister(c.fd)                               # epoll_ctl DEL
        del conns[c.fd]
        c.sock.close()
        log(f"fd {c.fd:<3} closed ({why}); clients connected: {len(conns)}")

    def accept_all():
        # Several clients may be waiting; take them all until the queue is empty.
        while True:
            try:
                sock, addr = server.accept()
            except BlockingIOError:
                return
            sock.setblocking(False)
            c = Conn(sock, addr)
            conns[c.fd] = c
            ep.register(c.fd, select.EPOLLIN)             # epoll_ctl ADD
            log(f"fd {c.fd:<3} connected from port {addr[1]}; "
                f"clients connected: {len(conns)}")

    def handle_read(c):
        nonlocal in_flight
        try:
            data = c.sock.recv(4096)
        except BlockingIOError:
            return
        except OSError as e:
            close(c, f"recv error: {e}")
            return
        if not data:                    # b"" = the client closed its side
            close(c, "client finished")
            return

        c.inbuf += data
        while b"\n" in c.inbuf:         # one line = one request
            line, c.inbuf = c.inbuf.split(b"\n", 1)
            request = line.decode(errors="replace").strip()
            if not request:
                continue
            delay = random.uniform(args.min, args.max)
            # Don't sleep! Schedule the reply and go straight back to epoll_wait.
            heapq.heappush(timers, (time.monotonic() + delay, next(seq),
                                    c, request, delay))
            c.pending += 1
            in_flight += 1
            stats["requests"] += 1
            stats["max_in_flight"] = max(stats["max_in_flight"], in_flight)
            log(f"fd {c.fd:<3} got {request:<7} -> reply in {delay:.2f}s   "
                f"(in flight: {in_flight})")

    def handle_write(c):
        if not c.outbuf:
            set_writing(c, False)
            return
        try:
            sent = c.sock.send(c.outbuf)    # may send only part of it
        except BlockingIOError:
            sent = 0
        except OSError as e:
            close(c, f"send error: {e}")
            return
        c.outbuf = c.outbuf[sent:]
        set_writing(c, bool(c.outbuf))      # leftovers -> wait for EPOLLOUT

    def fire_due_timers():
        nonlocal in_flight
        now = time.monotonic()
        while timers and timers[0][0] <= now:
            _, _, c, request, delay = heapq.heappop(timers)
            if c.closed:
                continue                    # client left before its reply was due
            c.pending -= 1
            in_flight -= 1
            stats["replies"] += 1
            c.outbuf += f"{request} done after {delay:.2f}s\n".encode()
            log(f"fd {c.fd:<3} reply  {request:<7} sent after {delay:.2f}s   "
                f"(in flight: {in_flight})")
            handle_write(c)                 # usually sends right away

    # ---- the event loop -----------------------------------------------------

    try:
        while True:
            # 1. How long may we sleep? Until the next reply is due.
            #    -1 = no timers pending, sleep until a socket event.
            if timers:
                timeout = max(0.0, timers[0][0] - time.monotonic())
            else:
                timeout = -1

            # 2. epoll_wait: returns only the ready fds, as (fd, event_mask).
            events = ep.poll(timeout)
            stats["epoll_wait"] += 1

            # 3. Handle socket events.
            for fd, ev in events:
                if fd == server.fileno():
                    accept_all()
                    continue
                c = conns.get(fd)
                if c is None:
                    continue
                if ev & select.EPOLLERR:
                    close(c, "socket error")
                    continue
                if ev & (select.EPOLLIN | select.EPOLLHUP):
                    handle_read(c)
                if not c.closed and ev & select.EPOLLOUT:
                    handle_write(c)

            # 4. Handle timers whose delay has expired.
            fire_due_timers()
    except KeyboardInterrupt:
        print()
    finally:
        for c in list(conns.values()):
            close(c, "server stopping")
        ep.close()
        server.close()
        log(f"stopped. requests: {stats['requests']}, replies: {stats['replies']}, "
            f"most in flight at once: {stats['max_in_flight']}, "
            f"epoll_wait calls: {stats['epoll_wait']}")


if __name__ == "__main__":
    main()