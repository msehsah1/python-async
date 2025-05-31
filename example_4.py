# example3.py
import asyncio, aiohttp

URLS = [
    "https://api.github.com",
    "https://api.github.com/emojis"
]

async def fetch(session, url):
    async with session.get(url) as resp:
        text = await resp.text()
        return url, resp.status, len(text)

async def main():
    async with aiohttp.ClientSession() as session:
        tasks = [fetch(session, u) for u in URLS]
        for coro in asyncio.as_completed(tasks):
            url, status, size = await coro
            print(f"{url} -> {status} ({size} bytes)")

asyncio.run(main())
