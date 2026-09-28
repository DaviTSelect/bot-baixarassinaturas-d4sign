"""One worker owns the browser from login until logout."""
import contextlib
import logging
import traceback
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from queue import Queue
from threading import Thread

from .browser import D4SignBrowser
from .cache import Cache
from .catalog import location_paths, selected_locations
from .discovery import CatalogDiscovery
from .downloader import Downloader
from .models import Statistics
from .processor import Processor


class QueueWriter:
    def __init__(self, events):
        self.events = events

    def write(self, text):
        if text:
            self.events.put(('log', text))
        return len(text)

    def flush(self):
        pass


class Session:
    def __init__(self, config, events):
        self.config, self.events = config, events
        self.commands = Queue()
        self.thread = Thread(target=self.run, daemon=False)
        self.browser = None
        self._browser_close_requested = False
        self.cancel_requested = False

    def start(self):
        self.thread.start()

    def close(self):
        self.commands.put(('close', None))
        browser = self.browser
        if browser is not None:
            # Closing the window must also release Chrome if a download is
            # currently blocked in Selenium.
            self._browser_close_requested = True
            browser.close()

    def cancel_download(self):
        """Abort the active Selenium operation and end this authenticated session."""
        self.cancel_requested = True
        self.close()

    def run(self):
        browser = D4SignBrowser(self.config)
        self.browser = browser
        try:
            with contextlib.redirect_stdout(QueueWriter(self.events)):
                try:
                    browser.start()
                    browser.login()
                    self.config = replace(self.config, password='')
                    browser.config = self.config
                    discovery = CatalogDiscovery(browser, lambda msg: self.events.put(('status', msg)))
                    roots = discovery.load()
                    self.events.put(('catalog', deepcopy(roots)))
                    while True:
                        command, data = self.commands.get()
                        if command == 'close':
                            break
                        try:
                            if command == 'refresh':
                                roots = discovery.load()
                                self.events.put(('catalog', deepcopy(roots)))
                            elif command == 'refresh_level':
                                current, selected = data
                                refreshed = self.refresh_catalog(browser, discovery, current, selected)
                                discovery, roots = refreshed, refreshed.roots
                                self.events.put(('catalog', deepcopy(roots)))
                            elif command == 'expand':
                                node = discovery.expand(data)
                                self.events.put(('branch', deepcopy(node)))
                            elif command == 'download':
                                selected, recursive, destination = data
                                if not selected or any(key not in discovery.nodes for key in selected):
                                    raise ValueError('A seleção contém uma localização indisponível.')
                                discovery.materialize(selected, recursive)
                                total = self.download(browser, roots, selected, recursive, destination)
                                if self.cancel_requested:
                                    self.events.put(('cancelled', 'Download cancelado. O Chrome foi encerrado e a sessão foi finalizada.'))
                                else:
                                    self.events.put(('catalog', deepcopy(roots)))
                                    kind = 'done_warning' if total.errors else 'done'
                                    message = ('Download concluído com pendências.' if total.errors else
                                               'Download concluído com sucesso.')
                                    self.events.put((kind, f'{message} {total.downloaded} arquivos baixados, '
                                                      f'{total.cached} já disponíveis, {total.errors} falhas.'))
                        except Exception as exc:
                            # A failed refresh invalidates the catalog; require a fresh login.
                            if command == 'refresh':
                                raise
                            if command == 'download' and self.cancel_requested:
                                self.events.put(('cancelled', 'Download cancelado. O Chrome foi encerrado e a sessão foi finalizada.'))
                            else:
                                self.report_error(exc)
                                message = ('Não foi possível preparar o download.' if command == 'download'
                                           else 'Não foi possível carregar esta pasta.')
                                self.events.put(('error', message + ' Tente novamente.'))
                finally:
                    if not self._browser_close_requested:
                        browser.close()
        except Exception as exc:
            self.report_error(exc)
            self.events.put(('session_error', 'Não foi possível carregar sua conta. Confira suas credenciais e conexão e entre novamente.'))
        finally:
            self.browser = None
            self.config = replace(self.config, password='')
            self.events.put(('closed', None))

    def report_error(self, exc):
        logging.getLogger(__name__).exception('Falha na sessão D4Sign')
        self.events.put(('log', ''.join(traceback.format_exception(exc))))

    def refresh_catalog(self, browser, discovery, current, selected):
        """Rebuild only paths needed by the current location and the selection.

        Keep the previous catalog if any request fails. Refreshing starts at the
        sidebar because the site has no independent, reliable branch reload API.
        """
        refreshed = CatalogDiscovery(browser, lambda msg: self.events.put(('status', msg)))
        refreshed.load()
        for key in dict.fromkeys([current, *selected]):
            if key is None:
                continue
            chain, parent = [key], discovery.parents.get(key)
            while parent:
                chain.insert(0, parent)
                parent = discovery.parents.get(parent)
            for ancestor in chain:
                if ancestor not in refreshed.nodes:
                    break  # Removed or no longer accessible in this account.
                if ancestor != key or key == current:
                    refreshed.expand(ancestor)
        return refreshed

    def download(self, browser, roots, selected, recursive, destination):
        paths = location_paths(roots)
        if not selected or any(key not in paths for key in selected):
            raise ValueError('Seleção inválida ou indisponível.')
        nodes = selected_locations(roots, selected, recursive)
        if not nodes:
            raise ValueError('Selecione pelo menos um cofre ou pasta.')
        destination = Path(destination).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        cache = Cache(destination / '.d4sign-cache.json')
        cache.load()
        total = Statistics()
        for index, node in enumerate(nodes, 1):
            self.events.put(('status', f'Baixando {index}/{len(nodes)}: {paths[node.key]}'))
            config = replace(self.config, vault_id=node.vault_id, vault_uuid=node.uuid,
                             download_dir=destination, cache_file=destination / '.d4sign-cache.json',
                             location_url=node.url)
            browser.config = config
            browser.current_driver.execute_cdp_cmd('Page.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': str(destination)})
            processor = Processor(config, browser, Downloader(config, browser), cache)
            stats = processor.process_location(node.uuid, node.name, destination / paths[node.key])
            total.add(stats)
            if processor.last_audit and not processor.last_audit['complete']:
                total.errors += len(processor.last_audit['missing']) + len(processor.last_audit['duplicate_uuids'])
        return total
