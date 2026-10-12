# server.py — Tutorial 1: accept one TCP connection.
import socket

HOST, PORT = "127.0.0.1", 9000

# AF_INET selects IPv4; SOCK_STREAM selects a TCP stream.
# The context manager closes the socket when this block finishes.
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    # Helps reuse the address after restarting on systems that support it.
    # This does not let you run two tutorial servers on the same port.
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))  # Choose this server's local address.
    server.listen()          # Allow incoming connections to queue.
    print(f"Waiting on {HOST}:{PORT}", flush=True)
    # Blocks until a connection is available. The listening socket stays
    # separate from the new socket used to talk to this particular client.
    client, address = server.accept()
    with client:
        print(f"Connected: {address}")

# This first example accepts once, closes both sockets, then exits.