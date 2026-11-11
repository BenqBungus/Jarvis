import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from jarvis.ai_client import JarvisAI
from jarvis.tool_registry import ToolRegistry
from jarvis.user_settings import JarvisSettings


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'fixture-only')
    client = MagicMock()
    client.__enter__.return_value = client
    client.responses.create.return_value = SimpleNamespace(output_text='Отговор', status='completed')
    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=lambda **kwargs: client))
    return client


@pytest.mark.parametrize('code,expected', [('bg','bg'), ('en','en'), ('auto','auto'), (' BG ', 'bg'),
    ('invalid','en'), (None,'en'), ([], 'en')])
def test_language_setting_normalizes_without_accepting_instructions(code, expected, tmp_path):
    settings = JarvisSettings(openai={'conversation_language': code})
    assert settings.conversation_language == expected
    target = tmp_path / 'settings.json'
    settings.save(target)
    assert JarvisSettings.load(target).conversation_language == expected


@pytest.mark.parametrize('language,marker', [('bg', 'Bulgarian (bg)'), ('en', 'Reply only in English'),
                                           ('auto', 'language of the current user request')])
@pytest.mark.parametrize('operation', ['chat', 'document', 'research', 'compare', 'page', 'screen', 'web', 'episode', 'edit', 'email'])
def test_answer_paths_follow_selected_language(provider, language, marker, operation):
    ai = JarvisAI(settings=JarvisSettings(openai={'conversation_language': language}))
    if operation == 'chat':
        ai.answer_conversation('Как си?')
    elif operation == 'document':
        ai.answer_document('Обобщи', source='[Page 1] example', coverage='one page')
    elif operation == 'research':
        ai.summarize_research('мишки', [])
    elif operation == 'compare':
        ai.compare_browser_session_pages([], 'Сравни')
    elif operation == 'page':
        ai.answer_browser_session_question([], 'Коя е по-добра?')
    elif operation == 'screen':
        ai.describe_image_bytes(b'fixture-image-no-capture', 'Обясни грешката')
    elif operation == 'web':
        ai.answer_with_web_search('новини')
    elif operation == 'episode':
        ai.summarize_episode([])
    elif operation == 'email':
        ai.summarize_email('{"body":"meeting at 10"}')
    else:
        provider.responses.create.return_value.output_text = json.dumps({'replacement': 'example', 'explanation': 'Пояснение'})
        ai.propose_text_edit('example', 'Подобри', '.txt')
    sent = json.dumps(provider.responses.create.call_args.kwargs, ensure_ascii=False)
    assert marker in sent
    assert 'JSON keys and enum values unchanged' in sent
    if language != 'en':
        assert 'only in English' not in sent
        assert 'English-speaking' not in sent


@pytest.mark.parametrize('operation', ['intent', 'plan', 'adaptive'])
def test_structured_routes_localize_prose_not_tool_names(provider, operation):
    ai = JarvisAI(settings=JarvisSettings(openai={'conversation_language': 'bg'}))
    provider.responses.create.return_value.output_text = '{}'
    registry = ToolRegistry()
    if operation == 'intent':
        ai.parse_intent('отвори сайта', registry)
    elif operation == 'plan':
        ai.plan_workflow('създай папка и файл', registry)
    else:
        ai.decide_next_workflow_step('провери файла', registry, [])
    sent = provider.responses.create.call_args.kwargs
    system = sent['input'][0]['content']
    assert 'Bulgarian (bg)' in system
    assert 'JSON keys and enum values unchanged' in system
    assert sent['text']['format']['type'] == 'json_schema'


def test_running_ai_instance_reads_new_preference(provider):
    settings = JarvisSettings()
    ai = JarvisAI(settings=settings)
    ai.answer_conversation('Hi')
    assert 'Reply only in English' in provider.responses.create.call_args.kwargs['instructions']
    settings.openai['conversation_language'] = 'bg'
    ai.answer_conversation('Здравей')
    assert 'Bulgarian (bg)' in provider.responses.create.call_args.kwargs['instructions']
