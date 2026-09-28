from pathlib import Path
from types import SimpleNamespace

import pytest
from selenium.common.exceptions import TimeoutException, WebDriverException

import d4sign.browser as browser_module
from d4sign.browser import D4SignBrowser

UUID1 = "12345678-1234-1234-1234-123456789abc"
UUID2 = "87654321-4321-4321-4321-cba987654321"


def make_config(tmp_path: Path, **overrides):
    data = dict(
        download_dir=tmp_path / "downloads",
        headless=True,
        page_timeout=10,
        base_url="https://example.test",
        email="user@example.com",
        password="secret",
        vault_id="10",
        vault_uuid="vault-uuid",
    )
    data.update(overrides)
    return SimpleNamespace(**data)


class FakeOptions:
    def __init__(self):
        self.arguments = []
        self.experimental = {}

    def add_argument(self, value):
        self.arguments.append(value)

    def add_experimental_option(self, name, value):
        self.experimental[name] = value


class FakeDriver:
    def __init__(self):
        self.timeout = None
        self.cdp = []
        self.quit_called = False
        self.current_url = "https://example.test/desk/"
        self.title = "Desk"
        self.page_source = "<html>ok</html>"
        self.find_elements_result = []
        self.scripts = []
        self.get_urls = []

    def set_page_load_timeout(self, value):
        self.timeout = value

    def execute_cdp_cmd(self, cmd, params):
        self.cdp.append((cmd, params))

    def quit(self):
        self.quit_called = True

    def get(self, url):
        self.get_urls.append(url)

    def execute_script(self, script, *args):
        self.scripts.append((script, args))
        if "document.readyState" in script:
            return "complete"
        return None

    def find_elements(self, by, selector):
        if isinstance(self.find_elements_result, dict):
            value = self.find_elements_result.get((by, selector), [])
            if isinstance(value, Exception):
                raise value
            return value
        return self.find_elements_result

    def find_element(self, by, selector):
        if selector == "body":
            return SimpleNamespace(text="conteúdo normal")
        raise WebDriverException("não encontrado")

    def save_screenshot(self, path):
        Path(path).write_bytes(b"png")


class FolderElement:
    def __init__(self, uuid, name=None):
        self.uuid = uuid
        self.name = name

    def get_attribute(self, name):
        if name == "outerHTML":
            return f"<li id='liFolder-{self.uuid}'></li>"
        return None

    def find_elements(self, by, selector):
        if selector == ".nome_pasta" and self.name is not None:
            return [SimpleNamespace(text=self.name)]
        return []


def test_init_e_current_driver(tmp_path: Path):
    browser = D4SignBrowser(make_config(tmp_path))
    with pytest.raises(RuntimeError, match="não foi iniciado"):
        _ = browser.current_driver
    fake = FakeDriver()
    browser.driver = fake
    assert browser.current_driver is fake


def test_start_configura_chrome(tmp_path: Path, monkeypatch):
    fake_driver = FakeDriver()
    monkeypatch.setattr(browser_module, "Options", FakeOptions)
    monkeypatch.setattr(browser_module, "Service", lambda executable_path: ("service", executable_path))
    monkeypatch.setattr(browser_module.ChromeDriverManager, "install", lambda self: "/fake/chromedriver")
    monkeypatch.setattr(browser_module.webdriver, "Chrome", lambda **kwargs: fake_driver)

    browser = D4SignBrowser(make_config(tmp_path))
    browser.start()

    assert browser.driver is fake_driver
    assert fake_driver.timeout == 10
    assert fake_driver.cdp[0][0] == "Page.setDownloadBehavior"
    assert (tmp_path / "downloads").is_dir()


def test_close_fecha_e_limpa_driver(tmp_path: Path):
    browser = D4SignBrowser(make_config(tmp_path))
    driver = FakeDriver()
    browser.driver = driver
    browser.close()
    assert driver.quit_called is True
    assert browser.driver is None


def test_get_abre_url_e_aguarda_dom(tmp_path: Path, monkeypatch):
    browser = D4SignBrowser(make_config(tmp_path))
    driver = FakeDriver()
    browser.driver = driver
    browser.get("https://example.test/x")
    assert driver.get_urls == ["https://example.test/x"]


