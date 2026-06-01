import sys
import os
import time
import logging

logging.basicConfig(filename="recfile.log", level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", encoding="utf-8")

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QComboBox, QPushButton, QFileDialog, 
                             QCheckBox, QProgressBar, QMessageBox, QTableWidget, QTableWidgetItem,
                             QSplitter, QTextEdit, QHeaderView, QGroupBox, QFrame, QStackedWidget,
                             QButtonGroup, QRadioButton, QGridLayout)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap, QIcon, QFont

from utils import get_drives, is_admin, analyze_boot_sector
from imager import Imager
from carver import Carver

class WorkerSignals(QObject):
    progress = pyqtSignal(int, int) # current, total
    finished = pyqtSignal()
    error = pyqtSignal(str)
    file_found = pyqtSignal(str, str, int, int, str) # path, type, size, offset, status

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Recfile - Data Recovery Tool")
        self.resize(1100, 750)
        self.setMinimumSize(1000, 650)

        self.drives = []
        self.active_worker = None
        self.rec_out_folder = None
        self.img_src_folder = None
        self.img_dest_file = None
        self.rec_start_time = 0
        self.img_start_time = 0
        self.found_files = 0
        self.success_files = 0
        logging.info("Программа запущена.")
        
        self.init_ui()
        self.load_drives()

        if not is_admin():
            QMessageBox.warning(self, "Предупреждение", "Программа запущена без прав администратора. Доступ к физическим дискам может быть ограничен.")

    def init_ui(self):
        # Main layout is horizontal: sidebar (left) + stacked widget (right)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Sidebar Container
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # Logo / Title
        logo_lbl = QLabel("Recfile")
        logo_lbl.setObjectName("logo_label")
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(logo_lbl)

        # Nav Buttons Group
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.btn_nav_rec = QPushButton("Восстановление")
        self.btn_nav_rec.setCheckable(True)
        self.btn_nav_rec.setChecked(True)
        self.btn_nav_rec.setProperty("class", "sidebar-btn")
        self.btn_nav_rec.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        self.nav_group.addButton(self.btn_nav_rec)
        sidebar_layout.addWidget(self.btn_nav_rec)

        self.btn_nav_img = QPushButton("Создание образа")
        self.btn_nav_img.setCheckable(True)
        self.btn_nav_img.setProperty("class", "sidebar-btn")
        self.btn_nav_img.clicked.connect(lambda: self.pages.setCurrentIndex(1))
        self.nav_group.addButton(self.btn_nav_img)
        sidebar_layout.addWidget(self.btn_nav_img)

        self.btn_nav_res = QPushButton("Результаты")
        self.btn_nav_res.setCheckable(True)
        self.btn_nav_res.setProperty("class", "sidebar-btn")
        self.btn_nav_res.clicked.connect(lambda: self.pages.setCurrentIndex(2))
        self.nav_group.addButton(self.btn_nav_res)
        sidebar_layout.addWidget(self.btn_nav_res)

        sidebar_layout.addStretch()
        
        main_layout.addWidget(sidebar)

        # 2. Pages Container (QStackedWidget)
        self.pages = QStackedWidget()
        
        # Setup pages
        self.setup_recovery_page()
        self.setup_imaging_page()
        self.setup_results_page()

        main_layout.addWidget(self.pages)

        # Style Application
        self.apply_styles()

    def setup_recovery_page(self):
        page = QWidget()
        page.setProperty("class", "page-container")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # Title
        title = QLabel("Восстановление файлов (Carving)")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #800020;")
        layout.addWidget(title)

        # Source Selection Card
        src_group = QGroupBox("Источник данных")
        src_layout = QVBoxLayout()
        src_layout.setSpacing(12)
        
        src_h_layout = QHBoxLayout()
        self.rec_src_combo = QComboBox()
        self.rec_src_combo.currentIndexChanged.connect(self.detect_filesystem)
        
        self.rec_btn_image = QPushButton("Выбрать образ (.img/.dd)...")
        self.rec_btn_image.setProperty("class", "btn-secondary")
        self.rec_btn_image.clicked.connect(self.browse_rec_image)
        
        src_h_layout.addWidget(self.rec_src_combo, 2)
        src_h_layout.addWidget(self.rec_btn_image, 1)
        src_layout.addLayout(src_h_layout)

        # Detected Filesystem Label
        self.lbl_detected_fs = QLabel("ФС: Не выбрано")
        self.lbl_detected_fs.setAlignment(Qt.AlignmentFlag.AlignLeft)
        src_layout.addWidget(self.lbl_detected_fs)
        
        src_group.setLayout(src_layout)
        layout.addWidget(src_group)

        # Output Selection Card
        out_group = QGroupBox("Папка назначения")
        out_layout = QHBoxLayout()
        self.rec_out_lbl = QLabel("Папка для сохранения не выбрана")
        self.rec_out_lbl.setStyleSheet("color: #7F8C8D;")
        self.rec_btn_out = QPushButton("Выбрать папку...")
        self.rec_btn_out.setProperty("class", "btn-secondary")
        self.rec_btn_out.clicked.connect(self.browse_rec_out)
        out_layout.addWidget(self.rec_out_lbl, 2)
        out_layout.addWidget(self.rec_btn_out, 1)
        out_group.setLayout(out_layout)
        layout.addWidget(out_group)

        # File Types (Signatures) Card
        types_group = QGroupBox("Типы восстанавливаемых файлов")
        types_layout = QGridLayout()
        self.cb_jpg = QCheckBox("JPEG (.jpg)")
        self.cb_png = QCheckBox("PNG (.png)")
        self.cb_pdf = QCheckBox("PDF (.pdf)")
        self.cb_zip = QCheckBox("ZIP (.zip)")
        self.cb_docx = QCheckBox("DOCX (.docx)")
        
        self.cb_jpg.setChecked(True)
        self.cb_png.setChecked(True)
        self.cb_pdf.setChecked(True)
        self.cb_zip.setChecked(True)
        self.cb_docx.setChecked(True)
        
        types_layout.addWidget(self.cb_jpg, 0, 0)
        types_layout.addWidget(self.cb_png, 0, 1)
        types_layout.addWidget(self.cb_pdf, 1, 0)
        types_layout.addWidget(self.cb_zip, 1, 1)
        types_layout.addWidget(self.cb_docx, 2, 0)
        types_group.setLayout(types_layout)
        layout.addWidget(types_group)

        # Progress bar
        self.rec_progress = QProgressBar()
        self.rec_progress.setTextVisible(True)
        self.rec_progress.setFormat("%p%")
        self.rec_progress.setValue(0)
        
        self.rec_lbl_stats = QLabel("Скорость: 0 МБ/с | Прошло: 0 с")
        self.rec_lbl_stats.setStyleSheet("color: #7F8C8D; font-size: 12px;")
        
        layout.addWidget(self.rec_progress)
        layout.addWidget(self.rec_lbl_stats)

        # Control Buttons
        ctrl_layout = QHBoxLayout()
        self.rec_btn_start = QPushButton("Старт восстановления")
        self.rec_btn_start.setProperty("class", "btn-primary")
        self.rec_btn_start.clicked.connect(self.start_recovery)
        
        self.rec_btn_pause = QPushButton("Пауза")
        self.rec_btn_pause.setProperty("class", "btn-secondary")
        self.rec_btn_pause.setEnabled(False)
        self.rec_btn_pause.clicked.connect(self.toggle_pause_recovery)

        self.rec_btn_stop = QPushButton("Стоп")
        self.rec_btn_stop.setProperty("class", "btn-secondary")
        self.rec_btn_stop.setEnabled(False)
        self.rec_btn_stop.clicked.connect(self.stop_recovery)

        ctrl_layout.addWidget(self.rec_btn_start, 2)
        ctrl_layout.addWidget(self.rec_btn_pause, 1)
        ctrl_layout.addWidget(self.rec_btn_stop, 1)
        layout.addLayout(ctrl_layout)
        
        layout.addStretch()
        self.pages.addWidget(page)

    def setup_imaging_page(self):
        page = QWidget()
        page.setProperty("class", "page-container")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # Title
        title = QLabel("Создание посекторного образа")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #800020;")
        layout.addWidget(title)

        # Source Type Selection Card
        src_type_group = QGroupBox("Тип источника")
        src_type_layout = QHBoxLayout()
        self.rbtn_src_disk = QRadioButton("Физический диск")
        self.rbtn_src_folder = QRadioButton("Папка (Директория)")
        self.rbtn_src_disk.setChecked(True)
        self.rbtn_src_disk.toggled.connect(self.toggle_imaging_src_mode)
        src_type_layout.addWidget(self.rbtn_src_disk)
        src_type_layout.addWidget(self.rbtn_src_folder)
        src_type_group.setLayout(src_type_layout)
        layout.addWidget(src_type_group)

        # Source Selection Card
        self.img_src_group = QGroupBox("Выбор источника")
        self.img_src_layout = QHBoxLayout()
        
        # Disk ComboBox (visible by default)
        self.img_src_combo = QComboBox()
        
        # Folder Select Widgets (hidden by default)
        self.img_src_folder_widget = QWidget()
        img_src_folder_layout = QHBoxLayout(self.img_src_folder_widget)
        img_src_folder_layout.setContentsMargins(0, 0, 0, 0)
        self.img_src_folder_lbl = QLabel("Папка не выбрана")
        self.img_src_folder_lbl.setStyleSheet("color: #7F8C8D;")
        self.img_btn_src_folder = QPushButton("Выбрать папку...")
        self.img_btn_src_folder.setProperty("class", "btn-secondary")
        self.img_btn_src_folder.clicked.connect(self.browse_img_src_folder)
        img_src_folder_layout.addWidget(self.img_src_folder_lbl, 2)
        img_src_folder_layout.addWidget(self.img_btn_src_folder, 1)
        self.img_src_folder_widget.hide()

        self.img_src_layout.addWidget(self.img_src_combo)
        self.img_src_layout.addWidget(self.img_src_folder_widget)
        
        self.img_src_group.setLayout(self.img_src_layout)
        layout.addWidget(self.img_src_group)

        # Dest Card
        dest_group = QGroupBox("Файл назначения (.img)")
        dest_layout = QHBoxLayout()
        self.img_dest_lbl = QLabel("Путь к образу не выбран")
        self.img_dest_lbl.setStyleSheet("color: #7F8C8D;")
        self.img_btn_dest = QPushButton("Выбрать файл...")
        self.img_btn_dest.setProperty("class", "btn-secondary")
        self.img_btn_dest.clicked.connect(self.browse_img_dest)
        dest_layout.addWidget(self.img_dest_lbl, 2)
        dest_layout.addWidget(self.img_btn_dest, 1)
        dest_group.setLayout(dest_layout)
        layout.addWidget(dest_group)

        # Progress bar
        self.img_progress = QProgressBar()
        self.img_progress.setTextVisible(True)
        self.img_progress.setFormat("%p%")
        self.img_progress.setValue(0)
        self.img_lbl_stats = QLabel("Скорость: 0 МБ/с | Прошло: 0 с")
        self.img_lbl_stats.setStyleSheet("color: #7F8C8D; font-size: 12px;")
        layout.addWidget(self.img_progress)
        layout.addWidget(self.img_lbl_stats)

        # Controls
        ctrl_layout = QHBoxLayout()
        self.img_btn_start = QPushButton("Создать образ")
        self.img_btn_start.setProperty("class", "btn-primary")
        self.img_btn_start.clicked.connect(self.start_imaging)
        
        self.img_btn_stop = QPushButton("Стоп")
        self.img_btn_stop.setProperty("class", "btn-secondary")
        self.img_btn_stop.setEnabled(False)
        self.img_btn_stop.clicked.connect(self.stop_imaging)

        ctrl_layout.addWidget(self.img_btn_start, 2)
        ctrl_layout.addWidget(self.img_btn_stop, 1)
        layout.addLayout(ctrl_layout)

        layout.addStretch()
        self.pages.addWidget(page)

    def setup_results_page(self):
        page = QWidget()
        page.setProperty("class", "page-container")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # Title
        title = QLabel("Восстановленные файлы")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #800020;")
        layout.addWidget(title)

        # Table
        self.res_table = QTableWidget()
        self.res_table.setColumnCount(6)
        self.res_table.setHorizontalHeaderLabels(["№", "Имя файла", "Тип", "Размер (Байт)", "Смещение", "Статус"])
        self.res_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.res_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        layout.addWidget(self.res_table)
        
        stats_layout = QHBoxLayout()
        self.lbl_found_count = QLabel("Найдено файлов: 0")
        self.lbl_success_count = QLabel("Успешно восстановлено: 0")
        self.btn_clear_res = QPushButton("Очистить результаты")
        self.btn_clear_res.setProperty("class", "btn-secondary")
        self.btn_clear_res.clicked.connect(self.clear_results)
        
        stats_layout.addWidget(self.lbl_found_count)
        stats_layout.addWidget(self.lbl_success_count)
        stats_layout.addStretch()
        stats_layout.addWidget(self.btn_clear_res)
        
        layout.addLayout(stats_layout)
        
        # Action Buttons
        btn_layout = QHBoxLayout()
        self.btn_open_file = QPushButton("Открыть выбранный файл")
        self.btn_open_file.setProperty("class", "btn-secondary")
        self.btn_open_file.clicked.connect(self.open_selected_file)
        
        btn_open_folder = QPushButton("Открыть папку с результатами")
        btn_open_folder.setProperty("class", "btn-secondary")
        btn_open_folder.clicked.connect(self.open_results_folder)
        
        btn_layout.addWidget(self.btn_open_file)
        btn_layout.addWidget(btn_open_folder)
        layout.addLayout(btn_layout)
        
        self.pages.addWidget(page)

    def load_drives(self):
        self.drives = get_drives()
        self.rec_src_combo.clear()
        self.img_src_combo.clear()
        
        for drive in self.drives:
            self.rec_src_combo.addItem(drive['label'], drive['path'])
            self.img_src_combo.addItem(drive['label'], drive['path'])
            
        self.detect_filesystem()

    def toggle_imaging_src_mode(self):
        if self.rbtn_src_disk.isChecked():
            self.img_src_combo.show()
            self.img_src_folder_widget.hide()
        else:
            self.img_src_combo.hide()
            self.img_src_folder_widget.show()

    # --- Real-Time FS Detection ---
    def detect_filesystem(self):
        if self.rec_src_combo.currentIndex() == -1:
            self.lbl_detected_fs.setText("ФС: Не выбрано")
            self.lbl_detected_fs.setStyleSheet("font-weight: bold; color: #7F8C8D; padding: 6px; border: 1px solid #BDC3C7; border-radius: 4px; background-color: #ECF0F1;")
            return
        
        path = self.rec_src_combo.currentData()
        if not path:
            self.lbl_detected_fs.setText("ФС: Неизвестно")
            self.lbl_detected_fs.setStyleSheet("font-weight: bold; color: #7F8C8D; padding: 6px; border: 1px solid #BDC3C7; border-radius: 4px; background-color: #ECF0F1;")
            return
            
        info = analyze_boot_sector(path)
        fs = info.get('fs_type', 'Unknown')
        
        if fs == 'NTFS':
            self.lbl_detected_fs.setText("ФС: NTFS")
            self.lbl_detected_fs.setStyleSheet("font-weight: bold; color: #27AE60; padding: 6px; border: 1px solid #2ECC71; border-radius: 4px; background-color: #E8F8F5;")
        elif fs == 'FAT32':
            self.lbl_detected_fs.setText("ФС: FAT32")
            self.lbl_detected_fs.setStyleSheet("font-weight: bold; color: #2980B9; padding: 6px; border: 1px solid #3498DB; border-radius: 4px; background-color: #EBF5FB;")
        else:
            self.lbl_detected_fs.setText("ФС: Неизвестно")
            self.lbl_detected_fs.setStyleSheet("font-weight: bold; color: #E67E22; padding: 6px; border: 1px solid #F39C12; border-radius: 4px; background-color: #FEF9E7;")

    # --- Button Handlers ---
    
    def browse_rec_image(self):
        file, _ = QFileDialog.getOpenFileName(self, "Выберите файл образа", "", "Images (*.img *.dd *.iso);;All Files (*.*)")
        if file:
            self.rec_src_combo.addItem(f"Образ: {os.path.basename(file)}", file)
            self.rec_src_combo.setCurrentIndex(self.rec_src_combo.count() - 1)

    def browse_rec_out(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку для сохранения")
        if folder:
            self.rec_out_folder = folder
            self.rec_out_lbl.setText(folder)
            self.rec_out_lbl.setStyleSheet("color: #212529;")

    def browse_img_src_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите исходную папку")
        if folder:
            self.img_src_folder = folder
            self.img_src_folder_lbl.setText(folder)
            self.img_src_folder_lbl.setStyleSheet("color: #212529;")

    def browse_img_dest(self):
        file, _ = QFileDialog.getSaveFileName(self, "Сохранить образ", "", "Disk Image (*.img)")
        if file:
            self.img_dest_file = file
            self.img_dest_lbl.setText(file)
            self.img_dest_lbl.setStyleSheet("color: #212529;")

    # --- Recovery Execution ---
    def start_recovery(self):
        if self.rec_src_combo.currentIndex() == -1:
            QMessageBox.warning(self, "Ошибка", "Выберите источник данных.")
            return
            
        if not self.rec_out_folder:
            QMessageBox.warning(self, "Ошибка", "Выберите папку для сохранения.")
            return
            
        file_types = {
            'jpg': self.cb_jpg.isChecked(),
            'png': self.cb_png.isChecked(),
            'pdf': self.cb_pdf.isChecked(),
            'zip': self.cb_zip.isChecked(),
            'docx': self.cb_docx.isChecked()
        }
        
        if not any(file_types.values()):
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы один тип файлов.")
            return

        source_path = self.rec_src_combo.currentData()
        
        self.res_table.setRowCount(0)
        self.rec_progress.setValue(0)
        self.rec_start_time = time.monotonic()
        self.found_files = 0
        self.success_files = 0
        self.lbl_found_count.setText("Найдено файлов: 0")
        self.lbl_success_count.setText("Успешно восстановлено: 0")
        logging.info(f"Начало восстановления. Источник: {source_path}, Папка: {self.rec_out_folder}, Типы: {file_types}")
        
        self.rec_btn_start.setEnabled(False)
        self.rec_btn_start.setText("Восстановление...")
        self.rec_btn_pause.setEnabled(True)
        self.rec_btn_pause.setText("Пауза")
        self.rec_btn_stop.setEnabled(True)
        
        self.set_ui_enabled(False, exceptions=[self.rec_btn_pause, self.rec_btn_stop])
        
        self.signals = WorkerSignals()
        self.signals.progress.connect(self.update_rec_progress)
        self.signals.finished.connect(self.worker_finished)
        self.signals.error.connect(self.worker_error)
        self.signals.file_found.connect(self.on_file_found)
        
        self.active_worker = Carver(
            source_path, self.rec_out_folder, file_types,
            progress_callback=self.signals.progress.emit,
            found_callback=self.signals.file_found.emit,
            finished_callback=self.signals.finished.emit,
            error_callback=self.signals.error.emit
        )
        self.active_worker.start()

    def toggle_pause_recovery(self):
        if self.active_worker and self.active_worker.is_alive():
            if self.rec_btn_pause.text() == "Пауза":
                self.active_worker.pause()
                self.rec_btn_pause.setText("Продолжить")
            else:
                self.active_worker.resume()
                self.rec_btn_pause.setText("Пауза")

    def stop_recovery(self):
        if self.active_worker and self.active_worker.is_alive():
            self.active_worker.stop()
            self.rec_btn_stop.setEnabled(False)
            self.rec_btn_pause.setEnabled(False)

    # --- Imaging Execution ---
    def start_imaging(self):
        if self.rbtn_src_disk.isChecked():
            if self.img_src_combo.currentIndex() == -1:
                QMessageBox.warning(self, "Ошибка", "Выберите исходный диск.")
                return
            source_path = self.img_src_combo.currentData()
        else:
            if not self.img_src_folder:
                QMessageBox.warning(self, "Ошибка", "Выберите исходную папку.")
                return
            source_path = self.img_src_folder
            
        if not self.img_dest_file:
            QMessageBox.warning(self, "Ошибка", "Выберите файл назначения.")
            return

        self.img_progress.setValue(0)
        self.img_start_time = time.monotonic()
        logging.info(f"Начало создания образа. Источник: {source_path}, Назначение: {self.img_dest_file}")
        
        self.img_btn_start.setEnabled(False)
        self.img_btn_start.setText("Создание образа...")
        self.img_btn_stop.setEnabled(True)
        self.set_ui_enabled(False, exceptions=[self.img_btn_stop])

        self.signals = WorkerSignals()
        self.signals.progress.connect(self.update_img_progress)
        self.signals.finished.connect(self.worker_finished)
        self.signals.error.connect(self.worker_error)

        self.active_worker = Imager(
            source_path, self.img_dest_file,
            progress_callback=self.signals.progress.emit,
            finished_callback=self.signals.finished.emit,
            error_callback=self.signals.error.emit
        )
        self.active_worker.start()

    def stop_imaging(self):
        if self.active_worker and self.active_worker.is_alive():
            self.active_worker.stop()
            self.img_btn_stop.setEnabled(False)

    # --- Callbacks ---

    def update_rec_progress(self, current, total):
        if total > 0:
            if current > total:
                current = total
            self.rec_progress.setMaximum(1000)
            pct = int((current / total) * 1000)
            self.rec_progress.setValue(pct)
        else:
            self.rec_progress.setMaximum(0)
            
        elapsed = time.monotonic() - self.rec_start_time
        if elapsed > 0:
            speed_mb = (current / 1024 / 1024) / elapsed
            self.rec_lbl_stats.setText(f"Скорость: {speed_mb:.2f} МБ/с | Прошло: {int(elapsed)} с")

    def update_img_progress(self, current, total):
        if total > 0:
            if current > total:
                current = total
            self.img_progress.setMaximum(1000)
            pct = int((current / total) * 1000)
            self.img_progress.setValue(pct)
        else:
            self.img_progress.setMaximum(0)
            
        elapsed = time.monotonic() - self.img_start_time
        if elapsed > 0:
            speed_mb = (current / 1024 / 1024) / elapsed
            self.img_lbl_stats.setText(f"Скорость: {speed_mb:.2f} МБ/с | Прошло: {int(elapsed)} с")

    def on_file_found(self, path, ext, size, offset, status):
        row = self.res_table.rowCount()
        self.res_table.insertRow(row)
        
        item_path = QTableWidgetItem(os.path.basename(path))
        item_path.setData(Qt.ItemDataRole.UserRole, path)
        
        self.res_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.res_table.setItem(row, 1, item_path)
        self.res_table.setItem(row, 2, QTableWidgetItem(ext.upper()))
        self.res_table.setItem(row, 3, QTableWidgetItem(str(size)))
        self.res_table.setItem(row, 4, QTableWidgetItem(str(offset)))
        self.res_table.setItem(row, 5, QTableWidgetItem(status))
        
        self.found_files += 1
        if status == "Успешно":
            self.success_files += 1
            
        self.lbl_found_count.setText(f"Найдено файлов: {self.found_files}")
        self.lbl_success_count.setText(f"Успешно восстановлено: {self.success_files}")
        logging.info(f"Найден файл: {path}, Смещение: {offset}, Статус: {status}")

    def worker_finished(self):
        self.reset_ui()
        QMessageBox.information(self, "Готово", "Операция успешно завершена!")
        logging.info("Операция успешно завершена!")

    def worker_error(self, msg):
        self.reset_ui()
        QMessageBox.critical(self, "Ошибка", msg)
        logging.error(msg)

    def reset_ui(self):
        self.active_worker = None
        
        self.rec_btn_start.setText("Старт восстановления")
        self.rec_btn_start.setEnabled(True)
        self.rec_btn_pause.setText("Пауза")
        self.rec_btn_pause.setEnabled(False)
        self.rec_btn_stop.setEnabled(False)
        
        self.img_btn_start.setText("Создать образ")
        self.img_btn_start.setEnabled(True)
        self.img_btn_stop.setEnabled(False)
        
        self.set_ui_enabled(True)
        self.rec_progress.setMaximum(1000)
        self.rec_progress.setValue(0)
        self.img_progress.setMaximum(1000)
        self.img_progress.setValue(0)

    def set_ui_enabled(self, enabled, exceptions=None):
        if exceptions is None:
            exceptions = []
        
        widgets = [self.rec_src_combo, self.rec_btn_image, self.rec_btn_out, 
                   self.cb_jpg, self.cb_png, self.cb_pdf, self.cb_zip, self.cb_docx,
                   self.rbtn_src_disk, self.rbtn_src_folder, self.img_src_combo, 
                   self.img_btn_src_folder, self.img_btn_dest,
                   self.btn_nav_rec, self.btn_nav_img, self.btn_nav_res]
        
        for w in widgets:
            if w not in exceptions:
                w.setEnabled(enabled)
    def open_path_cross_platform(self, path):
        import subprocess
        try:
            if sys.platform == 'win32':
                os.startfile(path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть: {e}")

    def open_selected_file(self):
        selected = self.res_table.selectedItems()
        if not selected:
            return
        path = self.res_table.item(selected[0].row(), 1).data(Qt.ItemDataRole.UserRole)
        if os.path.exists(path):
            self.open_path_cross_platform(path)

    def open_results_folder(self):
        if self.rec_out_folder and os.path.exists(self.rec_out_folder):
            self.open_path_cross_platform(self.rec_out_folder)

    def clear_results(self):
        self.res_table.setRowCount(0)
        self.found_files = 0
        self.success_files = 0
        self.lbl_found_count.setText("Найдено файлов: 0")
        self.lbl_success_count.setText("Успешно восстановлено: 0")
        
    def closeEvent(self, event):
        logging.info("Программа закрыта.")
        super().closeEvent(event)

    # --- QSS Style Application ---
    def apply_styles(self):
        qss = """
        QMainWindow {
            background-color: #F8F9FA;
        }

        #sidebar {
            background-color: #FFFFFF;
            border-right: 1px solid #E5E5E7;
            min-width: 220px;
            max-width: 220px;
        }

        #logo_label {
            font-size: 28px;
            font-weight: 900;
            color: #ffffff;
            background-color: #800020;
            padding: 20px 10px;
            border-bottom: 2px solid #5c0017;
            margin-bottom: 15px;
            border-radius: 8px;
            margin-left: 10px;
            margin-right: 10px;
            margin-top: 10px;
        }

        QPushButton.sidebar-btn {
            text-align: left;
            padding: 14px 20px;
            font-size: 14px;
            font-weight: bold;
            color: #555555;
            background-color: transparent;
            border: none;
            border-left: 4px solid transparent;
        }

        QPushButton.sidebar-btn:hover {
            background-color: #FDF4F5;
            color: #800020;
        }

        QPushButton.sidebar-btn:checked {
            background-color: #F5E6E8;
            color: #800020;
            border-left: 4px solid #800020;
        }

        .page-container {
            background-color: #F8F9FA;
        }

        QGroupBox {
            font-size: 14px;
            font-weight: bold;
            color: #800020;
            border: 1px solid #E5E5E7;
            border-radius: 8px;
            margin-top: 15px;
            padding-top: 20px;
            background-color: #FFFFFF;
        }

        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 15px;
            padding: 0 5px;
            background-color: #FFFFFF;
        }

        QComboBox {
            background-color: #FFFFFF;
            border: 1px solid #D0D0D5;
            border-radius: 6px;
            padding: 8px 12px;
            min-height: 20px;
            font-size: 13px;
            color: #212529;
        }

        QComboBox:hover {
            border: 1px solid #800020;
        }

        QComboBox::drop-down {
            border: none;
        }

        QRadioButton {
            font-size: 13px;
            color: #212529;
            spacing: 8px;
        }

        QCheckBox {
            font-size: 13px;
            color: #212529;
            spacing: 8px;
        }

        QPushButton.btn-primary {
            background-color: #800020;
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 10px 20px;
            font-size: 13px;
            font-weight: bold;
            min-height: 22px;
        }

        QPushButton.btn-primary:hover {
            background-color: #990026;
        }

        QPushButton.btn-primary:pressed {
            background-color: #66001A;
        }

        QPushButton.btn-primary:disabled {
            background-color: #CCCCCC;
            color: #888888;
        }

        QPushButton.btn-secondary {
            background-color: #FFFFFF;
            color: #800020;
            border: 1px solid #800020;
            border-radius: 6px;
            padding: 9px 20px;
            font-size: 13px;
            font-weight: bold;
            min-height: 22px;
        }

        QPushButton.btn-secondary:hover {
            background-color: #FDF4F5;
        }

        QPushButton.btn-secondary:pressed {
            background-color: #F5E6E8;
        }
        
        QPushButton.btn-secondary:disabled {
            border: 1px solid #CCCCCC;
            color: #888888;
        }

        QTableWidget {
            background-color: #FFFFFF;
            border: 1px solid #E5E5E7;
            border-radius: 6px;
            font-size: 13px;
            gridline-color: #F0F0F0;
        }

        QHeaderView::section {
            background-color: #F8F9FA;
            padding: 6px;
            border: none;
            border-bottom: 1px solid #E5E5E7;
            border-right: 1px solid #E5E5E7;
            text-align: center;
            color: #212529;
            font-weight: bold;
        }

        QProgressBar {
            border: 1px solid #E5E5E7;
            border-radius: 6px;
            background-color: #F0F0F0;
            text-align: center;
            font-weight: bold;
            color: #212529;
            height: 20px;
        }

        QProgressBar::chunk {
            background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #800020, stop:1 #A31D38);
            border-radius: 5px;
        }

        QTextEdit {
            background-color: #FFFFFF;
            border: 1px solid #E5E5E7;
            border-radius: 6px;
            font-family: Consolas, monospace;
            font-size: 12px;
            color: #212529;
        }
        """
        self.setStyleSheet(qss)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
