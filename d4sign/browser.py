from __future__ import annotations

from typing import Optional
import time

from selenium import webdriver
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
import os
from .config import Config
from .models import Folder
from .utils import extract_uuid


class D4SignBrowser:

    def __init__(self, config: Config):
        self.config = config
        self.driver: Optional[webdriver.Chrome] = None

    # =========================================================
    # START
    # =========================================================

    def start(self) -> None:
        print("Iniciando Chrome...")

        self.config.download_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        options = Options()

        if self.config.headless:
            options.add_argument("--headless=new")

        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-infobars")

        # ---------------------------------------------------------
        # Chrome e ChromeDriver manuais
        # ---------------------------------------------------------

        user_profile = os.environ["USERPROFILE"]

        chromedriver_path = os.path.join(
            user_profile,
            "Chrome",
            "chromedriver.exe",
        )

        chrome_path = os.path.join(
            user_profile,
            "Chrome",
            "GoogleChrome",
            "App",
            "Chrome-bin",
            "chrome.exe",
        )

        # Verifica se os arquivos existem
        if not os.path.isfile(chromedriver_path):
            raise FileNotFoundError(
                f"ChromeDriver nao encontrado em: {chromedriver_path}"
            )

        if not os.path.isfile(chrome_path):
            raise FileNotFoundError(
                f"Chrome nao encontrado em: {chrome_path}"
            )

        print(f"Chrome: {chrome_path}")
        print(f"ChromeDriver: {chromedriver_path}")

        # IMPORTANTE:
        # Forca o Selenium a usar exatamente o Chrome manual.
        options.binary_location = chrome_path

        # ---------------------------------------------------------
        # Downloads
        # ---------------------------------------------------------

        download_dir = str(
            self.config.download_dir.resolve()
        )

        prefs = {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True,
            "safebrowsing.enabled": True,
        }

        options.add_experimental_option(
            "prefs",
            prefs,
        )

        # Forca o ChromeDriver manual.
        service = Service(
            executable_path=chromedriver_path
        )

        # ---------------------------------------------------------
        # Inicia Chrome
        # ---------------------------------------------------------

        self.driver = webdriver.Chrome(
            service=service,
            options=options,
        )

        self.driver.set_page_load_timeout(
            self.config.page_timeout
        )

        # ---------------------------------------------------------
        # Download via CDP
        # ---------------------------------------------------------

        try:
            self.driver.execute_cdp_cmd(
                "Page.setDownloadBehavior",
                {
                    "behavior": "allow",
                    "downloadPath": download_dir,
                },
            )

        except Exception as exc:
            print(
                f"Aviso: nao foi possivel configurar "
                f"download CDP: {exc}"
            )

        print("Chrome iniciado.")
    # =========================================================
    # DRIVER
    # =========================================================

    @property
    def current_driver(self) -> webdriver.Chrome:

        if self.driver is None:
            raise RuntimeError(
                "O navegador não foi iniciado."
            )

        return self.driver

    # =========================================================
    # CLOSE
    # =========================================================

    def close(self) -> None:

        if self.driver:

            print("Fechando Chrome...")

            try:
                self.driver.quit()
            except Exception:
                pass

            self.driver = None

    # =========================================================
    # GET
    # =========================================================

    def get(self, url: str) -> None:

        driver = self.current_driver

        print(f"Abrindo: {url}")

        try:
            driver.get(url)
        except TimeoutException:
            print(
                "Aviso: timeout durante carregamento."
            )

        # Aguarda DOM estabilizar
        try:
            WebDriverWait(
                driver,
                self.config.page_timeout,
            ).until(
                lambda d:
                d.execute_script(
                    "return document.readyState"
                )
                in (
                    "interactive",
                    "complete",
                )
            )
        except TimeoutException:
            print(
                "Aviso: página demorou para estabilizar."
            )

    # =========================================================
    # LOGIN
    # =========================================================

    def login(self) -> None:

        driver = self.current_driver

        print("Login...")

        self.get(
            f"{self.config.base_url}/"
        )

        wait = WebDriverWait(
            driver,
            self.config.page_timeout,
        )

        print(
            "Localizando campo de e-mail..."
        )

        try:
            email = wait.until(
                EC.presence_of_element_located(
                    (
                        By.ID,
                        "Email",
                    )
                )
            )

        except TimeoutException:
            print("ERRO: campo Email não encontrado.")
            print("URL atual:", driver.current_url)
            print("Título:", driver.title)

            self._save_diagnostic(
                "erro_campo_email"
            )

            raise RuntimeError(
                "Campo de e-mail não encontrado."
            )

        print(
            "Localizando campo de senha..."
        )

        password = wait.until(
            EC.presence_of_element_located(
                (
                    By.ID,
                    "Passwd",
                )
            )
        )

        email.clear()
        email.send_keys(
            self.config.email
        )

        password.clear()
        password.send_keys(
            self.config.password
        )

        print(
            "Credenciais preenchidas."
        )

        button = self._find_login_button()

        if not button:
            self._save_diagnostic(
                "erro_botao_login"
            )
            raise RuntimeError(
                "Botão de login não encontrado."
            )

        print(
            "Botão de login encontrado."
        )

        try:
            button.click()
        except Exception:
            print(
                "Clique normal falhou."
            )
            print(
                "Tentando JavaScript..."
            )
            driver.execute_script(
                "arguments[0].click();",
                button,
            )

        print(
            "Login enviado."
        )

        print(
            "Aguardando confirmação..."
        )

        try:
            WebDriverWait(
                driver,
                self.config.page_timeout,
            ).until(
                self._login_concluido
            )
        except TimeoutException:
            self._save_diagnostic(
                "erro_login_timeout"
            )
            raise RuntimeError(
                "Login enviado, mas não foi possível "
                "confirmar o login."
            )

        print(
            "LOGIN OK!"
        )

    # =========================================================
    # ENCONTRAR BOTÃO LOGIN
    # =========================================================

    def _find_login_button(self):

        driver = self.current_driver

        selectors = [
            (
                By.ID,
                "logar",
            ),
            (
                By.NAME,
                "logar",
            ),
            (
                By.CSS_SELECTOR,
                "button[onclick*='logarC']",
            ),
            (
                By.CSS_SELECTOR,
                "input[onclick*='logarC']",
            ),
            (
                By.CSS_SELECTOR,
                "button[type='submit']",
            ),
            (
                By.CSS_SELECTOR,
                "input[type='submit']",
            ),
        ]

        for by, selector in selectors:
            try:
                elements = driver.find_elements(
                    by,
                    selector,
                )

                for element in elements:
                    if element.is_displayed():
                        return element

            except WebDriverException:
                continue

        return None

    # =========================================================
    # LOGIN CONCLUÍDO
    # =========================================================

    def _login_concluido(
        self,
        driver,
    ) -> bool:

        url = driver.current_url.lower()

        if (
            "/desk/" in url
            and "login" not in url
        ):
            return True

        indicadores = [
            "#filtrar_pastas_div",
            "[id*='liFolder']",
            ".nome_pasta",
            "a[href*='/desk/cofres/']",
        ]

        for selector in indicadores:
            try:
                if driver.find_elements(
                    By.CSS_SELECTOR,
                    selector,
                ):
                    return True
            except WebDriverException:
                pass

        try:
            body = driver.find_element(
                By.TAG_NAME,
                "body",
            ).text.lower()

            erros = [
                "senha inválida",
                "senha invalida",
                "usuário ou senha",
                "usuario ou senha",
                "login inválido",
                "login invalido",
                "credenciais inválidas",
                "credenciais invalidas",
            ]

            for erro in erros:
                if erro in body:
                    raise RuntimeError(
                        f"Falha no login: {erro}"
                    )

        except RuntimeError:
            raise

        except Exception:
            pass

        return False

    # =========================================================
    # COFRE
    # =========================================================

    def open_vault(self) -> None:

        url = (
            f"{self.config.base_url}"
            f"/desk/cofres/"
            f"{self.config.vault_id}/"
            f"{self.config.vault_uuid}"
        )

        print(
            "Abrindo cofre..."
        )

        self.get(url)

        print(
            "Cofre aberto."
        )

    # =========================================================
    # PASTAS
    # =========================================================

    def get_folders(self) -> list[Folder]:

        driver = self.current_driver

        print(
            "Procurando pastas..."
        )

        elements = driver.find_elements(
            By.CSS_SELECTOR,
            "[id*='liFolder']",
        )

        folders = []

        for element in elements:
            try:
                html = (
                    element.get_attribute(
                        "outerHTML"
                    )
                    or ""
                )

                uuid = extract_uuid(
                    html
                )

                if not uuid:
                    continue

                name_elements = (
                    element.find_elements(
                        By.CSS_SELECTOR,
                        ".nome_pasta",
                    )
                )

                if name_elements:
                    name = (
                        name_elements[0]
                        .text
                        .strip()
                    )
                else:
                    name = (
                        f"pasta_{uuid}"
                    )

                folders.append(
                    Folder(
                        uuid=uuid,
                        name=name,
                    )
                )

            except WebDriverException:
                continue

        unique = {}

        for folder in folders:
            unique[
                folder.uuid
            ] = folder

        folders = list(
            unique.values()
        )

        print(
            f"Pastas encontradas: {len(folders)}"
        )

        for folder in folders:
            print(
                f"  - {folder.name}"
                f" | {folder.uuid}"
            )

        return folders

    # =========================================================
    # PÁGINA DA PASTA
    # =========================================================

    # =========================================================
