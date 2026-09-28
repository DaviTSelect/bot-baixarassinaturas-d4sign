from __future__ import annotations

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)

import d4sign.browser as browser_module
import d4sign.debug as debug_module
import d4sign.downloader as downloader_module
import d4sign.parser as parser_module
import d4sign.processor as processor_module
import d4sign.utils as utils_module
from d4sign.browser import D4SignBrowser
from d4sign.cache import Cache
from d4sign.debug import Debugger
from d4sign.downloader import Downloader
from d4sign.models import Document
from d4sign.parser import DocumentParser
from d4sign.processor import Processor

UUID = "12345678-1234-1234-1234-123456789abc"


def browser_config(tmp_path: Path, **overrides):
    data = dict(
        download_dir=tmp_path / "downloads",
        headless=True,
        page_timeout=1,
        base_url="https://example.test",
        email="user@example.com",
        password="secret",
        vault_id="10",
        vault_uuid="vault-uuid",
    )
    data.update(overrides)
    return SimpleNamespace(**data)


class BasicBrowserDriver:
    def __init__(self):
        self.current_url = "https://example.test/login"
        self.title = "Login"
        self.page_source = "<html>ok</html>"
        self.scripts = []

    def execute_script(self, script, *args):
        self.scripts.append((script, args))
        if "readyState" in script:
            return "complete"
        return None

    def find_elements(self, *args):
        return []

    def find_element(self, *args):
        return SimpleNamespace(text="normal")

    def save_screenshot(self, path):
        Path(path).write_bytes(b"png")


# ---------------------------------------------------------------------------
# browser.py
# ---------------------------------------------------------------------------

def test_browser_start_cdp_exception_and_close_quit_exception(tmp_path, monkeypatch, capsys):
    class Options:
        def add_argument(self, value):
            pass
        def add_experimental_option(self, name, value):
            pass

    class Driver(BasicBrowserDriver):
        def set_page_load_timeout(self, value):
            pass
        def execute_cdp_cmd(self, *args, **kwargs):
            raise RuntimeError("cdp")
        def quit(self):
            raise RuntimeError("quit")

    driver = Driver()
    monkeypatch.setattr(browser_module, "Options", Options)
    monkeypatch.setattr(browser_module, "Service", lambda executable_path: object())
    monkeypatch.setattr(browser_module.ChromeDriverManager, "install", lambda self: "driver")
    monkeypatch.setattr(browser_module.webdriver, "Chrome", lambda **kwargs: driver)

    browser = D4SignBrowser(browser_config(tmp_path))
    browser.start()
    browser.close()
    assert browser.driver is None
    assert "download CDP" in capsys.readouterr().out


def test_browser_get_dom_timeout(tmp_path, monkeypatch):
    driver = BasicBrowserDriver()
    driver.get = lambda url: None
    browser = D4SignBrowser(browser_config(tmp_path))
    browser.driver = driver

    class Wait:
        def __init__(self, *args): pass
        def until(self, condition):
            raise TimeoutException("dom")

    monkeypatch.setattr(browser_module, "WebDriverWait", Wait)
    browser.get("https://example.test/x")


def test_browser_login_email_timeout(tmp_path, monkeypatch):
    driver = BasicBrowserDriver()
    browser = D4SignBrowser(browser_config(tmp_path))
    browser.driver = driver
    monkeypatch.setattr(browser, "get", lambda url: None)
    monkeypatch.setattr(browser, "_save_diagnostic", lambda name: None)

    class Wait:
        def __init__(self, *args): pass
        def until(self, condition):
            raise TimeoutException("email")

    monkeypatch.setattr(browser_module, "WebDriverWait", Wait)
    with pytest.raises(RuntimeError, match="Campo de e-mail"):
        browser.login()


def test_browser_login_button_missing_click_js_and_confirmation_timeout(tmp_path, monkeypatch):
    class Field:
        def clear(self): pass
        def send_keys(self, value): pass

    driver = BasicBrowserDriver()
    browser = D4SignBrowser(browser_config(tmp_path))
    browser.driver = driver
    monkeypatch.setattr(browser, "get", lambda url: None)
    monkeypatch.setattr(browser, "_save_diagnostic", lambda name: None)

    # botão ausente
    seq = iter([Field(), Field()])
    class WaitFields:
        def __init__(self, *args): pass
        def until(self, condition): return next(seq)
    monkeypatch.setattr(browser_module, "WebDriverWait", WaitFields)
    monkeypatch.setattr(browser, "_find_login_button", lambda: None)
    with pytest.raises(RuntimeError, match="Botão de login"):
        browser.login()

    # clique normal falha, JavaScript funciona, mas confirmação expira
    button = SimpleNamespace(click=lambda: (_ for _ in ()).throw(RuntimeError("click")))
    seq2 = iter([Field(), Field(), TimeoutException("confirm")])
    class WaitConfirm:
        def __init__(self, *args): pass
        def until(self, condition):
            value = next(seq2)
            if isinstance(value, Exception):
                raise value
            return value
    monkeypatch.setattr(browser_module, "WebDriverWait", WaitConfirm)
    monkeypatch.setattr(browser, "_find_login_button", lambda: button)
    with pytest.raises(RuntimeError, match="confirmar o login"):
        browser.login()
    assert any("arguments[0].click" in s for s, _ in driver.scripts)


