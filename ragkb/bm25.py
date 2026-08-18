"""BM25 (Okapi) на инвертированном индексе.

Реализован вручную, чтобы не тащить зависимость и чтобы индекс сериализовался
вместе с остальным состоянием. Для корпусов до сотен тысяч чанков этого хватает
с запасом; дальше имеет смысл вынести лексический поиск в OpenSearch/Elastic.
"""
from __future__ import annotations

import math
import pickle
from collections import defaultdict
from pathlib import Path
from typing import Sequence

from .text import tokenize

K1 = 1.5   # насыщение по частоте термина
B = 0.75   # степень нормализации по длине документа


class BM25Index:
    def __init__(self) -> None:
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.doc_len: list[int] = []
        self.avg_len: float = 0.0
        self.n_docs: int = 0

    def build(self, texts: Sequence[str]) -> "BM25Index":
        self.postings = defaultdict(list)
        self.doc_len = []
        for doc_id, text in enumerate(texts):
            tokens = tokenize(text)
            self.doc_len.append(len(tokens))
            counts: dict[str, int] = defaultdict(int)
            for token in tokens:
                counts[token] += 1
            for term, freq in counts.items():
                self.postings[term].append((doc_id, freq))
        self.n_docs = len(texts)
        self.avg_len = (sum(self.doc_len) / self.n_docs) if self.n_docs else 0.0
        return self

    def search(self, query: str, top_k: int = 30) -> list[tuple[int, float]]:
        if not self.n_docs:
            return []
        scores: dict[int, float] = defaultdict(float)
        for term in set(tokenize(query)):
            postings = self.postings.get(term)
            if not postings:
                continue
            # IDF в варианте с +0.5 (Robertson/Sparck Jones), обрезанный снизу нулём.
            df = len(postings)
            idf = math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))
            for doc_id, freq in postings:
                dl = self.doc_len[doc_id] or 1
                denom = freq + K1 * (1 - B + B * dl / (self.avg_len or 1))
                scores[doc_id] += idf * (freq * (K1 + 1)) / denom
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return ranked[:top_k]

    # ------------------------------------------------------------ персистентность

    def save(self, path: str | Path) -> None:
        payload = {
            "postings": dict(self.postings),
            "doc_len": self.doc_len,
            "avg_len": self.avg_len,
            "n_docs": self.n_docs,
        }
        Path(path).write_bytes(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))

    @classmethod
    def load(cls, path: str | Path) -> "BM25Index":
        index = cls()
        payload = pickle.loads(Path(path).read_bytes())
        index.postings = defaultdict(list, payload["postings"])
        index.doc_len = payload["doc_len"]
        index.avg_len = payload["avg_len"]
        index.n_docs = payload["n_docs"]
        return index
