# client.py — Tutorial 2: send one byte and receive its echo.
import socket

HOST, PORT = "127.0.0.1", 9000

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
    client.connect((HOST, PORT))
    # The b prefix creates bytes. The network carries bytes, not Python str.
    client.sendall(b"A")
    reply = client.recv(1)
    if reply:
        print("Echo:", reply.decode("utf-8"))
    else:
        print("Server closed before replying.")