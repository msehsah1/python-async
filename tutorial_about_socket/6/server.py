# server.py — Tutorial 6: complete nonblocking select echo server.
import select
import socket

HOST, PORT = "127.0.0.1", 9000
TIMEOUT = 5.0


def close_client(sock, read_watch, write_watch, outbox, read_eof):
    # Clean every tracking structure, then release the OS socket.
    print(f"Disconnected: fd {sock.fileno()}", flush=True)
    for watch in (read_watch, write_watch):
        if sock in watch:
            watch.remove(sock)
    outbox.pop(sock, None)
    read_eof.discard(sock)
    sock.close()


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen()
        server.setblocking(False)  # accept must never wait for a client.

        read_watch = [server]  # Listener plus clients whose input we want.
        write_watch = []      # Only clients with unsent outgoing bytes.
        outbox = {}           # socket -> bytes still waiting to be sent.
        read_eof = set()      # Peers that ended input; drain their output.
        print(f"select echo server on {HOST}:{PORT}", flush=True)

        try:
            while True:
                # 1. Build the sets we want to watch.
                # Include draining peers, which are no longer read-watched.
                exception_watch = list(set(read_watch) | set(write_watch))
                try:
                    # 2. Wait for readiness. This wait may block for 5 seconds,
                    # even though the individual sockets are nonblocking.
                    # Python does not mutate our input watch lists; the list()
                    # copies mirror the supplied example but are optional.
                    readable, writable, exceptional = select.select(
                        list(read_watch), list(write_watch),
                        exception_watch, TIMEOUT,
                    )
                except (OSError, ValueError) as error:
                    print(f"select error: {error}")
                    break

                # 3. Empty result lists mean the wait timed out.
                if not (readable or writable or exceptional):
                    count = len(set(read_watch) | set(write_watch)) - 1
                    print(f"Timeout: nothing ready, {count} client(s).", flush=True)
                    continue

                # Exceptional readiness is not a general error list.
                # This simple protocol closes peers with exceptional events,
                # such as TCP urgent data. Normal I/O errors are caught below.
                if server in exceptional:
                    print("Exceptional condition on listening socket.")
                    break
                for sock in exceptional:
                    close_client(sock, read_watch, write_watch, outbox, read_eof)

                # 4 + 5. Python returns ready sockets; dispatch their work.
                for sock in readable:
                    if sock not in read_watch:
                        continue  # It may have been closed above.

                    if sock is server:
                        try:
                            client, address = server.accept()
                        except BlockingIOError:
                            continue  # Readiness may have changed; retry later.
                        except OSError as error:
                            print(f"accept failed: {error}")
                            continue
                        client.setblocking(False)
                        read_watch.append(client)
                        print(f"Connected: {address} (fd {client.fileno()})", flush=True)
                    else:
                        try:
                            data = sock.recv(4096)
                        except BlockingIOError:
                            continue  # No bytes available right now.
                        except OSError as error:
                            print(f"recv failed: {error}")
                            close_client(sock, read_watch, write_watch, outbox, read_eof)
                            continue

                        if data:
                            # Queue bytes first; send only after write readiness.
                            outbox[sock] = outbox.get(sock, b"") + data
                            if sock not in write_watch:
                                write_watch.append(sock)
                        else:
                            # b"" means EOF, not "try again later".
                            # Stop reading, but preserve any unsent echo data.
                            read_watch.remove(sock)
                            if sock in outbox:
                                read_eof.add(sock)
                            else:
                                close_client(sock, read_watch, write_watch, outbox, read_eof)

                for sock in writable:
                    if sock not in outbox:
                        continue  # Another handler may already have closed it.
                    try:
                        # send returns the number accepted by the OS buffer.
                        # It may accept only PART of the queued bytes.
                        sent = sock.send(outbox[sock])
                    except BlockingIOError:
                        continue  # Keep all queued bytes and retry next time.
                    except OSError as error:
                        print(f"send failed: {error}")
                        close_client(sock, read_watch, write_watch, outbox, read_eof)
                        continue

                    if sent == 0:
                        close_client(sock, read_watch, write_watch, outbox, read_eof)
                        continue

                    # Remove only the bytes that were actually sent.
                    outbox[sock] = outbox[sock][sent:]
                    if not outbox[sock]:
                        del outbox[sock]
                        write_watch.remove(sock)  # Avoid constant write wakeups.
                        if sock in read_eof:
                            close_client(sock, read_watch, write_watch, outbox, read_eof)
        finally:
            # Also close connected sockets if Ctrl+C interrupts the event loop.
            clients = (set(read_watch) | set(write_watch) | read_eof) - {server}
            for sock in clients:
                sock.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nServer stopped.")