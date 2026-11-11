"""Interface PySide6 para download de documentos do D4Sign."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .config import Config
from .explorer import ExplorerState
from .session import Session
from .updates import check_update, download_update
from .version import VERSION

# ── Paleta ────────────────────────────────────────────────────────────────────
BG = '#203447'
TEXT = '#efede5'
ACTION = '#e94c1f'
COR_DIVISOR_ESCURO = '#415364'
COR_ICONE = '#7a8791'
COR_SELECIONADO = '#317458'

ESTILO_FUNDO_ICONE = 'background:#e9eef0; border-radius:12px;'
ESTILO_FUNDO_ICONE_OK = 'background:#e5f4ed; border-radius:12px;'
ESTILO_BOTAO_LINHA = '''
    QPushButton {background:#ffffff; border:1px solid #d9dddc; border-radius:9px;
        color:#344a5b; font-family:"Segoe UI"; font-size:11px; font-weight:600; padding:0 12px;}
    QPushButton:hover {background:#f1f3f1; border-color:#b5bec3;}
    QPushButton:disabled {background:#ebebeb; color:#b0b8bc; border-color:#e0e0e0;}'''
ESTILO_INICIAR_ATIVO = f'''
    QPushButton {{background:{ACTION}; color:white; border:none; border-radius:9px;
        font:600 11px "Segoe UI"; padding:0 19px;}}
    QPushButton:hover {{background:#d74118;}}'''
ESTILO_INICIAR_INATIVO = '''
    QPushButton {background:#d8dad9; color:#92999b; border:none; border-radius:9px;
        font:600 11px "Segoe UI"; padding:0 19px;}
    QPushButton:disabled {background:#d8dad9; color:#92999b;}'''
ESTILO_INICIAR_RODANDO = '''
    QPushButton {background:#2a4255; color:#a5b4c0; border:none; border-radius:9px;
        font:600 11px "Segoe UI"; padding:0 19px;}
    QPushButton:disabled {background:#2a4255; color:#a5b4c0;}'''
ESTILO_ITEM_PASTA = '''
    QPushButton {background:#ffffff; border:1px solid #dde1df; border-radius:8px;
        color:#203447; font-family:"Segoe UI"; font-size:11px; font-weight:500;
        padding:8px 12px; text-align:left;}
    QPushButton:hover {background:#f4f6f5; border-color:#b5bec3;}
    QPushButton:disabled {background:#f1f1ed; color:#9ba5ac;}'''
ESTILO_ITEM_PASTA_SELECIONADO = '''
    QPushButton {background:#e5f4ed; border:1px solid #9bcfb8; border-radius:8px;
        color:#1d5e3a; font-family:"Segoe UI"; font-size:11px; font-weight:500;
        padding:8px 12px; text-align:left;}
    QPushButton:hover {background:#d8ede4; border-color:#7ec4a8;}
    QPushButton:disabled {background:#e5f4ed; color:#2a6648;}'''


def _rotulo(text, size, color, weight=QFont.Normal, wrap=False):
    w = QLabel(text)
    f = QFont('Segoe UI', size)
    f.setWeight(weight)
    w.setFont(f)
    w.setStyleSheet(f'color:{color}; background:transparent;')
    w.setWordWrap(wrap)
    return w


def _divisor(color):
    d = QFrame()
    d.setFixedHeight(1)
    d.setStyleSheet(f'background:{color}; border:none;')
    return d


# ── Ícone desenhado ───────────────────────────────────────────────────────────

class Icon(QWidget):
    def __init__(self, kind, color=COR_ICONE, size=24, parent=None):
        super().__init__(parent)
        self.kind, self.color = kind, color
        self.setFixedSize(size, size)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(self.width() / 24, self.height() / 24)
        pen = QPen(QColor(self.color), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if self.kind == 'folder':
            self._pasta(p)
        elif self.kind == 'download':
            self._download(p)
        elif self.kind == 'check':
            pen.setWidthF(2)
            p.setPen(pen)
            self._check(p)
        elif self.kind == 'file':
            self._arquivo(p)
        p.end()

    @staticmethod
    def _ln(p, x1, y1, x2, y2):
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def _pasta(self, p):
        path = QPainterPath()
        path.moveTo(3.75, 16.25); path.lineTo(3.75, 6.75)
        path.cubicTo(3.75, 5.65, 4.65, 4.75, 5.75, 4.75)
        path.lineTo(9.11, 4.75); path.lineTo(11.91, 7.75); path.lineTo(18.25, 7.75)
        path.cubicTo(19.35, 7.75, 20.25, 8.65, 20.25, 9.75); path.lineTo(20.25, 16.25)
        path.cubicTo(20.25, 18, 19, 19.25, 17.25, 19.25); path.lineTo(6.75, 19.25)
        path.cubicTo(5, 19.25, 3.75, 18, 3.75, 16.25)
        p.drawPath(path)

    def _download(self, p):
        self._ln(p, 12, 4, 12, 15)
        self._ln(p, 9, 12, 12, 15)
        self._ln(p, 15, 12, 12, 15)
        self._ln(p, 4, 19, 20, 19)

    def _arquivo(self, p):
        path = QPainterPath()
        path.moveTo(7, 3.75); path.lineTo(13.17, 3.75); path.lineTo(18, 8.58)
        path.lineTo(18, 20.25); path.lineTo(7, 20.25)
        path.cubicTo(5.7, 20.25, 5, 19.4, 5, 18.25)
        path.lineTo(5, 5.75); path.cubicTo(5, 4.6, 5.8, 3.75, 7, 3.75)
        p.drawPath(path)
        self._ln(p, 13.5, 4, 13.5, 8.5); self._ln(p, 13.5, 8.5, 18, 8.5)

    @staticmethod
    def _check(p):
        path = QPainterPath()
        path.moveTo(6.75, 12.25); path.lineTo(10, 15.5); path.lineTo(17.25, 8.25)
        p.drawPath(path)


# ── FolderRow: linha individual da lista de pastas ───────────────────────────

class FolderRow(QFrame):
    toggled = Signal(str)
    opened = Signal(str)

    def __init__(self, node, state, busy, parent=None):
        super().__init__(parent)
        self.key = node.key
        self.setObjectName('folderRow')
        inherited = state.included_by(node.key)
        selected = node.key in state.selected or bool(inherited)
        self.setStyleSheet('#folderRow {background:transparent; border:none;}')

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)

        self.chk = QCheckBox()
        self.chk.setChecked(selected)
        self.chk.setEnabled(not busy and not inherited)
        self.chk.setStyleSheet('''
            QCheckBox::indicator {width:16px; height:16px; border-radius:4px;
                border:2px solid #c0c8cc; background:#fff;}
            QCheckBox::indicator:checked {background:#317458; border-color:#317458;}
            QCheckBox::indicator:disabled {background:#ebebeb; border-color:#d0d8dc;}
        ''')
        self.chk.toggled.connect(lambda _: self.toggled.emit(self.key))
        lay.addWidget(self.chk, 0, Qt.AlignVCenter)

        icon_box = QFrame()
        icon_box.setFixedSize(28, 28)
        icon_box.setStyleSheet(ESTILO_FUNDO_ICONE_OK if selected else ESTILO_FUNDO_ICONE)
        il = QHBoxLayout(icon_box)
        il.setContentsMargins(4, 4, 4, 4)
        il.addWidget(Icon('folder', COR_SELECIONADO if selected else COR_ICONE, 20))
        lay.addWidget(icon_box, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(2)
        col.setContentsMargins(0, 0, 0, 0)
        name_lbl = _rotulo(node.name, 11, '#203447', QFont.Medium)
        name_lbl.setWordWrap(True)
        col.addWidget(name_lbl)
        if inherited:
            detail = f'Incluída pela seleção de {state.nodes[inherited].name}'
            detail_color = '#5aaa7a'
        elif node.loaded:
            count = len(node.children)
            detail = f'Cofre' if state.parents[node.key] is None else 'Pasta'
            detail += f' • {count} subpasta{"s" if count != 1 else ""}'
            detail_color = '#8998a3'
        else:
            detail_color = '#8998a3'
            detail = 'Cofre' if state.parents[node.key] is None else 'Pasta'
            detail += ' • Abrir para ver subpastas'
        col.addWidget(_rotulo(detail, 9, detail_color))
        lay.addLayout(col, 1)

        self.open_btn = QPushButton('›')
        self.open_btn.setFixedSize(32, 32)
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.setEnabled(not busy)
        self.open_btn.setStyleSheet(ESTILO_BOTAO_LINHA)
        self.open_btn.clicked.connect(lambda: self.opened.emit(self.key))
        lay.addWidget(self.open_btn, 0, Qt.AlignVCenter)


# ── FolderExplorerWidget: painel principal do explorador ─────────────────────

class FolderExplorerWidget(QFrame):
    navigated = Signal(object)   # key or None
    toggled = Signal(str)
    refreshed = Signal()

    def __init__(self, state: ExplorerState, parent=None):
        super().__init__(parent)
        self.state = state
        self.busy = False
        self.setStyleSheet('background:transparent; border:none;')
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(16, 8, 16, 8)
        self._lay.setSpacing(8)

        # Breadcrumbs
        self._crumbs_frame = QFrame()
        self._crumbs_frame.setStyleSheet('background:transparent; border:none;')
        self._crumbs_lay = QHBoxLayout(self._crumbs_frame)
        self._crumbs_lay.setContentsMargins(0, 0, 0, 0)
        self._crumbs_lay.setSpacing(4)
        self._lay.addWidget(self._crumbs_frame)

        # Toolbar: select all + refresh
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        self._chk_all = QCheckBox('Selecionar pastas desta página')
        self._chk_all.setStyleSheet('''
            QCheckBox {color:#344a5b; font-family:"Segoe UI"; font-size:10px; spacing:6px;}
            QCheckBox::indicator {width:14px; height:14px; border-radius:3px;
                border:2px solid #c0c8cc; background:#fff;}
            QCheckBox::indicator:checked {background:#317458; border-color:#317458;}
            QCheckBox::indicator:disabled {background:#ebebeb; border-color:#d0d8dc;}
        ''')
        self._chk_all.toggled.connect(self._select_visible)
        toolbar.addWidget(self._chk_all)
        toolbar.addStretch()
        self._btn_refresh = QPushButton('Atualizar')
        self._btn_refresh.setFixedHeight(32)
        self._btn_refresh.setCursor(Qt.PointingHandCursor)
        self._btn_refresh.setStyleSheet(ESTILO_BOTAO_LINHA)
        self._btn_refresh.clicked.connect(self.refreshed.emit)
        toolbar.addWidget(self._btn_refresh)
        self._lay.addLayout(toolbar)

        # Scroll area for folder rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(180)
        scroll.setStyleSheet('''
            QScrollArea {background:#f8f7f3; border:1px solid #dde1df; border-radius:8px;}
            QScrollBar:vertical {background:#ebebe7; width:6px; border-radius:3px; margin:0;}
            QScrollBar::handle:vertical {background:#c5c8c6; border-radius:3px; min-height:24px;}
            QScrollBar::handle:vertical:hover {background:#a8aaa8;}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {height:0;}
        ''')
        self._rows_widget = QWidget()
        self._rows_widget.setStyleSheet('background:transparent;')
        self._rows_lay = QVBoxLayout(self._rows_widget)
        self._rows_lay.setContentsMargins(8, 8, 8, 8)
        self._rows_lay.setSpacing(4)
        scroll.setWidget(self._rows_widget)
        self._lay.addWidget(scroll, 1)

        # Pagination
        self._pag_frame = QFrame()
        self._pag_frame.setStyleSheet('background:transparent; border:none;')
        pag_lay = QHBoxLayout(self._pag_frame)
        pag_lay.setContentsMargins(0, 0, 0, 0)
        self._btn_prev = QPushButton('← Anterior')
        self._btn_prev.setFixedHeight(32)
        self._btn_prev.setCursor(Qt.PointingHandCursor)
        self._btn_prev.setStyleSheet(ESTILO_BOTAO_LINHA)
        self._btn_prev.clicked.connect(lambda: self._turn_page(-1))
        self._pag_count = _rotulo('', 9, '#8998a3')
        self._pag_count.setAlignment(Qt.AlignCenter)
        self._btn_next = QPushButton('Próxima →')
        self._btn_next.setFixedHeight(32)
        self._btn_next.setCursor(Qt.PointingHandCursor)
        self._btn_next.setStyleSheet(ESTILO_BOTAO_LINHA)
        self._btn_next.clicked.connect(lambda: self._turn_page(1))
        pag_lay.addWidget(self._btn_prev)
        pag_lay.addStretch()
        pag_lay.addWidget(self._pag_count)
        pag_lay.addStretch()
        pag_lay.addWidget(self._btn_next)
        self._lay.addWidget(self._pag_frame)

    def render(self):
        # Breadcrumbs
        for i in reversed(range(self._crumbs_lay.count())):
            w = self._crumbs_lay.itemAt(i).widget()
            if w:
                w.deleteLater()
        chain = [None]
        if self.state.current:
            chain += self.state.ancestors(self.state.current) + [self.state.current]
        for key in chain:
            name = 'Início' if key is None else self.state.nodes[key].name
            if key is not None:
                name = '› ' + name
            display = name if len(name) <= 30 else name[:27] + '…'
            btn = QPushButton(display)
            btn.setFixedHeight(28)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(ESTILO_BOTAO_LINHA)
            btn.setEnabled(not self.busy)
            k = key
            btn.clicked.connect(lambda _, k=k: self.navigated.emit(k))
            self._crumbs_lay.addWidget(btn)
        self._crumbs_lay.addStretch()
        self._render_rows()

    def _render_rows(self):
        for i in reversed(range(self._rows_lay.count())):
            item = self._rows_lay.itemAt(i)
            w = item.widget()
            if w:
                w.deleteLater()
            else:
                self._rows_lay.removeItem(item)

        items = self.state.visible()
        if not items:
            if self.busy:
                msg = 'Carregando…'
            elif self.state.current and not self.state.nodes[self.state.current].loaded:
                msg = 'Conteúdo indisponível. Clique em Atualizar para tentar novamente.'
            elif self.state.current:
                msg = 'Nenhuma subpasta neste nível.'
            else:
                msg = 'Nenhum cofre disponível. Clique em Atualizar para tentar novamente.'
            lbl = _rotulo(msg, 10, '#8998a3', wrap=True)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setContentsMargins(12, 24, 12, 24)
            self._rows_lay.addWidget(lbl)
        else:
            for node in items:
                row = FolderRow(node, self.state, self.busy)
                row.toggled.connect(self._on_toggle)
                row.opened.connect(lambda k: self.navigated.emit(k))
                self._rows_lay.addWidget(row)
                sep = _divisor('#edecea')
                self._rows_lay.addWidget(sep)
        self._rows_lay.addStretch()

        keys = {n.key for n in items if not self.state.included_by(n.key)}
        self._chk_all.blockSignals(True)
        self._chk_all.setChecked(bool(keys) and keys <= self.state.selected)
        self._chk_all.blockSignals(False)
        self._chk_all.setEnabled(not self.busy and bool(keys))

        total = len(self.state.results())
        pages = max(1, (total + self.state.page_size - 1) // self.state.page_size)
        self._pag_frame.setVisible(pages > 1)
        self._pag_count.setText(f'{total} locais • Página {self.state.page + 1} de {pages}')
        self._btn_prev.setEnabled(bool(self.state.page) and not self.busy)
        self._btn_next.setEnabled(self.state.page + 1 < pages and not self.busy)
        self._btn_refresh.setEnabled(not self.busy)

    def _on_toggle(self, key):
        if not self.busy:
            self.state.toggle(key)
            self._render_rows()
            self.toggled.emit(key)

    def _select_visible(self):
        if not self.busy:
            self.state.select_visible()
            self._render_rows()

    def _turn_page(self, delta):
        if not self.busy:
            self.state.page += delta
            self._render_rows()

    def set_busy(self, value):
        self.busy = value
        self.render()


# ── Janela principal ──────────────────────────────────────────────────────────

def _resource_path(relative: str) -> Path:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative
    return Path(__file__).resolve().parent.parent / relative


class Desktop(QWidget):
    _sinal_status = Signal(str)
    _sinal_catalog = Signal(list)
    _sinal_branch = Signal(object)
    _sinal_progress = Signal(tuple)
    _sinal_session_error = Signal(str)
    _sinal_done = Signal(str, str)
    _sinal_closed = Signal()
    _sinal_update = Signal(object)
    _sinal_update_error = Signal(str)
    _sinal_update_progress = Signal(int)
    _sinal_installer = Signal(object)
    _sinal_update_failed = Signal(str)

    def __init__(self):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle('Fusion')
        super().__init__()

        self.events: Queue = Queue()
        self.busy = self.checking = self.closing = False
        self.auto_updating = False
        self.session: Session | None = None
        self.pending_installer = None
        self.update_info = None
        self.roots: list = []
        self.explorer_state = ExplorerState()
        self.operation: str | None = None
        self.retry_action = None
        self._config: Config | None = None

        self.setWindowTitle(f'D4Sign • Baixar Assinaturas • {VERSION}')
        icon_path = _resource_path('icon/logo.ico')
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1440, 820)
        self.setMinimumSize(1000, 640)
        self.setStyleSheet(f'background:{BG};')

        root = QVBoxLayout(self)
        root.setContentsMargins(48, 24, 48, 26)
        root.setSpacing(0)
        self._montar_cabecalho(root)
        center = QHBoxLayout()
        center.setSpacing(65)
        center.addLayout(self._montar_painel_esquerdo(), 5)
        center.addWidget(self._montar_cartao(), 9)
        root.addLayout(center, 1)
        self._montar_rodape(root)

        self._sinal_status.connect(self._ao_status)
        self._sinal_catalog.connect(self._mostrar_catalogo)
        self._sinal_branch.connect(self._mostrar_branch)
        self._sinal_progress.connect(self._ao_progresso)
        self._sinal_session_error.connect(self._ao_erro_sessao)
        self._sinal_done.connect(self._ao_concluir)
        self._sinal_closed.connect(self._ao_fechar_sessao)
        self._sinal_update.connect(self._ao_update)
        self._sinal_update_error.connect(lambda m: self._update_status_lbl.setText(m))
        self._sinal_update_progress.connect(lambda p: self._ao_status(f'Baixando atualização: {p}%'))
        self._sinal_installer.connect(self._ao_installer)
        self._sinal_update_failed.connect(self._ao_update_falhou)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(100)

        self.show()
        QTimer.singleShot(500, self._checar_atualizacoes)
        sys.exit(self._app.exec())

    # ── Montagem ──────────────────────────────────────────────────────────────

    def _montar_cabecalho(self, root):
        hdr = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(5)
        left.addWidget(_rotulo('B A I X A R   A S S I N A T U R A S', 9, '#85929c', QFont.Bold))
        left.addWidget(_rotulo('D4Sign Central Bolsas', 14, TEXT, QFont.DemiBold))
        hdr.addLayout(left)
        hdr.addStretch()
        root.addLayout(hdr)
        root.addSpacing(20)
        root.addWidget(_divisor(COR_DIVISOR_ESCURO))

    def _montar_painel_esquerdo(self):
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)
        left.addStretch()
        left.addWidget(_rotulo('A U T O M A Ç Ã O   D 4 S I G N', 9, ACTION, QFont.Bold))
        left.addSpacing(20)
        left.addWidget(
            _rotulo('Baixe documentos\nassinados do\nportal D4Sign.', 29, TEXT, QFont.DemiBold, True)
        )
        left.addSpacing(22)
        intro = _rotulo(
            'Conecta ao D4Sign usando as credenciais do arquivo .env, '
            'navega pelos cofres e pastas e baixa os documentos '
            'assinados diretamente para o seu computador.',
            12, '#a5afb6', wrap=True,
        )
        intro.setMinimumWidth(270)
        intro.setMaximumWidth(365)
        left.addWidget(intro)
        left.addSpacing(37)
        left.addWidget(_divisor(COR_DIVISOR_ESCURO))
        left.addSpacing(24)
        sec = QHBoxLayout()
        sec.setSpacing(14)
        circle = QFrame()
        circle.setFixedSize(34, 34)
        circle.setStyleSheet('background:#304658; border-radius:17px;')
        cl = QHBoxLayout(circle)
        cl.setContentsMargins(5, 5, 5, 5)
        cl.addWidget(Icon('file', '#a6b4bd', 20))
        sec.addWidget(circle, 0, Qt.AlignTop)
        sec.addWidget(
            _rotulo(
                'As credenciais são lidas do arquivo .env local. '
                'A senha nunca é armazenada externamente.',
                10, '#8998a3', wrap=True,
            ), 1,
        )
        left.addLayout(sec)
        left.addStretch()
        return left

    def _montar_cartao(self):
        card = QFrame()
        card.setObjectName('card')
        card.setStyleSheet('#card {background:#f8f7f3; border-radius:18px;}')
        sombra = QGraphicsDropShadowEffect(card)
        sombra.setBlurRadius(52)
        sombra.setOffset(0, 22)
        sombra.setColor(QColor(6, 18, 28, 80))
        card.setGraphicsEffect(sombra)
        lay = QVBoxLayout(card)
        lay.setSpacing(0)
        lay.setContentsMargins(0, 0, 0, 0)
        self._montar_titulo_cartao(lay)
        lay.addWidget(_divisor('#dde1df'))
        self._montar_corpo_cartao(lay)
        self._montar_rodape_cartao(lay)
        return card

    def _montar_titulo_cartao(self, lay):
        top = QHBoxLayout()
        top.setContentsMargins(30, 20, 30, 16)
        titles = QVBoxLayout()
        titles.setSpacing(5)
        titles.addWidget(
            _rotulo('Baixar documentos do D4Sign', 14, BG, QFont.DemiBold)
        )
        self._subtitle = _rotulo('Clique em Realizar login para começar.', 10, '#7a838a')
        titles.addWidget(self._subtitle)
        top.addLayout(titles)
        top.addStretch()
        self._badge_total = _rotulo('0 pastas', 9, '#68747d', QFont.Bold)
        self._badge_total.setStyleSheet(
            'color:#68747d; background:transparent; border:1px solid #d9dddc; border-radius:12px; padding:7px 12px;'
        )
        top.addWidget(self._badge_total)
        lay.addLayout(top)

    def _montar_corpo_cartao(self, lay):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet('''
            QScrollArea {background:transparent; border:none;}
            QScrollBar:vertical {background:#ebebe7; width:6px; border-radius:3px; margin:0;}
            QScrollBar::handle:vertical {background:#c5c8c6; border-radius:3px; min-height:24px;}
            QScrollBar::handle:vertical:hover {background:#a8aaa8;}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {height:0;}
        ''')
        conteudo = QWidget()
        conteudo.setStyleSheet('background:transparent;')
        cly = QVBoxLayout(conteudo)
        cly.setContentsMargins(0, 0, 0, 0)
        cly.setSpacing(0)

        # Estado de carregamento (visível enquanto não há catálogo)
        self._loading_frame = QFrame()
        self._loading_frame.setStyleSheet('background:transparent; border:none;')
        ll = QVBoxLayout(self._loading_frame)
        ll.setContentsMargins(30, 30, 30, 30)
        ll.setSpacing(12)
        self._loading_lbl = _rotulo('Clique em "Realizar login" para conectar ao D4Sign.', 12, '#7a838a', wrap=True)
        self._loading_lbl.setAlignment(Qt.AlignCenter)
        ll.addWidget(self._loading_lbl)
        cly.addWidget(self._loading_frame)

        # Explorador de pastas (oculto até login)
        cly.addWidget(_divisor('#e3e5e2'))
        self._explorer = FolderExplorerWidget(self.explorer_state)
        self._explorer.navigated.connect(self._navegar)
        self._explorer.toggled.connect(self._selecao_mudou)
        self._explorer.refreshed.connect(self._atualizar_nivel)
        self._explorer.hide()
        cly.addWidget(self._explorer)

        # Destino do download
        self._div_destino = _divisor('#e3e5e2')
        self._div_destino.hide()
        cly.addWidget(self._div_destino)
        self._destino_frame = QFrame()
        self._destino_frame.hide()
        self._destino_frame.setStyleSheet('background:transparent; border:none;')
        dl = QVBoxLayout(self._destino_frame)
        dl.setContentsMargins(16, 12, 16, 12)
        dl.setSpacing(8)
        dl.addWidget(_rotulo('Pasta de destino', 10, BG, QFont.DemiBold))
        dest_row = QHBoxLayout()
        dest_row.setSpacing(8)
        self._destino_entry = QLineEdit(str(Path.home() / 'Downloads' / 'D4Sign'))
        self._destino_entry.setStyleSheet('''
            QLineEdit {background:#ffffff; border:1px solid #dde1df; border-radius:8px;
                font-family:"Segoe UI"; font-size:11px; color:#344a5b; padding:6px 10px; min-height:34px;}
            QLineEdit:focus {border-color:#a0b0bc;}
        ''')
        dest_row.addWidget(self._destino_entry, 1)
        self._btn_escolher = QPushButton('Escolher pasta')
        self._btn_escolher.setFixedHeight(38)
        self._btn_escolher.setCursor(Qt.PointingHandCursor)
        self._btn_escolher.setStyleSheet(ESTILO_BOTAO_LINHA)
        self._btn_escolher.clicked.connect(self._escolher_destino)
        dest_row.addWidget(self._btn_escolher)
        dl.addLayout(dest_row)
        cly.addWidget(self._destino_frame)

        cly.addStretch()
        scroll.setWidget(conteudo)
        lay.addWidget(scroll, 1)

    def _montar_rodape_cartao(self, lay):
        footer = QFrame()
        footer.setStyleSheet(
            'background:#f1f1ed; border-bottom-left-radius:18px; border-bottom-right-radius:18px;'
        )
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(30, 20, 30, 20)
        texts = QVBoxLayout()
        texts.setSpacing(5)
        self._ready_title = _rotulo('Aguardando login', 10, '#344a5b', QFont.DemiBold)
        self._ready_hint = _rotulo('Ajuste o checkbox "Ocultar Chrome" e clique em Realizar login.', 9, '#838c91', wrap=True)
        texts.addWidget(self._ready_title)
        texts.addWidget(self._ready_hint)
        fl.addLayout(texts, 1)

        self._chk_headless = QCheckBox('Ocultar Chrome')
        self._chk_headless.setToolTip('Executar o Chrome em segundo plano (sem janela visível)')
        self._chk_headless.setStyleSheet('''
            QCheckBox {color:#344a5b; font-family:"Segoe UI"; font-size:10px; spacing:6px;}
            QCheckBox::indicator {width:16px; height:16px; border-radius:4px;
                border:2px solid #c0c8cc; background:#fff;}
            QCheckBox::indicator:checked {background:#e94c1f; border-color:#e94c1f;}
            QCheckBox::indicator:disabled {background:#ebebeb; border-color:#d0d8dc;}
        ''')
        fl.addWidget(self._chk_headless)
        fl.addSpacing(16)

        self._btn_cancelar = QPushButton('Cancelar download')
        self._btn_cancelar.setFixedHeight(42)
        self._btn_cancelar.setCursor(Qt.PointingHandCursor)
        self._btn_cancelar.setStyleSheet(ESTILO_BOTAO_LINHA)
        self._btn_cancelar.clicked.connect(self._cancelar_download)
        self._btn_cancelar.hide()
        fl.addWidget(self._btn_cancelar)
        fl.addSpacing(8)

        self._btn_sair = QPushButton('Sair da conta')
        self._btn_sair.setFixedHeight(42)
        self._btn_sair.setCursor(Qt.PointingHandCursor)
        self._btn_sair.setStyleSheet(ESTILO_BOTAO_LINHA)
        self._btn_sair.clicked.connect(self._logout)
        self._btn_sair.hide()
        fl.addWidget(self._btn_sair)
        fl.addSpacing(8)

        self._download_btn = QPushButton('Realizar login  →')
        self._download_btn.setFixedHeight(46)
        self._download_btn.setMinimumWidth(190)
        self._download_btn.setCursor(Qt.PointingHandCursor)
        self._download_btn.setEnabled(True)
        self._download_btn.setStyleSheet(ESTILO_INICIAR_ATIVO)
        self._download_btn.clicked.connect(self._acao_principal)
        fl.addWidget(self._download_btn)
        lay.addWidget(footer)

    def _montar_rodape(self, root):
        root.addWidget(_divisor(COR_DIVISOR_ESCURO))
        root.addSpacing(17)
        bot = QHBoxLayout()
        bot.addWidget(
            _rotulo('D4Sign Central Bolsas — Download de Documentos Assinados', 9, '#83919c')
        )
        bot.addStretch()
        self._update_status_lbl = QPushButton(f'v{VERSION}')
        self._update_status_lbl.setFlat(True)
        self._update_status_lbl.setStyleSheet(
            'QPushButton {color:#83919c; font-family:"Segoe UI"; font-size:9px;'
            ' border:none; padding:0; background:transparent;}'
        )
        self._update_status_lbl.clicked.connect(self._iniciar_atualizacao)
        bot.addWidget(self._update_status_lbl)
        root.addLayout(bot)

    # ── Conexão automática ────────────────────────────────────────────────────

    def _iniciar_conexao(self):
        try:
            self._config = Config.load()
        except RuntimeError as exc:
            self._loading_lbl.setText(
                f'Erro ao ler credenciais do .env:\n{exc}\n\n'
                'Adicione D4SIGN_EMAIL e D4SIGN_PASSWORD ao arquivo .env.'
            )
            self._loading_lbl.setStyleSheet('color:#c0351a; background:transparent;')
            self._ready_title.setText('Credenciais ausentes')
            self._ready_hint.setText('Configure o arquivo .env e reinicie o aplicativo.')
            return

        from dataclasses import replace as _replace
        headless = self._chk_headless.isChecked()
        self._config = _replace(self._config, headless=headless)

        self._loading_lbl.setText('Entrando e carregando cofres…')
        self._loading_lbl.setStyleSheet('color:#7a838a; background:transparent;')
        self.busy = True
        self.session = Session(self._config, self.events)
        self.session.start()

    # ── Estado da UI ──────────────────────────────────────────────────────────

    def _set_busy(self, value):
        self.busy = value
        self._explorer.set_busy(value)
        self._btn_escolher.setEnabled(not value)
        self._destino_entry.setEnabled(not value)
        self._selecao_mudou()
        if value and self.operation == 'download':
            self._btn_cancelar.show()
            self._btn_sair.hide()
        else:
            self._btn_cancelar.hide()
            if self.session:
                self._btn_sair.show()
            else:
                self._btn_sair.hide()

    def _acao_principal(self):
        if self.busy:
            return
        if not self.session:
            self._iniciar_conexao()
        else:
            self._iniciar_download()

    def _selecao_mudou(self):
        count = len(self.explorer_state.selected)
        self._badge_total.setText(
            f'{count} pasta{"s" if count != 1 else ""} selecionada{"s" if count != 1 else ""}'
        )
        if self.busy:
            self._download_btn.setText('◌  Processando…')
            self._download_btn.setEnabled(False)
            self._download_btn.setStyleSheet(ESTILO_INICIAR_RODANDO)
        elif not self.session:
            self._download_btn.setText('Realizar login  →')
            self._download_btn.setEnabled(True)
            self._download_btn.setStyleSheet(ESTILO_INICIAR_ATIVO)
        elif count > 0:
            label = 'Baixar pasta' if count == 1 else f'Baixar {count} pastas'
            self._download_btn.setText(f'{label}  →')
            self._download_btn.setEnabled(True)
            self._download_btn.setStyleSheet(ESTILO_INICIAR_ATIVO)
        else:
            self._download_btn.setText('Selecione pastas para baixar')
            self._download_btn.setEnabled(False)
            self._download_btn.setStyleSheet(ESTILO_INICIAR_INATIVO)

    # ── Eventos da sessão ─────────────────────────────────────────────────────

    def _ao_status(self, msg: str):
        self._subtitle.setText(msg)
        self._ready_hint.setText(msg)

    def _mostrar_catalogo(self, roots: list):
        previous = set(self.explorer_state.selected)
        self.roots = roots
        self.explorer_state.catalog(roots)
        self._loading_frame.hide()
        self._explorer.show()
        self._div_destino.show()
        self._destino_frame.show()
        self._set_busy(False)
        self._explorer.render()
        self._selecao_mudou()
        self._btn_sair.show()
        self._subtitle.setText('Abra uma pasta ou marque as caixas para selecionar.')
        self._ready_title.setText('Cofres disponíveis')
        self._ready_hint.setText('Navegue e selecione as pastas que deseja baixar.')
        if previous - self.explorer_state.selected:
            self._ready_hint.setText('A lista mudou. Pastas indisponíveis foram removidas da seleção.')

    def _mostrar_branch(self, node):
        current = self.explorer_state.nodes[node.key]
        current.children, current.loaded = node.children, node.loaded
        self.explorer_state.catalog(self.roots)
        self._set_busy(False)
        self._explorer.render()
        self._ao_status('Conteúdo carregado.')
        self.operation = None

    def _ao_progresso(self, value: tuple):
        total, downloaded, cached, errors = value
        total_text = str(total) if total is not None else '?'
        msg = (
            f'Baixando… {downloaded}/{total_text} documentos'
            f' • Cache: {cached} • Erros: {errors}'
        )
        self._ao_status(msg)
        self._ready_title.setText(msg)

    def _ao_erro_sessao(self, msg: str):
        self._subtitle.setText(msg)
        self._loading_lbl.setText(msg)
        self._loading_lbl.setStyleSheet('color:#c0351a; background:transparent;')
        self._loading_frame.show()
        self._ready_title.setText('Falha na conexão')
        self._ready_hint.setText(msg)
        self._set_busy(False)

        _PALAVRAS_CREDENCIAL = ('senha', 'e-mail', 'email', 'credencial', 'inválid', 'invalida', 'login')
        msg_lower = msg.lower()
        if any(p in msg_lower for p in _PALAVRAS_CREDENCIAL):
            dlg = QMessageBox(self)
            dlg.setWindowTitle('Credenciais inválidas')
            dlg.setText(msg)
            dlg.setInformativeText('Verifique o D4SIGN_EMAIL e D4SIGN_PASSWORD no arquivo .env e reinicie o aplicativo.')
            dlg.setIcon(QMessageBox.Critical)
            dlg.setStandardButtons(QMessageBox.Ok)
            dlg.setStyleSheet('''
                QMessageBox {background-color:#203447;}
                QLabel {color:#efede5; font-family:"Segoe UI"; font-size:13px;}
                QPushButton {background:#e94c1f; color:white; border:none; border-radius:6px;
                             font:600 11px "Segoe UI"; padding:6px 20px; min-width:70px;}
                QPushButton:hover {background:#d74118;}
            ''')
            dlg.exec()

    def _ao_concluir(self, kind: str, msg: str):
        self._set_busy(kind == 'cancelled')
        self._ao_status(msg)
        self._ready_title.setText(
            'Download concluído' if kind == 'done' else
            'Concluído com avisos' if kind == 'done_warning' else
            'Erro no download' if kind == 'error' else
            'Cancelado'
        )
        self._ready_hint.setText(msg)
        if kind == 'error' and self.retry_action:
            pass
        elif kind in ('done', 'done_warning'):
            self.operation = None

    def _ao_fechar_sessao(self):
        self.session = None
        self.operation = self.retry_action = None
        self.roots = []
        self.explorer_state.catalog([])
        self.explorer_state.navigate(None)
        self._explorer.hide()
        self._div_destino.hide()
        self._destino_frame.hide()
        self._btn_sair.hide()
        self._btn_cancelar.hide()
        self._loading_frame.show()
        self._loading_lbl.setStyleSheet('color:#7a838a; background:transparent;')
        self._loading_lbl.setText('Sessão encerrada. Clique em "Realizar login" para conectar novamente.')
        self._ready_title.setText('Aguardando login')
        self._ready_hint.setText('Ajuste o checkbox "Ocultar Chrome" e clique em Realizar login.')
        self._selecao_mudou()
        if self.pending_installer:
            path, self.pending_installer = self.pending_installer, None
            if self._abrir_instalador(path):
                return
        elif self.closing:
            self.close()
            return
        self._set_busy(False)

    # ── Navegação e download ──────────────────────────────────────────────────

    def _navegar(self, key):
        if self.busy:
            return
        self.operation = None
        self.retry_action = None
        self.explorer_state.navigate(key)
        self._explorer.render()
        node = self.explorer_state.nodes.get(key)
        if node and not node.loaded and self.session:
            self.operation = 'expand'
            self.retry_action = lambda: self._navegar(key)
            self._set_busy(True)
            self._ao_status(f'Carregando subpastas de {node.name}…')
            self.session.commands.put(('expand', key))
        else:
            self._ao_status('Seleção mantida ao navegar.')

    def _escolher_destino(self):
        if self.busy:
            return
        path = QFileDialog.getExistingDirectory(
            self, 'Escolher pasta para os downloads', self._destino_entry.text()
        )
        if path:
            self._destino_entry.setText(path)

    def _iniciar_download(self):
        if self.busy or not self.session:
            return
        selected = sorted(self.explorer_state.selected)
        destination = self._destino_entry.text().strip()
        if not selected or not destination:
            return
        self.operation = 'download'
        self.retry_action = self._iniciar_download
        self._set_busy(True)
        self._ao_status('Preparando download…')
        self.session.commands.put(('download', (selected, True, destination)))

    def _atualizar_nivel(self):
        if not self.busy and self.session:
            self.operation = 'refresh'
            self.retry_action = self._atualizar_nivel
            self._set_busy(True)
            self._ao_status('Atualizando nível…')
            self.session.commands.put(
                ('refresh_level', (self.explorer_state.current, sorted(self.explorer_state.selected)))
            )

    def _cancelar_download(self):
        if not self.session or not self.busy:
            return
        self._ao_status('Cancelando download e encerrando o Chrome…')
        self._btn_cancelar.setEnabled(False)
        self.session.cancel_download()

    def _logout(self):
        if not self.busy and self.session:
            self.operation = 'logout'
            self._set_busy(True)
            self._ao_status('Encerrando sessão…')
            self.session.close()

    # ── Poll de eventos ───────────────────────────────────────────────────────

    def _poll(self):
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except Empty:
                break
            if kind == 'log':
                logging.info('%s', str(value).rstrip())
            elif kind == 'status':
                self._sinal_status.emit(value)
            elif kind == 'download_progress':
                self._sinal_progress.emit(value)
            elif kind == 'catalog':
                self._sinal_catalog.emit(value)
            elif kind == 'branch':
                self._sinal_branch.emit(value)
            elif kind == 'closed':
                self._sinal_closed.emit()
            elif kind == 'session_error':
                self._sinal_session_error.emit(value)
            elif kind in ('done', 'done_warning', 'error', 'cancelled'):
                self._sinal_done.emit(kind, value)
            elif kind == 'update':
                self._sinal_update.emit(value)
            elif kind == 'update_error':
                self._sinal_update_error.emit(value)
            elif kind == 'progress':
                self._sinal_update_progress.emit(value)
            elif kind == 'installer':
                self._sinal_installer.emit(value)
            elif kind == 'update_failed':
                self._sinal_update_failed.emit(value)

    # ── Atualizações automáticas ──────────────────────────────────────────────

    def _checar_atualizacoes(self):
        if self.checking:
            return
        self.checking = True
        self._update_status_lbl.setText('Consultando atualizações…')

        def worker():
            try:
                self.events.put(('update', check_update()))
            except Exception as exc:
                self.events.put(('update_error', f'Não foi possível consultar atualizações: {exc}'))

        Thread(target=worker, daemon=True).start()

    def _ao_update(self, update):
        self.checking = False
        self.update_info = update
        if update and sys.platform == 'win32' and not self.session and not self.busy:
            self._update_status_lbl.setText(f'Atualização {update.version} encontrada. Baixando…')
            self._iniciar_download_update(update, automatic=True)
        elif update:
            self._update_status_lbl.setText(f'Nova versão disponível: {update.version} — clique para atualizar')
            self._update_status_lbl.setCursor(Qt.PointingHandCursor)
            self._update_status_lbl.setStyleSheet(
                'QPushButton {color:#e9a833; font-family:"Segoe UI"; font-size:9px;'
                ' border:none; padding:0; background:transparent; text-decoration:underline;}'
            )
        else:
            self._update_status_lbl.setText(f'● v{VERSION} — atualizado')
            self._update_status_lbl.setStyleSheet(
                'QPushButton {color:#5aaa7a; font-family:"Segoe UI"; font-size:9px;'
                ' border:none; padding:0; background:transparent;}'
            )

    def _iniciar_atualizacao(self):
        if not self.update_info:
            return
        self._iniciar_download_update(self.update_info)

    def _iniciar_download_update(self, update, automatic=False):
        if self.auto_updating:
            return
        self.auto_updating = automatic or self.auto_updating
        self._set_busy(True)
        self._ao_status('Baixando atualização segura…')

        def worker():
            try:
                path = download_update(update, lambda p: self.events.put(('progress', p)))
                self.events.put(('installer', path))
            except Exception as exc:
                self.events.put(('update_failed', f'Não foi possível atualizar: {exc}'))

        Thread(target=worker, daemon=False).start()

    def _ao_update_falhou(self, msg: str):
        self.auto_updating = False
        self._set_busy(False)
        self._update_status_lbl.setText(msg)

    def _ao_installer(self, path):
        if self.session:
            self.pending_installer = path
            self.session.close()
        elif self._abrir_instalador(path):
            return

    def _abrir_instalador(self, path) -> bool:
        try:
            subprocess.Popen([str(path)], close_fds=True)
        except OSError:
            return False
        self.close()
        return True

    # ── Fechar janela ─────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self.session:
            self.closing = True
            self.operation = 'close'
            self._set_busy(True)
            self.session.close()
            event.ignore()
        else:
            event.accept()


def main():
    data_dir = Path(
        os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'share'))
    ) / 'D4SignDesktop'
    data_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(data_dir)
    logging.basicConfig(
        filename=data_dir / 'd4sign.log', encoding='utf-8',
        level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
    )
    Desktop()
