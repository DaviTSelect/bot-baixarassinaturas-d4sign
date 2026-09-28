from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from selenium.common.exceptions import WebDriverException

import d4sign.browser as browser_module
import d4sign.debug as debug_module
import d4sign.downloader as downloader_module
import d4sign.processor as processor_module
from d4sign.browser import D4SignBrowser
from d4sign.cache import Cache
from d4sign.debug import Debugger
from d4sign.downloader import Downloader
from d4sign.parser import DocumentParser
from d4sign.processor import Processor

UUID = "12345678-1234-1234-1234-123456789abc"


def bcfg(tmp_path, headless=False):
    return SimpleNamespace(
        download_dir=tmp_path / "downloads",
        headless=headless,
        page_timeout=1,
        base_url="https://example.test",
        email="x",
        password="y",
        vault_id="1",
        vault_uuid="v",
    )


class BrowserDriver:
    current_url = "https://example.test/login"
    title = "Login"
    page_source = "<html/>"
    def set_page_load_timeout(self, value): pass
    def execute_cdp_cmd(self, *args): pass
    def execute_script(self, script, *args): return "complete"
    def find_elements(self, *args): return []
    def find_element(self, *args): return SimpleNamespace(text="conteudo normal")
    def quit(self): pass


def test_browser_branch_headless_false_close_sem_driver_e_login_body_normal(tmp_path, monkeypatch):
    class Options:
        def add_argument(self, value): pass
        def add_experimental_option(self, name, value): pass
    driver = BrowserDriver()
    monkeypatch.setattr(browser_module, "Options", Options)
    monkeypatch.setattr(browser_module, "Service", lambda executable_path: object())
    monkeypatch.setattr(browser_module.ChromeDriverManager, "install", lambda self: "driver")
    monkeypatch.setattr(browser_module.webdriver, "Chrome", lambda **kwargs: driver)

    browser = D4SignBrowser(bcfg(tmp_path, headless=False))
    browser.start()  # branch headless=False
    browser.driver = None
    browser.close()  # branch sem driver

    browser.driver = driver
    assert browser._login_concluido(driver) is False  # body sem mensagens de erro


def test_browser_find_login_button_elementos_ocultos_percorre_todos_seletores(tmp_path):
    class Hidden:
        def is_displayed(self): return False
    driver = BrowserDriver()
    driver.find_elements = lambda *args: [Hidden()]
    browser = D4SignBrowser(bcfg(tmp_path))
    browser.driver = driver
    assert browser._find_login_button() is None


def test_cache_clear_project_inexistente(tmp_path):
    cache = Cache(tmp_path / "cache.json")
    cache.clear_project("nao-existe")
    assert cache.data == {}


def test_debug_separator_sem_titulo_e_save_state_com_flags_desligadas(tmp_path, capsys):
    class Driver:
        page_source = "html"
        def save_screenshot(self, path): raise AssertionError("não deveria salvar")
        def execute_script(self, *args): raise AssertionError("não deveria ler texto")
    dbg = Debugger(
        Driver(),
        directory=tmp_path,
        save_screenshots=False,
        save_html=False,
        save_text=False,
    )
    dbg.separator()
    dbg.save_state("flags_off")
    assert "flags_off" in capsys.readouterr().out


class PElement:
    def __init__(self, text="", attrs=None):
        self.text = text
        self.attrs = attrs or {}
    def get_attribute(self, name): return self.attrs.get(name)


class PRow:
    def __init__(self, mapping=None, text="", outer=""):
        self.mapping = mapping or {}; self.text = text; self.outer = outer
    def find_elements(self, by, selector): return self.mapping.get(selector, [])
    def get_attribute(self, name): return self.outer


