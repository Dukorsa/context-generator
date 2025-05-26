# main_app.py
import sys
import os
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QFileDialog, QTextEdit, QGroupBox, QScrollArea,
    QCheckBox, QMessageBox, QFrame, QGridLayout
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter

# Tenta importar as configurações e o processador reais.
# Se falhar, usa mocks para que a UI ainda possa ser testada visualmente.
try:
    from config import SUPPORTED_LANGUAGES
    from code_processor import process_project_folder
    APP_MODE_REAL = True
except ImportError as e:
    print(f"ALERTA: Não foi possível importar módulos reais (config, code_processor): {e}. "
          "A aplicação usará dados MOCK para a UI.")
    APP_MODE_REAL = False
    
    # --- Fallback Mock Definitions ---
    SUPPORTED_LANGUAGES = {
        "Python (Mock)": [".py", ".pyw"],
        "JavaScript (Mock)": [".js", ".jsx"],
        "HTML (Mock)": [".html"],
    }
    def process_project_folder(source_dir, dest_dir, selected_exts, progress_callback):
        progress_callback("MOCK: Iniciando varredura de arquivos...")
        mock_files_processed = [
            f"mock_file1{list(selected_exts)[0] if selected_exts else '.txt'}",
            f"mock_file2{list(selected_exts)[0] if selected_exts else '.txt'}"
        ]
        count = 0
        for i, fname in enumerate(mock_files_processed):
            progress_callback(f"📄 MOCK Processando: {fname}...")
            QThread.msleep(300) # Simula trabalho
            count +=1
        QThread.msleep(500)
        progress_callback("✅ MOCK: Geração de arquivos de contexto concluída.")
        return [f"Log MOCK {i+1}" for i in range(5)], count
    # --- End of Fallback Mock Definitions ---

