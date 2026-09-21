"""Public stateless answer contract."""
import json

import pytest
from fastapi.testclient import TestClient
from helpers import ScriptedChatModel, make_app

from ragkb.core.config import Settings
from ragkb.core.pipeline import build_index


@pytest.fixture
def public_app(tmp_path, monkeypatch):
    docs = tmp_path / 'docs'
    docs.mkdir()
    (docs / 'policy.md').write_text('# Отпуск\n\nЕжегодный отпуск составляет 28 календарных дней.')
    cfg = Settings(docs_dir=str(docs), index_dir=str(tmp_path / 'index'))
    cfg.database_url = ''
    cfg.store.backend = 'memory'
    cfg.logging.dir = str(tmp_path / 'logs')
    cfg.llm.base_url = 'http://llm.test/v1'
    cfg.llm.model = 'test-model'
    monkeypatch.setattr(
        'ragkb.core.pipeline.build_chat_model',
        lambda *_args, **_kwargs: ScriptedChatModel(
            responses=['Ежегодный отпуск — 28 календарных дней [1].']
        ),
    )
    build_index(cfg)
    return make_app(cfg)


def test_public_answer(public_app):
    with TestClient(public_app) as client:
        response = client.post('/api/v1/ask', json={'question': 'Сколько дней отпуска?'})
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]['type'] == 'done'
    assert events[-1]['sources']
    assert events[-1]['truncated'] is False
    assert '28' in ''.join(e.get('text', '') for e in events)
    assert 'conversation_id' not in events[-1]
    assert 'message_id' not in events[-1]
    assert 'set-cookie' not in response.headers


@pytest.mark.parametrize('body', [
    {'question': '   '}, {'question': ''}, {'question': 'вопрос', 'top_k': 0},
    {'question': 'вопрос', 'top_k': 21},
])
def test_invalid_question(public_app, body):
    with TestClient(public_app) as client:
        assert client.post('/api/v1/ask', json=body).status_code == 422


def test_unknown_model(public_app):
    with TestClient(public_app) as client:
        response = client.post('/api/v1/ask', json={'question': 'Отпуск?', 'model': 'missing'})
    assert response.status_code == 400


@pytest.mark.parametrize('method,path', [
    ('POST', '/api/v1/auths/signin'), ('GET', '/api/v1/auths/me'),
    ('GET', '/api/v1/admin/users'), ('POST', '/api/v1/organization/acme/chat_conversations'),
])
def test_removed_routes(public_app, method, path):
    with TestClient(public_app) as client:
        assert client.request(method, path, json={}).status_code == 404


@pytest.mark.parametrize('mode', ['normal', 'after'])
def test_stream_failures_and_independence(public_app, mode):
    """Два клиента не делят состояние; обрыв потока виден в truncated."""

    class Engine:
        def llm_available(self, model=None):
            return True

        def stream_answer(self, question, *, history=None, **kwargs):
            assert history is None

            def tokens():
                yield question
                if mode == 'after':
                    raise RuntimeError('interrupted')

            return [], tokens()

        def cited_sources(self, text, hits):
            return []

    public_app.state.engine = lambda: Engine()
    with TestClient(public_app) as first, TestClient(public_app) as second:
        for client, question in [(first, 'Первый вопрос'), (second, 'Второй вопрос')]:
            response = client.post('/api/v1/ask', json={'question': question})
            assert response.status_code == 200
            events = [json.loads(line) for line in response.text.splitlines()]
            assert events[-1]['type'] == 'done'
            assert events[-1]['truncated'] is (mode == 'after')
            assert events[0]['text'] == question


def test_generation_failure_before_first_token_is_reported_as_warning(public_app):
    """Поток уже открыт: причину сообщаем предупреждением, а не HTTP-кодом."""

    class Engine:
        def llm_available(self, model=None):
            return True

        def stream_answer(self, question, *, history=None, **kwargs):
            def tokens():
                raise RuntimeError('модель недоступна')
                yield  # pragma: no cover

            return [], tokens()

        def cited_sources(self, text, hits):
            return []

    public_app.state.engine = lambda: Engine()
    with TestClient(public_app) as client:
        response = client.post('/api/v1/ask', json={'question': 'Сколько дней отпуска?'})

    events = [json.loads(line) for line in response.text.splitlines()]
    assert response.status_code == 200
    assert [event['type'] for event in events] == ['done']
    assert events[0]['truncated'] is False
    assert any('Модель не ответила' in warning for warning in events[0]['warnings'])


def test_answer_without_llm_address_is_rejected_before_stream(public_app):
    """Без адреса генерации вопрос отклоняется HTTP-ошибкой, а не пустым ответом."""
    public_app.state.cfg.llm.base_url = ''

    with TestClient(public_app) as client:
        response = client.post('/api/v1/ask', json={'question': 'Сколько дней отпуска?'})

    assert response.status_code == 503
    assert 'Генерация недоступна' in response.json()['detail']
