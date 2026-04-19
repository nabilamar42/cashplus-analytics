"""Client OSRM Table API. Batche automatiquement pour respecter les limites."""
from __future__ import annotations
import requests
from concurrent.futures import ThreadPoolExecutor

BATCH_SRC = 100
BATCH_DST = 100
MAX_THREADS = 10


class HttpOsrmClient:
    def __init__(self, base_url: str = "http://localhost:5001", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _table_batch(self, sources, destinations):
        coords = sources + destinations
        coord_str = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in coords)
        params = {
            "sources": ";".join(str(i) for i in range(len(sources))),
            "destinations": ";".join(str(i) for i in range(len(sources),
                                                           len(sources) + len(destinations))),
            "annotations": "distance,duration",
        }
        r = requests.get(
            f"{self.base_url}/table/v1/driving/{coord_str}",
            params=params, timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
        return data["distances"], data["durations"]

    def table(self, sources, destinations):
        """sources/destinations: list[(lon, lat)]. Retourne (dist_m, dur_s) NxM."""
        ns, nd = len(sources), len(destinations)
        dist = [[None] * nd for _ in range(ns)]
        dur = [[None] * nd for _ in range(ns)]

        batches = []
        for i in range(0, ns, BATCH_SRC):
            for j in range(0, nd, BATCH_DST):
                batches.append((i, j, sources[i:i+BATCH_SRC], destinations[j:j+BATCH_DST]))

        def run(batch):
            i, j, src, dst = batch
            return i, j, *self._table_batch(src, dst)

        with ThreadPoolExecutor(max_workers=MAX_THREADS) as ex:
            for i, j, d, t in ex.map(run, batches):
                for bi, row in enumerate(d):
                    for bj, v in enumerate(row):
                        dist[i + bi][j + bj] = v
                for bi, row in enumerate(t):
                    for bj, v in enumerate(row):
                        dur[i + bi][j + bj] = v
        return dist, dur

    def ping(self) -> bool:
        try:
            r = requests.get(
                f"{self.base_url}/route/v1/driving/-6.851,33.991;-7.589,33.573",
                params={"overview": "false"}, timeout=5,
            )
            return r.status_code == 200
        except Exception:
            return False
