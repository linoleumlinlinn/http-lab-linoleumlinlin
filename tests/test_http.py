import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.data = Path(cls.directory.name) / "catalog.jsonl"
        cls.records = [
            {"id": index, "title": f"Book {index}", "score": index // 2}
            for index in range(14)
        ] + [{"id": 99, "title": "Lamp", "score": 100}]
        cls.data.write_text(
            "".join(json.dumps(row) + "\n" for row in reversed(cls.records)),
            encoding="utf-8",
        )
        cls.log = tempfile.TemporaryFile(mode="w+t")
        cls.server = subprocess.Popen(
            [sys.executable, str(ROOT / "server.py"), "--port", "0", "--data", str(cls.data)],
            stdout=subprocess.PIPE, stderr=cls.log, text=True,
        )
        line = cls.server.stdout.readline().strip()
        if not line.startswith("listening on http://127.0.0.1:"):
            cls.server.kill()
            cls.server.communicate()
            cls.log.seek(0)
            error = cls.log.read()
            cls.log.close()
            cls.directory.cleanup()
            raise RuntimeError(f"server failed to start: {line}\n{error}")
        cls.port = int(line.rsplit(":", 1)[1])
        cls.url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.communicate(timeout=5)
        cls.log.close()
        cls.directory.cleanup()

    def get(self, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            body = response.read()
            self.assertEqual(int(response.getheader("Content-Length")), len(body))
            return response.status, json.loads(body)
        finally:
            connection.close()

    def test_search_contract(self):
        status, payload = self.get("/search?q=bOoK")
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 14)
        self.assertEqual([row["id"] for row in payload["items"]],
                         [12, 13, 10, 11, 8, 9, 6, 7, 4, 5])
        self.assertEqual(payload["items"][0], self.records[12])

    def test_empty_result(self):
        self.assertEqual(self.get("/search?q=missing"), (200, {"total": 0, "items": []}))

    def test_query_decoding(self):
        status, payload = self.get("/search?q=Book%2012")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"total": 1, "items": [self.records[12]]})

    def test_invalid_queries(self):
        for path in ("/search", "/search?q=", "/search?q=a&q=b",
                     "/search?q=a&extra=b", "/search?q=" + "a" * 65):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], 400)

    def test_not_found(self):
        self.assertEqual(self.get("/unknown")[0], 404)

    def test_catalog_error(self):
        original = self.data.read_bytes()
        try:
            self.data.write_text("not JSON\n", encoding="utf-8")
            self.assertEqual(self.get("/search?q=book")[0], 500)
        finally:
            self.data.write_bytes(original)

    def run_client(self, path):
        result = subprocess.run(
            [sys.executable, str(ROOT / "client.py"), "--url", self.url + path,
             "--requests", "12", "--concurrency", "3", "--warmup", "0"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode, json.loads(result.stdout)

    def test_load_success(self):
        code, report = self.run_client("/search?q=book")
        self.assertEqual(code, 0)
        self.assertEqual((report["succeeded"], report["failed"]), (12, 0))
        self.assertGreater(report["successful_rps"], 0)
        latency = report["latency_ms"]
        self.assertLessEqual(latency["p50"], latency["p95"])
        self.assertLessEqual(latency["p95"], latency["p99"])
        self.assertLessEqual(latency["p99"], latency["max"])

    def test_load_errors_are_not_successes(self):
        code, report = self.run_client("/unknown")
        self.assertEqual(code, 1)
        self.assertEqual((report["succeeded"], report["failed"]), (0, 12))
        self.assertEqual(report["successful_rps"], 0)
        self.assertIsNone(report["successful_latency_ms"])
        self.assertEqual(report["errors"], {"HTTP 404": 12})


if __name__ == "__main__":
    unittest.main()
