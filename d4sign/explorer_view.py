"""Native desktop folder explorer with separate selection and navigation."""
import tkinter as tk
from tkinter import ttk


COLORS = {
    'background': '#f3f5f7', 'surface': '#ffffff', 'text': '#203447',
    'muted': '#526578', 'border': '#ced6df', 'primary': '#b93812',
    'hover': '#e9eef3', 'selected': '#fff0e9', 'success': '#21633b',
    'error': '#a32424',
}


def configure_theme(root):
    style = ttk.Style(root)
    try:
        style.theme_use('clam')
    except tk.TclError:
        pass
    root.configure(background=COLORS['background'])
    style.configure('.', font=('Segoe UI', 10), background=COLORS['background'],
                    foreground=COLORS['text'])
    style.configure('TButton', padding=(8, 5), width=0, background=COLORS['surface'])
    style.map('TButton', background=[('active', COLORS['hover'])],
              bordercolor=[('focus', COLORS['primary'])])
    style.configure('Primary.TButton', background=COLORS['primary'], foreground='white')
    style.map('Primary.TButton', background=[('disabled', COLORS['muted']),
                                            ('active', '#962d0e')])
    style.configure('Muted.TLabel', foreground=COLORS['muted'])
    style.configure('Error.TLabel', foreground=COLORS['error'])
    style.configure('Success.TLabel', foreground=COLORS['success'])
    for prefix, color in [('Row', COLORS['surface']), ('Selected', COLORS['selected'])]:
        style.configure(prefix + '.TFrame', background=color)
        style.configure(prefix + '.TLabel', background=color, foreground=COLORS['muted'])
        style.configure(prefix + '.TCheckbutton', background=color, padding=8)
        style.map(prefix + '.TCheckbutton', background=[('active', COLORS['hover'])])
        style.configure(prefix + '.TButton', background=color, anchor='w', relief='flat')