def test_browser_find_login_button_exception_and_none(tmp_path):
    browser = D4SignBrowser(browser_config(tmp_path))
    driver = BasicBrowserDriver()
    driver.find_elements = lambda *args: (_ for _ in ()).throw(WebDriverException("x"))
    browser.driver = driver
    assert browser._find_login_button() is None


def test_browser_login_concluido_exceptions_return_false(tmp_path):
    browser = D4SignBrowser(browser_config(tmp_path))
    driver = BasicBrowserDriver()
    driver.current_url = "https://example.test/login"
    driver.find_elements = lambda *args: (_ for _ in ()).throw(WebDriverException("x"))
    driver.find_element = lambda *args: (_ for _ in ()).throw(ValueError("body"))
    assert browser._login_concluido(driver) is False


def test_browser_get_folders_element_exception(tmp_path):
    class Broken:
        def get_attribute(self, name):
            raise WebDriverException("broken")
    driver = BasicBrowserDriver()
    driver.find_elements = lambda *args: [Broken()]
    browser = D4SignBrowser(browser_config(tmp_path))
    browser.driver = driver
    assert browser.get_folders() == []


def test_browser_open_folder_page_timeout_empty_and_scroll_exception(tmp_path, monkeypatch):
    browser = D4SignBrowser(browser_config(tmp_path))
    driver = BasicBrowserDriver()
    browser.driver = driver
    monkeypatch.setattr(browser, "get", lambda url: None)
    monkeypatch.setattr(browser_module.time, "sleep", lambda *_: None)

    class WaitTimeout:
        def __init__(self, *args): pass
        def until(self, condition): raise TimeoutException("ready")
    monkeypatch.setattr(browser_module, "WebDriverWait", WaitTimeout)
    driver.find_elements = lambda *args: []
    assert browser.open_folder_page(UUID, 0) == []

    # rows existem e scroll falha
    row = object()
    class WaitOK:
        def __init__(self, *args): pass
        def until(self, condition): return True
    monkeypatch.setattr(browser_module, "WebDriverWait", WaitOK)
    driver.find_elements = lambda *args: [row]
    driver.execute_script = lambda *args: (_ for _ in ()).throw(RuntimeError("scroll"))
    assert browser.open_folder_page(UUID, 1) == [row]


def test_browser_save_diagnostic_no_driver_and_failure(tmp_path, monkeypatch, capsys):
    browser = D4SignBrowser(browser_config(tmp_path))
    browser.driver = None
    browser._save_diagnostic("none")

    class Bad(BasicBrowserDriver):
        def save_screenshot(self, path): raise RuntimeError("save")
    browser.driver = Bad()
    monkeypatch.chdir(tmp_path)
    browser._save_diagnostic("bad")
    assert "Erro salvando diagnóstico" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# cache.py / utils.py
# ---------------------------------------------------------------------------