def test_parser_branches_elemento_sem_uuid_texto_vazio_e_score_menor():
    sem_uuid = PElement(attrs={"value": "x", "id": "y", "data-id": "z", "data-uuid": "q"})
    com_uuid = PElement(attrs={"data-uuid": UUID})
    row = PRow({"input.chevmov": [sem_uuid, com_uuid]})
    assert DocumentParser.uuid(row) == UUID

    empty = PElement(text="   ")
    named = PElement(text="Contrato")
    row2 = PRow({"[id^='nome_documento_']": [empty, named]})
    assert DocumentParser.name(row2) == "Contrato"

    best = PElement(text="Download (apenas assinaturas) PDF")
    lower = PElement(text="baixar")
    row3 = PRow({"a, button, input": [best, lower]})
    assert DocumentParser.download_element(row3) is best


def dcfg(tmp_path, **overrides):
    data = dict(download_dir=tmp_path / "downloads", download_timeout=2, download_retries=1, retry_delay=0, debug=False)
    data.update(overrides)
    return SimpleNamespace(**data)


class DBrowser:
    def __init__(self, driver): self.current_driver = driver


class DDriver:
    current_url = "https://example.test/doc"
    title = "Doc"
    def execute_script(self, script, *args): return "complete"
    def find_elements(self, by, selector): return []
    def get_cookies(self): return []


def make_d(tmp_path, driver=None, **cfg):
    driver = driver or DDriver()
    return Downloader(dcfg(tmp_path, **cfg), DBrowser(driver)), driver


class Elem:
    def __init__(self, text="", attrs=None, displayed=True):
        self.text = text; self.attrs = attrs or {}; self.displayed = displayed
    def get_attribute(self, name): return self.attrs.get(name)
    def is_displayed(self): return self.displayed
    def click(self): pass


class Row:
    def __init__(self, mapping=None, outer=""):
        self.mapping = mapping or {}; self.outer = outer
    def find_elements(self, by, selector): return self.mapping.get(selector, [])
    def get_attribute(self, name): return self.outer


def test_downloader_ready_state_nao_complete_e_find_rows_vazio(tmp_path, monkeypatch):
    class Driver(DDriver):
        def execute_script(self, script, *args): return "loading"
    d, _ = make_d(tmp_path, driver=Driver())
    monkeypatch.setattr(downloader_module.time, "sleep", lambda *_: None)
    times = iter([0.0, 0.1, 2.0])
    monkeypatch.setattr(downloader_module.time, "time", lambda: next(times))
    assert d.wait_document_ready(timeout=1) is False

    d2, _ = make_d(tmp_path)
    assert d2.find_document_rows() == []


def test_downloader_extract_url_links_sem_match_sem_href_e_html_url_irrelevante(tmp_path):
    d, _ = make_d(tmp_path)
    irrelevant = Elem(text="Abrir", attrs={"href": "https://example.test/view"})
    download_no_href = Elem(text="Download", attrs={})
    valid = Elem(text="Baixar", attrs={"href": "https://example.test/download/f.pdf"})
    row = Row({"a": [irrelevant, download_no_href, valid]})
    assert d.extract_download_url(row) == "https://example.test/download/f.pdf"

    html = '<tr data-a="https://example.test/view" data-b="https://example.test/file.pdf"></tr>'
    row2 = Row({"a": []}, outer=html)
    assert d.extract_download_url(row2) == "https://example.test/file.pdf"


def test_downloader_find_button_oculto_depois_visivel(tmp_path):
    d, _ = make_d(tmp_path)
    hidden = Elem(text="Download", displayed=False)
    visible = Elem(text="Download", displayed=True)
    class AnyRow:
        def __init__(self): self.n = 0
        def find_elements(self, by, selector):
            self.n += 1
            return [hidden, visible] if self.n == 1 else []
    assert d.find_download_button(AnyRow()) is visible


def test_downloader_http_200_nao_pdf_e_content_type_nao_html(tmp_path, monkeypatch):
    d, _ = make_d(tmp_path)
    monkeypatch.setattr(d, "sync_cookies", lambda: None)
    response = SimpleNamespace(
        status_code=200,
        url="https://example.test/x",
        headers={"Content-Type": "application/octet-stream"},
        content=b"conteudo",
        text="conteudo",
    )
    monkeypatch.setattr(d.session, "get", lambda *a, **k: response)
    assert d.download_http("https://x", tmp_path / "x.pdf") is False


