import heapq
import inspect
import time
from collections import deque


def banner(title):                    # drop this if your tutorial already defines it
    print(f"\n{'-' * 75}\n{title}\n{'-' * 75}")


START = time.monotonic()


def log(msg):
    """Print with a timestamp so you can SEE when things happen."""
    print(f"  [{time.monotonic() - START:4.1f}s] {msg}")


# ---------------------------------------------------------------------------
banner("4. The same thing with async def / await -- now with a real clock")
# ---------------------------------------------------------------------------
class Future:
    """A box that will hold a result later (same shape as tinyio.Future)."""

    def __init__(self, name):
        self.name, self.done, self.result = name, False, None
        self.waiter = None            # the Task to wake up when the box is filled

    def __await__(self):              # `await fut` calls this
        if not self.done:
            yield self                # <-- the one real pause point
        return self.result


class Task:
    """Wraps one coroutine. step() = run it until its next pause."""

    def __init__(self, name, coro):
        self.name, self.coro = name, coro

    def step(self):
        try:
            fut = self.coro.send(None)        # run until some Future pauses us
        except StopIteration as stop:
            log(f"loop: task {self.name} finished -> {stop.value!r}")
        else:
            # The coroutine handed us the Future it's waiting on.
            # The task is now in NO queue: only that Future remembers it.
            fut.waiter = self
            log(f"loop: task {self.name} parked, waiting on <{fut.name}>")


class Loop:
    """A tiny event loop: a run queue plus a timer heap."""

    def __init__(self):
        self.ready = deque()          # tasks that can run right now
        self.timers = []              # heap of (when, seq, future, value)
        self.seq = 0                  # tie-breaker so the heap never compares Futures

    def spawn(self, name, coro):
        self.ready.append(Task(name, coro))

    def call_later(self, delay, fut, value):
        """At time now+delay, fill `fut` with `value`."""
        heapq.heappush(self.timers, (time.monotonic() + delay, self.seq, fut, value))
        self.seq += 1

    def run(self):
        while self.ready or self.timers:
            # 1. Run everything that is ready, one step each.
            while self.ready:
                self.ready.popleft().step()

            if not self.timers:       # last task just finished: nothing left to wait for
                break

            # 2. Nobody can run. Wait for the earliest timer.
            when, _, fut, value = heapq.heappop(self.timers)
            gap = when - time.monotonic()
            if gap > 0:
                if gap > 0.01:        # don't log the tiny gaps between timers due together
                    log(f"loop: nothing to run -> sleeping {gap:.1f}s until <{fut.name}>")
                time.sleep(gap)       # the ONLY place where real time passes

            # 3. Fill the box and wake the task that was waiting on it.
            fut.done, fut.result = True, value     # same line as before, now done by the loop
            log(f"loop: <{fut.name}> is done -> waking task {fut.waiter.name}")
            self.ready.append(fut.waiter)


loop = Loop()


async def sleep(seconds, label):
    """Like asyncio.sleep: a Future that the loop fills after `seconds`."""
    fut = Future(f"{label} timer {seconds}s")
    loop.call_later(seconds, fut, None)
    await fut


async def fetch2(name, latency):
    log(f"{name}: sending request")
    reply = Future(f"{name} reply")
    loop.call_later(latency, reply, f"{name}-payload")   # pretend the network answers later
    data = await reply                                   # pause here; resume with the payload
    log(f"{name}: reply arrived")
    return data


async def handler2(name, latency):
    data = await fetch2(name, latency)
    log(f"{name}: handler got {data!r}")
    return data.upper()


async def ticker():
    """Proves the loop keeps working while the requests are in flight."""
    for i in range(4):
        log(f"tick {i}")
        await sleep(0.5, "tick")
    return "ticks done"


slow = handler2("h1", latency=6.0)
fast = handler2("h2", latency=4.0)
print("  calling an async def runs NOTHING:", type(slow).__name__,"|", inspect.getcoroutinestate(slow))

loop.spawn("H1", slow)
loop.spawn("H2", fast)
loop.spawn("TICK", ticker())
loop.run()

print(f"\n  total: {time.monotonic() - START:.1f}s""  (one at a time would take 2.0 + 1.0 = 3.0s for the requests alone)")