# A tiny local web server for testing fetch_10_urls.py.
# GET /delay/0.8 waits 0.8 seconds before answering, so you can see
# responses arrive in a different order than the requests were sent.
#
# Run it in one terminal:   python3 slow_server.py
# Then in another:          python3 fetch_10_urls.py --compare
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class SlowHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        m = re.match(r"/delay/([\d.]+)", self.path)
        delay = float(m.group(1)) if m else 0.0
        time.sleep(delay)
        body = f"waited {delay}s for {self.path}\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass                                    # keep the terminal quiet


class Server(ThreadingHTTPServer):
    # Listen backlog: how many new connections the kernel queues before accept().
    # Python's default is 5; with 10 simultaneous connects the extra ones get dropped
    # and the client's TCP retries after 1 second. 128 avoids that.
    request_queue_size = 128


if __name__ == "__main__":
    print("slow server on http://127.0.0.1:8000  (try /delay/1)")
    Server(("127.0.0.1", 8000), SlowHandler).serve_forever()