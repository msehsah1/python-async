"""
generators_to_async.py — how `async def` / `await` are built from generators.

Four steps, each one a small addition to the previous:
  1. a generator can pause and resume          (yield, next, send)
  2. generators can be tasks in a scheduler    (a loop that calls send(None))
  3. `yield from` passes a pause up a call chain
  4. `async def` + `await` is the same machinery with new, stricter syntax

Run:  python3 generators_to_async.py
"""

import dis
import inspect
from collections import deque


def banner(text):
    print(f"\n=== {text} ===")


# ---------------------------------------------------------------------------
banner("1. A generator is a function that can pause")
# ---------------------------------------------------------------------------
def counter():
    print("  start")
    x = yield 1                       # pause here, hand 1 to the caller
    print(f"  resumed, got {x!r}")
    y = yield 2
    print(f"  resumed, got {y!r}")
    return "done"


g = counter()
print("created, but nothing ran yet:", inspect.getgeneratorstate(g))
print("next(g)    ->", next(g), "|", inspect.getgeneratorstate(g))
print("g.send('a') ->", g.send("a"))
try:
    g.send("b")
except StopIteration as stop:
    print("finished. The return value rides inside StopIteration:", repr(stop.value))


# ---------------------------------------------------------------------------
banner("2. Generators as tasks: a tiny round-robin scheduler")
# ---------------------------------------------------------------------------
class Pause:
    """What a task yields to say: 'I'm waiting, run someone else.'"""


def worker(name, steps):
    for i in range(1, steps + 1):
        print(f"  {name}: step {i}")
        yield Pause()                 # give up the CPU
    return f"{name}-result"


def run_named(tasks):
    """Our whole 'event loop': resume each task in turn until all are done."""
    ready = deque(tasks)
    while ready:
        name, gen = ready.popleft()
        try:
            gen.send(None)            # run until the next yield
        except StopIteration as stop:
            print(f"  [{name}] finished -> {stop.value!r}")
        else:
            ready.append((name, gen)) # it paused: go to the back of the line

run_named([("A", worker("A", 2)), ("B", worker("B", 3))])
print("  ^ A and B interleave on ONE thread: each yield is a hand-off")


# ---------------------------------------------------------------------------
banner("3. `yield from`: pass a pause up through nested calls")
# ---------------------------------------------------------------------------
def fetch(name):
    print(f"  {name}: sending request")
    yield Pause()                     # this pause happens two calls deep...
    print(f"  {name}: reply arrived")
    return f"{name}-data"


def handler(name):
    data = yield from fetch(name)     # ...but reaches the scheduler through here
    print(f"  {name}: handler got {data!r}")
    return data.upper()


run_named([("H1", handler("h1")), ("H2", handler("h2"))])
print("  ^ handler() never yields itself, yet the scheduler saw fetch()'s pause.")
print("    `yield from` is the pipe that carries a pause up, and the result back down.")


# ---------------------------------------------------------------------------
banner("4. The same thing with async def / await")
# ---------------------------------------------------------------------------
class Future:
    """A box that will hold a result later (same shape as tinyio.Future)."""

    def __init__(self, name):
        self.name, self.done, self.result = name, False, None

    def __await__(self):              # `await fut` calls this
        if not self.done:
            yield self                # <-- the one real pause point
        return self.result


async def fetch2(name, fut):
    print(f"  {name}: sending request")
    data = await fut                  # same job as `yield from` in step 3
    print(f"  {name}: reply arrived")
    return data


async def handler2(name, fut):
    data = await fetch2(name, fut)
    print(f"  {name}: handler got {data!r}")
    return data.upper()


fut = Future("reply")
coro = handler2("h", fut)
print("calling an async def runs NOTHING:", type(coro).__name__,
      "|", inspect.getcoroutinestate(coro))

yielded = coro.send(None)             # exactly what Task.step() does
print("coro.send(None) returned our Future:", yielded is fut,
      "|", inspect.getcoroutinestate(coro))
print("  ^ the pause travelled up through TWO awaits: fetch2 -> handler2 -> us")

fut.done, fut.result = True, "payload"   # something (the event loop) completes it
try:
    coro.send(None)                   # resume: `await fut` returns "payload"
except StopIteration as stop:
    print("second send(None) finished the coroutine ->", repr(stop.value))


# ---------------------------------------------------------------------------
banner("5. Proof it is the same machinery")
# ---------------------------------------------------------------------------
ops = [i.opname for i in dis.get_instructions(fetch2) if i.opname in
       ("GET_AWAITABLE", "SEND", "YIELD_VALUE", "RETURN_VALUE")]
print("bytecode of `data = await fut` and return:", ops)

print("a coroutine object is built on the generator type's methods:",
      all(hasattr(coro, m) for m in ("send", "throw", "close")))

try:
    async def bad():
        await counter()               # a plain generator is NOT awaitable
    bad().send(None)
except TypeError as exc:
    print("await on a plain generator ->", exc)
print("  ^ async/await keeps 'awaitable' and 'generator' apart on purpose,")
print("    so you can't mix them up by accident. Underneath, it is still send().")