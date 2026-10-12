# server.py — Tutorial 3: repeated messages, one client at a time.
import socket

HOST, PORT = "127.0.0.1", 9000

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    print(f"Listening on {HOST}:{PORT}", flush=True)

    while True:  # Outer loop accepts the next client.
        client, address = server.accept()
        print(f"Connected: {address}", flush=True)
        with client:
            try:
                while True:  # Inner loop serves only this client.
                    # 4096 is a maximum chunk size, not a message boundary.
                    data = client.recv(4096)
                    if not data:  # b"" means the peer ended its sending side.
                        break
                    client.sendall(data)  # Echo this chunk unchanged.
            except OSError as error:
                print(f"Client connection failed: {error}")
        print(f"Disconnected: {address}", flush=True)