def test_get_tolera_timeout_do_driver(tmp_path: Path, monkeypatch):
    browser = D4SignBrowser(make_config(tmp_path))
    driver = FakeDriver()
    driver.get = lambda url: (_ for _ in ()).throw(TimeoutException("timeout"))
    browser.driver = driver
    browser.get("https://example.test/x")


def test_find_login_button_retorna_primeiro_visivel(tmp_path: Path):
    browser = D4SignBrowser(make_config(tmp_path))
    driver = FakeDriver()
    hidden = SimpleNamespace(is_displayed=lambda: False)
    visible = SimpleNamespace(is_displayed=lambda: True)
    driver.find_elements_result = {
        (browser_module.By.ID, "logar"): [hidden, visible],
    }
    browser.driver = driver
    assert browser._find_login_button() is visible


def test_login_concluido_por_url_indicador_e_erro(tmp_path: Path):
    browser = D4SignBrowser(make_config(tmp_path))
    driver = FakeDriver()
    driver.current_url = "https://example.test/desk/home"
    assert browser._login_concluido(driver) is True

    driver.current_url = "https://example.test/login"
    indicator = object()
    driver.find_elements_result = {(browser_module.By.CSS_SELECTOR, "#filtrar_pastas_div"): [indicator]}
    assert browser._login_concluido(driver) is True

    driver.find_elements_result = []
    driver.find_element = lambda by, selector: SimpleNamespace(text="Usuário ou senha incorretos")
    with pytest.raises(RuntimeError, match="Falha no login"):
        browser._login_concluido(driver)


def test_login_preenche_campos_e_clica(tmp_path: Path, monkeypatch):
    browser = D4SignBrowser(make_config(tmp_path))
    driver = FakeDriver()
    browser.driver = driver

    class Field:
        def __init__(self):
            self.value = None
        def clear(self):
            self.value = ""
        def send_keys(self, value):
            self.value = value

    email, password = Field(), Field()
    button = SimpleNamespace(click=lambda: None)
    sequence = iter([email, password, True])

    class Wait:
        def __init__(self, driver, timeout):
            pass
        def until(self, condition):
            return next(sequence)

    monkeypatch.setattr(browser_module, "WebDriverWait", Wait)
    monkeypatch.setattr(browser, "get", lambda url: None)
    monkeypatch.setattr(browser, "_find_login_button", lambda: button)

    browser.login()
    assert email.value == "user@example.com"
    assert password.value == "secret"


def test_open_vault_monta_url(tmp_path: Path, monkeypatch):
    browser = D4SignBrowser(make_config(tmp_path))
    urls = []
    monkeypatch.setattr(browser, "get", urls.append)
    browser.open_vault()
    assert urls == ["https://example.test/desk/cofres/10/vault-uuid"]


def test_get_folders_extrai_nome_fallback_e_remove_duplicados(tmp_path: Path):
    browser = D4SignBrowser(make_config(tmp_path))
    driver = FakeDriver()
    driver.find_elements_result = [
        FolderElement(UUID1, " Pasta A "),
        FolderElement(UUID1, "Pasta A duplicada"),
        FolderElement(UUID2, None),
        FolderElement("sem-uuid", "Ignorar"),
    ]
    browser.driver = driver
    folders = browser.get_folders()
    assert [f.uuid for f in folders] == [UUID1, UUID2]
    assert folders[0].name == "Pasta A duplicada"
    assert folders[1].name == f"pasta_{UUID2}"


def test_open_folder_page_retorna_rows(tmp_path: Path, monkeypatch):
    browser = D4SignBrowser(make_config(tmp_path))
    driver = FakeDriver()
    rows = [object(), object()]
    driver.find_elements_result = rows
    browser.driver = driver
    urls = []
    monkeypatch.setattr(browser, "get", urls.append)
    monkeypatch.setattr(browser_module.time, "sleep", lambda *_: None)

    result = browser.open_folder_page(UUID1, 2)
    assert result == rows
    assert f"/{UUID1}.html?p=2" in urls[0]


def test_save_diagnostic_cria_png_e_html(tmp_path: Path, monkeypatch):
    browser = D4SignBrowser(make_config(tmp_path))
    browser.driver = FakeDriver()
    monkeypatch.chdir(tmp_path)
    browser._save_diagnostic("estado")
    assert (tmp_path / "estado.png").exists()
    assert (tmp_path / "estado.html").read_text(encoding="utf-8") == "<html>ok</html>"
