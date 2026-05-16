"""
Softline Theory - Vote & Email Capture Backend
Zero dependencies. Stores to local JSON files.
"""
import http.server
import json
import os
import uuid
from datetime import datetime
from urllib.parse import urlparse, parse_qs

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WEBSITE_DIR = os.path.dirname(SCRIPT_DIR)  # one level up from api/
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
VOTES_FILE = os.path.join(DATA_DIR, "votes.json")
EMAILS_FILE = os.path.join(DATA_DIR, "emails.json")

os.makedirs(DATA_DIR, exist_ok=True)

PRODUCTS = ["lace-bow-tote", "canvas-bear-tote", "chain-hobo", "winged-tote", "turn-lock-flap"]

def load_json(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return []

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

class Handler(http.server.BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length).decode())
        return {}

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        # API routes
        if parsed.path == "/api/votes":
            votes = load_json(VOTES_FILE)
            counts = {p: sum(1 for v in votes if v["product_id"] == p) for p in PRODUCTS}
            self._send_json({"counts": counts, "total_votes": len(votes)})
            return

        if parsed.path == "/api/emails/count":
            self._send_json({"count": len(load_json(EMAILS_FILE))})
            return

        # Static file serving from website directory
        if parsed.path == "/":
            filepath = os.path.join(WEBSITE_DIR, "index.html")
        else:
            filepath = os.path.join(WEBSITE_DIR, parsed.path.lstrip("/"))

        # Security: ensure we don't serve files outside website dir
        filepath = os.path.normpath(filepath)
        if not filepath.startswith(os.path.normpath(WEBSITE_DIR)):
            self.send_error(403)
            return

        if os.path.isfile(filepath):
            ext = os.path.splitext(filepath)[1]
            content_types = {
                ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".gif": "image/gif", ".svg": "image/svg+xml", ".ico": "image/x-icon",
                ".json": "application/json", ".webp": "image/webp"
            }
            ct = content_types.get(ext, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.end_headers()
            with open(filepath, "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/vote":
            data = self._read_body()
            product_id = data.get("product_id", "")
            if product_id not in PRODUCTS:
                self._send_json({"error": "Invalid product"}, 400)
                return

            vote = {
                "id": str(uuid.uuid4())[:8],
                "product_id": product_id,
                "email": data.get("email", "").strip().lower(),
                "color": data.get("color", ""),
                "size": data.get("size", ""),
                "timestamp": datetime.utcnow().isoformat(),
                "ip": self.client_address[0]
            }
            votes = load_json(VOTES_FILE)
            votes.append(vote)
            save_json(VOTES_FILE, votes)
            print(f"[VOTE] {product_id} | {vote['color']} | {vote['size']} | {vote['email'] or 'anon'}")
            self._send_json({"success": True, "vote_id": vote["id"]})
            return

        if parsed.path == "/api/waitlist":
            data = self._read_body()
            email = data.get("email", "").strip().lower()
            if not email or "@" not in email:
                self._send_json({"error": "Valid email required"}, 400)
                return

            emails = load_json(EMAILS_FILE)
            if any(e["email"] == email for e in emails):
                self._send_json({"success": True, "message": "Already registered"})
                return

            entry = {
                "id": str(uuid.uuid4())[:8],
                "email": email,
                "source": data.get("source", "waitlist"),
                "timestamp": datetime.utcnow().isoformat(),
                "ip": self.client_address[0]
            }
            emails.append(entry)
            save_json(EMAILS_FILE, emails)
            print(f"[EMAIL] {email} | source: {entry['source']}")
            self._send_json({"success": True, "email_id": entry["id"]})
            return

        self.send_error(404)

    def log_message(self, fmt, *args):
        pass  # Quiet

if __name__ == "__main__":
    PORT = 8181
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Softline Theory backend + static server")
    print(f"  http://localhost:{PORT}")
    print(f"  Website: {WEBSITE_DIR}")
    print(f"  Data:    {DATA_DIR}")
    print()
    print("  POST /api/vote      - Record a product vote")
    print("  POST /api/waitlist  - Record email signup")
    print("  GET  /api/votes     - Get vote counts per product")
    print("  GET  /api/emails/count - Get total email signups")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()