def test_downloader_selenium_botao_ausente_sem_debug(tmp_path, monkeypatch):
    d, _ = make_d(tmp_path, debug=False)
    monkeypatch.setattr(d, "find_download_button", lambda row: None)
    assert d.download_selenium(Row(), tmp_path / "x.pdf") is False


def test_downloader_selenium_tres_falhas_de_clique_percorre_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader_module.time, "sleep", lambda *_: None)
    class Driver(DDriver):
        def execute_script(self, script, *args):
            # scroll inicial passa; revalidação de clique falha sempre
            if "inline: 'nearest'" in script:
                return None
            raise WebDriverException("clique")
    d, _ = make_d(tmp_path, driver=Driver())
    button = Elem(text="Download")
    monkeypatch.setattr(d, "find_download_button", lambda row: button)
    assert d.download_selenium(Row(), tmp_path / "x.pdf") is False


def make_processor(tmp_path, driver):
    cfg = SimpleNamespace(download_dir=tmp_path / "downloads", download_timeout=2)
    cfg.download_dir.mkdir(parents=True, exist_ok=True)
    browser = SimpleNamespace(driver=driver)
    return Processor(cfg, browser, SimpleNamespace(), SimpleNamespace())


class ProcRow:
    def find_element(self, *args): return object()


class ProcLink:
    def get_attribute(self, name): return "javascript: noop()" if name == "href" else None


def patch_wait(monkeypatch):
    class Wait:
        def __init__(self, *args): pass
        def until(self, condition): return ProcLink()
    monkeypatch.setattr(processor_module, "WebDriverWait", Wait)
    monkeypatch.setattr(processor_module.time, "sleep", lambda *_: None)


def test_processor_pdf_tamanho_zero_nao_estavel_e_pdf_final_invalido(tmp_path, monkeypatch):
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()

    class StatZero:
        st_mtime = 1
        st_size = 0
    class FakeZero:
        name = "zero.pdf"; suffix = ".pdf"
        def is_file(self): return True
        def resolve(self): return self
        def stat(self): return StatZero()
        def exists(self): return True
    zero = FakeZero()

    state = {"n": 0}
    original_glob = Path.glob
    def glob_zero(self, pattern):
        if self == download_dir:
            state["n"] += 1
            if state["n"] == 1: return iter([])
            if state["n"] == 2: return iter([zero])
            return iter([])
        return original_glob(self, pattern)

    driver = SimpleNamespace(execute_script=lambda *a, **k: None)
    p = make_processor(tmp_path, driver)
    patch_wait(monkeypatch)
    monkeypatch.setattr(Path, "glob", glob_zero)
    times = iter([0, .1, .2, 3, 10, 13, 20, 23])
    monkeypatch.setattr(processor_module.time, "time", lambda: next(times, 100))
    assert p.download_selenium(ProcRow(), tmp_path / "zero-out.pdf") is False

    # Agora um PDF estável é movido, mas a validação final retorna False.
    class StatOk:
        st_mtime = 1
        st_size = 10
    class FakeOk:
        name = "ok.pdf"; suffix = ".pdf"
        def is_file(self): return True
        def resolve(self): return self
        def stat(self): return StatOk()
        def exists(self): return True
        def replace(self, destination): pass
    ok = FakeOk()
    state2 = {"n": 0}
    def glob_ok(self, pattern):
        if self == download_dir:
            state2["n"] += 1
            return iter([]) if state2["n"] == 1 else iter([ok])
        return original_glob(self, pattern)
    monkeypatch.setattr(Path, "glob", glob_ok)
    monkeypatch.setattr(processor_module, "is_pdf", lambda p: False)
    times2 = iter([0, .1, .2, 10, 13, 20, 23])
    monkeypatch.setattr(processor_module.time, "time", lambda: next(times2, 100))
    assert p.download_selenium(ProcRow(), tmp_path / "invalid-final.pdf") is False
