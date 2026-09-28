from queue import Queue
from unittest.mock import Mock

import pytest

from d4sign import session
from d4sign.catalog import Location
from d4sign.desktop import desktop_config
from d4sign.models import Statistics


def worker(tmp_path):
    return session.Session(desktop_config('test@example.test', 'fake', str(tmp_path)), Queue())


def test_refresh_loads_only_current_and_selected_paths(monkeypatch, tmp_path):
    previous = Mock(parents={'a:b': 'a:a', 'a:c': 'a:b', 'a:d': 'a:a'})
    refreshed = Mock(nodes={k: Mock() for k in ['a:a', 'a:b', 'a:c', 'a:d']})
    factory = Mock(return_value=refreshed)
    monkeypatch.setattr(session, 'CatalogDiscovery', factory)
    result = worker(tmp_path).refresh_catalog(Mock(), previous, 'a:b', ['a:d'])
    assert result is refreshed
    assert [call.args[0] for call in refreshed.expand.call_args_list] == ['a:a', 'a:b', 'a:a']
    refreshed.load.assert_called_once()


def test_failed_refresh_keeps_session_and_previous_catalog(monkeypatch, tmp_path):
    browser, discovery = Mock(), Mock()
    roots = [Location('a', 'a', 'Projetos')]
    discovery.load.return_value = roots
    discovery.expand.return_value = roots[0]
    monkeypatch.setattr(session, 'D4SignBrowser', Mock(return_value=browser))
    monkeypatch.setattr(session, 'CatalogDiscovery', Mock(return_value=discovery))
    instance = worker(tmp_path)
    instance.refresh_catalog = Mock(side_effect=RuntimeError('private technical detail'))
    instance.commands.put(('refresh_level', ('a:a', [])))
    instance.commands.put(('expand', 'a:a'))
    instance.close()
    instance.run()
    events = list(instance.events.queue)
    assert [k for k, _ in events] == ['catalog', 'log', 'error', 'branch', 'closed']
    assert 'private technical detail' not in dict(events)['error']
    assert 'private technical detail' in dict(events)['log']
    discovery.expand.assert_called_once_with('a:a')


@pytest.mark.parametrize('selected', [[], ['invalid'], ['a:a', 'invalid']])
def test_download_rejects_unknown_ids_before_touching_destination(tmp_path, selected):
    destination = tmp_path / 'not-created'
    with pytest.raises(ValueError):
        worker(tmp_path).download(Mock(), [Location('a', 'a', 'Projetos')], selected, True, destination)
    assert not destination.exists()


@pytest.mark.parametrize('errors, expected', [(0, 'done'), (2, 'done_warning')])
def test_partial_download_is_not_reported_as_success(monkeypatch, tmp_path, errors, expected):
    browser, discovery = Mock(), Mock()
    roots = [Location('a', 'a', 'Projetos')]
    discovery.load.return_value = roots
    discovery.nodes = {'a:a': roots[0]}
    monkeypatch.setattr(session, 'D4SignBrowser', Mock(return_value=browser))
    monkeypatch.setattr(session, 'CatalogDiscovery', Mock(return_value=discovery))
    instance = worker(tmp_path)
    instance.download = Mock(return_value=Statistics(downloaded=1, errors=errors))
    instance.commands.put(('download', (['a:a'], True, str(tmp_path))))
    instance.close()
    instance.run()
    events = dict(instance.events.queue)
    assert expected in events
    if errors:
        assert 'sucesso' not in events[expected]