STYLESHEET = """
    QWidget {
        background-color: #f8fafc; /* Light gray background */
        font-family: 'Inter', 'Segoe UI', sans-serif;
    }

    QLabel {
        font-size: 11pt;
        color: #334155; /* slate-700 */
        font-weight: 500;
    }
    
    QLabel#title {
        font-size: 28pt;
        font-weight: 700;
        color: #0f172a; /* slate-900, darker for more contrast */
        margin: 5px 0;
    }
    
    QLabel#subtitle {
        font-size: 14pt;
        color: #64748b; /* slate-500 */
        font-weight: 400;
        margin-bottom: 25px;
    }
    
    QLineEdit {
        background: white;
        border: 1px solid #cbd5e1; /* slate-300 */
        border-radius: 8px;
        padding: 10px 14px;
        font-size: 11pt;
        color: #1e293b;
    }
    
    QLineEdit:focus {
        border-color: #3b82f6; /* blue-500 */
    }
    
    QLineEdit:hover {
        border-color: #94a3b8; /* slate-400 */
    }
    
    QPushButton {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3b82f6, stop:1 #2563eb); /* blue-500 to blue-600 */
        color: white;
        border: none;
        padding: 10px 20px;
        border-radius: 8px;
        font-weight: 600;
        font-size: 11pt;
        min-height: 20px;
    }
    
    QPushButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2563eb, stop:1 #1d4ed8); /* blue-600 to blue-700 */
    }
    
    QPushButton:pressed {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1d4ed8, stop:1 #1e40af); /* blue-700 to blue-800 */
    }
    
    QPushButton:disabled {
        background: #94a3b8; /* slate-400 */
        color: #e2e8f0; /* slate-200 */
    }
    
    QPushButton#secondary {
        background: white;
        color: #475569; /* slate-600 */
        border: 1px solid #cbd5e1; /* slate-300 */
    }
    
    QPushButton#secondary:hover {
        background: #f1f5f9; /* slate-100 */
        border-color: #94a3b8; /* slate-400 */
    }
    
    QPushButton#success {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #10b981, stop:1 #059669); /* emerald-500 to emerald-600 */
        padding: 8px 16px; /* Slightly smaller padding for these buttons */
        font-size: 10pt;
    }
    
    QPushButton#success:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #059669, stop:1 #047857); /* emerald-600 to emerald-700 */
    }
    
    QPushButton#danger {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ef4444, stop:1 #dc2626); /* red-500 to red-600 */
        padding: 8px 16px; /* Slightly smaller padding for these buttons */
        font-size: 10pt;
    }
    
    QPushButton#danger:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #dc2626, stop:1 #b91c1c); /* red-600 to red-700 */
    }

    QGroupBox {
        border: 1px solid #e2e8f0; /* slate-200 */
        border-radius: 12px;
        margin-top: 8px; /* Reduced margin-top as custom title is inside */
        padding: 0px; /* No padding, custom layout inside handles it */
        background: white;
    }

    /* Hide the default QGroupBox title rendering area */
    QGroupBox::title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 0 0 0;
        height: 0px; /* Effectively hide */
    }

    QLabel#customGroupTitleIconSquare {
        min-width: 14px;
        max-width: 14px;
        min-height: 14px;
        max-height: 14px;
        border-radius: 3px;
        /* background-color is set in Python */
    }
    QLabel#customGroupTitleIconChar {
        font-size: 13pt; /* For emoji icons */
        color: #334155; /* slate-700 */
    }
    QLabel#customGroupTitleText {
        font-size: 12pt; /* Slightly smaller for better fit */
        font-weight: 600;
        color: #1e293b; /* slate-800 */
        padding-top: 0px; /* Adjust if needed for vertical alignment */
    }
    
    QTextEdit {
        background: #ffffff;
        border: 1px solid #e2e8f0; /* slate-200 */
        border-radius: 8px;
        padding: 12px;
        font-family: 'JetBrains Mono', 'Consolas', monospace;
        font-size: 10pt;
        color: #1e293b;
    }
    
    QTextEdit:focus {
        border-color: #3b82f6; /* blue-500 */
    }
    
    QCheckBox {
        font-size: 11pt;
        color: #334155; /* slate-700 */
        spacing: 8px;
        font-weight: 500;
        padding: 6px 2px; /* Add some padding for better spacing in grid */
    }
    
    QCheckBox::indicator {
        width: 18px;
        height: 18px;
        border-radius: 5px;
        border: 2px solid #cbd5e1; /* slate-300 */
        background: white;
    }
    
    QCheckBox::indicator:hover {
        border-color: #3b82f6; /* blue-500 */
    }
    
    QCheckBox::indicator:checked {
        background-color: #3b82f6; /* Fundo azul */
        border-color: #3b82f6;    /* Borda azul para consistência */
        image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iOSIgdmlld0JveD0iMCAwIDEyIDkiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxwYXRoIGQ9Ik0xIDQuNUw0LjUgOEwxMSAxIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPgo8L3N2Zz4K); /* Checkmark BRANCO */
    }
    
    QScrollArea {
        border: 1px solid #e2e8f0; /* slate-200 */
        border-radius: 8px;
        background: white;
    }
    
    QScrollArea > QWidget > QWidget { /* Target the container inside scroll area */
        background: white;
    }
    
    QScrollBar:vertical {
        border: none;
        background: #f1f5f9; /* slate-100 */
        width: 10px;
        border-radius: 5px;
        margin: 1px;
    }
    
    QScrollBar::handle:vertical {
        background: #cbd5e1; /* slate-300 */
        min-height: 25px;
        border-radius: 5px;
    }
    
    QScrollBar::handle:vertical:hover {
        background: #94a3b8; /* slate-400 */
    }
    
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
    QScrollBar:horizontal {
        border: none; background: #f1f5f9; height: 10px;
        border-radius: 5px; margin: 1px;
    }
    QScrollBar::handle:horizontal {
        background: #cbd5e1; min-width: 25px; border-radius: 5px;
    }
    QScrollBar::handle:horizontal:hover { background: #94a3b8; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
"""

