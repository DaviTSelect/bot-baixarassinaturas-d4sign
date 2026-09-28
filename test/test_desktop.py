from dataclasses import replace
from queue import Queue
from unittest.mock import Mock

import pytest

from d4sign.desktop import desktop_config
from d4sign.catalog import Location, location_paths, selected_locations, directory_name
from d4sign import session
from d4sign.discovery import CatalogDiscovery, parse_location_link
from d4sign.models import Statistics
from d4sign.processor import Processor

ROOT = '11111111-1111-1111-1111-111111111111'
CHILD = '22222222-2222-2222-2222-222222222222'
LEAF = '33333333-3333-3333-3333-333333333333'
BASE = 'https://secure.d4sign.com.br'


def tree():
    return [Location('42', ROOT, 'Financeiro', [Location('42', CHILD, 'Contratos', [Location('42', LEAF, '2026')])])]


def test_login_config_requires_only_credentials(tmp_path):
    config = desktop_config(' user@example.com ', 'secret', str(tmp_path))
    assert config.email == 'user@example.com'
    assert config.headless and config.include_all_statuses
    assert config.vault_id == config.vault_uuid == ''
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('email,password', [('', 'pass'), ('a', '')])
def test_missing_login(email, password, tmp_path):
    with pytest.raises(ValueError):
        desktop_config(email, password, str(tmp_path))


def test_selection_subtree_and_overlap():
    roots = tree()
    assert [n.uuid for n in selected_locations(roots, ['42:' + ROOT, '42:' + CHILD])] == [ROOT, CHILD, LEAF]
    assert [n.uuid for n in selected_locations(roots, ['42:' + CHILD])] == [CHILD, LEAF]
    assert [n.uuid for n in selected_locations(roots, ['42:' + CHILD], False)] == [CHILD]
    assert not selected_locations(roots, ['unknown'])


def test_preserve_hierarchy_and_names():
    paths = location_paths(tree())
    assert paths['42:' + LEAF].parts == ('Financeiro', 'Contratos', '2026')


def test_windows_names_and_collisions():
    nodes = [Location('1', ROOT, 'A/B'), Location('1', CHILD, 'A:B'), Location('1', LEAF, 'a_b')]
    paths = location_paths(nodes)
    assert len({str(p).casefold() for p in paths.values()}) == 3
    assert directory_name('CON') == '_CON'
    assert directory_name('..') != '..'


@pytest.mark.parametrize('href', ['https://evil.test/desk/cofres/42/' + ROOT, 'javascript:alert(1)', '/desk/cofres/42/invalid'])
def test_reject_unsafe_links(href):
    assert parse_location_link(href, BASE) is None


def test_parse_site_links():
    assert parse_location_link('/desk/cofres/42/' + ROOT + '.html?p=0', BASE) == ('42', ROOT)


def test_session_login_failure_closes_browser(monkeypatch, tmp_path):
    browser = Mock()
    browser.login.side_effect = RuntimeError('login failed')
    monkeypatch.setattr(session, 'D4SignBrowser', Mock(return_value=browser))
    worker = session.Session(desktop_config('a', 'b', str(tmp_path)), Queue())
    worker.run()
    browser.close.assert_called_once()
    assert worker.events.get()[0] == 'log'
    assert worker.events.get()[0] == 'session_error'
    assert worker.events.get()[0] == 'closed'
    assert worker.config.password == ''


def test_session_keeps_login_until_close(monkeypatch, tmp_path):
    browser = Mock()
    monkeypatch.setattr(session, 'D4SignBrowser', Mock(return_value=browser))
    discovery = Mock()
    discovery.load.return_value = tree()
    monkeypatch.setattr(session, 'CatalogDiscovery', Mock(return_value=discovery))
    worker = session.Session(desktop_config('a', 'b', str(tmp_path)), Queue())
    worker.commands.put(('refresh', None))
    worker.close()
    worker.run()
    browser.login.assert_called_once()
    browser.close.assert_called_once()
    assert discovery.load.call_count == 2
    assert worker.config.password == browser.config.password == ''
    assert [worker.events.get()[0] for _ in range(3)] == ['catalog', 'catalog', 'closed']


