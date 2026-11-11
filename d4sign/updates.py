"""Stable GitHub releases and verified Windows installer downloads."""
import hashlib
import json
from pathlib import Path
import re
import tempfile
from dataclasses import dataclass
from urllib.request import Request, urlopen

from .version import REPOSITORY, VERSION


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        raise ValueError("Versão inválida; use vMAJOR.MINOR.PATCH.")
    return tuple(map(int, value.removeprefix("v").split(".")))


@dataclass(frozen=True)
class Update:
    version: str
    url: str
    size: int
    sha256: str


def request(url):
    return Request(url, headers={"User-Agent": "D4Sign-Desktop", "Accept": "application/vnd.github+json"})


def validate_url(url):
    prefix = f"https://github.com/{REPOSITORY}/releases/download/"
    if not isinstance(url, str) or not url.startswith(prefix):
        raise ValueError("Endereço do instalador inválido.")


def check_update():
    with urlopen(request(f"https://api.github.com/repos/{REPOSITORY}/releases/latest"), timeout=15) as response:
        release = json.load(response)
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        raise ValueError("Release estável inválida.")
    tag = release.get("tag_name")
    if version_tuple(tag) <= version_tuple(VERSION):
        return None
    ver = tag.removeprefix("v")
    exe_name = f"BaixarAssinaturasD4sign v{ver}.exe"
    sha_name = f"BaixarAssinaturasD4sign v{ver}.sha256"
    assets = {a.get("name"): a for a in release.get("assets", [])}
    exe = assets.get(exe_name)
    if not exe:
        raise ValueError(f"Versão {tag} disponível, mas o executável {exe_name} ainda não foi publicado.")
    url = exe.get("browser_download_url", "")
    validate_url(url)
    size = exe.get("size")
    if type(size) is not int or size <= 0:
        raise ValueError("Tamanho do executável inválido.")
    # Lê SHA-256 do arquivo sidecar publicado junto com o exe
    sha_asset = assets.get(sha_name)
    sha256 = ""
    if sha_asset:
        sha_url = sha_asset.get("browser_download_url", "")
        validate_url(sha_url)
        with urlopen(request(sha_url), timeout=10) as r:
            sha256 = r.read(128).decode().strip().split()[0].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("Arquivo SHA-256 da release com formato inválido.")
    return Update(tag, url, size, sha256)


def download_update(update, progress=lambda value: None):
    validate_url(update.url)
    folder = Path(tempfile.mkdtemp(prefix="d4sign-update-"))
    ver = update.version.removeprefix("v")
    path = folder / f"BaixarAssinaturasD4sign v{ver}.exe"
    digest = hashlib.sha256()
    received = 0
    try:
        with urlopen(request(update.url), timeout=60) as response, path.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                received += len(chunk)
                if received > update.size + 1024:
                    raise ValueError("Executável maior que o tamanho informado.")
                output.write(chunk)
                digest.update(chunk)
                progress(int(min(received, update.size) * 100 / update.size))
        if update.sha256 and digest.hexdigest() != update.sha256:
            raise ValueError("A integridade do executável não foi confirmada. Tente novamente.")
        return path
    except Exception:
        path.unlink(missing_ok=True)
        folder.rmdir()
        raise
