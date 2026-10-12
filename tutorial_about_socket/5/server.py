# server.py — Tutorial 5: monitor several clients in one event loop.
import select
import socket

HOST, PORT = "127.0.0.1", 9000
TIMEOUT = 5.0


def close_client(sock, read_watch):
    # Remove the socket BEFORE closing so select never sees a closed FD.
    print(f"Disconnected: fd {sock.fileno()}", flush=True)
    if sock in read_watch:
        read_watch.remove(sock)
    sock.close()


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen()

        # The listening socket and connected sockets share the read watch.
        read_watch = [server]
        print(f"Listening on {HOST}:{PORT}", flush=True)
        try:
            while True:
                readable, _, _ = select.select(read_watch, [], [], TIMEOUT)
                if not readable:
                    print(f"Timeout: {len(read_watch) - 1} client(s).", flush=True)
                    continue

                for sock in readable:
                    if sock is server:
                        # A readable listener has a connection to accept.
                        client, address = server.accept()
                        read_watch.append(client)
                        print(f"Connected: {address}", flush=True)
                    else:
                        try:
                            data = sock.recv(4096)
                            if data:
                                # Deliberate intermediate limitation:
                                # a slow receiver can block this sendall.
                                sock.sendall(data)
                            else:
                                close_client(sock, read_watch)
                        except OSError as error:
                            print(f"Client connection failed: {error}")
                            close_client(sock, read_watch)
        finally:
            # The outer context manager closes the listening socket.
            for sock in read_watch:
                if sock is not server:
                    sock.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nServer stopped.")