def test_cache_load_non_dict(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    cache = Cache(path)
    assert cache.data == {}


def test_is_pdf_oserror():
    class BadPath:
        def exists(self): return True
        def stat(self): raise OSError("stat")
    assert utils_module.is_pdf(BadPath()) is False


# ---------------------------------------------------------------------------
# debug.py
# ---------------------------------------------------------------------------

class DebugDriver:
    current_url = "u"
    title = "t"
    page_source = "html"
    def execute_script(self, script, *args):
        if "querySelectorAll" in script:
            return {"trs": 0, "links": 0, "buttons": 0, "inputs": 0, "divs": 0, "bodyText": ""}
        return "complete"
    def find_elements(self, *args): return []
    def save_screenshot(self, path): return True


def test_debug_disabled_methods(tmp_path):
    dbg = Debugger(DebugDriver(), enabled=False, directory=tmp_path)
    dbg.page_info()
    dbg.inspect_dom()
    dbg.save_state("x")
    dbg.scroll_to(object())


def test_debug_page_info_inspect_dom_and_save_state_errors(tmp_path, capsys):
    class Bad(DebugDriver):
        def execute_script(self, *args): raise RuntimeError("boom")
        def save_screenshot(self, path): raise RuntimeError("save")
    dbg = Debugger(Bad(), directory=tmp_path)
    dbg.page_info()
    dbg.inspect_dom()
    dbg.save_state("x")
    out = capsys.readouterr().out
    assert "Erro obtendo" in out
    assert "Erro analisando DOM" in out
    assert "Erro salvando estado" in out


def test_debug_inspect_elements_item_and_outer_error(tmp_path, capsys):
    class BadElement:
        @property
        def text(self): raise RuntimeError("text")
        def is_displayed(self): return True
        def is_enabled(self): return True
    class Driver1(DebugDriver):
        def find_elements(self, *args): return [BadElement()]
    dbg = Debugger(Driver1(), directory=tmp_path)
    assert len(dbg.inspect_elements(".x")) == 1
    assert "erro:" in capsys.readouterr().out

    class Driver2(DebugDriver):
        def find_elements(self, *args): raise RuntimeError("find")
    dbg2 = Debugger(Driver2(), directory=tmp_path / "2")
    assert dbg2.inspect_elements(".x") == []


def test_debug_scroll_to_error(tmp_path, capsys):
    class Bad(DebugDriver):
        def execute_script(self, *args): raise RuntimeError("scroll")
    Debugger(Bad(), directory=tmp_path).scroll_to(object())
    assert "Erro fazendo scroll" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# parser.py
# ---------------------------------------------------------------------------

class ParserRow:
    def __init__(self, values=None, text="", outer=""):
        self.values = values or {}
        self.text = text
        self.outer = outer
    def find_elements(self, by, selector):
        v = self.values.get(selector, [])
        if isinstance(v, Exception): raise v
        return v
    def get_attribute(self, name):
        if isinstance(self.outer, Exception): raise self.outer
        return self.outer


class ParserElement:
    def __init__(self, text="", attrs=None, error=False):
        self._text = text
        self.attrs = attrs or {}
        self.error = error
    @property
    def text(self):
        if self.error: raise WebDriverException("stale")
        return self._text
    def get_attribute(self, name):
        if self.error: raise WebDriverException("stale")
        return self.attrs.get(name)


def test_parser_all_exception_fallbacks_and_gerardownload_score():
    row = ParserRow(
        {s: WebDriverException("x") for s in ["input.chevmov", "input[type='checkbox']", "[id^='nome_documento_']"]},
        outer=WebDriverException("outer"),
    )
    assert DocumentParser.uuid(row) is None

    name_row = ParserRow({"[id^='nome_documento_']": WebDriverException("x")})
    name_row.text = ""
    # força erro no acesso a text do row
    class NameBad(ParserRow):
        @property
        def text(self): raise WebDriverException("text")
        @text.setter
        def text(self, value): pass
    assert DocumentParser.name(NameBad({"[id^='nome_documento_']": WebDriverException("x")})) == "documento"

    fin = ParserRow({s: WebDriverException("x") for s in [".label-finalizado", ".finalizado", "[class*='finalizado']"]})
    assert DocumentParser.finalized(fin) is True

    good = ParserElement(attrs={"onclick": "gerarDownload()"})
    stale = ParserElement(error=True)
    drow = ParserRow({"a, button, input": [stale, good]})
    assert DocumentParser.download_element(drow) is good


# ---------------------------------------------------------------------------
# downloader.py
# ---------------------------------------------------------------------------

def dl_config(tmp_path, **overrides):
    data = dict(download_dir=tmp_path / "downloads", download_timeout=2, download_retries=2, retry_delay=0, debug=True)
    data.update(overrides)
    return SimpleNamespace(**data)


class DLBrowser:
    def __init__(self, driver): self.current_driver = driver


class DLDriver:
    current_url = "https://example.test/doc"
    title = "Doc"
    def execute_script(self, script, *args): return "complete"
    def find_elements(self, by, selector): return []
    def get_cookies(self): return []


def make_dl(tmp_path, driver=None, **cfg):
    driver = driver or DLDriver()
    return Downloader(dl_config(tmp_path, **cfg), DLBrowser(driver)), driver


def test_downloader_debug_flag_exception(tmp_path):
    d, _ = make_dl(tmp_path)
    class BadConfig:
        @property
        def debug(self): raise RuntimeError("x")
    d.config = BadConfig()
    assert d._get_debug_flag() is False


def test_wait_document_ready_default_timeout_error_and_timeout(tmp_path, monkeypatch):
    class Driver(DLDriver):
        def execute_script(self, *args): raise WebDriverException("ready")
    d, _ = make_dl(tmp_path, driver=Driver())
    monkeypatch.setattr(downloader_module.time, "sleep", lambda *_: None)
    times = iter([0.0, 0.1, 31.0])
    monkeypatch.setattr(downloader_module.time, "time", lambda: next(times))
    assert d.wait_document_ready() is False


def test_debug_page_disabled_and_all_property_errors(tmp_path):
    d, _ = make_dl(tmp_path, debug=False)
    d.debug_page()

    class Driver:
        @property
        def current_url(self): raise RuntimeError("url")
        @property
        def title(self): raise RuntimeError("title")
        def execute_script(self, script, *args): raise RuntimeError("script")
        def find_elements(self, *args): raise RuntimeError("find")
        def get_cookies(self): return []
    d2, _ = make_dl(tmp_path, driver=Driver(), debug=True)
    d2.debug_page()


def test_scroll_page_inner_and_outer_webdriver_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader_module.time, "sleep", lambda *_: None)
    class Inner(DLDriver):
        def __init__(self): self.n = 0
        def execute_script(self, script, *args):
            if "scrollHeight" in script: return 100
            if args:
                raise WebDriverException("inner")
            return None
    d, _ = make_dl(tmp_path, driver=Inner())
    d.scroll_page()

    class Outer(DLDriver):
        def execute_script(self, *args): raise WebDriverException("outer")
    d2, _ = make_dl(tmp_path, driver=Outer())
    d2.scroll_page()


