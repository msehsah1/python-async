# example2.py
import asyncio, random

async def random_job(i):
    await asyncio.sleep(random.uniform(0.1, 0.5))
    if i % 7 == 0:
        raise ValueError(f"Task {i} blew up!")   # simulate failure
    return i*i

async def main():
    tasks = [asyncio.create_task(random_job(i)) for i in range(15)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for i, res in enumerate(results):
        if isinstance(res, Exception):
            print(f"❌ Job {i} failed: {res}")
        else:
            print(f"✅ Job {i} result = {res}")

asyncio.run(main())
