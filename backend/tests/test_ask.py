"""Public stateless answer contract."""
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from helpers import ScriptedChatModel, corpus_names, make_app

from ragkb.api.schemas.ask import DoneEvent
from ragkb.core.answer_events import AnswerEvent
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
    build_index(cfg, corpus_names(cfg))
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
        """Движок нового контракта: поиск, ответ с инструментами, цитаты."""

        def llm_available(self, model=None):
            return True

        def search(self, question, top_k=None, expand=False):
            return []

        def stream_tool_answer(
            self, question, *, hits, model=None, candidates=(), resolve_download=None
        ):
            async def events():
                yield AnswerEvent('token', question)
                if mode == 'after':
                    raise RuntimeError('interrupted')

            return events()

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

        def search(self, question, top_k=None, expand=False):
            return []

        def stream_tool_answer(
            self, question, *, hits, model=None, candidates=(), resolve_download=None
        ):
            async def events():
                raise RuntimeError('модель недоступна')
                yield  # pragma: no cover

            return events()

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

ATTACHMENT_ID = '11111111-1111-4111-8111-111111111111'


def _attachment_engine(events_factory):
    """Движок, отдающий заранее заданные события ответа."""

    class Engine:
        def llm_available(self, model=None):
            return True

        def search(self, question, top_k=None, expand=False):
            return []

        def stream_tool_answer(
            self, question, *, hits, model=None, candidates=(), resolve_download=None
        ):
            return events_factory()

        def cited_sources(self, text, hits):
            return []

    return Engine()


def test_attachment_goes_into_done_and_not_into_its_own_line(public_app):
    """Вложения — часть завершающего события, отдельных строк потока нет."""

    async def events():
        yield AnswerEvent('token', 'Требования приложены. ')
        yield AnswerEvent(
            'attachment',
            {
                'document_id': ATTACHMENT_ID,
                'filename': 'AdSmart Multi.pdf',
                'url': f'/api/documents/{ATTACHMENT_ID}/download',
                'media_type': 'application/pdf',
                'size': 1024,
            },
        )

    public_app.state.engine = lambda: _attachment_engine(events)
    with TestClient(public_app) as client:
        response = client.post(
            '/api/v1/ask', json={'question': 'Пришли требования к AdSmart Multi'}
        )

    assert response.status_code == 200
    lines = [json.loads(line) for line in response.text.splitlines()]
    assert [line['type'] for line in lines] == ['token', 'done']

    done = DoneEvent(**lines[-1])
    assert done.truncated is False
    assert [str(attachment.document_id) for attachment in done.attachments] == [ATTACHMENT_ID]
    assert done.attachments[0].filename == 'AdSmart Multi.pdf'
    assert lines[-1]['attachments'][0]['document_id'] == ATTACHMENT_ID


def test_attachments_survive_a_broken_generation(public_app):
    """Обрыв после вложения сохраняет вложение: файл уже выдан."""

    async def events():
        yield AnswerEvent('token', 'Начало ответа. ')
        yield AnswerEvent(
            'attachment',
            {
                'document_id': ATTACHMENT_ID,
                'filename': 'AdSmart Multi.pdf',
                'url': f'/api/documents/{ATTACHMENT_ID}/download',
                'media_type': 'application/pdf',
                'size': 1024,
            },
        )
        raise RuntimeError('обрыв')

    public_app.state.engine = lambda: _attachment_engine(events)
    with TestClient(public_app) as client:
        response = client.post('/api/v1/ask', json={'question': 'Пришли требования'})

    lines = [json.loads(line) for line in response.text.splitlines()]
    done = DoneEvent(**lines[-1])
    assert done.truncated is True
    assert len(done.attachments) == 1
    assert any('оборвался' in warning for warning in done.warnings)


def test_attachment_identifier_is_a_valid_uuid(public_app):
    """Идентификатор вложения обязан быть UUID: иначе карточка в интерфейсе сломается."""

    async def events():
        yield AnswerEvent(
            'attachment',
            {
                'document_id': str(uuid.uuid4()),
                'filename': 'spec.pdf',
                'url': '/api/documents/x/download',
                'media_type': 'application/pdf',
                'size': 1,
            },
        )

    public_app.state.engine = lambda: _attachment_engine(events)
    with TestClient(public_app) as client:
        response = client.post('/api/v1/ask', json={'question': 'Пришли spec.pdf'})

    done = DoneEvent(**json.loads(response.text.splitlines()[-1]))
    assert isinstance(done.attachments[0].document_id, uuid.UUID)
