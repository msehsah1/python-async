# example5.py
import asyncio
from contextlib import asynccontextmanager
import time

@asynccontextmanager
async def timer(label: str):
    start = time.perf_counter()
    yield
    end = time.perf_counter()
    print(f"{label} took {end - start:.3f}s")

async def long_io():
    await asyncio.sleep(1.2)

async def main():
    async with timer("Long I/O"):
        await long_io()

asyncio.run(main())