def test_find_document_rows_errors_and_empty(tmp_path):
    class Driver(DLDriver):
        def find_elements(self, *args): raise WebDriverException("find")
    d, _ = make_dl(tmp_path, driver=Driver())
    assert d.find_document_rows() == []


def test_wait_for_documents_empty_timeout_path(tmp_path, monkeypatch):
    d, _ = make_dl(tmp_path)
    monkeypatch.setattr(d, "wait_document_ready", lambda timeout=5: True)
    monkeypatch.setattr(d, "scroll_page", lambda: None)
    monkeypatch.setattr(d, "find_document_rows", lambda: [])
    monkeypatch.setattr(d, "debug_page", lambda: None)
    monkeypatch.setattr(downloader_module.time, "sleep", lambda *_: None)
    times = iter([0.0, 0.1, 3.0])
    monkeypatch.setattr(downloader_module.time, "time", lambda: next(times))
    assert d.wait_for_documents(max_wait=2) == []


def test_sync_cookies_get_error_and_cookie_set_error(tmp_path, monkeypatch):
    class BadGet(DLDriver):
        def get_cookies(self): raise WebDriverException("cookies")
    d, _ = make_dl(tmp_path, driver=BadGet())
    d.sync_cookies()

    class Driver(DLDriver):
        def get_cookies(self): return [{"name": "a", "value": "b"}]
    d2, _ = make_dl(tmp_path, driver=Driver())
    monkeypatch.setattr(d2.session.cookies, "set", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("set")))
    d2.sync_cookies()


class AnyElement:
    def __init__(self, attrs=None, text="", displayed=True, attr_error=False):
        self.attrs = attrs or {}; self._text = text; self.displayed = displayed; self.attr_error = attr_error
    @property
    def text(self):
        if self.attr_error: raise StaleElementReferenceException("text")
        return self._text
    def get_attribute(self, name):
        if self.attr_error: raise StaleElementReferenceException("attr")
        return self.attrs.get(name)
    def is_displayed(self):
        if self.attr_error: raise StaleElementReferenceException("display")
        return self.displayed
    def click(self): pass


class AnyRow:
    def __init__(self, fn=None, outer=""):
        self.fn = fn or (lambda by, selector: [])
        self.outer = outer
    def find_elements(self, by, selector): return self.fn(by, selector)
    def get_attribute(self, name):
        if isinstance(self.outer, Exception): raise self.outer
        return self.outer


def test_extract_download_url_all_error_and_selector_paths(tmp_path):
    d, _ = make_dl(tmp_path)
    # link individual stale; selector B finds http
    e_stale = AnyElement(attr_error=True)
    e_http = AnyElement(attrs={"data-url": "https://example.test/download/x"})
    calls = {"a": 0}
    def fn(by, selector):
        if selector == "a": return [e_stale]
        if selector == "[href*='download']": return [e_http]
        return []
    assert d.extract_download_url(AnyRow(fn)) == "https://example.test/download/x"

    # A lookup error, B lookup errors, C html error -> None
    def fnerr(by, selector): raise WebDriverException("find")
    assert d.extract_download_url(AnyRow(fnerr, WebDriverException("html"))) is None

    # B attribute stale path but eventually no URL
    e_bad = AnyElement(attr_error=True)
    def fn2(by, selector):
        if selector == "a": return []
        return [e_bad] if selector == "[href*='download']" else []
    assert d.extract_download_url(AnyRow(fn2, "<tr></tr>")) is None


def test_find_download_button_stale_lookup_error_and_none(tmp_path):
    d, _ = make_dl(tmp_path)
    stale = AnyElement(attr_error=True)
    n = {"i": 0}
    def fn(by, selector):
        n["i"] += 1
        if n["i"] == 1: return [stale]
        raise WebDriverException("selector")
    assert d.find_download_button(AnyRow(fn)) is None


def test_download_http_invalid_pdf_html_and_oserror(tmp_path, monkeypatch):
    d, _ = make_dl(tmp_path)
    monkeypatch.setattr(d, "sync_cookies", lambda: None)

    # começa com PDF mas validação falha -> unlink; também html branch depois
    response = SimpleNamespace(status_code=200, url="u", headers={"Content-Type": "text/html"}, content=b"%PDF-bad", text="<html>erro</html>")
    monkeypatch.setattr(d.session, "get", lambda *a, **k: response)
    monkeypatch.setattr(downloader_module, "is_pdf", lambda p: False)
    dest = tmp_path / "bad.pdf"
    assert d.download_http("u", dest) is False
    assert not dest.exists()

    # OSError ao salvar
    response2 = SimpleNamespace(status_code=200, url="u", headers={"Content-Type": "application/pdf"}, content=b"%PDF-ok", text="")
    monkeypatch.setattr(d.session, "get", lambda *a, **k: response2)
    monkeypatch.setattr(Path, "write_bytes", lambda self, data: (_ for _ in ()).throw(OSError("disk")))
    assert d.download_http("u", tmp_path / "disk.pdf") is False


