"""
File descriptors and sockets, step by step (same story as the interactive demo).

  1. A new process already has fd 0, 1, 2 (stdin, stdout, stderr)
  2. FDs are just integers: you can write to fd 1 directly
  3. socket + bind + listen  -> listening socket gets the lowest free fd (3)
  4. Two clients connect     -> accept() creates a NEW socket per client (4, 5)
  5. Read from a client using only its fd number
  6. close(4), accept again  -> the new client reuses fd 4
  7. open() a regular file   -> files and sockets share the same numbering

The clients run as separate processes on purpose: each process has its OWN
FD table, so the client sockets don't take numbers in the server's table.

Run:  python3 fd_sockets_demo.py      (Linux or macOS)
"""

import os
import socket
import subprocess
import sys
import tempfile
import time


def show_table(title):
    """Print this process's FD table. On Linux we ask the kernel directly."""
    print(f"\n--- FD table: {title} ---")
    proc_dir = "/proc/self/fd"
    if os.path.isdir(proc_dir):                      # Linux: kernel's real view
        for name in sorted(os.listdir(proc_dir), key=int):
            try:
                target = os.readlink(f"{proc_dir}/{name}")
            except OSError:
                continue                             # the fd used to list the dir itself
            print(f"  fd {name:>2} -> {target}")
    else:                                            # macOS: list open numbers
        fds = sorted(int(n) for n in os.listdir("/dev/fd"))
        print("  open fds:", fds)


def start_client(port, message):
    """Launch a separate process that connects, sends a message, then waits."""
    code = (
        "import socket, time\n"
        f"s = socket.create_connection(('127.0.0.1', {port}))\n"
        f"s.sendall({message!r})\n"
        "time.sleep(3)\n"
    )
    return subprocess.Popen([sys.executable, "-c", code])


def main():
    # 1. A fresh process starts with 0, 1, 2 already open
    show_table("process just started")

    # 2. FDs are plain integers. Writing to fd 1 is writing to stdout.
    os.write(1, b"\n[step 2] this line was written with os.write(1, ...)\n")

    # 3. Listening socket: socket() + bind() + listen()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))            # port 0 = let the OS pick a free port
    server.listen()
    port = server.getsockname()[1]
    print(f"\n[step 3] listening socket: fd {server.fileno()}, port {port}")
    show_table("after listen()")

    # 4. Two clients connect; accept() gives each one a brand-new socket
    clients = [start_client(port, b"hello from client A"),
               start_client(port, b"hello from client B")]
    conn_a, addr_a = server.accept()
    conn_b, addr_b = server.accept()
    print(f"\n[step 4] accepted {addr_a} -> fd {conn_a.fileno()}")
    print(f"         accepted {addr_b} -> fd {conn_b.fileno()}")
    print(f"         listening socket is still fd {server.fileno()}, untouched")
    show_table("after two accept() calls")

    # 5. Read using only the integer, no socket object methods
    fd_a = conn_a.fileno()
    data = os.read(fd_a, 100)
    print(f"\n[step 5] os.read({fd_a}, 100) -> {data!r}")

    # 6. Close fd 4, accept another client: the lowest free number is reused
    freed = conn_a.fileno()
    conn_a.close()
    print(f"\n[step 6] closed fd {freed}")
    clients.append(start_client(port, b"hello from client C"))
    conn_c, addr_c = server.accept()
    print(f"         accepted {addr_c} -> fd {conn_c.fileno()}  (reused!)")

    # 7. A regular file gets the next lowest free number, same table
    path = os.path.join(tempfile.gettempdir(), "notes.txt")
    f = open(path, "w")
    print(f"\n[step 7] open({path!r}) -> fd {f.fileno()}")
    show_table("final")

    # Cleanup
    f.close()
    for s in (conn_b, conn_c, server):
        s.close()
    for p in clients:
        p.terminate()
    os.remove(path)


if __name__ == "__main__":
    main()