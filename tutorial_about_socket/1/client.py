# client.py — Tutorial 1: connect to the server.
import socket

HOST, PORT = "127.0.0.1", 9000

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
    # Connect to the address on which server.py is listening.
    client.connect((HOST, PORT))
    print("Connected to the server.")
    # No application data is exchanged in this first tutorial.

# Leaving the block closes this client's socket.