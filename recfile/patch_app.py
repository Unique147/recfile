import sys
import re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Imports & Logging
if 'import logging' not in content:
    content = content.replace('import sys\nimport os', 'import sys\nimport os\nimport time\nimport logging\n\nlogging.basicConfig(filename="recfile.log", level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", encoding="utf-8")\n')

content = content.replace('get_physical_drives,', 'get_drives,')
content = content.replace('self.drives = get_physical_drives()', 'self.drives = get_drives()')

# 2. WorkerSignals
content = content.replace(
    'file_found = pyqtSignal(str, str, int) # path, type, size',
    'file_found = pyqtSignal(str, str, int, int, str) # path, type, size, offset, status'
)

# 3. MainWindow.__init__
if 'self.rec_start_time = 0' not in content:
    content = content.replace(
        'self.img_dest_file = None\n',
        'self.img_dest_file = None\n        self.rec_start_time = 0\n        self.img_start_time = 0\n        self.found_files = 0\n        self.success_files = 0\n        logging.info("Программа запущена.")\n'
    )

# 4. setup_recovery_page
content = content.replace('self.cb_zip = QCheckBox("ZIP/DOCX/XLSX (.zip)")', 'self.cb_zip = QCheckBox("ZIP (.zip)")\n        self.cb_docx = QCheckBox("DOCX (.docx)")')
content = content.replace('self.cb_zip.setChecked(True)', 'self.cb_zip.setChecked(True)\n        self.cb_docx.setChecked(True)')
content = content.replace('types_layout.addWidget(self.cb_zip, 1, 1)', 'types_layout.addWidget(self.cb_zip, 1, 1)\n        types_layout.addWidget(self.cb_docx, 2, 0)')

if 'self.rec_lbl_stats' not in content:
    content = content.replace(
        'self.rec_progress.setValue(0)\n        layout.addWidget(self.rec_progress)',
        'self.rec_progress.setValue(0)\n        self.rec_lbl_stats = QLabel("Скорость: 0 МБ/с | Прошло: 0 с")\n        self.rec_lbl_stats.setStyleSheet("color: #7F8C8D; font-size: 12px;")\n        layout.addWidget(self.rec_progress)\n        layout.addWidget(self.rec_lbl_stats)'
    )

# 5. setup_imaging_page
if 'self.img_lbl_stats' not in content:
    content = content.replace(
        'self.img_progress.setValue(0)\n        layout.addWidget(self.img_progress)',
        'self.img_progress.setValue(0)\n        self.img_lbl_stats = QLabel("Скорость: 0 МБ/с | Прошло: 0 с")\n        self.img_lbl_stats.setStyleSheet("color: #7F8C8D; font-size: 12px;")\n        layout.addWidget(self.img_progress)\n        layout.addWidget(self.img_lbl_stats)'
    )

# 6. setup_results_page
content = content.replace('self.res_table.setColumnCount(3)', 'self.res_table.setColumnCount(6)')
content = content.replace('self.res_table.setHorizontalHeaderLabels(["Имя файла", "Тип", "Размер (Байт)"])', 'self.res_table.setHorizontalHeaderLabels(["№", "Имя файла", "Тип", "Размер (Байт)", "Смещение", "Статус"])')
content = content.replace('self.res_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)', 'self.res_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)')

if 'self.lbl_found_count' not in content:
    content = content.replace(
        'layout.addWidget(splitter)',
        'layout.addWidget(splitter)\n        \n        stats_layout = QHBoxLayout()\n        self.lbl_found_count = QLabel("Найдено файлов: 0")\n        self.lbl_success_count = QLabel("Успешно восстановлено: 0")\n        self.btn_clear_res = QPushButton("Очистить результаты")\n        self.btn_clear_res.setProperty("class", "btn-secondary")\n        self.btn_clear_res.clicked.connect(self.clear_results)\n        stats_layout.addWidget(self.lbl_found_count)\n        stats_layout.addWidget(self.lbl_success_count)\n        stats_layout.addStretch()\n        stats_layout.addWidget(self.btn_clear_res)\n        layout.addLayout(stats_layout)'
    )

