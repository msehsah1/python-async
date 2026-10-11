# Level 2: the SAME program, but with our own tiny event loop instead of asyncio.
# About 60 lines replace asyncio.run / Task / Future / sleep / sock_recv,
# and the loop talks to Linux epoll directly. Every print shows one step.
import heapq
import select
import socket
import time
from collections import deque

T0 = time.monotonic()


def log(who, msg):
    print(f"[{time.monotonic() - T0:4.2f}s] {who:<8} {msg}")


# ---------- Future: a box that will hold a result later ----------
class Future:
    def __init__(self, name):
        self.name, self.done, self.result, self.callbacks = name, False, None, []

    def set_result(self, value):
        self.done, self.result = True, value
        log("future", f"{self.name} DONE -> schedule {len(self.callbacks)} waiting task(s)")
        for cb in self.callbacks:
            loop.ready.append(cb)

    def __await__(self):
        if not self.done:
            yield self            # <-- the ONLY place a coroutine actually pauses
        return self.result


# ---------- Task: drives one coroutine, step by step ----------
class Task:
    def __init__(self, coro, name):
        self.coro, self.name = coro, name
        loop.ready.append(self.step)          # like call_soon(task.__step)

    def step(self):
        log("task", f"{self.name}: resume (coro.send)")
        try:
            fut = self.coro.send(None)        # run until the next `yield self`
        except StopIteration:
            log("task", f"{self.name}: finished")
            return
        log("task", f"{self.name}: suspended, waiting on {fut.name}")
        fut.callbacks.append(self.step)       # wake me when that future is done


# ---------- Loop: ready queue + timer heap + epoll ----------
class Loop:
    def __init__(self):
        self.ready = deque()                  # callbacks to run now
        self.timers = []                      # heap of (when, seq, callback)
        self.readers = {}                     # fd -> callback
        self.ep = select.epoll()              # syscall: epoll_create1
        log("loop", f"epoll_create1 -> epoll fd {self.ep.fileno()}")

    def call_later(self, delay, cb):
        heapq.heappush(self.timers, (time.monotonic() + delay, len(self.timers), cb))

    def add_reader(self, fd, cb):
        self.readers[fd] = cb
        self.ep.register(fd, select.EPOLLIN)  # syscall: epoll_ctl(ADD)
        log("loop", f"epoll_ctl ADD fd {fd} (tell me when it is readable)")

    def remove_reader(self, fd):
        del self.readers[fd]
        self.ep.unregister(fd)                # syscall: epoll_ctl(DEL)
        log("loop", f"epoll_ctl DEL fd {fd}")

    def run(self):
        while self.ready or self.timers or self.readers:
            # 1. how long may we sleep?
            if self.ready:
                timeout = 0                    # work waiting: don't sleep
            elif self.timers:
                timeout = max(0, self.timers[0][0] - time.monotonic())
            else:
                timeout = -1                   # nothing scheduled: sleep until I/O
            # 2. sleep inside the kernel
            if timeout != 0:
                log("loop", f"epoll_wait(timeout={'inf' if timeout < 0 else f'{timeout:.2f}s'}) ... thread sleeps")
            events = self.ep.poll(timeout)     # syscall: epoll_wait
            if timeout != 0:
                log("loop", f"epoll_wait returned {[(fd, 'IN') for fd, _ in events]}")
            # 3. I/O events -> ready queue
            for fd, _ in events:
                self.ready.append(self.readers[fd])
            # 4. expired timers -> ready queue
            now = time.monotonic()
            while self.timers and self.timers[0][0] <= now:
                log("loop", "timer expired -> ready queue")
                self.ready.append(heapq.heappop(self.timers)[2])
            # 5. run everything that is ready right now
            for _ in range(len(self.ready)):
                self.ready.popleft()()


# ---------- our own versions of asyncio.sleep and loop.sock_recv ----------
async def sleep(delay):
    fut = Future("sleep-future")
    loop.call_later(delay, lambda: fut.set_result(None))
    log("sleep", f"timer pushed on heap for +{delay}s")
    await fut


async def sock_recv(sock, n):
    fut = Future("recv-future")

    def on_readable():
        loop.remove_reader(sock.fileno())
        fut.set_result(sock.recv(n))           # data is there now, recv won't block

    loop.add_reader(sock.fileno(), on_readable)
    return await fut


# ---------- the program: same shape as 01_asyncio.py ----------
async def sender(sock):
    await sleep(1)
    log("sender", "send(b'hello')")
    sock.send(b"hello")


async def receiver(sock):
    data = await sock_recv(sock, 1024)
    log("receiver", f"received: {data}")


loop = Loop()
a, b = socket.socketpair()
a.setblocking(False)
b.setblocking(False)
log("main", f"socketpair -> fd {a.fileno()} (receiver side), fd {b.fileno()} (sender side)")
Task(receiver(a), "receiver")
Task(sender(b), "sender")
loop.run()