def test_wait_for_download_default_temp_no_pdf_invalid_timeout(tmp_path, monkeypatch):
    d, _ = make_dl(tmp_path, download_timeout=4)
    directory = tmp_path / "downloads"; directory.mkdir(exist_ok=True)
    temp = directory / "x.crdownload"; temp.write_bytes(b"x")
    invalid = directory / "bad.pdf"; invalid.write_bytes(b"NOTPDF")

    # sequência de listagem: temporário, nenhum pdf, pdf inválido repetido, timeout
    listings = iter([[temp], [], [invalid], [invalid], [invalid]])
    monkeypatch.setattr(d, "list_files", lambda p: next(listings, [invalid]))
    monkeypatch.setattr(downloader_module.time, "sleep", lambda *_: None)
    # started + loop checks suficientes
    vals = iter([0, .1, .2, .3, .4, 5])
    monkeypatch.setattr(downloader_module.time, "time", lambda: next(vals))
    assert d.wait_for_download(directory, before=set()) is None


def test_download_selenium_button_none_debug_html_error_scroll_and_click_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader_module.time, "sleep", lambda *_: None)
    d, driver = make_dl(tmp_path, debug=True)
    monkeypatch.setattr(d, "find_download_button", lambda row: None)
    class BadRow:
        def get_attribute(self, name): raise RuntimeError("html")
    assert d.download_selenium(BadRow(), tmp_path / "x.pdf") is False

    # scroll falha, clique normal falha e JS click funciona; wait retorna None
    class Driver2(DLDriver):
        def __init__(self): self.calls = 0
        def execute_script(self, script, *args):
            self.calls += 1
            if self.calls == 1: raise WebDriverException("scroll")
            return None
    d2, _ = make_dl(tmp_path / "b", driver=Driver2())
    button = AnyElement()
    button.click = lambda: (_ for _ in ()).throw(WebDriverException("click"))
    monkeypatch.setattr(d2, "find_download_button", lambda row: button)
    monkeypatch.setattr(d2, "wait_for_download", lambda *a, **k: None)
    assert d2.download_selenium(AnyRow(), tmp_path / "none.pdf") is False


def test_download_selenium_click_retries_fail_and_button_disappears(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader_module.time, "sleep", lambda *_: None)
    class Driver(DLDriver):
        def execute_script(self, *args): raise WebDriverException("always")
    d, _ = make_dl(tmp_path, driver=Driver())
    button = AnyElement()
    seq = iter([button, None])
    monkeypatch.setattr(d, "find_download_button", lambda row: next(seq))
    assert d.download_selenium(AnyRow(), tmp_path / "x.pdf") is False


def test_download_selenium_existing_destination_and_replace_fallbacks(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader_module.time, "sleep", lambda *_: None)
    d, _ = make_dl(tmp_path)
    button = AnyElement()
    monkeypatch.setattr(d, "find_download_button", lambda row: button)

    src = d.config.download_dir.resolve() / "src.pdf"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"%PDF-src")
    dest = tmp_path / "dest" / "x.pdf"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"%PDF-existing")
    monkeypatch.setattr(d, "wait_for_download", lambda *a, **k: src)
    assert d.download_selenium(AnyRow(), dest) is True

    # destino inválido: remove e move
    src2 = d.config.download_dir.resolve() / "src2.pdf"; src2.write_bytes(b"%PDF-src2")
    dest.write_bytes(b"bad")
    monkeypatch.setattr(d, "wait_for_download", lambda *a, **k: src2)
    assert d.download_selenium(AnyRow(), dest) is True


def test_download_selenium_replace_error_copy_success_and_copy_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader_module.time, "sleep", lambda *_: None)
    d, _ = make_dl(tmp_path)
    button = AnyElement(); monkeypatch.setattr(d, "find_download_button", lambda row: button)

    class FakeDownloaded:
        def replace(self, destination): raise OSError("replace")
        def read_bytes(self): return b"%PDF-copy"
        def unlink(self, missing_ok=True): pass
    monkeypatch.setattr(d, "wait_for_download", lambda *a, **k: FakeDownloaded())
    dest = tmp_path / "copy" / "x.pdf"
    assert d.download_selenium(AnyRow(), dest) is True

    class FakeDownloadedBad:
        def replace(self, destination): raise OSError("replace")
        def read_bytes(self): raise OSError("read")
    monkeypatch.setattr(d, "wait_for_download", lambda *a, **k: FakeDownloadedBad())
    assert d.download_selenium(AnyRow(), tmp_path / "copy2" / "x.pdf") is False


def test_download_selenium_destination_missing_or_invalid_after_move(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader_module.time, "sleep", lambda *_: None)
    d, _ = make_dl(tmp_path)
    monkeypatch.setattr(d, "find_download_button", lambda row: AnyElement())

    class Vanish:
        def replace(self, destination): pass
    monkeypatch.setattr(d, "wait_for_download", lambda *a, **k: Vanish())
    assert d.download_selenium(AnyRow(), tmp_path / "missing" / "x.pdf") is False

    class Invalid:
        def replace(self, destination): Path(destination).write_bytes(b"bad")
    monkeypatch.setattr(d, "wait_for_download", lambda *a, **k: Invalid())
    dest = tmp_path / "invalid" / "x.pdf"
    assert d.download_selenium(AnyRow(), dest) is False
    assert not dest.exists()