def test_download_preserves_paths_and_reuses_browser(monkeypatch, tmp_path):
    browser = Mock()
    processor = Mock(last_audit={'complete': True})
    processor.process_location.return_value = Statistics(downloaded=1)
    factory = Mock(return_value=processor)
    monkeypatch.setattr(session, 'Processor', factory)
    monkeypatch.setattr(session, 'Downloader', Mock())
    worker = session.Session(desktop_config('a', 'b', str(tmp_path)), Queue())
    total = worker.download(browser, tree(), ['42:' + CHILD], True, str(tmp_path))
    assert total.downloaded == 2
    calls = processor.process_location.call_args_list
    assert calls[0].args == (CHILD, 'Contratos', tmp_path / 'Financeiro' / 'Contratos')
    assert calls[1].args[2] == tmp_path / 'Financeiro' / 'Contratos' / '2026'
    assert factory.call_args.args[0].vault_id == '42'
    browser.login.assert_not_called()


def test_processor_uses_selected_location(tmp_path):
    config = replace(desktop_config('a', 'b', str(tmp_path)), vault_uuid=CHILD)
    browser, cache = Mock(), Mock()
    browser.open_folder_page.return_value = []
    cache.get_project.return_value = {}
    Processor(config, browser, Mock(), cache).process_location(CHILD, 'Contracts', tmp_path / 'Vault' / 'Contracts')
    browser.open_folder_page.assert_called_once_with(CHILD, 0)
    assert (tmp_path / 'Vault' / 'Contracts').is_dir()


def test_desktop_login_and_selection_widgets(monkeypatch):
    import tkinter as tk
    from d4sign import desktop
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip('Display not available')
    root.withdraw()
    try:
        app = desktop.Desktop(root)
        worker = Mock()
        worker.commands = Queue()
        factory = Mock(return_value=worker)
        monkeypatch.setattr(desktop, 'Session', factory)
        app.email.insert(0, 'user@example.com')
        app.password.insert(0, 'secret')
        app.login()
        worker.start.assert_called_once()
        assert app.password.get() == ''
        assert factory.call_args.args[0].headless
        roots = tree()
        roots[0].children[0].loaded = False
        app.show_catalog(roots)
        assert '42:' + ROOT in app.explorer.row_checks
        app.navigate('42:' + ROOT)
        assert app.explorer_state.current == '42:' + ROOT
        assert not app.explorer_state.selected
        app.navigate('42:' + CHILD)
        assert worker.commands.get_nowait() == ('expand', '42:' + CHILD)
        roots[0].children[0].loaded = True
        app.show_branch(roots[0].children[0])
        app.explorer_state.toggle('42:' + CHILD)
        app.start()
        kind, data = worker.commands.get_nowait()
        assert kind == 'download'
        assert data[0] == ['42:' + CHILD] and data[1] is True
        app.set_busy(False)
        app.start(True)
        assert worker.commands.get_nowait()[1][:2] == (['42:' + ROOT], True)
        app.set_busy(False)
        app.close()
        worker.close.assert_called_once()
    finally:
        app.progress.stop()
        for callback in root.tk.splitlist(root.tk.call('after', 'info')):
            root.after_cancel(callback)
        root.destroy()


def test_download_summary_is_user_friendly_and_has_no_technical_url(monkeypatch):
    import tkinter as tk
    from d4sign import desktop
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip('Display not available')
    root.withdraw()
    try:
        app = desktop.Desktop(root)
        app.show_catalog(tree())
        summary = app.download_summary(['42:' + CHILD], True, 'C:/Downloads/D4Sign')
        assert 'Pastas selecionadas:' in summary
        assert 'Financeiro\\Contratos' in summary or 'Financeiro/Contratos' in summary
        assert 'C:/Downloads/D4Sign' in summary or 'C:\\Downloads\\D4Sign' in summary
        assert 'https://' not in summary
        assert 'uuid' not in summary.lower()
    finally:
        for callback in root.tk.splitlist(root.tk.call('after', 'info')):
            root.tk.call('after', 'cancel', callback)
        root.destroy()
