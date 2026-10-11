# Level 1: normal asyncio code.
# Two coroutines share one socket pair:
#   receiver waits for data, sender sleeps 1s then sends "hello".
import asyncio
import socket


async def sender(sock):
    await asyncio.sleep(1)               # wait 1 second without blocking
    sock.send(b"hello")


async def receiver(sock):
    loop = asyncio.get_running_loop()
    data = await loop.sock_recv(sock, 1024)   # wait until data arrives
    print("received:", data)


async def main():
    a, b = socket.socketpair()           # two connected sockets (like a tiny network)
    a.setblocking(False)
    b.setblocking(False)
    await asyncio.gather(receiver(a), sender(b))


asyncio.run(main())