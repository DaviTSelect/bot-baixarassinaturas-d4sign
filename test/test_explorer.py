from queue import Queue
from unittest.mock import Mock

import pytest

from d4sign.catalog import Location
from d4sign.explorer import ExplorerState


def catalog():
    return [Location('1', 'a', 'Projetos', [
        Location('1', 'b', 'Contratos', [Location('1', 'c', '2026')]),
        Location('1', 'd', 'Financeiro', loaded=False),
    ]), Location('2', 'e', 'Outros')]


def state():
    result = ExplorerState()
    result.catalog(catalog())
    return result


def test_navigation_does_not_select_and_selection_survives_search():
    model = state()
    model.navigate('1:a')
    assert model.selected == set()
    model.toggle('1:b')
    model.navigate('2:e')
    model.toggle('2:e')
    assert model.selected == {'1:b', '2:e'}
    assert model.ancestors('1:c') == ['1:a', '1:b']
    model.navigate('1:a')
    model.search = 'CONTRAT'
    assert [n.key for n in model.results()] == ['1:b']
    model.search = 'inexistente'
    assert model.results() == []
    assert len(model.selected) == 2


def test_recursive_parent_selection_removes_redundant_children():
    model = state()
    model.toggle('1:c')
    model.toggle('1:a')
    assert model.selected == {'1:a'}
    assert model.included_by('1:c') == '1:a'
    model.toggle('1:b')
    assert model.selected == {'1:a'}
    model.toggle('1:a')
    assert model.selected == set()
    model.recursive = False
    model.toggle('1:c')
    model.toggle('1:a')
    assert model.selected == {'1:a', '1:c'}
    model.recursive = True
    model.normalize()
    assert model.selected == {'1:a'}


def test_select_all_is_limited_to_current_page_and_filter():
    model = ExplorerState()
    model.catalog([Location('1', str(i), f'Pasta {i:04}') for i in range(5000)])
    assert len(model.visible()) == 40
    model.select_visible()
    assert len(model.selected) == 40
    model.page = 1
    model.select_visible()
    assert len(model.selected) == 80
    model.select_visible()
    assert len(model.selected) == 40
    model.page = 0
    model.search = '4999'
    model.select_visible()
    assert '1:4999' in model.selected


def test_review_refresh_and_invalid_navigation():
    model = state()
    model.toggle('1:b')
    model.toggle('2:e')
    model.reviewing = True
    assert {n.key for n in model.results()} == model.selected
    assert model.path('1:b') == 'Projetos / Contratos'
    model.catalog(catalog()[:1])
    assert model.selected == {'1:b'}
    with pytest.raises(ValueError):
        model.navigate('unknown')


@pytest.fixture(scope='module')
def tk_root():
    import tkinter as tk
    # Use one Tcl interpreter per module; widgets are isolated per test.
    root = tk.Tk()
    yield root
    root.destroy()


@pytest.fixture
def app(monkeypatch, tk_root):
    from d4sign.desktop import Desktop
    root = tk_root
    root.withdraw()
    monkeypatch.setattr(Desktop, 'check', lambda self: None)
    application = Desktop(root)
    application.session = Mock(commands=Queue())
    application.show_catalog(catalog())
    yield application
    application.progress.stop()
    for callback in root.tk.splitlist(root.tk.call('after', 'info')):
        root.after_cancel(callback)
    for child in root.winfo_children():
        child.destroy()


def test_native_checkbox_opens_no_download_and_name_opens_no_selection(app):
    app.explorer.row_checks['1:a'].invoke()
    assert app.explorer_state.selected == {'1:a'}
    assert app.session.commands.empty()
    app.navigate('1:a')
    assert app.explorer_state.current == '1:a'
    assert app.explorer_state.selected == {'1:a'}
    assert app.explorer.row_checks['1:b'].instate(['disabled'])
    app.clear_selection()
    app.explorer.row_checks['1:b'].invoke()
    app.navigate(None)
    app.explorer.row_checks['2:e'].invoke()
    app.review_selection()
    assert set(app.explorer.row_checks) == {'1:b', '2:e'}
    app.start()
    command, (keys, recursive, destination) = app.session.commands.get_nowait()
    assert command == 'download' and keys == ['1:b', '2:e'] and recursive
    assert app.busy and app.cancel_button.instate(['!disabled'])


def test_lazy_loading_error_retry_and_done_feedback(app):
    app.navigate('1:d')
    assert app.session.commands.get_nowait() == ('expand', '1:d')
    assert app.cancel_button.instate(['disabled'])
    app.events.put(('error', 'Não foi possível carregar esta pasta.'))
    app.poll()
    assert not app.busy and app.retry_button.winfo_manager() == 'grid'
    app.retry()
    assert app.session.commands.get_nowait() == ('expand', '1:d')
    app.show_branch(Location('1', 'd', 'Financeiro'))
    app.navigate(None)
    app.explorer.row_checks['1:a'].invoke()
    app.start()
    app.events.put(('done', 'Download concluído com sucesso.'))
    app.poll()
    assert not app.busy
    assert app.status_label.cget('style') == 'Success.TLabel'


def test_search_pagination_and_empty_directory(app):
    app.navigate('1:a')
    app.explorer.search.set('CONTRAT')
    assert list(app.explorer.row_checks) == ['1:b']
    app.explorer.search.set('não existe')
    assert not app.explorer.row_checks
    app.navigate('2:e')
    assert not app.explorer.row_checks
    app.show_catalog([Location('1', str(i), f'Pasta {i:04}') for i in range(1000)])
    assert len(app.explorer.row_checks) == 40
    app.explorer.turn_page(1)
    app.set_busy(True)
    app.set_busy(False)
    assert app.explorer_state.page == 1
    assert len(app.explorer.row_checks) == 40


@pytest.mark.parametrize('size', ['960x850', '440x640'])
def test_compact_layout_keeps_download_action_visible(app, size):
    app.explorer_state.nodes['1:a'].name = 'Uma pasta com nome bastante longo para testar quebra de linha ' * 3
    app.explorer_state.toggle('1:a')
    app.explorer.render()
    app.selection_changed()
    app.root.geometry(size)
    app.root.deiconify()
    app.root.update_idletasks()
    button = app.download_button
    assert button.winfo_ismapped()
    assert button.winfo_rootx() >= app.root.winfo_rootx()
    assert button.winfo_rootx() + button.winfo_width() <= app.root.winfo_rootx() + app.root.winfo_width()
    assert button.winfo_rooty() + button.winfo_height() <= app.root.winfo_rooty() + app.root.winfo_height()
    assert app.explorer.canvas.winfo_height() >= 60


def test_keyboard_space_selects_without_starting_download(app):
    app.root.deiconify()
    app.root.update()
    check = app.explorer.row_checks['1:a']
    check.focus_force()
    app.root.update()
    check.event_generate('<KeyPress-space>')
    app.root.update()
    assert app.explorer_state.selected == {'1:a'}
    assert app.explorer_state.current is None
    assert app.session.commands.empty()
