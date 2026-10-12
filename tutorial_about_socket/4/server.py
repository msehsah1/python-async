# server.py — Tutorial 4: use select to wait for one client's input.
import select
import socket

HOST, PORT = "127.0.0.1", 9000
TIMEOUT = 5.0

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    print(f"Listening on {HOST}:{PORT}", flush=True)

    while True:
        # Accept still blocks here. This stage still serves one client.
        client, address = server.accept()
        print(f"Connected: {address}", flush=True)
        with client:
            try:
                while True:
                    # Watch only this client's read readiness.
                    # The empty lists mean no write or exceptional watches.
                    readable, _, _ = select.select([client], [], [], TIMEOUT)
                    if not readable:
                        print("Timeout: client has sent nothing.", flush=True)
                        continue  # A timeout does not disconnect the client.

                    # Readable can mean incoming bytes OR end of stream.
                    data = client.recv(4096)
                    if not data:
                        break
                    # Still blocking: write readiness is taught in lesson 6.
                    client.sendall(data)
            except OSError as error:
                print(f"Client connection failed: {error}")
        print(f"Disconnected: {address}", flush=True)