import asyncio 


async def nap(number, name):
    print(f"{name} is napping for {number} seconds")
    await asyncio.sleep(number)
    print(f"{name} woke up after {number} seconds")




async def main():
    # Create a list of tasks
    tasks = [
        nap(2, "Task 1"),
        nap(3, "Task 2"),
        nap(1, "Task 3"),
        nap(1, "Task 4")
    ]
    
    # Run the tasks concurrently
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
    print("All tasks completed")