import os
import logging
from pathlib import Path
from queue import Queue, Empty
import subprocess
import sys
from threading import Thread
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

from .config import Config
from .cache import Cache
from .explorer import ExplorerState
from .explorer_view import FolderExplorer, configure_theme, COLORS
from .catalog import location_paths, selected_locations
from .session import Session
from .updates import check_update, download_update
from .version import VERSION


def desktop_config(email, password, directory):
    if not email.strip() or not password:
        raise ValueError("Informe seu e-mail e sua senha.")
    destination = Path(directory).expanduser().resolve()
    return Config(
        base_url="https://secure.d4sign.com.br", vault_id="", vault_uuid="",
        email=email.strip(), password=password, download_dir=destination,
        cache_file=destination / ".d4sign-cache.json", log_file=destination / "d4sign.log",
        headless=True, page_timeout=40, download_timeout=120,
        download_retries=3, retry_delay=2, folder_name_filter=None, include_all_statuses=True,
    )

def resource_path(relative_path: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative_path

    return Path(__file__).resolve().parent.parent / relative_path


class Desktop:
    def __init__(self, root):
        self.root, self.events = root, Queue()
        self.busy = self.checking = self.closing = False
        self.auto_updating = False
        self.session = self.update = self.pending_installer = None
        self.roots = []
        self.explorer_state = ExplorerState()
        self.operation = None
        self.retry_action = None
        
        root.title(f"D4Sign • Baixar Assinaturas • {VERSION}")
        configure_theme(root)
        root.geometry("960x850")
        icon_path = resource_path("icon/logo.ico")

        if icon_path.exists():
            self.root.iconbitmap(str(icon_path))
        root.minsize(440, 640)
        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Arquivos D4Sign", font=("Segoe UI", 18, "bold")).pack(anchor="w", pady=(0, 15))
        self.pages = ttk.Frame(frame)
        self.pages.pack(fill="both", expand=True)
        self.login_frame = ttk.LabelFrame(self.pages, text="1. Entre na sua conta", padding=12)
        self.login_frame.pack(fill="x")
        self.login_frame.columnconfigure(1, weight=1)
        self.email = ttk.Entry(self.login_frame)
        self.password = ttk.Entry(self.login_frame, show="*")
        for row, (name, entry) in enumerate([("E-mail", self.email), ("Senha", self.password)]):
            ttk.Label(self.login_frame, text=name).grid(row=row, column=0, padx=(0, 12), pady=5)
            entry.grid(row=row, column=1, sticky="ew", pady=5)
        self.login_button = ttk.Button(self.login_frame, text="Entrar", command=self.login)
        self.login_button.grid(row=2, column=1, sticky="e")
        self.password.bind("<Return>", lambda event: self.login())
        self.selection_frame = ttk.Frame(self.pages)
        ttk.Label(self.selection_frame, text="Abra pelo nome. Marque a caixa para selecionar.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        self.explorer = FolderExplorer(self.selection_frame, self.explorer_state,
                                       self.navigate, self.selection_changed, self.refresh)
        self.explorer.pack(fill="both", expand=True)
        self.recursive = tk.BooleanVar(value=True)
        recursive = ttk.Checkbutton(self.selection_frame, text="Incluir todas as subpastas",
                                     variable=self.recursive, command=self.recursion_changed)
        recursive.pack(anchor="w", pady=4)
        ttk.Label(self.selection_frame, text="Salvar documentos em", style="Muted.TLabel").pack(anchor="w")
        destination = ttk.Frame(self.selection_frame)
        destination.pack(fill="x", pady=(4, 8))
        self.destination = ttk.Entry(destination)
        self.destination.insert(0, str(Path.home() / "Downloads" / "D4Sign"))
        Cache(Path(self.destination.get()) / ".d4sign-cache.json")
        self.destination.pack(side="left", fill="x", expand=True)
        browse = ttk.Button(destination, text="Escolher destino…", command=self.browse)
        browse.pack(side="right", padx=(8, 0))
        self.selection_bar = ttk.Frame(self.selection_frame, padding=(0, 8))
        self.selection_text = tk.StringVar()
        ttk.Label(self.selection_bar, textvariable=self.selection_text,
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))
        actions = ttk.Frame(self.selection_bar)
        actions.pack(fill="x")
        review = ttk.Button(actions, text="Revisar", command=self.review_selection)
        review.pack(side="left")
        clear = ttk.Button(actions, text="Limpar seleção", command=self.clear_selection)
        clear.pack(side="left", padx=4)
        self.download_button = ttk.Button(actions, text="Baixar pasta", command=self.start,
                                          style="Primary.TButton")
        self.download_button.pack(side="right")
        footer = ttk.Frame(self.selection_frame)
        footer.pack(side="bottom", fill="x", pady=(4, 0))
        logout = ttk.Button(footer, text="Sair da conta", command=self.logout)
        logout.pack(side="left")
        self.cancel_button = ttk.Button(footer, text="Cancelar download", command=self.cancel_download, state="disabled")
        self.cancel_button.pack(side="right")
        self.controls = [self.destination, browse, recursive, review, clear, self.download_button, logout]
        self.status = tk.StringVar(value="Informe suas credenciais. O navegador ficará oculto e a senha não será salva.")
        self.status_label = ttk.Label(frame, textvariable=self.status, wraplength=780)
        self.status_label.pack(fill="x", pady=(8, 4))
        frame.bind('<Configure>', lambda event: self.status_label.configure(wraplength=max(280, event.width - 40)))
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.retry_button = ttk.Button(frame, text="Tentar novamente", command=self.retry)
        self.log = ScrolledText(frame, state="disabled", height=5, font=("Consolas", 9))
        self.log.configure(bg=COLORS['surface'], fg=COLORS['text'])
        self.details_button = ttk.Button(frame, text="Mostrar detalhes técnicos", command=self.toggle_details)
        self.details_button.pack(anchor="w", pady=(6, 0))
        updates = ttk.Frame(frame)
        updates.pack(fill="x", pady=(10, 0))
        self.check_button = ttk.Button(updates, text="Verificar atualização", command=self.check)
        self.check_button.pack(side="left")
        self.install_button = ttk.Button(updates, text="Baixar e instalar", command=self.install, state="disabled")
        self.install_button.pack(side="left", padx=8)
        self.update_status = tk.StringVar()
        ttk.Label(frame, textvariable=self.update_status, wraplength=780).pack(fill="x")
        root.protocol("WM_DELETE_WINDOW", self.close)
        # Fixed actions remain reachable while the explorer uses remaining space.
        for child in frame.winfo_children():
            child.pack_forget()
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        for row, child in enumerate(frame.winfo_children()):
            child.grid(row=row, column=0, sticky='nsew' if child is self.pages else 'ew', pady=3)
        self.progress.grid_remove()
        self.retry_button.grid_remove()
        self.log.grid_remove()
        for child in self.selection_frame.winfo_children():
            child.pack_forget()
        self.selection_frame.columnconfigure(0, weight=1)
        self.selection_frame.rowconfigure(1, weight=1)
        for row, child in enumerate(self.selection_frame.winfo_children()):
            child.grid(row=row, column=0, sticky='nsew' if child is self.explorer else 'ew', pady=3)
        self.selection_bar.grid_remove()
        root.after(100, self.poll)
        root.after(500, self.check)

    def set_busy(self, value):
        self.busy = value
        self.explorer.set_busy(value)
        if value:
            self.progress.grid()
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.grid_remove()
        self.selection_changed()
        for control in self.controls + [self.email, self.password, self.login_button]:
            control.configure(state="disabled" if value else "normal")
        if hasattr(self, 'cancel_button'):
            self.cancel_button.configure(state="normal" if value and self.operation == "download" else "disabled")
        self.install_button.configure(state="normal" if self.update and not value and sys.platform == "win32" else "disabled")

    def login(self):
        if self.checking:
            self.status.set("Aguarde a verificação automática de atualizações terminar.")
            return
        if self.busy or self.session:
            return
        try:
            config = desktop_config(self.email.get(), self.password.get(), str(Path.cwd() / "temporary-downloads"))
        except ValueError as exc:
            self.status.set(str(exc))
            return
        self.password.delete(0, "end")
        self.set_busy(True)
        self.status.set("Entrando e carregando seus cofres e pastas…")
        self.session = Session(config, self.events)
        self.session.start()

    def show_catalog(self, roots):
        previous_selection = set(self.explorer_state.selected)
        self.roots = roots
        self.explorer_state.catalog(roots)
        self.login_frame.pack_forget()
        self.selection_frame.pack(fill="both", expand=True)
        self.set_busy(False)
        self.explorer.render()
        self.selection_changed()
        self.status.set("Abra uma pasta pelo nome ou marque as caixas para baixar.")
        if previous_selection - self.explorer_state.selected:
            self.status.set("A lista mudou. Pastas indisponíveis foram removidas da seleção; revise antes de baixar.")
        self.status_label.configure(style="TLabel")

    def navigate(self, key):
        if self.busy:
            return
        self.retry_button.grid_remove()
        self.retry_action = None
        self.operation = None
        self.explorer_state.navigate(key)
        self.explorer.canvas.yview_moveto(0)
        self.explorer.render()
        node = self.explorer_state.nodes.get(key)
        if node and not node.loaded and self.session:
            self.operation = "expand"
            self.retry_action = lambda: self.navigate(key)
            self.retry_button.grid_remove()
            self.set_busy(True)
            self.status.set(f"Carregando subpastas de {node.name}…")
            self.session.commands.put(("expand", key))
        else:
            self.status.set("Marque a caixa para selecionar; clique no nome para abrir.")
        self.status_label.configure(style="TLabel")

    def show_branch(self, node):
        current = self.explorer_state.nodes[node.key]
        current.children, current.loaded = node.children, node.loaded
        self.explorer_state.catalog(self.roots)
        self.set_busy(False)
        self.explorer.render()
        self.status.set("Conteúdo carregado.")
        self.operation = None

    def selection_changed(self):
        count = len(self.explorer_state.selected)
        self.selection_text.set("1 pasta selecionada" if count == 1 else f"{count} pastas selecionadas")
        self.download_button.configure(text="Baixar pasta" if count == 1 else f"Baixar {count} pastas")
        if count:
            self.selection_bar.grid()
        else:
            self.selection_bar.grid_remove()

    def recursion_changed(self):
        self.explorer_state.recursive = self.recursive.get()
        self.explorer_state.normalize()
        self.explorer.render_rows()
        self.selection_changed()

    def clear_selection(self):
        if not self.busy:
            self.explorer_state.selected.clear()
            self.explorer.render_rows()
            self.selection_changed()

    def review_selection(self):
        if not self.busy:
            self.explorer_state.reviewing = True
            self.explorer_state.search, self.explorer_state.page = '', 0
            self.explorer.render()
            self.status.set("Revise as pastas selecionadas. Use Início para continuar navegando.")

    def retry(self):
        if not self.busy and self.retry_action:
            self.retry_action()

    def toggle_details(self):
        if self.log.winfo_manager():
            self.log.grid_remove()
            self.details_button.configure(text="Mostrar detalhes técnicos")
        else:
            self.log.grid()
            self.details_button.configure(text="Ocultar detalhes técnicos")

    def browse(self):
        path = filedialog.askdirectory(parent=self.root)
        if path:
            self.destination.delete(0, "end")
            self.destination.insert(0, path)

    def start(self, everything=False):
        if self.busy or not self.session:
            return
        selected = [root.key for root in self.roots] if everything else sorted(self.explorer_state.selected)
        if not selected or not self.destination.get().strip():
            self.status.set("Selecione um cofre ou pasta e escolha o destino.")
            return
        self.operation = "download"
        self.retry_action = self.start
        self.retry_button.grid_remove()
        self.status_label.configure(style="TLabel")
        self.set_busy(True)
        self.status.set("Preparando download… Lendo documentos e subpastas.")
        self.session.commands.put(("download", (selected, everything or self.recursive.get(), self.destination.get())))

    def download_summary(self, selected, recursive, destination):
        paths = location_paths(self.roots)
        nodes = selected_locations(self.roots, selected, recursive)
        destination_path = Path(destination).expanduser().resolve()
        lines = [
            "Tudo pronto para baixar!",
            "",
            "Pastas selecionadas:",
        ]
        for node in nodes[:30]:
            local_path = destination_path / paths[node.key]
            lines.append(f"  📁 {paths[node.key]}")
            lines.append(f"     Será salvo em: {local_path}")
        if len(nodes) > 30:
            lines.append(f"… e mais {len(nodes) - 30} locais")
        lines.extend([
            "",
            f"Total: {len(nodes)} pasta(s)",
            f"Destino principal: {destination_path}",
            "As subpastas também serão baixadas." if recursive else "Somente os arquivos diretamente nessas pastas serão baixados.",
            "",
            "Deseja começar o download?",
        ])
        return "\n".join(lines)

    def refresh(self):
        if not self.busy and self.session:
            self.operation = "refresh"
            self.retry_action = self.refresh
            self.retry_button.grid_remove()
            self.set_busy(True)
            self.status.set("Atualizando este nível…")
            self.session.commands.put(("refresh_level", (self.explorer_state.current,
                                                         sorted(self.explorer_state.selected))))

    def cancel_download(self):
        if not self.session or not self.busy:
            return
        if not messagebox.askyesno("Cancelar download", "Deseja cancelar agora? O Chrome será encerrado e será necessário entrar novamente.", parent=self.root):
            return
        self.status.set("Cancelando download e encerrando o Chrome…")
        self.cancel_button.configure(state="disabled")
        self.session.cancel_download()

    def logout(self):
        if not self.busy and self.session:
            self.operation = 'logout'
            self.set_busy(True)
            self.status.set("Encerrando sessão…")
            self.session.close()

    def check(self):
        if self.checking:
            return
        self.checking = True
        self.check_button.configure(state="disabled")
        self.update_status.set("Consultando atualizações…")
        def worker():
            try:
                self.events.put(("update", check_update()))
            except Exception as exc:
                self.events.put(("update_error", f"Não foi possível consultar atualizações: {exc}"))
        Thread(target=worker, daemon=True).start()

    def install(self):
        if self.busy or not self.update:
            return
        if not messagebox.askyesno("Atualização", f"Baixar a versão {self.update.version} e abrir o instalador? O aplicativo será fechado.", parent=self.root):
            return
        self.begin_update(self.update)

    def begin_update(self, update, automatic=False):
        if self.auto_updating:
            return
        self.auto_updating = automatic or self.auto_updating
        self.set_busy(True)
        self.status.set("Baixando atualização segura…")
        def worker():
            try:
                path = download_update(update, lambda progress: self.events.put(("progress", progress)))
                self.events.put(("installer", path))
            except Exception as exc:
                self.events.put(("update_failed", f"Não foi possível atualizar automaticamente: {exc}"))
        Thread(target=worker, daemon=False).start()

    def poll(self):
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except Empty:
                break
            if kind == "log":
                self.log.configure(state="normal")
                self.log.insert("end", value)
                if int(self.log.index("end-1c").split(".")[0]) > 2500:
                    self.log.delete("1.0", "501.0")
                self.log.see("end")
                self.log.configure(state="disabled")
            elif kind == "status":
                self.status.set(value)
            elif kind == "catalog":
                self.show_catalog(value)
            elif kind == 'branch':
                self.show_branch(value)
            elif kind == "closed":
                self.session = None
                self.operation = self.retry_action = None
                self.retry_button.grid_remove()
                self.roots = []
                self.explorer_state.catalog([])
                self.explorer_state.navigate(None)
                self.selection_frame.pack_forget()
                self.login_frame.pack(fill="x")
                if self.pending_installer:
                    path, self.pending_installer = self.pending_installer, None
                    if self.launch_installer(path):
                        return
                elif self.closing:
                    self.root.destroy()
                    return
                self.set_busy(False)
            elif kind == "session_error":
                self.status.set(value)
                self.status_label.configure(style="Error.TLabel")
            elif kind in ("done", "done_warning", "error", "cancelled"):
                self.set_busy(kind == "cancelled")
                self.status.set(value)
                if kind == "error":
                    self.status_label.configure(style="Error.TLabel")
                    self.retry_button.grid()
                elif kind == "done":
                    self.status_label.configure(style="Success.TLabel")
                    self.operation = None
                elif kind == "done_warning":
                    self.status_label.configure(style="Error.TLabel")
                    self.retry_button.grid()
                    self.operation = None
                elif kind == "cancelled":
                    self.cancel_button.configure(state="disabled")
                    self.status.set(value)
            elif kind in ("update", "update_error"):
                self.checking = False
                self.check_button.configure(state="normal")
                if kind == "update":
                    self.update = value
                    if value and sys.platform == "win32" and not self.session and not self.busy:
                        self.update_status.set(f"Atualização {value.version} encontrada. Baixando automaticamente…")
                        self.begin_update(value, automatic=True)
                    elif value:
                        self.update_status.set(f"Nova versão disponível: {value.version}")
                        self.set_busy(self.busy)
                    else:
                        self.update_status.set(f"Versão {VERSION} atualizada.")
                else:
                    self.update_status.set(value)
            elif kind == "update_failed":
                self.auto_updating = False
                self.set_busy(False)
                self.update_status.set(value)
            elif kind == "progress":
                self.status.set(f"Baixando atualização: {value}%")
            elif kind == "installer":
                if self.session:
                    self.pending_installer = value
                    self.session.close()
                elif self.launch_installer(value):
                    return
        self.root.after(100, self.poll)

    def launch_installer(self, path):
        try:
            subprocess.Popen([str(path)], close_fds=True)
        except OSError as exc:
            self.set_busy(False)
            messagebox.showerror("Instalador", str(exc), parent=self.root)
            return False
        self.root.destroy()
        return True

    def close(self):
        if self.session:
            self.closing = True
            self.operation = 'close'
            self.set_busy(True)
            self.session.close()
        else:
            self.root.destroy()


def main():
    # Diagnósticos relativos são gravados no perfil, nunca na instalação.
    data_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share"))) / "D4SignDesktop"
    data_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(data_dir)
    logging.basicConfig(filename=data_dir / 'd4sign.log', encoding='utf-8',
                        level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    root = tk.Tk()
    Desktop(root)
    root.mainloop()
