# server.py — Tutorial 2: echo exactly one byte.
import socket

HOST, PORT = "127.0.0.1", 9000

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    print(f"Waiting on {HOST}:{PORT}", flush=True)

    client, address = server.accept()
    with client:
        # Our tiny protocol allows exactly one byte for this lesson.
        # recv(1) waits for up to one byte, or returns b"" at end of stream.
        data = client.recv(1)
        if data:
            print(f"Received from {address}: {data!r}")
            # On a blocking socket, sendall sends all these bytes or raises.
            client.sendall(data)
        else:
            print("Client closed without sending a byte.")