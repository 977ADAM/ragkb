"""Промпты: правила про контекст отделены от задачи прислать оригинал.

Замер на рабочей модели показал, что требование «нет ответа в контексте — так и
скажи» перебивает просьбу прислать файл: вызов инструмента пропадал ровно
тогда, когда контекст был. Поэтому шаг с инструментом повторяется в самом
вопросе, а не только в системных правилах, и эти тесты следят за тем, чтобы
такая оговорка не потерялась при правке формулировок.
"""
from __future__ import annotations

from ragkb.core.prompts import (
    DOWNLOAD_POLICY,
    SYSTEM_PROMPT,
    TOOL_ANSWER_TEMPLATE,
    TOOL_SYSTEM_PROMPT,
)
from ragkb.core.tool_answers import TOOL_DEFINITION

TOOL_NAME = TOOL_DEFINITION["function"]["name"]


def test_context_rules_say_they_cover_only_the_answer_text():
    """Правила 1–3 описывают текст ответа, а не всю задачу вопроса."""
    assert "не отменяют остальные задачи вопроса" in SYSTEM_PROMPT
    assert "базе знаний нет информации" in SYSTEM_PROMPT


def test_tool_answer_repeats_the_request_next_to_the_question():
    """Просьба о файле стоит в самом вопросе и не зависит от контекста."""
    text = TOOL_ANSWER_TEMPLATE.format(context="контекст", question="вопрос", downloads="один")

    assert TOOL_NAME in text
    assert "Порядок действий" in text
    assert "не отменяет шаг 2" in text
    assert "не пересказывай его" in text
    assert text.index("Порядок действий") > text.index("ВОПРОС")


def test_download_policy_asks_for_the_tool_even_with_a_context_answer():
    assert "даже если ответ есть в контексте" in DOWNLOAD_POLICY
    assert "ОРИГИНАЛЫ" in DOWNLOAD_POLICY


def test_tool_prompt_joins_both_blocks():
    assert SYSTEM_PROMPT in TOOL_SYSTEM_PROMPT
    assert DOWNLOAD_POLICY in TOOL_SYSTEM_PROMPT