# PÁGINA DA PASTA
# =========================================================

    def document_total(self, folder_uuid):
        """Read the site's document count for this location, not just one page."""
        self.open_folder_page(folder_uuid, 0)
        elements = self.current_driver.find_elements(
            By.CSS_SELECTOR,
            '[data-original-title="Total de documentos"] b, '
            '[title="Total de documentos"] b',
        )
        for element in elements:
            value = element.text.strip()
            digits = value.replace('.', '').replace(',', '').replace(' ', '').replace('\u00a0', '')
            if digits.isdecimal():
                return int(digits)
        return None

    def open_folder_page(
        self,
        folder_uuid: str,
        page: int,
    ):
        driver = self.current_driver

        location_url = getattr(self.config, 'location_url', '')
        url = (
            f"{location_url}?p={page}&f=&fase=NA=="
            if location_url else
            f"{self.config.base_url}"
            f"/desk/cofres/"
            f"{self.config.vault_id}/"
            f"{folder_uuid}.html"
            f"?p={page}"
            f"&f="
            f"&fase=NA=="
        )

        print()
        print("=" * 70)
        print(f"ABRINDO PÁGINA {page}")
        print("=" * 70)
        print(url)

        self.get(url)

        if getattr(self.config, 'include_all_statuses', False):
            if folder_uuid.lower() not in driver.current_url.lower() or driver.find_elements(By.CSS_SELECTOR, 'input#Passwd'):
                raise RuntimeError('A sessão expirou ou esta pasta não está mais acessível. Entre novamente.')

        try:
            WebDriverWait(
                driver,
                self.config.page_timeout,
            ).until(
                lambda d: d.execute_script(
                    "return document.readyState"
                ) == "complete"
            )

        except TimeoutException:
            print(
                "Aviso: document.readyState não chegou a complete."
            )

        time.sleep(1.5)

        rows = []

        for tentativa in range(5):

            rows = driver.find_elements(
                By.CSS_SELECTOR,
                "tr.read",
            )

            if rows:
                break

            print(
                f"Aguardando documentos aparecerem... "
                f"tentativa {tentativa + 1}/5"
            )

            time.sleep(1)

        print(
            f"Documentos encontrados: {len(rows)}"
        )

        if rows:

            try:
                driver.execute_script(
                    """
                    arguments[0].scrollIntoView({
                        behavior: 'instant',
                        block: 'center'
                    });
                    """,
                    rows[0],
                )

                time.sleep(0.5)

            except Exception:
                pass

        return rows

    def _save_diagnostic(
        self,
        name: str,
    ) -> None:

        driver = self.driver

        if not driver:
            return

        try:
            screenshot = (
                f"{name}.png"
            )

            html_file = (
                f"{name}.html"
            )

            driver.save_screenshot(
                screenshot
            )

            with open(
                html_file,
                "w",
                encoding="utf-8",
            ) as file:
                file.write(
                    driver.page_source
                )

            print(
                f"Diagnóstico salvo:"
            )
            print(
                f"  {screenshot}"
            )
            print(
                f"  {html_file}"
            )

        except Exception as exc:
            print(
                f"Erro salvando diagnóstico: {exc}"
            )
