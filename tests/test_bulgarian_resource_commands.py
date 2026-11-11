from unittest.mock import Mock

import pytest

from jarvis.local_commands import LocalCommandService
from jarvis.models import CommandResult
from jarvis.safety import SafetyPolicy
from jarvis.tool_registry import ToolRegistry, ToolSpec, ToolParameter
from jarvis.user_settings import JarvisSettings


@pytest.mark.parametrize('command,tool,arguments', [
    ('преименувай "Documents/Бележки.txt" на "План.txt"', 'rename_local_path', {'path':'Documents/Бележки.txt','new_name':'План.txt'}),
    ('копирай "Documents/Бележки.txt" в "Documents/Копие.txt"', 'copy_local_file', {'source':'Documents/Бележки.txt','destination':'Documents/Копие.txt'}),
    ('премести "Documents/Бележки.txt" в "Documents/Нов.txt"', 'move_local_path', {'source':'Documents/Бележки.txt','destination':'Documents/Нов.txt'}),
    ('архивирай "Documents/Проект" в "Documents/Проект.zip"', 'create_zip', {'source':'Documents/Проект','destination':'Documents/Проект.zip'}),
    ('разархивирай "Documents/Проект.zip" в "Documents/Резултат"', 'extract_zip', {'source':'Documents/Проект.zip','destination':'Documents/Резултат'}),
    ('създай файл "Documents/Бележки.txt" с текст Здравей, Берк!', 'create_local_file', {'path':'Documents/Бележки.txt','content':'Здравей, Берк!'}),
    ('анализирай документа "Documents/Доклад.pdf"', 'analyze_document', {'path':'Documents/Доклад.pdf'}),
    ('прочети документ "Documents/Доклад.docx"', 'analyze_document', {'path':'Documents/Доклад.docx'}),
    ('информация за файл "Documents/Бележки.txt"', 'inspect_local_path', {'path':'Documents/Бележки.txt'}),
    ('сподели екрана', 'start_screen_sharing', {}),
    ('спри споделянето на екрана', 'stop_screen_sharing', {}),
    ('забрави документа', 'forget_document', {}),
])
def test_bulgarian_routes_keep_arguments_and_confirmation(command, tool, arguments):
    handler = Mock(return_value=CommandResult(True, 'fixture'))
    registry = ToolRegistry()
    registry.register(ToolSpec(tool, 'fixture', permission='confirm', parameters=tuple(
        ToolParameter(name, 'string', name) for name in arguments)), handler)
    safety = SafetyPolicy(auto_confirm=False)
    safety.confirm = Mock(return_value=False)
    service = LocalCommandService(Mock(dry_run=True), JarvisSettings(), Mock(has_search_context=False), registry, safety)
    denied = service.resource_command(command)
    assert denied is not None and not denied.ok and denied.confirmed is False
    handler.assert_not_called()
    safety.confirm.return_value = True
    allowed = service.resource_command(command)
    assert allowed.ok and allowed.confirmed
    handler.assert_called_once_with(**arguments)


@pytest.mark.parametrize('text,expected', [('затвори приложение Notepad','close_app'),
                                         ('спри принудително Notepad','end_process')])
def test_normal_close_and_force_stop_are_distinct_in_bulgarian(text, expected):
    service = LocalCommandService(Mock(), JarvisSettings(), Mock(has_search_context=False), Mock(), Mock())
    service._execute = Mock(side_effect=[CommandResult(True, 'observed', metadata={
        'processes': [{'name':'Notepad', 'pid':123, 'selection_id':'fixture-selection', 'eligible':True, 'has_window':True}]}),
        CommandResult(True, 'fixture')])
    result = service.resource_command(text)
    assert result.ok
    assert service._execute.call_args.args[0] == expected