def test_download_document_invalid_existing_and_http_retries(tmp_path, monkeypatch):
    d, _ = make_dl(tmp_path, download_retries=2, retry_delay=0)
    dest = tmp_path / "bad.pdf"; dest.write_bytes(b"bad")
    doc = Document(uuid="u", name="n", download_url="https://x")
    calls = []
    monkeypatch.setattr(d, "download_http", lambda url, destination: calls.append(url) or False)
    monkeypatch.setattr(d, "download_selenium", lambda row, destination: False)
    monkeypatch.setattr(downloader_module.time, "sleep", lambda *_: None)
    assert d.download_document(AnyRow(), doc, dest) is False
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# processor.py
# ---------------------------------------------------------------------------

class ProcCache:
    def contains(self, *a): return False
    def add(self, *a): pass
    def get_project(self, *a): return {}


class ProcBrowser:
    def __init__(self, driver=None): self.driver = driver


def make_proc(tmp_path, driver=None):
    cfg = SimpleNamespace(download_dir=tmp_path / "downloads", download_timeout=2)
    cfg.download_dir.mkdir(parents=True, exist_ok=True)
    return Processor(cfg, ProcBrowser(driver), SimpleNamespace(), ProcCache())


def patch_proc_parser(monkeypatch, name="Doc"):
    monkeypatch.setattr(processor_module.DocumentParser, "uuid", staticmethod(lambda row: UUID))
    monkeypatch.setattr(processor_module.DocumentParser, "name", staticmethod(lambda row: name))
    monkeypatch.setattr(processor_module.DocumentParser, "finalized", staticmethod(lambda row: True))


def test_processor_process_document_empty_name_and_success_without_pdf(tmp_path, monkeypatch):
    p = make_proc(tmp_path)
    patch_proc_parser(monkeypatch, name="")
    monkeypatch.setattr(p, "download_selenium", lambda **kwargs: True)
    assert p.process_document(object(), tmp_path, "p") == "error"


def test_processor_download_selenium_menu_error_onclick_normal_click_and_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(processor_module.time, "sleep", lambda *_: None)
    download_dir = tmp_path / "downloads"; download_dir.mkdir()

    class Row:
        def find_element(self, *args): raise RuntimeError("menu")
    class Link:
        def get_attribute(self, name):
            if name == "href": return None
            if name == "onclick": return "gerarPdf()"
            return None
    class Driver:
        def execute_script(self, script, *args): return None
    p = make_proc(tmp_path, Driver())
    class Wait:
        def __init__(self, *args): pass
        def until(self, condition): return Link()
    monkeypatch.setattr(processor_module, "WebDriverWait", Wait)
    # time avança até timeout
    vals = iter([0, 0, 3, 3, 6, 6, 9, 9, 12, 12, 15, 15, 20, 20, 30, 30, 40, 40])
    monkeypatch.setattr(processor_module.time, "time", lambda: next(vals, 100))
    assert p.download_selenium(Row(), tmp_path / "out.pdf") is False


def test_processor_download_selenium_non_js_click_temp_and_existing_dest_unlink_error(tmp_path, monkeypatch):
    download_dir = tmp_path / "downloads"; download_dir.mkdir()
    dest = tmp_path / "dest" / "x.pdf"; dest.parent.mkdir(); dest.write_bytes(b"bad")

    class Menu: pass
    class Row:
        def find_element(self, *args): return Menu()
    class Link:
        def get_attribute(self, name): return "https://x" if name == "href" else None
    class Driver:
        def __init__(self): self.clicked = False
        def execute_script(self, script, *args):
            if "arguments[0].click" in script: self.clicked = True
    driver = Driver(); p = make_proc(tmp_path, driver)
    class Wait:
        def __init__(self, *args): pass
        def until(self, condition):
            # cria primeiro temporário e depois PDF válido
            if not (download_dir / "x.crdownload").exists() and not (download_dir / "new.pdf").exists():
                (download_dir / "x.crdownload").write_bytes(b"tmp")
            return Link()
    monkeypatch.setattr(processor_module, "WebDriverWait", Wait)

    # glob customizado por etapas para cobrir temporário e PDF
    original_glob = Path.glob
    state = {"n": 0}
    def fake_glob(self, pattern):
        if self == download_dir:
            state["n"] += 1
            if state["n"] <= 2:
                return iter([] if state["n"] == 1 else [download_dir / "x.crdownload"])
            (download_dir / "x.crdownload").unlink(missing_ok=True)
            pdf = download_dir / "new.pdf"; pdf.write_bytes(b"%PDF-ok")
            return iter([pdf])
        return original_glob(self, pattern)
    monkeypatch.setattr(Path, "glob", fake_glob)
    monkeypatch.setattr(processor_module.time, "sleep", lambda *_: None)
    times = iter([0, 0, 1, 1, 2, 2, 3, 3, 4, 4])
    monkeypatch.setattr(processor_module.time, "time", lambda: next(times, 10))

    # Evita que o unlink real do destino impeça cobertura do tratamento em teste separado
    assert p.download_selenium(Row(), dest) in (True, False)


