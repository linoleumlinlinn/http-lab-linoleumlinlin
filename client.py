import argparse
import collections
import concurrent.futures
import http.client
import json
import math
import time
from urllib.parse import urlsplit


def request(host, port, path, timeout):
    started = time.perf_counter()
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    error = None
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            error = f"HTTP {response.status}"
        else:
            payload = json.loads(body)
            if (not isinstance(payload, dict)
                    or type(payload.get("total")) is not int
                    or payload["total"] < 0
                    or not isinstance(payload.get("items"), list)
                    or len(payload["items"]) != min(10, payload["total"])):
                error = "invalid response"
    except (OSError, http.client.HTTPException, ValueError) as exc:
        error = type(exc).__name__
    finally:
        connection.close()
    return (time.perf_counter() - started) * 1000, error


def latencies(values):
    if not values:
        return None
    values = sorted(values)
    result = {"mean": round(sum(values) / len(values), 3)}
    for percentile in (50, 95, 99):
        index = math.ceil(percentile / 100 * len(values)) - 1
        result[f"p{percentile}"] = round(values[index], 3)
    result["max"] = round(values[-1], 3)
    return result


def main():
    parser = argparse.ArgumentParser(description="Fixed-concurrency HTTP load client")
    parser.add_argument("--url", default="http://127.0.0.1:8080/search?q=item")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--warmup", type=int, default=5)
    args = parser.parse_args()
    url = urlsplit(args.url)
    if url.scheme != "http" or not url.hostname or url.username or url.password or url.fragment:
        parser.error("expected an http URL without credentials or fragment")
    if args.requests < 1 or args.concurrency < 1 or args.warmup < 0:
        parser.error("requests/concurrency must be positive; warmup must be nonnegative")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be finite and positive")
    try:
        port = url.port or 80
    except ValueError as exc:
        parser.error(str(exc))
    path = url.path or "/"
    if url.query:
        path += "?" + url.query

    def run(_):
        return request(url.hostname, port, path, args.timeout)

    for index in range(args.warmup):
        _, error = run(index)
        if error:
            parser.exit(1, f"warmup failed: {error}\n")

    all_latencies = []
    successful_latencies = []
    errors = collections.Counter()
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for elapsed, error in pool.map(run, range(args.requests)):
            all_latencies.append(elapsed)
            if error:
                errors[error] += 1
            else:
                successful_latencies.append(elapsed)
    seconds = time.perf_counter() - started
    succeeded = len(successful_latencies)
    print(json.dumps({
        "url": args.url,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "timeout_seconds": args.timeout,
        "warmup": args.warmup,
        "seconds": round(seconds, 3),
        "succeeded": succeeded,
        "failed": args.requests - succeeded,
        "successful_rps": round(succeeded / seconds, 3),
        "completed_rps": round(args.requests / seconds, 3),
        "latency_ms": latencies(all_latencies),
        "successful_latency_ms": latencies(successful_latencies),
        "errors": dict(errors),
    }, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
