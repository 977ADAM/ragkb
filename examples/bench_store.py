"""Сравнение бэкендов хранилища на синтетических векторах.

Запуск: python examples/bench_store.py [число_чанков] [размерность]

Показывает, с какого объёма ANN-индекс Chroma начинает выигрывать у точного
перебора. Обратите внимание на колонку recall: HNSW — приближённый поиск,
и часть правильных соседей он теряет. Насколько — зависит от hnsw_search_ef.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np


def bench(n: int = 50_000, dim: int = 384, queries: int = 20, top_k: int = 10) -> None:
    rng = np.random.default_rng(0)
    # Векторы кластеризованы вокруг случайных центров: настоящие эмбеддинги
    # тоже группируются по темам. На равномерном шуме HNSW выглядит гораздо
    # хуже (recall падает до ~60%), но это artefact теста, а не реальности —
    # в шуме все точки почти равноудалены, и приближённому поиску не за что
    # зацепиться.
    centers = rng.standard_normal((max(2, n // 100), dim), dtype=np.float32)
    vectors = centers[rng.integers(0, len(centers), n)] + 0.35 * rng.standard_normal(
        (n, dim), dtype=np.float32
    )
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    probes = vectors[rng.choice(n, queries, replace=False)]

    # --- эталон: точный перебор
    t0 = time.perf_counter()
    exact = []
    for q in probes:
        scores = vectors @ q
        idx = np.argpartition(-scores, top_k)[:top_k]
        exact.append(set(idx[np.argsort(-scores[idx])].tolist()))
    numpy_ms = (time.perf_counter() - t0) / queries * 1000

    print(f"чанков: {n}, размерность: {dim}, top-{top_k}")
    print(f"  numpy (точный перебор): {numpy_ms:6.1f} мс/запрос, "
          f"{vectors.nbytes / 2**20:.0f} МБ RAM")

    # --- Chroma
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError:
        print("  chroma: не установлена (pip install chromadb)")
        return

    import shutil
    import tempfile

    path = tempfile.mkdtemp()
    client = chromadb.PersistentClient(path=path, settings=Settings(anonymized_telemetry=False))
    collection = client.create_collection(
        "bench_collection", metadata={"hnsw:space": "cosine"}, embedding_function=None
    )

    t0 = time.perf_counter()
    batch = 5000
    for i in range(0, n, batch):
        collection.add(
            ids=[str(j) for j in range(i, min(i + batch, n))],
            embeddings=[v.tolist() for v in vectors[i : i + batch]],
        )
    build_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    recalls = []
    for q, truth in zip(probes, exact, strict=False):
        res = collection.query(query_embeddings=[q.tolist()], n_results=top_k)
        got = {int(i) for i in res["ids"][0]}
        recalls.append(len(got & truth) / top_k)
    chroma_ms = (time.perf_counter() - t0) / len(probes) * 1000

    print(f"  chroma (HNSW):          {chroma_ms:6.1f} мс/запрос, "
          f"сборка {build_s:.1f} с, recall@{top_k} {np.mean(recalls):.1%}")
    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50_000
    dim = int(sys.argv[2]) if len(sys.argv) > 2 else 384
    bench(n, dim)
