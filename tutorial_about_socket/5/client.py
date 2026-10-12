# client.py — Interactive client for Tutorial 5.
import socket

HOST, PORT = "127.0.0.1", 9000

def receive_exactly(sock, size):
    # TCP can split a reply across multiple recv calls. Because this is an
    # echo service, we know the reply must contain as many bytes as we sent.
    result = bytearray()
    while len(result) < size:
        chunk = sock.recv(size - len(result))
        if not chunk:
            raise ConnectionError("Server closed before the full echo arrived.")
        result.extend(chunk)
    return bytes(result)


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.connect((HOST, PORT))
        print("Connected. Type text, or /quit to leave.")
        while True:
            text = input("> ")
            if text == "/quit":
                break  # /quit is a local command; it is not sent.

            # A newline makes even an empty input line a nonempty payload.
            # Count encoded bytes, since UTF-8 characters may use >1 byte.
            payload = (text + "\n").encode("utf-8")
            client.sendall(payload)
            reply = receive_exactly(client, len(payload))
            print("Echo:", reply.decode("utf-8"), end="")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nClient stopped.")
    except OSError as error:
        print(f"Connection error: {error}")