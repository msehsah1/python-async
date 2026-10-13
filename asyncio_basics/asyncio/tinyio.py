"""
tinyio.py — a miniature asyncio built directly on Linux epoll.

This is your Level 2 loop, grown just enough to run a real TCP server and
client. Every piece has the same name and job as in asyncio:

    tinyio                      asyncio
    ------------------------    ---------------------------------------
    Future                      asyncio.Future
    Task                        asyncio.Task (a Task IS a Future)
    Loop                        the event loop (asyncio's _run_once)
    run(coro)                   asyncio.run(coro)
    create_task(coro)           asyncio.create_task(coro)
    gather(*tasks)              asyncio.gather(*tasks)
    sleep(delay)                asyncio.sleep(delay)
    sock_accept / sock_recv /   loop.sock_accept / loop.sock_recv /
    sock_sendall / sock_connect loop.sock_sendall / loop.sock_connect

The whole trick, in three sentences:
  1. `await future` inside a coroutine reaches `yield self` in
     Future.__await__, which pauses the coroutine and hands the future
     back to the Task that is running it.
  2. The Task asks the future to call Task.step when it finishes.
  3. The Loop finishes futures when epoll says a socket is ready or when a
     timer expires, and then runs the waiting Task.step callbacks.

Set TRACE = False to hide the loop / task / future internals.
"""

import heapq
import itertools
import os
import select
import socket
import time
from collections import deque

T0 = time.monotonic()
TRACE = True
_loop = None                      # the one running loop (asyncio: get_running_loop)


def log(who, msg):
    print(f"[{time.monotonic() - T0:7.3f}s] {who:<7} {msg}", flush=True)


def trace(who, msg):
    if TRACE:
        log(who, msg)


# ---------------------------------------------------------------------------
# Future: a box that will hold a result later
# ---------------------------------------------------------------------------
class Future:
    def __init__(self, name="future"):
        self.name = name
        self.done = False
        self.result = None
        self.exception = None
        self.callbacks = []          # functions to run when this future is done

    def add_done_callback(self, cb):
        if self.done:
            _loop.call_soon(cb)
        else:
            self.callbacks.append(cb)

    def set_result(self, value):
        self.result = value
        self._finish()

    def set_exception(self, exc):
        self.exception = exc
        self._finish()

    def _finish(self):
        self.done = True
        trace("future", f"{self.name} done -> {len(self.callbacks)} waiter(s) to ready queue")
        for cb in self.callbacks:
            _loop.call_soon(cb)      # never run callbacks inline: always via the loop
        self.callbacks = []

    def __await__(self):
        if not self.done:
            yield self               # <-- the ONLY place a coroutine actually pauses
        if self.exception is not None:
            raise self.exception
        return self.result


# ---------------------------------------------------------------------------
# Task: drives one coroutine step by step. A Task is itself a Future,
# so other coroutines can `await task` to wait for it to finish.
# ---------------------------------------------------------------------------
class Task(Future):
    _ids = itertools.count(1)

    def __init__(self, coro, name=None):
        super().__init__(name or f"task-{next(Task._ids)}")
        self.coro = coro
        _loop.call_soon(self.step)   # start it on the next loop iteration

    def step(self):
        trace("task", f"{self.name}: resume")
        try:
            fut = self.coro.send(None)   # run until the next `yield self`
        except StopIteration as stop:    # the coroutine returned
            trace("task", f"{self.name}: finished")
            self.set_result(stop.value)
            return
        except Exception as exc:         # the coroutine raised
            log("task", f"{self.name}: crashed with {exc!r}")
            self.set_exception(exc)
            return
        trace("task", f"{self.name}: suspended, waiting on {fut.name}")
        fut.add_done_callback(self.step) # wake me when that future is done


