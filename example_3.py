import asyncio

async def background_work():
    for i in range(1, 4):
        print(f"🔄 background step {i}")
        await asyncio.sleep(1)
    return "✅ background done"

async def main():
    # 1. Create & schedule the background task
    task = asyncio.create_task(background_work())

    # 2. Meanwhile, do other work
    print("🏃 main doing something else...")
    await asyncio.sleep(0.5)
    print("🏃 main still working...")

    # 3. Later, await the background task’s result
    result = await task
    print("Background result:", result)

asyncio.run(main())
