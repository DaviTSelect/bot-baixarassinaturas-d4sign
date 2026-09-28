"""Navigation and download selection, independent of Tk and Selenium."""
from dataclasses import dataclass, field


@dataclass
class ExplorerState:
    roots: list = field(default_factory=list)
    current: str | None = None
    selected: set = field(default_factory=set)
    search: str = ''
    page: int = 0
    recursive: bool = True
    page_size: int = 40
    reviewing: bool = False
    nodes: dict = field(default_factory=dict)
    parents: dict = field(default_factory=dict)

    def catalog(self, roots):
        previous_path = self.ancestors(self.current)
        self.roots = roots
        self.nodes, self.parents = {}, {}
        pending = [(node, None) for node in roots]
        while pending:
            node, parent = pending.pop()
            self.nodes[node.key] = node
            self.parents[node.key] = parent
            pending.extend((child, node.key) for child in node.children)
        self.selected.intersection_update(self.nodes)
        if self.current not in self.nodes:
            self.current = next((key for key in reversed(previous_path) if key in self.nodes), None)
        self.normalize()

    def ancestors(self, key):
        result = []
        parent = self.parents.get(key)
        while parent:
            result.append(parent)
            parent = self.parents.get(parent)
        return list(reversed(result))

    def included_by(self, key):
        if self.recursive:
            return next((p for p in self.ancestors(key) if p in self.selected), None)
        return None

    def normalize(self):
        self.selected.difference_update({key for key in self.selected if self.included_by(key)})

    def toggle(self, key):
        if key not in self.nodes or self.included_by(key):
            return
        if key in self.selected:
            self.selected.remove(key)
        else:
            self.selected.add(key)
        self.normalize()

    def navigate(self, key):
        if key is not None and key not in self.nodes:
            raise ValueError('Localização indisponível.')
        self.current, self.search, self.page, self.reviewing = key, '', 0, False

    def results(self):
        if self.reviewing:
            items = [self.nodes[key] for key in self.selected]
        else:
            items = self.nodes[self.current].children if self.current else self.roots
        term = self.search.strip().casefold()
        return sorted((node for node in items if term in node.name.casefold()),
                      key=lambda node: (node.name.casefold(), node.key))

    def visible(self):
        items = self.results()
        self.page = min(self.page, max(0, (len(items) - 1) // self.page_size))
        return items[self.page * self.page_size:(self.page + 1) * self.page_size]

    def select_visible(self):
        keys = {node.key for node in self.visible() if not self.included_by(node.key)}
        if keys and keys <= self.selected:
            self.selected.difference_update(keys)
        else:
            self.selected.update(keys)
        self.normalize()

    def path(self, key):
        return ' / '.join(self.nodes[p].name for p in self.ancestors(key) + [key])