class FolderExplorer(ttk.Frame):
    def __init__(self, parent, state, on_open, on_change, on_refresh):
        super().__init__(parent)
        self.state, self.on_open, self.on_change = state, on_open, on_change
        self.busy = False
        self.row_checks = {}
        self.folder_icon = tk.PhotoImage(master=self, width=20, height=18)
        for rectangle in [(2, 3, 8, 4), (2, 3, 3, 15), (8, 4, 10, 5),
                          (10, 5, 18, 6), (17, 5, 18, 15), (2, 14, 18, 15), (3, 6, 17, 7)]:
            self.folder_icon.put(COLORS['muted'], to=rectangle)
        self.crumbs = ttk.Frame(self)
        tools = ttk.Frame(self)
        ttk.Label(tools, text='Buscar pasta neste nível', style='Muted.TLabel').pack(anchor='w')
        search_row = ttk.Frame(tools)
        search_row.pack(fill='x', pady=4)
        self.search = tk.StringVar()
        self.entry = ttk.Entry(search_row, textvariable=self.search)
        self.entry.pack(side='left', fill='x', expand=True)
        self.clear_search = ttk.Button(search_row, text='Limpar busca', command=lambda: self.search.set(''))
        self.clear_search.pack(side='left', padx=4)
        self.refresh_button = ttk.Button(search_row, text='Atualizar', command=on_refresh)
        self.refresh_button.pack(side='left')
        self.search.trace_add('write', self.filter)
        self.all_var = tk.BooleanVar()
        self.all_check = ttk.Checkbutton(self, text='Selecionar pastas desta página',
                                         variable=self.all_var, command=self.select_visible)
        container = ttk.Frame(self)
        self.canvas = tk.Canvas(container, background=COLORS['surface'], highlightthickness=1,
                                highlightbackground=COLORS['border'], height=220, takefocus=False)
        scrollbar = ttk.Scrollbar(container, command=self.canvas.yview)
        scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.rows = ttk.Frame(self.canvas, style='Row.TFrame')
        self.window = self.canvas.create_window(0, 0, window=self.rows, anchor='nw')
        self.canvas.bind('<Configure>', self.resize)
        self.rows.bind('<Configure>', lambda event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<MouseWheel>', self.wheel)
        self.rows.bind('<MouseWheel>', self.wheel)
        self.pagination = ttk.Frame(self)
        self.previous = ttk.Button(self.pagination, text='Anterior', command=lambda: self.turn_page(-1))
        self.previous.pack(side='left')
        self.count = ttk.Label(self.pagination, style='Muted.TLabel')
        self.count.pack(side='left', padx=8)
        self.next = ttk.Button(self.pagination, text='Próxima', command=lambda: self.turn_page(1))
        self.next.pack(side='right')
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        for row, child in enumerate([self.crumbs, tools, self.all_check, container, self.pagination]):
            child.grid(row=row, column=0, sticky='nsew' if child is container else 'ew', pady=3)
        self.bind('<Configure>', self.layout_crumbs)

    def wheel(self, event):
        self.canvas.yview_scroll(-int(event.delta / 120), 'units')
        return 'break'

    def resize(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)
        for row in self.rows.winfo_children():
            for child in row.winfo_children():
                if isinstance(child, ttk.Label):
                    child.configure(wraplength=max(160, event.width - 100))

    def layout_crumbs(self, event=None):
        width = max(300, self.winfo_width())
        x = row = column = 0
        for widget in self.crumbs.winfo_children():
            needed = widget.winfo_reqwidth() + 4
            if x and x + needed > width:
                row, column, x = row + 1, 0, 0
            widget.grid(row=row, column=column, sticky='w', padx=(0, 4), pady=2)
            x, column = x + needed, column + 1

    def filter(self, *args):
        self.state.search, self.state.page = self.search.get(), 0
        self.render_rows()

    def navigate(self, key):
        if not self.busy:
            self.on_open(key)

    def render(self):
        for child in self.crumbs.winfo_children():
            child.destroy()
        chain = [None]
        if self.state.current:
            chain += self.state.ancestors(self.state.current) + [self.state.current]
        for key in chain:
            name = 'Início' if key is None else self.state.nodes[key].name
            if key is not None:
                name = '› ' + name
            button = ttk.Button(self.crumbs, text=name if len(name) <= 34 else name[:31] + '…',
                                command=lambda k=key: self.navigate(k))
            button.configure(state='disabled' if self.busy else 'normal')
        if self.state.reviewing:
            ttk.Label(self.crumbs, text='› Seleção para download').grid()
        self.layout_crumbs()
        if self.search.get() != self.state.search:
            self.search.set(self.state.search)
        self.render_rows()

    def render_rows(self, focus_key=None):
        y = self.canvas.yview()[0]
        for child in self.rows.winfo_children():
            child.destroy()
        self.row_checks = {}
        items = self.state.visible()
        for node in items:
            inherited = self.state.included_by(node.key)
            selected = node.key in self.state.selected or bool(inherited)
            prefix = 'Selected' if selected else 'Row'
            row = ttk.Frame(self.rows, style=prefix + '.TFrame', padding=(4, 4))
            row.pack(fill='x', pady=(0, 1))
            row.columnconfigure(1, weight=1)
            var = tk.BooleanVar(value=selected)
            check = ttk.Checkbutton(row, variable=var, style=prefix + '.TCheckbutton',
                                    command=lambda k=node.key: self.toggle(k))
            check.variable = var
            check.grid(row=0, column=0, rowspan=2, sticky='ns')
            check.configure(state='disabled' if self.busy or inherited else 'normal')
            self.row_checks[node.key] = check
            # A wrapping native button keeps long folder names readable on narrow windows.
            button = tk.Button(row, text='  ' + node.name, image=self.folder_icon, compound='left', anchor='w', relief='flat',
                               background=COLORS['selected'] if selected else COLORS['surface'],
                               foreground=COLORS['text'], activebackground=COLORS['hover'],
                               font=('Segoe UI', 11), cursor='hand2', padx=8, pady=6,
                               highlightthickness=1, highlightcolor=COLORS['primary'],
                               highlightbackground=COLORS['selected'] if selected else COLORS['surface'],
                               command=lambda k=node.key: self.navigate(k))
            button.grid(row=0, column=1, sticky='ew')
            button.bind('<Configure>', lambda event: event.widget.configure(wraplength=max(120, event.width - 24)))
            button.bind('<Return>', lambda event, k=node.key: self.navigate(k))
            button.configure(state='disabled' if self.busy else 'normal')
            detail = 'Cofre' if self.state.parents[node.key] is None else 'Pasta'
            if node.loaded:
                count = len(node.children)
                detail += f' • {count} ' + ('subpasta' if count == 1 else 'subpastas')
            else:
                detail += ' • Abrir para ver subpastas'
            if inherited:
                detail = 'Incluída pela seleção de ' + self.state.nodes[inherited].name
            elif self.state.reviewing:
                detail = self.state.path(node.key)
            ttk.Label(row, text=detail, style=prefix + '.TLabel',
                      wraplength=max(160, self.canvas.winfo_width() - 100)).grid(row=1, column=1, sticky='w', padx=8)
            open_button = ttk.Button(row, text='›', width=3, command=lambda k=node.key: self.navigate(k))
            open_button.grid(row=0, column=2, rowspan=2, padx=4)
            open_button.configure(state='disabled' if self.busy else 'normal')
            for widget in [row, *row.winfo_children()]:
                widget.bind('<MouseWheel>', self.wheel)
            check.bind('<FocusIn>', lambda event, r=row: self.reveal(r))
            button.bind('<FocusIn>', lambda event, r=row: self.reveal(r))
        if not items:
            if self.busy:
                message = 'Carregando conteúdo…'
            elif self.state.search.strip():
                message = f'Nenhuma pasta encontrada para “{self.state.search.strip()}”.'
            elif self.state.reviewing:
                message = 'Nenhuma pasta selecionada.'
            elif self.state.current and not self.state.nodes[self.state.current].loaded:
                message = 'Conteúdo indisponível. Use Tentar novamente para carregar as subpastas.'
            elif self.state.current:
                message = 'Nenhuma subpasta neste nível.\nOs documentos desta pasta serão incluídos ao selecioná-la no nível anterior.'
            else:
                message = 'Nenhum cofre disponível. Use Atualizar para tentar novamente.'
            ttk.Label(self.rows, text=message, padding=20, style='Row.TLabel',
                      wraplength=max(240, self.canvas.winfo_width() - 40)).pack(fill='x')
        keys = {n.key for n in items if not self.state.included_by(n.key)}
        self.all_var.set(bool(keys) and keys <= self.state.selected)
        self.all_check.state(['!alternate'])
        if keys & self.state.selected and not keys <= self.state.selected:
            self.all_check.state(['alternate'])
        self.all_check.configure(state='disabled' if self.busy or not keys else 'normal')
        total = len(self.state.results())
        pages = max(1, (total + self.state.page_size - 1) // self.state.page_size)
        if pages > 1:
            self.pagination.grid()
        else:
            self.pagination.grid_remove()
        if self.state.search:
            self.clear_search.pack(side='left', padx=4, before=self.refresh_button)
        else:
            self.clear_search.pack_forget()
        self.count.configure(text=f'{total} locais • Página {self.state.page + 1} de {pages}')
        self.previous.configure(state='normal' if self.state.page and not self.busy else 'disabled')
        self.next.configure(state='normal' if self.state.page + 1 < pages and not self.busy else 'disabled')
        for control in (self.entry, self.clear_search, self.refresh_button):
            control.configure(state='disabled' if self.busy else 'normal')
        self.rows.update_idletasks()
        self.canvas.yview_moveto(y)
        if focus_key in self.row_checks:
            self.row_checks[focus_key].focus_set()

    def reveal(self, row):
        self.rows.update_idletasks()
        height = max(1, self.rows.winfo_height())
        top = self.canvas.canvasy(0)
        if row.winfo_y() < top or row.winfo_y() + row.winfo_height() > top + self.canvas.winfo_height():
            self.canvas.yview_moveto(row.winfo_y() / height)

    def toggle(self, key):
        if not self.busy:
            self.state.toggle(key)
            self.render_rows(key)
            self.on_change()

    def select_visible(self):
        if not self.busy:
            self.state.select_visible()
            self.render_rows()
            self.on_change()

    def turn_page(self, delta):
        if not self.busy:
            self.state.page += delta
            self.canvas.yview_moveto(0)
            self.render_rows()

    def set_busy(self, value):
        self.busy = value
        self.render()
