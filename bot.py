import os
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Stock Bot is Live!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

# รัน Web Server แยก Thread เพื่อไม่ให้รบกวนการทำงานของบอท
Thread(target=run_web_server, daemon=True).start()