# 7. start_recovery
content = content.replace("'zip': self.cb_zip.isChecked()", "'zip': self.cb_zip.isChecked(),\n            'docx': self.cb_docx.isChecked()")
if 'self.rec_start_time = time.time()' not in content:
    content = content.replace(
        'self.rec_progress.setValue(0)',
        'self.rec_progress.setValue(0)\n        self.rec_start_time = time.time()\n        self.found_files = 0\n        self.success_files = 0\n        self.lbl_found_count.setText("Найдено файлов: 0")\n        self.lbl_success_count.setText("Успешно восстановлено: 0")\n        logging.info(f"Начало восстановления. Источник: {source_path}, Папка: {self.rec_out_folder}, Типы: {file_types}")'
    )

# 8. start_imaging
if 'self.img_start_time = time.time()' not in content:
    content = content.replace(
        'self.img_progress.setValue(0)',
        'self.img_progress.setValue(0)\n        self.img_start_time = time.time()\n        logging.info(f"Начало создания образа. Источник: {source_path}, Назначение: {self.img_dest_file}")'
    )

# 9. update_rec_progress & update_img_progress
if 'speed_mb =' not in content:
    content = content.replace(
        'self.rec_progress.setMaximum(0)',
        'self.rec_progress.setMaximum(0)\n            \n        elapsed = time.time() - self.rec_start_time\n        if elapsed > 0:\n            speed_mb = (current / 1024 / 1024) / elapsed\n            self.rec_lbl_stats.setText(f"Скорость: {speed_mb:.2f} МБ/с | Прошло: {int(elapsed)} с")'
    )
    content = content.replace(
        'self.img_progress.setMaximum(0)',
        'self.img_progress.setMaximum(0)\n            \n        elapsed = time.time() - self.img_start_time\n        if elapsed > 0:\n            speed_mb = (current / 1024 / 1024) / elapsed\n            self.img_lbl_stats.setText(f"Скорость: {speed_mb:.2f} МБ/с | Прошло: {int(elapsed)} с")'
    )

# 10. on_file_found
content = content.replace('def on_file_found(self, path, ext, size):', 'def on_file_found(self, path, ext, size, offset, status):')
if 'self.found_files += 1' not in content:
    content = content.replace(
        '''        self.res_table.setItem(row, 0, item_path)
        self.res_table.setItem(row, 1, QTableWidgetItem(ext.upper()))
        self.res_table.setItem(row, 2, QTableWidgetItem(str(size)))''',
        '''        self.res_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
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
        logging.info(f"Найден файл: {path}, Смещение: {offset}, Статус: {status}")'''
    )

# 11. worker_finished / error
if 'logging.info("Операция успешно завершена!")' not in content:
    content = content.replace(
        'QMessageBox.information(self, "Готово", "Операция успешно завершена!")',
        'QMessageBox.information(self, "Готово", "Операция успешно завершена!")\n        logging.info("Операция успешно завершена!")'
    )
if 'logging.error(msg)' not in content:
    content = content.replace(
        'QMessageBox.critical(self, "Ошибка", msg)',
        'QMessageBox.critical(self, "Ошибка", msg)\n        logging.error(msg)'
    )

# 12. clear_results & closeEvent
if 'def clear_results(self):' not in content:
    content += '''

    def clear_results(self):
        self.res_table.setRowCount(0)
        self.found_files = 0
        self.success_files = 0
        self.lbl_found_count.setText("Найдено файлов: 0")
        self.lbl_success_count.setText("Успешно восстановлено: 0")
        self.preview_text.hide()
        self.preview_lbl.show()
        self.preview_lbl.setText("Выберите файл слева")
        
    def closeEvent(self, event):
        logging.info("Программа закрыта.")
        super().closeEvent(event)
'''

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Patch applied to app.py")
