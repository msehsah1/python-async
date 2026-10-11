# Level 3: no async, no await, no loop. Just the three epoll calls.
import select
import socket

a, b = socket.socketpair()
a.setblocking(False)

ep = select.epoll()                        # epoll_create1: make an epoll instance
ep.register(a.fileno(), select.EPOLLIN)    # epoll_ctl ADD: "wake me when fd a is readable"

print("1st wait:", ep.poll(1.0))           # epoll_wait 1000 ms: nobody wrote -> [] after 1s (this IS a sleep)

b.send(b"hello")                           # someone writes to the other end

print("2nd wait:", ep.poll(1.0))           # epoll_wait: data is there -> returns at once
print("recv:", a.recv(1024))               # reading now never blocks