class ProcessingThread(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(list, int)

    def __init__(self, source_dir, dest_dir, selected_exts):
        super().__init__()
        self.source_dir = source_dir
        self.dest_dir = dest_dir
        self.selected_exts = selected_exts

    def run(self):
        # Esta função `process_project_folder` será a real (se importada com sucesso)
        # ou a mock (se o import falhar).
        def cb(message): # Callback para o process_project_folder
            # Adiciona timestamp antes de emitir o sinal para a UI
            now = datetime.now().strftime('%H:%M:%S')
            if message: self.progress_signal.emit(f"[{now}] {message}")
        
        logs, count = process_project_folder(self.source_dir, self.dest_dir, self.selected_exts, cb)
        self.finished_signal.emit(logs, count)


class AnimatedButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setMinimumHeight(48) 
        self._original_style_sheet = self.styleSheet()

    def enterEvent(self, event):
        super().enterEvent(event) 
        
    def leaveEvent(self, event):
        super().leaveEvent(event) 


class CodeContextExtractorApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gerador de Contexto de Código")
        self.setStyleSheet(STYLESHEET)
        self.thread = None
        self._set_window_icon()
        self._init_ui()

    def _set_window_icon(self):
        pixmap = QPixmap(32,32)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setFont(QFont("Arial", 20)) 
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "🚀")
        painter.end()
        self.setWindowIcon(QIcon(pixmap))

    def _create_custom_group_title(self, icon_char_or_color, text, is_char_icon=True):
        title_widget = QWidget()
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(12, 8, 12, 8) 
        title_layout.setSpacing(8)

        icon_label = QLabel()
        if is_char_icon:
            icon_label.setText(icon_char_or_color)
            icon_label.setObjectName("customGroupTitleIconChar")
        else: 
            icon_label.setObjectName("customGroupTitleIconSquare")
            icon_label.setStyleSheet(f"background-color: {icon_char_or_color};")
        
        text_label = QLabel(text)
        text_label.setObjectName("customGroupTitleText")

        title_layout.addWidget(icon_label)
        title_layout.addWidget(text_label)
        title_layout.addStretch(1)
        return title_widget

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(18) 
        main_layout.setContentsMargins(25, 20, 25, 25)

        # --- Header ---
        header_layout = QVBoxLayout()
        header_layout.setSpacing(2)
        title_label = QLabel("🚀 Gerador de Contexto de Código")
        title_label.setObjectName("title")
        title_label.setAlignment(Qt.AlignCenter)
        
        subtitle_text = "Selecione as pastas, escolha as linguagens e gere arquivos de contexto."
        if not APP_MODE_REAL:
            subtitle_text += " (MODO MOCK ATIVO)"
        subtitle_label = QLabel(subtitle_text)
        subtitle_label.setObjectName("subtitle")
        subtitle_label.setAlignment(Qt.AlignCenter)
        if not APP_MODE_REAL:
            subtitle_label.setStyleSheet("color: #ef4444; font-weight: bold;")


        header_layout.addWidget(title_label)
        header_layout.addWidget(subtitle_label)
        main_layout.addLayout(header_layout)

        # --- Folders Section (Side by Side) ---
        folders_main_layout = QHBoxLayout()
        folders_main_layout.setSpacing(20)
        
        source_group = QGroupBox() 
        source_group_content_layout = QVBoxLayout(source_group)
        source_group_content_layout.setContentsMargins(0,0,0,0) 
        source_group_content_layout.setSpacing(10)
        source_group_content_layout.addWidget(self._create_custom_group_title("📂", "Pasta de Origem"))

        source_path_layout = QHBoxLayout()
        source_path_layout.setContentsMargins(12,0,12,10) 
        self.source_path_edit = QLineEdit()
        self.source_path_edit.setPlaceholderText("Ex: /caminho/para/seu/projeto")
        self.source_path_edit.setReadOnly(True)
        source_btn = QPushButton("Selecionar Pasta")
        source_btn.setObjectName("secondary")
        source_btn.clicked.connect(self.select_source_folder)
        source_path_layout.addWidget(self.source_path_edit, 3)
        source_path_layout.addWidget(source_btn, 1)
        source_group_content_layout.addLayout(source_path_layout)
        
        dest_group = QGroupBox() 
        dest_group_content_layout = QVBoxLayout(dest_group)
        dest_group_content_layout.setContentsMargins(0,0,0,0)
        dest_group_content_layout.setSpacing(10)
        dest_group_content_layout.addWidget(self._create_custom_group_title("🎯", "Pasta de Destino"))

        dest_path_layout = QHBoxLayout()
        dest_path_layout.setContentsMargins(12,0,12,10) 
        self.dest_path_edit = QLineEdit()
        self.dest_path_edit.setPlaceholderText("Ex: /caminho/para/salvar/contexto")
        self.dest_path_edit.setReadOnly(True)
        dest_btn = QPushButton("Selecionar Pasta")
        dest_btn.setObjectName("secondary")
        dest_btn.clicked.connect(self.select_dest_folder)
        dest_path_layout.addWidget(self.dest_path_edit, 3)
        dest_path_layout.addWidget(dest_btn, 1)
        dest_group_content_layout.addLayout(dest_path_layout)
        
        folders_main_layout.addWidget(source_group)
        folders_main_layout.addWidget(dest_group)
        main_layout.addLayout(folders_main_layout)

        # --- Language Selection Group ---
        lang_group = QGroupBox() 
        lang_group_content_layout = QVBoxLayout(lang_group)
        lang_group_content_layout.setContentsMargins(0,0,0,0)
        lang_group_content_layout.setSpacing(10) 

        lang_title_text = "Linguagens para Processar"
        if APP_MODE_REAL:
            lang_title_text += " (com análise AST robusta)"

        lang_title_widget = self._create_custom_group_title("🔧", lang_title_text)
        lang_title_layout = lang_title_widget.layout() 

        if lang_title_layout.count() > 0:
            last_item_index = lang_title_layout.count() -1
            item = lang_title_layout.itemAt(last_item_index)
            if item and item.spacerItem():
                lang_title_layout.takeAt(last_item_index) 
        
        lang_title_layout.addStretch(1)

        select_all_btn = QPushButton("✅ Selecionar Todas")
        select_all_btn.setObjectName("success")
        select_all_btn.clicked.connect(lambda: self._toggle_all_langs(True))
        
        deselect_all_btn = QPushButton("❌ Desmarcar Todas")
        deselect_all_btn.setObjectName("danger")
        deselect_all_btn.clicked.connect(lambda: self._toggle_all_langs(False))

        lang_title_layout.addWidget(select_all_btn)
        lang_title_layout.addWidget(deselect_all_btn)
        
        lang_group_content_layout.addWidget(lang_title_widget) 
        
        lang_checkbox_container = QWidget()
        self.lang_checkbox_layout = QGridLayout(lang_checkbox_container)
        self.lang_checkbox_layout.setContentsMargins(0, 0, 0, 0) 
        self.lang_checkbox_layout.setSpacing(5) 
        
        self.lang_checkboxes = {}
        # SUPPORTED_LANGUAGES é agora a versão real ou mock, dependendo do import
        sorted_langs = sorted(SUPPORTED_LANGUAGES.keys())
        num_cols = 6
        for i, lang_name in enumerate(sorted_langs):
            cb = QCheckBox(f"{lang_name}")
            cb.setChecked(True)
            self.lang_checkbox_layout.addWidget(cb, i // num_cols, i % num_cols)
            self.lang_checkboxes[lang_name] = cb
            
        scroll_area_widget = QWidget() 
        scroll_area_layout = QVBoxLayout(scroll_area_widget)
        scroll_area_layout.setContentsMargins(12, 5, 12, 10) 
        scroll_area_layout.addWidget(lang_checkbox_container)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(scroll_area_widget)
        # Ajuste de altura para acomodar 1-2 linhas de checkboxes com 6 colunas
        num_rows = (len(sorted_langs) + num_cols - 1) // num_cols
        min_h = max(50, num_rows * 40) # 40px aprox por linha de checkbox
        scroll_area.setMinimumHeight(min_h)
        scroll_area.setMaximumHeight(max(100, min_h + 20)) # Permitir um pouco mais se houver muitas linhas
        
        lang_group_content_layout.addWidget(scroll_area)
        main_layout.addWidget(lang_group)

        # --- Process Button ---
        process_btn_layout = QHBoxLayout()
        process_btn_layout.addStretch(1)
        self.process_btn = AnimatedButton("🚀 Iniciar Processamento")
        self.process_btn.clicked.connect(self.start_processing)
        process_btn_layout.addWidget(self.process_btn)
        process_btn_layout.addStretch(1)
        main_layout.addLayout(process_btn_layout)

        # --- Log Group ---
        log_group = QGroupBox() 
        log_group_content_layout = QVBoxLayout(log_group)
        log_group_content_layout.setContentsMargins(0,0,0,0)
        log_group_content_layout.setSpacing(10)
        log_group_content_layout.addWidget(self._create_custom_group_title("📋", "Log de Processamento"))
        
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        self.log_text_edit.setPlaceholderText("Os logs do processamento aparecerão aqui...")
        self.log_text_edit.setMinimumHeight(120)
        # self.log_text_edit.setMaximumHeight(250) # Removido para permitir expansão com stretch

        log_content_wrapper = QWidget() 
        log_content_layout = QVBoxLayout(log_content_wrapper)
        log_content_layout.setContentsMargins(12,0,12,10)
        log_content_layout.addWidget(self.log_text_edit)
        log_group_content_layout.addWidget(log_content_wrapper)
        
        main_layout.addWidget(log_group, 1) # Adiciona stretch factor ao log group
        # main_layout.addStretch(1) # Removido pois o log_group agora tem o stretch

        self.setLayout(main_layout)

    def _toggle_all_langs(self, checked):
        for cb in self.lang_checkboxes.values(): cb.setChecked(checked)

    def select_source_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Selecionar Pasta de Origem", self.source_path_edit.text() or os.path.expanduser("~"))
        if folder:
            self.source_path_edit.setText(folder)
            self.log_message(f"✅ Pasta de origem selecionada: <code>{folder}</code>")

    def select_dest_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Selecionar Pasta de Destino", self.dest_path_edit.text() or os.path.expanduser("~"))
        if folder:
            self.dest_path_edit.setText(folder)
            self.log_message(f"✅ Pasta de destino selecionada: <code>{folder}</code>")

    def log_message(self, message):
        self.log_text_edit.append(message)

    def update_progress(self, message): # Recebe string formatada do ProcessingThread
        if "✅" in message or "SUCCESS" in message or "Sucesso" in message or "concluído" in message:
            colored_message = f"<span style='color: #059669; font-weight: 500;'>{message}</span>"
        elif "❌" in message or "ERROR" in message or "Erro" in message or "falhou" in message:
            colored_message = f"<span style='color: #dc2626; font-weight: 500;'>{message}</span>"
        elif "⚠️" in message or "WARN" in message or "Aviso" in message:
            colored_message = f"<span style='color: #d97706; font-weight: 500;'>{message}</span>"
        elif "📄" in message or "Processando" in message or "Iniciando varredura" in message or "INFO:" in message:
            colored_message = f"<span style='color: #3b82f6; font-weight: 500;'>{message}</span>"
        elif "ℹ️" in message or "MOCK:" in message:
             colored_message = f"<span style='color: #64748b; font-style: italic;'>{message}</span>"
        else:
            colored_message = f"<span style='color: #475569;'>{message}</span>" # Default color
        self.log_text_edit.append(colored_message)

    def processing_finished(self, logs, count):
        # `logs` não é mais usado diretamente aqui, pois o `update_progress` já lida com as mensagens.
        final_message_prefix = "MOCK: " if not APP_MODE_REAL else ""
        self.log_message(f"<br>🎉 <b>{final_message_prefix}PROCESSAMENTO CONCLUÍDO!</b>")
        self.log_message(f"📊 Total de arquivos TXT gerados: <b>{count}</b>")
        self.process_btn.setEnabled(True)
        self.process_btn.setText("🚀 Iniciar Processamento")
        
        msg = QMessageBox(self)
        msg.setWindowTitle("✅ Processamento Concluído")
        msg.setText(f"<h3>🎉 {final_message_prefix}Processamento finalizado com sucesso!</h3><p><b>{count}</b> arquivos TXT foram gerados.</p><p>Verifique a pasta de destino.</p>")
        msg.setIcon(QMessageBox.Information) 
        msg.setStyleSheet("QMessageBox { background-color: white; font-family: 'Inter', 'Segoe UI', sans-serif; } QMessageBox QLabel { color: #1e293b; } QMessageBox QPushButton { background-color: #3b82f6; color: white; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 600; min-width: 80px; } QMessageBox QPushButton:hover { background-color: #2563eb; }")
        msg.exec()
        self.thread = None

    def start_processing(self):
        source_dir, dest_dir = self.source_path_edit.text(), self.dest_path_edit.text()
        if not source_dir or not os.path.isdir(source_dir):
            self._show_warning("Pasta de Origem Inválida", "Selecione uma pasta de origem válida.")
            return
        if not dest_dir:
            self._show_warning("Pasta de Destino Inválida", "Selecione uma pasta de destino.")
            return
        if os.path.abspath(source_dir) == os.path.abspath(dest_dir):
            self._show_warning("Pastas Idênticas", "A pasta de origem e destino não podem ser a mesma.")
            return
        if os.path.abspath(dest_dir).startswith(os.path.abspath(source_dir) + os.sep):
            self._show_warning("Estrutura de Pastas Inválida", "A pasta de destino não pode ser uma subpasta da origem.")
            return

        selected_extensions = set()
        selected_lang_names = []
        for lang_name, cb in self.lang_checkboxes.items():
            if cb.isChecked():
                selected_lang_names.append(lang_name)
                # SUPPORTED_LANGUAGES é a versão real ou mock, dependendo do import
                if lang_name in SUPPORTED_LANGUAGES:
                    selected_extensions.update(SUPPORTED_LANGUAGES[lang_name])

        if not selected_extensions:
            self._show_warning("Nenhuma Linguagem Selecionada", "Selecione pelo menos uma linguagem.")
            return

        self.log_text_edit.clear()
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.log_message(f"<span style='color: #64748b;'><i>Log iniciado em: {ts}</i></span><br>")
        
        processing_mode_message = " (MODO REAL)" if APP_MODE_REAL else " (MODO MOCK)"
        self.log_message(f"🚀 <b>INICIANDO PROCESSAMENTO{processing_mode_message}...</b>")
        self.log_message(f"📁 Origem: <code>{source_dir}</code>")
        self.log_message(f"💾 Destino: <code>{dest_dir}</code>")
        self.log_message(f"🔧 Linguagens: <b>{', '.join(selected_lang_names)}</b>")
        
        self.process_btn.setEnabled(False)
        self.process_btn.setText("⏳ Processando...")
        self.thread = ProcessingThread(source_dir, dest_dir, selected_extensions)
        self.thread.progress_signal.connect(self.update_progress)
        self.thread.finished_signal.connect(self.processing_finished)
        self.thread.start()

    def _show_warning(self, title, message):
        msg = QMessageBox(self)
        msg.setWindowTitle("⚠️ Atenção")
        msg.setText(f"<h3>{title}</h3><p>{message}</p>")
        msg.setIcon(QMessageBox.Warning)
        msg.setStyleSheet("QMessageBox { background-color: white; font-family: 'Inter', 'Segoe UI', sans-serif; } QMessageBox QLabel { color: #1e293b; } QMessageBox QPushButton { background-color: #f59e0b; color: white; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 600; min-width: 80px; } QMessageBox QPushButton:hover { background-color: #d97706; }")
        msg.exec()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    font = QFont("Inter", 10)
    if not QFont(font).exactMatch(): font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    if APP_MODE_REAL:
        print("INFO: Code Context Extractor rodando com módulos REAIS.")
    else:
        print("ALERTA: Code Context Extractor rodando com módulos MOCK. "
              "Verifique os imports de 'config' e 'code_processor' se o comportamento real é esperado.")

    window = CodeContextExtractorApp()
    window.showMaximized()
    sys.exit(app.exec())