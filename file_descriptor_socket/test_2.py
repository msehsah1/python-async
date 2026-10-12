"""
Echo server built on select(), following the select() system call flow:

  1. Set up the FD sets       (FD_ZERO / FD_SET)
  2. Call select()            (kernel copies sets, scans every FD: O(n))
  3. Return results           (some ready / timeout / error)
  4. Check which FDs are ready (FD_ISSET)
  5. Handle ready FDs         (accept / read / write)

Python's select.select() wraps the C call: you pass plain lists instead of
fd_set bitmasks, and it returns lists of the ready ones (it runs the FD_ISSET
checks for you).

Run:   python3 select_server.py
Test:  nc localhost 9000   (open a few terminals, type lines, get them echoed back)
"""

import select
import socket

HOST, PORT = "127.0.0.1", 9000
TIMEOUT = 5.0  # seconds; select() returns empty lists if nothing is ready


def main():
    # Listening socket. It becomes "readable" when a new client connects.
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    server.setblocking(False)

    # Our own record of which FDs we care about. With C select() the kernel
    # overwrites the fd_sets, so you must rebuild them before every call.
    # Here we keep the "master" lists and pass copies each time.
    read_watch = [server]   # sockets we want to read from
    write_watch = []        # sockets with data waiting to be sent
    outbox = {}             # socket -> bytes still to send

    print(f"select() echo server on {HOST}:{PORT}")

    while True:
        # --- 1 + 2. Set up the FD sets and call select() --------------------
        # Equivalent to FD_ZERO + FD_SET for each fd, then select(nfds, ...).
        # The kernel scans EVERY fd in these lists on every call: O(n).
        try:
            readable, writable, exceptional = select.select(
                list(read_watch), list(write_watch), list(read_watch), TIMEOUT
            )
        except (OSError, ValueError) as err:
            # select() returned -1 (error), e.g. a closed fd still in a list
            print(f"select() error: {err}")
            break

        # --- 3. Return results: timeout case ------------------------------
        if not (readable or writable or exceptional):
            print(f"timeout: nothing ready, {len(read_watch) - 1} client(s) idle")
            continue

        # --- 4 + 5. Check which FDs are ready and handle them ---------------
        # (Python already did the FD_ISSET loop: these lists hold only ready FDs.)

        for sock in readable:
            if sock is server:
                # Listening socket ready -> new connection -> accept()
                client, addr = server.accept()
                client.setblocking(False)
                read_watch.append(client)
                print(f"connected: {addr}  (fd {client.fileno()})")
            else:
                # Client socket ready -> read()
                data = sock.recv(4096)
                if data:
                    outbox[sock] = outbox.get(sock, b"") + data
                    if sock not in write_watch:
                        write_watch.append(sock)
                else:
                    close(sock, read_watch, write_watch, outbox)

        for sock in writable:
            # Socket ready for writing -> write() whatever is queued
            if sock not in outbox:
                continue
            sent = sock.send(outbox[sock])
            outbox[sock] = outbox[sock][sent:]
            if not outbox[sock]:
                del outbox[sock]
                write_watch.remove(sock)

        for sock in exceptional:
            close(sock, read_watch, write_watch, outbox)


def close(sock, read_watch, write_watch, outbox):
    print(f"disconnected: fd {sock.fileno()}")
    for lst in (read_watch, write_watch):
        if sock in lst:
            lst.remove(sock)
    outbox.pop(sock, None)
    sock.close()


if __name__ == "__main__":
    main()