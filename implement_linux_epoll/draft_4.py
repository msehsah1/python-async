# Lesson 6: the vocabulary, made visible.
# Every UPPERCASE name is just a number with a name. This script triggers each one for real.
import errno
import os
import select
import socket
import time

FLAGS = {select.EPOLLIN: "EPOLLIN", select.EPOLLOUT: "EPOLLOUT",
         select.EPOLLERR: "EPOLLERR", select.EPOLLHUP: "EPOLLHUP"}


def decode(mask):
    """Turn an event number like 5 into 'EPOLLIN | EPOLLOUT'."""
    return " | ".join(name for value, name in FLAGS.items() if mask & value)


print("=== 1. The names are just numbers ===")
for value, name in FLAGS.items():
    print(f"  select.{name:<9} = {value}")
for name in ("EAGAIN", "EINPROGRESS", "ECONNREFUSED"):
    code = getattr(errno, name)
    print(f"  errno.{name:<12} = {code:<4} meaning: {os.strerror(code)}")

# A tiny local server to connect to
server = socket.socket()
server.bind(("127.0.0.1", 0))          # port 0 = "pick any free port"
server.listen()
port = server.getsockname()[1]

print("\n=== 2. EINPROGRESS: 'I started, but I'm not finished' ===")
c = socket.socket()
c.setblocking(False)
rc = c.connect_ex(("127.0.0.1", port))
print(f"  connect_ex() returned {rc} = {errno.errorcode.get(rc, 'OK')}  (handshake started, not done yet)")

ep = select.epoll()
ep.register(c.fileno(), select.EPOLLIN | select.EPOLLOUT)   # watch for BOTH "readable" and "writable"
fd = c.fileno()

print("\n=== 3. EPOLLOUT: 'you can send now' (for a new connection: it's connected) ===")
events = ep.poll(1.0)
print(f"  epoll_wait -> {events}   {events[0][1]} = {decode(events[0][1])}")
print("  -> writable, but NOT readable: the server hasn't sent anything yet")

print("\n=== 4. EPOLLIN: 'there is something to read' ===")
conn, _ = server.accept()
conn.send(b"hi")                        # the server side sends 2 bytes
events = ep.poll(1.0)
print(f"  epoll_wait -> {events}   {events[0][1]} = {decode(events[0][1])}")
print(f"  recv() -> {c.recv(1024)}")

print("\n=== 5. EAGAIN: 'nothing to read right now, try again later' ===")
try:
    c.recv(1024)
except BlockingIOError as e:
    print(f"  recv() on an empty socket -> BlockingIOError errno {e.errno} = {errno.errorcode[e.errno]}")

print("\n=== 6. epoll_wait timeout: nothing happens -> empty list ===")
ep.modify(fd, select.EPOLLIN)           # only care about reading now
t = time.monotonic()
events = ep.poll(0.5)
print(f"  epoll_wait(timeout=0.5s) -> {events} after {time.monotonic() - t:.2f}s")

print("\n=== 7. EPOLLIN also means 'the other side hung up' ===")
conn.close()                            # server closes the connection
events = ep.poll(1.0)
print(f"  epoll_wait -> {events}   {events[0][1]} = {decode(events[0][1])}")
print(f"  recv() -> {c.recv(1024)}   (b'' = closed, no more data ever)")
ep.unregister(fd)
c.close()

print("\n=== 8. ECONNREFUSED: connecting to a port where nobody listens ===")
server.close()                          # now nobody is listening on that port
c2 = socket.socket()
c2.setblocking(False)
rc = c2.connect_ex(("127.0.0.1", port))
print(f"  connect_ex() returned {rc} = {errno.errorcode.get(rc, 'OK')}")
ep.register(c2.fileno(), select.EPOLLOUT)
events = ep.poll(1.0)
print(f"  epoll_wait -> {events}   {events[0][1]} = {decode(events[0][1])}")
err = c2.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
print(f"  SO_ERROR = {err} = {errno.errorcode[err]}  <- this is how you learn WHY")