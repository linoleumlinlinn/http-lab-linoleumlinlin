import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


class CatalogServer(HTTPServer):
    request_queue_size = 32


catalog_cache = {}


def search(path, query):
    modified_at = path.stat().st_mtime_ns
    saved_time, records = catalog_cache.get(path, (None, None))
    if saved_time != modified_at:
        with path.open(encoding="utf-8") as source:
            records = [json.loads(line) for line in source]
        records.sort(key=lambda record: (-record["score"], record["id"]))
        records = [(record["title"].lower(), record) for record in records]
        catalog_cache[path] = (modified_at, records)
    total = 0
    items = []
    query = query.lower()
    for title_lower, record in records:
        if query in title_lower:
            total += 1
            if total <= 10:
                items.append(record)
    return {"total": total, "items": items}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    timeout = 5

    def reply(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path != "/search":
            self.reply(404, {"error": "not found"})
            return
        params = parse_qs(url.query, keep_blank_values=True)
        queries = params.get("q", [])
        if set(params) != {"q"} or len(queries) != 1 or not 1 <= len(queries[0]) <= 64:
            self.reply(400, {"error": "expected one q, 1..64 characters"})
            return
        try:
            result = search(self.server.data_path, queries[0])
        except (OSError, ValueError, KeyError, TypeError):
            self.reply(500, {"error": "cannot read catalog"})
            return
        self.reply(200, result)


def main():
    parser = argparse.ArgumentParser(description="Single-threaded catalog search")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data", type=Path, default=Path("data/catalog.jsonl"))
    args = parser.parse_args()
    if not args.data.is_file():
        parser.error(f"catalog does not exist: {args.data}")
    with CatalogServer((args.host, args.port), Handler) as server:
        server.data_path = args.data
        print(f"listening on http://{args.host}:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