# ---------------------------------------------------------------------------
# Loop: ready queue + timer heap + epoll
# ---------------------------------------------------------------------------
class Loop:
    def __init__(self):
        self.ready = deque()             # callbacks to run now
        self.timers = []                 # heap of (when, seq, callback)
        self.seq = itertools.count()     # tie-breaker for equal deadlines
        self.readers = {}                # fd -> callback when readable
        self.writers = {}                # fd -> callback when writable
        self.masks = {}                  # fd -> mask currently registered in epoll
        self.ep = select.epoll()         # syscall: epoll_create1
        self.stats = {"epoll_wait": 0, "callbacks": 0}
        trace("loop", f"epoll_create1 -> epoll fd {self.ep.fileno()}")

    # --- scheduling -------------------------------------------------------
    def call_soon(self, cb):
        self.ready.append(cb)

    def call_later(self, delay, cb):
        heapq.heappush(self.timers, (time.monotonic() + delay, next(self.seq), cb))

    # --- I/O interest: keeps epoll in sync with readers/writers ------------
    def _sync(self, fd):
        want = ((select.EPOLLIN if fd in self.readers else 0)
                | (select.EPOLLOUT if fd in self.writers else 0))
        have = self.masks.get(fd, 0)
        if want == have:
            return
        if not have:
            self.ep.register(fd, want)       # syscall: epoll_ctl(ADD)
            op = "ADD"
        elif not want:
            self.ep.unregister(fd)           # syscall: epoll_ctl(DEL)
            op = "DEL"
        else:
            self.ep.modify(fd, want)         # syscall: epoll_ctl(MOD)
            op = "MOD"
        if want:
            self.masks[fd] = want
        else:
            del self.masks[fd]
        names = "+".join(n for n, bit in (("IN", select.EPOLLIN), ("OUT", select.EPOLLOUT))
                         if want & bit) or "-"
        trace("loop", f"epoll_ctl {op} fd {fd} ({names})")

    def add_reader(self, fd, cb):
        self.readers[fd] = cb
        self._sync(fd)

    def remove_reader(self, fd):
        self.readers.pop(fd, None)
        self._sync(fd)

    def add_writer(self, fd, cb):
        self.writers[fd] = cb
        self._sync(fd)

    def remove_writer(self, fd):
        self.writers.pop(fd, None)
        self._sync(fd)

    # --- the loop ---------------------------------------------------------
    def run_once(self):
        # 1. How long may we sleep?
        if self.ready:
            timeout = 0                       # work is waiting: just peek
        elif self.timers:
            timeout = max(0.0, self.timers[0][0] - time.monotonic())
        else:
            timeout = -1                      # sleep until some fd is ready
            if not self.masks:
                raise RuntimeError("deadlock: no work, no timers, no fds to wake us")

        # 2. Sleep inside the kernel.
        if timeout != 0:
            shown = "inf" if timeout < 0 else f"{timeout:.2f}s"
            trace("loop", f"epoll_wait(timeout={shown}) ... thread sleeps")
        events = self.ep.poll(timeout)        # syscall: epoll_wait
        self.stats["epoll_wait"] += 1
        if timeout != 0:
            trace("loop", f"epoll_wait woke up: {[fd for fd, _ in events] or 'timeout'}")

        # 3. I/O events -> ready queue.
        for fd, ev in events:
            if ev & (select.EPOLLIN | select.EPOLLHUP | select.EPOLLERR) and fd in self.readers:
                self.ready.append(self.readers[fd])
            if ev & (select.EPOLLOUT | select.EPOLLHUP | select.EPOLLERR) and fd in self.writers:
                self.ready.append(self.writers[fd])

        # 4. Expired timers -> ready queue.
        now = time.monotonic()
        while self.timers and self.timers[0][0] <= now:
            self.ready.append(heapq.heappop(self.timers)[2])

        # 5. Run what is ready NOW. Callbacks added while running wait for the
        #    next iteration, so one busy task can't starve the I/O check.
        for _ in range(len(self.ready)):
            self.stats["callbacks"] += 1
            self.ready.popleft()()

    def run_until_complete(self, fut):
        while not fut.done:
            self.run_once()
        if fut.exception is not None:
            raise fut.exception
        return fut.result

    def close(self):
        self.ep.close()


# ---------------------------------------------------------------------------
# Public API, same names as asyncio
# ---------------------------------------------------------------------------
def run(coro):
    """asyncio.run(): make a loop, run the main coroutine to completion."""
    global _loop
    _loop = Loop()
    try:
        return _loop.run_until_complete(Task(coro, name="main"))
    finally:
        _loop.close()


def get_loop():
    return _loop


def create_task(coro, name=None):
    return Task(coro, name)


async def gather(*aws):
    """Wait for several tasks. They already run concurrently; awaiting them
    one after another only decides when *we* resume, so the total wait is
    the slowest task, not the sum."""
    tasks = [a if isinstance(a, Future) else create_task(a) for a in aws]
    for t in tasks:
        await t
    return [t.result for t in tasks]


async def sleep(delay):
    fut = Future(f"sleep({delay:.2f}s)")
    _loop.call_later(delay, lambda: fut.set_result(None))
    trace("sleep", f"timer pushed on heap for +{delay:.2f}s")
    await fut


# Socket helpers follow asyncio's pattern:
#   try the operation now; only if it would block, register with epoll,
#   await a future, and retry when epoll says the socket is ready.

async def sock_accept(sock):
    try:
        conn, addr = sock.accept()             # fast path: someone is waiting
    except BlockingIOError:
        fd = sock.fileno()
        fut = Future(f"accept(fd {fd})")

        def on_readable():
            try:
                conn, addr = sock.accept()
            except BlockingIOError:
                return                         # false alarm: keep waiting
            _loop.remove_reader(fd)
            fut.set_result((conn, addr))

        _loop.add_reader(fd, on_readable)
        conn, addr = await fut
    conn.setblocking(False)
    return conn, addr


async def sock_recv(sock, n):
    try:
        return sock.recv(n)                    # fast path: data already there
    except BlockingIOError:
        pass
    fd = sock.fileno()
    fut = Future(f"recv(fd {fd})")

    def on_readable():
        try:
            data = sock.recv(n)
        except BlockingIOError:
            return
        except OSError as exc:
            _loop.remove_reader(fd)
            fut.set_exception(exc)
            return
        _loop.remove_reader(fd)
        fut.set_result(data)

    _loop.add_reader(fd, on_readable)
    return await fut


async def sock_sendall(sock, data):
    view = memoryview(data)
    try:
        sent = sock.send(view)                 # fast path: usually sends it all
    except BlockingIOError:
        sent = 0
    if sent == len(view):
        return
    view = view[sent:]                         # send buffer full: wait for room
    fd = sock.fileno()
    fut = Future(f"sendall(fd {fd})")

    def on_writable():
        nonlocal view
        try:
            n = sock.send(view)
        except BlockingIOError:
            return
        except OSError as exc:
            _loop.remove_writer(fd)
            fut.set_exception(exc)
            return
        view = view[n:]
        if not view:
            _loop.remove_writer(fd)
            fut.set_result(None)

    _loop.add_writer(fd, on_writable)
    await fut


async def sock_connect(sock, address):
    try:
        sock.connect(address)
        return
    except BlockingIOError:
        pass                                   # EINPROGRESS: handshake under way
    fd = sock.fileno()
    fut = Future(f"connect(fd {fd})")

    def on_writable():                         # writable = handshake finished
        _loop.remove_writer(fd)
        err = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if err:
            fut.set_exception(OSError(err, os.strerror(err)))
        else:
            fut.set_result(None)

    _loop.add_writer(fd, on_writable)
    await fut