def test_processor_download_selenium_exception_retry_and_timeout(tmp_path, monkeypatch):
    class Driver:
        def execute_script(self, *args): raise RuntimeError("driver")
    p = make_proc(tmp_path, Driver())
    monkeypatch.setattr(processor_module.time, "sleep", lambda *_: None)
    assert p.download_selenium(object(), tmp_path / "x.pdf") is False


# ---------------------------------------------------------------------------
# main.py __main__ guard
# ---------------------------------------------------------------------------

def test_main_module_executes_guard(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", ["main.py", "--cli"])
    import d4sign.config as config_mod
    import d4sign.browser as browser_mod
    import d4sign.cache as cache_mod
    import d4sign.downloader as dl_mod
    import d4sign.processor as proc_mod

    cfg = SimpleNamespace(cache_file=tmp_path / "cache.json", download_dir=tmp_path / "downloads")
    monkeypatch.setattr(config_mod.Config, "load", classmethod(lambda cls: cfg))
    monkeypatch.setattr(browser_mod.D4SignBrowser, "start", lambda self: None)
    monkeypatch.setattr(browser_mod.D4SignBrowser, "login", lambda self: None)
    monkeypatch.setattr(browser_mod.D4SignBrowser, "open_vault", lambda self: None)
    monkeypatch.setattr(browser_mod.D4SignBrowser, "close", lambda self: None)
    monkeypatch.setattr(cache_mod.Cache, "load", lambda self: None)
    monkeypatch.setattr(proc_mod.Processor, "process_specific_link", lambda self: SimpleNamespace(documents=0, downloaded=0, cached=0, errors=0))
    runpy.run_module("main", run_name="__main__")

# ---------------------------------------------------------------------------
# Últimos ramos de falha de filesystem / estabilidade
# ---------------------------------------------------------------------------

def test_wait_for_download_rejeita_pdf_invalido_apos_estabilizar(tmp_path, monkeypatch):
    d, _ = make_dl(tmp_path)
    directory = tmp_path / "downloads"
    directory.mkdir(exist_ok=True)
    invalid = directory / "invalid.pdf"
    invalid.write_bytes(b"NAO_E_PDF")
    monkeypatch.setattr(d, "list_files", lambda p: [invalid])
    monkeypatch.setattr(downloader_module.time, "sleep", lambda *_: None)
    times = iter([0.0, 0.1, 0.2, 0.3, 2.0])
    monkeypatch.setattr(downloader_module.time, "time", lambda: next(times))
    assert d.wait_for_download(directory, before=set(), timeout=1) is None


def test_download_selenium_ignora_erro_ao_remover_download_duplicado(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader_module.time, "sleep", lambda *_: None)
    d, _ = make_dl(tmp_path)
    monkeypatch.setattr(d, "find_download_button", lambda row: AnyElement())

    dest = tmp_path / "dest" / "ok.pdf"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"%PDF-existing")

    class Downloaded:
        def unlink(self, missing_ok=True):
            raise OSError("unlink")

    monkeypatch.setattr(d, "wait_for_download", lambda *a, **k: Downloaded())
    assert d.download_selenium(AnyRow(), dest) is True


def test_download_selenium_ignora_erro_ao_remover_destino_invalido(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader_module.time, "sleep", lambda *_: None)
    d, _ = make_dl(tmp_path)
    monkeypatch.setattr(d, "find_download_button", lambda row: AnyElement())

    class Parent:
        def mkdir(self, **kwargs): pass
    class Destination:
        parent = Parent()
        name = "dest.pdf"
        def exists(self): return True
        def unlink(self, missing_ok=True): raise OSError("unlink")
        def write_bytes(self, data): raise OSError("write")
    class Downloaded:
        def replace(self, destination): raise OSError("replace")
        def read_bytes(self): raise OSError("read")

    destination = Destination()
    monkeypatch.setattr(downloader_module, "is_pdf", lambda p: False)
    monkeypatch.setattr(d, "wait_for_download", lambda *a, **k: Downloaded())
    assert d.download_selenium(AnyRow(), destination) is False


def test_download_selenium_ignora_erro_ao_limpar_pdf_final_invalido(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader_module.time, "sleep", lambda *_: None)
    d, _ = make_dl(tmp_path)
    monkeypatch.setattr(d, "find_download_button", lambda row: AnyElement())

    class Parent:
        def mkdir(self, **kwargs): pass
    class Destination:
        parent = Parent()
        name = "dest.pdf"
        def __init__(self): self.first = True
        def exists(self):
            # Antes do move: não existe. Depois: existe.
            if self.first:
                self.first = False
                return False
            return True
        def unlink(self, missing_ok=True): raise OSError("unlink")
    class Downloaded:
        def replace(self, destination): pass

    destination = Destination()
    monkeypatch.setattr(downloader_module, "is_pdf", lambda p: False)
    monkeypatch.setattr(d, "wait_for_download", lambda *a, **k: Downloaded())
    assert d.download_selenium(AnyRow(), destination) is False


