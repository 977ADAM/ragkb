"""Бэкенды генерации.

ollama     — локальная модель (qwen2.5, llama3.1, mistral, saiga). Рекомендуется.
openai     — любой OpenAI-совместимый endpoint: vLLM, LM Studio, TGI, llama.cpp.
extractive — без LLM вообще: собирает ответ из найденных фрагментов. Нужен,
             чтобы проверить качество поиска отдельно от качества генерации, и
             как деградация, когда LLM-сервис недоступен.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from .config import LLMConfig


class LLMError(RuntimeError):
    pass


class LLM(ABC):
    name: str

    @abstractmethod
    def generate(self, system: str, user: str) -> str: ...

    def stream(self, system: str, user: str) -> Iterator[str]:
        yield self.generate(system, user)

    def available(self) -> bool:
        return True


def build_llm(cfg: LLMConfig) -> LLM:
    backend = cfg.backend.lower()
    if backend == "ollama":
        return OllamaLLM(cfg)
    if backend in {"openai", "vllm", "openai-compatible"}:
        return OpenAILLM(cfg)
    if backend in {"extractive", "none"}:
        return ExtractiveLLM(cfg)
    raise ValueError(f"Неизвестный бэкенд LLM: {cfg.backend}")


class OllamaLLM(LLM):
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self.name = f"ollama:{cfg.model}"
        self.base_url = cfg.base_url.rstrip("/")

    def available(self) -> bool:
        try:
            import httpx

            with httpx.Client(timeout=3) as client:
                return client.get(f"{self.base_url}/api/tags").status_code == 200
        except Exception:
            return False

    def generate(self, system: str, user: str) -> str:
        import httpx

        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {
                "temperature": self.cfg.temperature,
                "num_predict": self.cfg.max_tokens,
            },
        }
        try:
            with httpx.Client(timeout=self.cfg.timeout) as client:
                resp = client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                return resp.json()["message"]["content"].strip()
        except Exception as exc:
            raise LLMError(f"Ollama недоступна ({self.base_url}): {exc}") from exc

    def stream(self, system: str, user: str) -> Iterator[str]:
        import json

        import httpx

        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": True,
            "options": {
                "temperature": self.cfg.temperature,
                "num_predict": self.cfg.max_tokens,
            },
        }
        with (
            httpx.Client(timeout=self.cfg.timeout) as client,
            client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp,
        ):
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    piece = data.get("message", {}).get("content", "")
                    if piece:
                        yield piece


class OpenAILLM(LLM):
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self.name = f"openai:{cfg.model}"
        self.base_url = cfg.base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.cfg.api_key}"} if self.cfg.api_key else {}

    def available(self) -> bool:
        try:
            import httpx

            with httpx.Client(timeout=3, headers=self._headers()) as client:
                return client.get(f"{self.base_url}/models").status_code < 500
        except Exception:
            return False

    def generate(self, system: str, user: str) -> str:
        import httpx

        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
        }
        try:
            with httpx.Client(timeout=self.cfg.timeout, headers=self._headers()) as client:
                resp = client.post(f"{self.base_url}/chat/completions", json=payload)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            raise LLMError(f"LLM-эндпоинт недоступен ({self.base_url}): {exc}") from exc


class ExtractiveLLM(LLM):
    """Фолбэк без нейросети: возвращает найденные фрагменты как есть."""

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self.name = "extractive"

    def generate(self, system: str, user: str) -> str:
        fragments = _extract_context_fragments(user)
        if not fragments:
            return "В базе знаний не найдено релевантной информации по этому вопросу."
        lines = ["Ответ собран из найденных фрагментов (LLM отключена):", ""]
        for marker, text in fragments[:3]:
            snippet = text.strip()
            if len(snippet) > 600:
                snippet = snippet[:600].rsplit(" ", 1)[0] + "…"
            lines.append(f"{marker} {snippet}")
            lines.append("")
        return "\n".join(lines).strip()


def _extract_context_fragments(prompt: str) -> list[tuple[str, str]]:
    """Разбирает промпт обратно на фрагменты вида [1] ... — только для фолбэка."""
    import re

    # Контекст ограничен блоком между «КОНТЕКСТ:» и «ВОПРОС:» — иначе в
    # «фрагмент» попадут сами инструкции промпта.
    body = prompt
    if "КОНТЕКСТ:" in body:
        body = body.split("КОНТЕКСТ:", 1)[1]
    body = re.split(r"\n\s*ВОПРОС:", body)[0]

    fragments = []
    pattern = re.compile(r"^\[(\d+)\][^\n]*\n(.*?)(?=\n\[\d+\]|\Z)", re.DOTALL | re.MULTILINE)
    for match in pattern.finditer(body):
        fragments.append((f"[{match.group(1)}]", match.group(2)))
    return fragments
