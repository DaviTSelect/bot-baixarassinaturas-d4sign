from pathlib import Path
from types import SimpleNamespace

import pytest

import main as main_module


class FakeBrowser:
    def __init__(self, config):
        self.config = config
        self.calls = []
    def start(self): self.calls.append("start")
    def login(self): self.calls.append("login")
    def open_vault(self): self.calls.append("open_vault")
    def close(self): self.calls.append("close")


class FakeCache:
    def __init__(self, path):
        self.path = path
        self.load_calls = 0
    def load(self): self.load_calls += 1


def test_main_orquestra_fluxo_e_fecha_browser(tmp_path: Path, monkeypatch, capsys):
    cfg = SimpleNamespace(cache_file=tmp_path / "cache.json", download_dir=tmp_path / "downloads")
    browser_box = {}
    cache_box = {}

    monkeypatch.setattr(main_module.Config, "load", classmethod(lambda cls: cfg))
    def browser_factory(config):
        browser_box["obj"] = FakeBrowser(config)
        return browser_box["obj"]
    def cache_factory(path):
        cache_box["obj"] = FakeCache(path)
        return cache_box["obj"]
    monkeypatch.setattr(main_module, "D4SignBrowser", browser_factory)
    monkeypatch.setattr(main_module, "Cache", cache_factory)
    monkeypatch.setattr(main_module, "Downloader", lambda config, browser: object())
    monkeypatch.setattr(
        main_module,
        "Processor",
        lambda config, browser, downloader, cache: SimpleNamespace(
            process_specific_link=lambda: SimpleNamespace(documents=3, downloaded=2, cached=1, errors=0)
        ),
    )

    main_module.main(["--cli"])

    assert browser_box["obj"].calls == ["start", "login", "open_vault", "close"]
    assert cache_box["obj"].load_calls == 1
    out = capsys.readouterr().out
    assert "Documentos: 3" in out
    assert "Total baixados: 2" in out


def test_main_fecha_browser_mesmo_com_erro(tmp_path: Path, monkeypatch):
    cfg = SimpleNamespace(cache_file=tmp_path / "cache.json", download_dir=tmp_path / "downloads")
    browser = FakeBrowser(cfg)
    monkeypatch.setattr(main_module.Config, "load", classmethod(lambda cls: cfg))
    monkeypatch.setattr(main_module, "D4SignBrowser", lambda config: browser)
    monkeypatch.setattr(main_module, "Cache", FakeCache)
    monkeypatch.setattr(main_module, "Downloader", lambda config, browser: object())
    monkeypatch.setattr(main_module, "Processor", lambda *args: SimpleNamespace(process_specific_link=lambda: (_ for _ in ()).throw(RuntimeError("falha"))))

    with pytest.raises(RuntimeError, match="falha"):
        main_module.main(["--cli"])
    assert browser.calls[-1] == "close"


def test_main_abre_interface_por_padrao(monkeypatch):
    from d4sign import desktop

    calls = []
    monkeypatch.setattr(desktop, "main", lambda: calls.append("desktop"))
    monkeypatch.setattr(main_module, "run_cli", lambda: pytest.fail("Terminal iniciado sem --cli"))

    main_module.main([])

    assert calls == ["desktop"]