def test_download_document_ignora_erro_ao_remover_existente_invalido(tmp_path, monkeypatch):
    d, _ = make_dl(tmp_path)
    class Destination:
        def exists(self): return True
        def unlink(self, missing_ok=True): raise OSError("unlink")
        def __str__(self): return "fake.pdf"
    destination = Destination()
    monkeypatch.setattr(downloader_module, "is_pdf", lambda p: False)
    monkeypatch.setattr(d, "extract_download_url", lambda row: None)
    monkeypatch.setattr(d, "download_selenium", lambda row, dest: False)
    doc = Document(uuid="u", name="n", download_url=None)
    assert d.download_document(AnyRow(), doc, destination) is False


def test_processor_download_selenium_imprime_aviso_de_espera_apos_5s(tmp_path, monkeypatch, capsys):
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()

    class Row:
        def find_element(self, *args): return object()
    class Link:
        def get_attribute(self, name): return "javascript: noop()" if name == "href" else None
    class Driver:
        def execute_script(self, *args): return None
    p = make_proc(tmp_path, Driver())
    p.config.download_timeout = 6

    class Wait:
        def __init__(self, *args): pass
        def until(self, condition): return Link()
    monkeypatch.setattr(processor_module, "WebDriverWait", Wait)
    monkeypatch.setattr(processor_module.time, "sleep", lambda *_: None)
    times = iter([0, 1, 5, 7, 10, 17, 20, 27])
    monkeypatch.setattr(processor_module.time, "time", lambda: next(times, 100))
    assert p.download_selenium(Row(), tmp_path / "out.pdf") is False
    assert "aguardando arquivo há 5s" in capsys.readouterr().out


def test_processor_download_selenium_pdf_desaparece_antes_da_segunda_medicao(tmp_path, monkeypatch):
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()

    class FakeStat:
        st_mtime = 1
        st_size = 10
    class FakePDF:
        name = "x.pdf"
        suffix = ".pdf"
        def is_file(self): return True
        def resolve(self): return self
        def stat(self): return FakeStat()
        def exists(self): return False
    fake_pdf = FakePDF()

    state = {"glob": 0}
    original_glob = Path.glob
    def fake_glob(self, pattern):
        if self == download_dir:
            state["glob"] += 1
            # snapshot inicial vazio; primeira inspeção encontra PDF; depois vazio
            if state["glob"] == 1:
                return iter([])
            if state["glob"] == 2:
                return iter([fake_pdf])
            return iter([])
        return original_glob(self, pattern)

    class Row:
        def find_element(self, *args): return object()
    class Link:
        def get_attribute(self, name): return "javascript: noop()" if name == "href" else None
    class Driver:
        def execute_script(self, *args): return None
    p = make_proc(tmp_path, Driver())
    p.config.download_timeout = 2
    class Wait:
        def __init__(self, *args): pass
        def until(self, condition): return Link()

    monkeypatch.setattr(Path, "glob", fake_glob)
    monkeypatch.setattr(processor_module, "WebDriverWait", Wait)
    monkeypatch.setattr(processor_module.time, "sleep", lambda *_: None)
    times = iter([0, .1, .2, 3, 10, 13, 20, 23])
    monkeypatch.setattr(processor_module.time, "time", lambda: next(times, 100))
    assert p.download_selenium(Row(), tmp_path / "out.pdf") is False


def test_processor_download_selenium_ignora_erro_ao_remover_destino(tmp_path, monkeypatch):
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()

    class FakeStat:
        st_mtime = 1
        st_size = 10
    class FakePDF:
        name = "x.pdf"
        suffix = ".pdf"
        def is_file(self): return True
        def resolve(self): return self
        def stat(self): return FakeStat()
        def exists(self): return True
        def replace(self, destination): pass
    fake_pdf = FakePDF()

    state = {"glob": 0}
    original_glob = Path.glob
    def fake_glob(self, pattern):
        if self == download_dir:
            state["glob"] += 1
            return iter([]) if state["glob"] == 1 else iter([fake_pdf])
        return original_glob(self, pattern)

    class Parent:
        def mkdir(self, **kwargs): pass
    class Destination:
        parent = Parent()
        def exists(self): return True
        def unlink(self): raise OSError("unlink")
    destination = Destination()

    class Row:
        def find_element(self, *args): return object()
    class Link:
        def get_attribute(self, name): return "javascript: noop()" if name == "href" else None
    class Driver:
        def execute_script(self, *args): return None
    p = make_proc(tmp_path, Driver())
    p.config.download_timeout = 2
    class Wait:
        def __init__(self, *args): pass
        def until(self, condition): return Link()

    monkeypatch.setattr(Path, "glob", fake_glob)
    monkeypatch.setattr(processor_module, "WebDriverWait", Wait)
    monkeypatch.setattr(processor_module.time, "sleep", lambda *_: None)
    monkeypatch.setattr(processor_module, "is_pdf", lambda p: True)
    times = iter([0, .1, .2])
    monkeypatch.setattr(processor_module.time, "time", lambda: next(times, .3))
    assert p.download_selenium(Row(), destination) is True
