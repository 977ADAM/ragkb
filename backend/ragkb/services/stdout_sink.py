from __future__ import annotations

import json
from typing import Any


class StdoutSink:
    def emit(self, payload: dict[str, Any]) -> None:
        print(json.dumps(payload, ensure_ascii=False))
