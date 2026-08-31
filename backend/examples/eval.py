"""Оценка поиска: python examples/eval.py examples/eval_set.jsonl"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ragkb.core.config import Config
from ragkb.core.evaluation import evaluate, load_cases
from ragkb.core.pipeline import RAGPipeline


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("-c", "--config", default="config.yaml")
    args = parser.parse_args()
    cfg = Config.load(args.config)
    result = evaluate(RAGPipeline(cfg), load_cases(args.cases), top_k=args.k)
    print(result.summary())
    return 0 if not result.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
