"""Public stateless answer contract."""
import json

import pytest
from fastapi.testclient import TestClient
from helpers import make_app

from ragkb.core.config import Settings
from ragkb.core.pipeline import build_index


@pytest.fixture
def public_app(tmp_path):
    docs = tmp_path / 'docs'
    docs.mkdir()
    (docs / 'policy.md').write_text('# Отпуск\n\nЕжегодный отпуск составляет 28 календарных дней.')
    cfg = Settings(docs_dir=str(docs), index_dir=str(tmp_path / 'index'))
    cfg.database_url = ''
    cfg.store.backend = 'numpy'
    cfg.logging.dir = str(tmp_path / 'logs')
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


@pytest.mark.parametrize('mode', ['normal', 'before', 'after'])
def test_stream_failures_and_independence(public_app, mode):
    class Engine:
        def stream_answer(self, question, *, history=None, **kwargs):
            assert history is None
            def tokens():
                if mode == 'before':
                    raise RuntimeError('unavailable')
                yield question
                if mode == 'after':
                    raise RuntimeError('interrupted')
            return [], tokens()

        def fallback_text(self, question, hits):
            return 'Резервный ответ'

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
            assert events[0]['text'] == ('Резервный ответ' if mode == 'before' else question)
