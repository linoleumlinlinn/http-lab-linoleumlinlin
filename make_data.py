import argparse
import json
import random
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Generate a reproducible catalog")
    parser.add_argument("--rows", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("data/catalog.jsonl"))
    args = parser.parse_args()
    if args.rows < 1:
        parser.error("rows must be positive")
    rng = random.Random(args.seed)
    colors = ["Red", "Green", "Blue", "White", "Black"]
    products = ["Book", "Lamp", "Chair", "Table", "Bag"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as target:
        for item_id in range(args.rows):
            record = {
                "id": item_id,
                "title": f"Item {item_id} {rng.choice(colors)} {rng.choice(products)}",
                "score": rng.randrange(10000),
            }
            target.write(json.dumps(record) + "\n")
    print(f"wrote {args.rows} rows to {args.output}")


if __name__ == "__main__":
    main()
