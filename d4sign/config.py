import os

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def env_bool(value: str) -> bool:
    return value.lower() in {
        "1",
        "true",
        "yes",
        "sim",
        "on",
    }


@dataclass(frozen=True)
class Config:
    base_url: str
    vault_id: str
    vault_uuid: str
    email: str
    password: str
    download_dir: Path
    cache_file: Path
    log_file: Path
    headless: bool
    page_timeout: int
    download_timeout: int
    download_retries: int
    retry_delay: float
    folder_name_filter: str | None
    include_all_statuses: bool = False
    location_url: str = ''

    @classmethod
    def load(cls):
        load_dotenv()

        email = os.getenv("D4SIGN_EMAIL", "").strip()
        password = os.getenv("D4SIGN_PASSWORD", "")

        if not email:
            raise RuntimeError(
                "D4SIGN_EMAIL não configurado."
            )

        if not password:
            raise RuntimeError(
                "D4SIGN_PASSWORD não configurado."
            )

        return cls(
            # URL principal do D4Sign
            base_url=os.getenv(
                "D4SIGN_BASE_URL",
                "https://secure.d4sign.com.br",
            ).rstrip("/"),

           
            vault_id=os.getenv(
                "D4SIGN_VAULT_ID",
                
            ),

            # UUID 
            vault_uuid=os.getenv(
                "D4SIGN_VAULT_UUID",
                
            ),

            email=email,

            password=password,

            # Pasta onde os documentos serão baixados
            download_dir=Path(
                os.getenv(
                    "DOWNLOAD_DIR",
                    "downloads",
                )
            ),

            # Arquivo de cache
            cache_file=Path(
                os.getenv(
                    "CACHE_FILE",
                    "cache.json",
                )
            ),

            # Arquivo de log
            log_file=Path(
                os.getenv(
                    "LOG_FILE",
                    "d4sign_downloader.log",
                )
            ),

            # Chrome sem interface gráfica
            headless=not os.getenv("DEVELOPMENT") and env_bool(
                os.getenv(
                    "HEADLESS",
                    "True",
                )
            ),

            # Tempo máximo para carregamento de páginas
            page_timeout=int(
                os.getenv(
                    "PAGE_TIMEOUT",
                    "40",
                )
            ),

            # Tempo máximo para download
            download_timeout=int(
                os.getenv(
                    "DOWNLOAD_TIMEOUT",
                    "120",
                )
            ),

            # Número de tentativas de download
            download_retries=int(
                os.getenv(
                    "DOWNLOAD_RETRIES",
                    "3",
                )
            ),

            # Intervalo entre tentativas
            retry_delay=float(
                os.getenv(
                    "RETRY_DELAY",
                    "2",
                )
            ),

            # Filtro pelo nome da pasta
            folder_name_filter=(
                os.getenv(
                    "FOLDER_NAME_FILTER",
                    "",
                ).strip()
                or None
            ),
        )
