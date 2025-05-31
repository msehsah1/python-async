# example6.py
import asyncio, random

async def producer(queue: asyncio.Queue):
    for i in range(20):
        await asyncio.sleep(0.1)                 # pretend we read from Kafka
        item = random.randint(1, 100)
        await queue.put(item)
        print(f"P  produced {item}")
    for _ in range(NUM_WORKERS):
        await queue.put(None)                     # poison pills

async def worker(name: int, queue: asyncio.Queue, results: list[int]):
    while True:
        item = await queue.get()
        if item is None:
            break
        await asyncio.sleep(0.2)                  # CPU-light processing step
        squared = item * item
        results.append(squared)
        print(f"W  worker {name} processed {item} -> {squared}")

async def main():
    queue: asyncio.Queue[int | None] = asyncio.Queue()
    results: list[int] = []

    prod_task = asyncio.create_task(producer(queue))
    workers = [
        asyncio.create_task(worker(i, queue, results))
        for i in range(NUM_WORKERS)
    ]
    await prod_task
    await asyncio.gather(*workers)
    print(f"\nResults: {results}")

NUM_WORKERS = 4
asyncio.run(main())