"""
asyncio_server.py — the SAME server as tinyio_server.py, using the real asyncio.

Put the two files side by side: the application code is the same shape.
  tinyio.sleep          -> asyncio.sleep
  tinyio.create_task    -> asyncio.create_task
  tinyio.gather         -> asyncio.gather
  tinyio.sock_accept    -> loop.sock_accept
  tinyio.sock_recv      -> loop.sock_recv
  tinyio.sock_sendall   -> loop.sock_sendall
  tinyio.run            -> asyncio.run

Run:  python3 asyncio_server.py
Then: python3 tinyio_client.py
"""

import argparse
import asyncio
import random
import socket
import time

T0 = time.monotonic()
ARGS = None
BACKGROUND = set()   # real asyncio keeps only WEAK refs to tasks: hold them here


def log(msg):
    print(f"[{time.monotonic() - T0:7.3f}s] app     {msg}", flush=True)


async def handle_request(loop, conn, cid, request):
    delay = random.uniform(ARGS.min, ARGS.max)
    log(f"client {cid}: got {request:<7} -> reply in {delay:.2f}s")
    await asyncio.sleep(delay)
    await loop.sock_sendall(conn, f"{request} done after {delay:.2f}s\n".encode())
    log(f"client {cid}: reply  {request:<7} sent")


async def handle_client(loop, conn, addr, cid):
    log(f"client {cid}: connected from port {addr[1]} (fd {conn.fileno()})")
    buf, pending = b"", []
    try:
        while True:
            data = await loop.sock_recv(conn, 4096)
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                request = line.decode(errors="replace").strip()
                if request:
                    pending.append(asyncio.create_task(handle_request(loop, conn, cid, request)))
        await asyncio.gather(*pending)
    except OSError as exc:
        log(f"client {cid}: connection error {exc}")
    finally:
        conn.close()
        log(f"client {cid}: closed")


async def main():
    loop = asyncio.get_running_loop()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((ARGS.host, ARGS.port))
    server.listen(1024)
    server.setblocking(False)
    log(f"asyncio server on {ARGS.host}:{ARGS.port} (listener fd {server.fileno()})")
    cid = 0
    while True:
        conn, addr = await loop.sock_accept(server)
        cid += 1
        task = asyncio.create_task(handle_client(loop, conn, addr, cid))
        BACKGROUND.add(task)
        task.add_done_callback(BACKGROUND.discard)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--min", type=float, default=0.5)
    p.add_argument("--max", type=float, default=3.0)
    ARGS = p.parse_args()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")