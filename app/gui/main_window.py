from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThreadPool, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QPlainTextEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app import __version__
from app.audio.artwork import find_cover_image, load_cover_image
from app.audio.scanner import inspect_audio, scan_folder
from app.audio.tags import TagOptions, TagService
from app.matching import match_tracks
from app.models import AlbumMetadata, MatchStatus, TrackMatch
from app.providers.html_parser import CasaMusicaHtmlParser
from app.providers.playwright_provider import PlaywrightCasaMusicaProvider
from app.services.album_io import (
    export_album_csv, load_album_json, save_album_json, update_album_details,
)
from app.services.backup import BackupService
from app.services.local_editing import build_local_editing_session
from app.services.rename_templates import (
    DEFAULT_TEMPLATE_NAME, dump_template_mapping, load_template_mapping,
)
from app.services.renaming import (
    DEFAULT_FOLDER_TEMPLATE, DEFAULT_RENAME_TEMPLATE,
    album_folder_target, build_audio_filename, rename_album_folder,
    rename_audio_file,
)
from app.services.tagging import build_change_plan
from app.services.updater import (
    can_install_automatically, discard_prepared_update, fetch_latest_release,
    is_newer_version, launch_prepared_update, prepare_update,
)
from app.gui.worker import Worker
from app.utils.text import split_title_dance_suffix
from app.utils.drop import classify_dropped_paths


HEADERS = [
    "Обрабатывать", "Статус", "Диск", "Трек", "Локальный файл",
    "Текущий Artist", "Новый Artist", "Текущий Title", "Новый Title",
    "Language", "Dance Style", "Dance Tempo", "Длительность файла",
    "Длительность сайта", "Разница", "Примечание",
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TagStiller — теги Casa Musica")
        self.resize(1500, 850)
        self.setAcceptDrops(True)
        self.album: AlbumMetadata | None = None
        self.files = []
        self.cover_file: Path | None = None
        self.matches: list[TrackMatch] = []
        self.pool = QThreadPool.globalInstance()
        self.settings = QSettings("TagStiller", "TagStiller")
        self.tags = TagService()
        self.backups = BackupService(self.tags)
        self._build_ui()

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)

        source_box = QGroupBox("1. Данные альбома")
        source_layout = QGridLayout(source_box)
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://casa-musica.com/…")
        load_url = QPushButton("Загрузить данные")
        load_url.clicked.connect(self.load_url)
        load_html = QPushButton("Открыть HTML")
        load_html.clicked.connect(self.load_html)
        load_json = QPushButton("Открыть JSON")
        load_json.clicked.connect(self.load_json)
        install_browser = QPushButton("Установить Chromium")
        install_browser.clicked.connect(self.install_browser)
        source_layout.addWidget(QLabel("URL Casa Musica:"), 0, 0)
        source_layout.addWidget(self.url, 0, 1)
        source_layout.addWidget(load_url, 0, 2)
        source_layout.addWidget(load_html, 0, 3)
        source_layout.addWidget(load_json, 0, 4)
        source_layout.addWidget(install_browser, 0, 5)
        self.album_title = QLineEdit()
        self.album_title.setPlaceholderText("Будет получено со страницы; при необходимости можно исправить")
        source_layout.addWidget(QLabel("Название альбома:"), 1, 0)
        source_layout.addWidget(self.album_title, 1, 1, 1, 5)
        self.album_artist = QLineEdit()
        self.album_year = QLineEdit()
        self.album_year.setMaximumWidth(100)
        self.album_label = QLineEdit()
        source_layout.addWidget(QLabel("Album Artist:"), 2, 0)
        source_layout.addWidget(self.album_artist, 2, 1, 1, 2)
        source_layout.addWidget(QLabel("Год:"), 2, 3)
        source_layout.addWidget(self.album_year, 2, 4)
        source_layout.addWidget(QLabel("Album Label:"), 3, 0)
        source_layout.addWidget(self.album_label, 3, 1, 1, 5)
        layout.addWidget(source_box)

        drop_hint = QLabel(
            "Можно перетащить сюда сохранённый HTML и/или папку с аудиофайлами"
        )
        drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_hint.setStyleSheet(
            "padding: 7px; border: 1px dashed #888; border-radius: 5px;"
        )
        layout.addWidget(drop_hint)

        folder_box = QGroupBox("2. Локальные аудиофайлы")
        folder_layout = QHBoxLayout(folder_box)
        self.folder = QLineEdit()
        choose = QPushButton("Выбрать папку")
        choose.clicked.connect(self.choose_folder)
        scan = QPushButton("Сканировать папку")
        scan.clicked.connect(self.scan)
        local_edit = QPushButton("Редактировать без HTML")
        local_edit.clicked.connect(self.edit_local)
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setRange(0, 60)
        self.tolerance.setValue(4)
        self.tolerance.setSuffix(" с")
        self.write_cover = QCheckBox("Записывать cover")
        self.write_cover.setChecked(True)
        self.cover_label = QLabel("Обложка: не найдена")
        folder_layout.addWidget(self.folder, 1)
        folder_layout.addWidget(choose)
        folder_layout.addWidget(scan)
        folder_layout.addWidget(local_edit)
        folder_layout.addWidget(QLabel("Допуск длительности:"))
        folder_layout.addWidget(self.tolerance)
        folder_layout.addWidget(self.write_cover)
        folder_layout.addWidget(self.cover_label)
        layout.addWidget(folder_box)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(15, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self.change_file)
        layout.addWidget(self.table, 1)

        settings = QGroupBox("3. Какие теги обновлять")
        settings_layout = QHBoxLayout(settings)
        labels = {
            "track_number": "Track", "disc_number": "Disc", "artist": "Artist",
            "title": "Title", "album": "Album", "album_artist": "Album Artist",
            "album_label": "Album Label",
            "language": "Language", "dance_style": "DANCE_STYLE",
            "dance_tempo": "DANCE_TEMPO", "year": "Year",
        }
        self.field_checks: dict[str, QCheckBox] = {}
        for field, label in labels.items():
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            self.field_checks[field] = checkbox
            settings_layout.addWidget(checkbox)
        self.genre = QCheckBox("Style → GENRE")
        self.overwrite_empty = QCheckBox("Перезаписывать пустыми")
        self.full_backup = QCheckBox("Копии аудиофайлов")
        settings_layout.addWidget(self.genre)
        settings_layout.addWidget(self.overwrite_empty)
        settings_layout.addWidget(self.full_backup)
        layout.addWidget(settings)

        rename_box = QGroupBox("4. Переименование файлов и папки")
        rename_layout = QHBoxLayout(rename_box)
        self.rename_files = QCheckBox("Переименовывать после записи тегов")
        last_template = str(
            self.settings.value("rename/last_template", DEFAULT_RENAME_TEMPLATE)
        )
        self.rename_template = QLineEdit(last_template or DEFAULT_RENAME_TEMPLATE)
        self.rename_template.textEdited.connect(self._rename_template_edited)
        self.rename_template.editingFinished.connect(self._persist_last_template)
        self.rename_template.setToolTip(
            "Доступно: {disc}, {disc_prefix}, {track}, {artist}, {title}, {album}, {year}"
        )
        self.rename_presets = QComboBox()
        self.rename_presets.setMinimumWidth(140)
        self._reload_rename_presets()
        self.rename_presets.currentTextChanged.connect(self._apply_rename_preset)
        save_template = QPushButton("Сохранить шаблон")
        save_template.clicked.connect(self.save_rename_template)
        delete_template = QPushButton("Удалить шаблон")
        delete_template.clicked.connect(self.delete_rename_template)
        rename_layout.addWidget(self.rename_files)
        rename_layout.addWidget(QLabel("Пресет:"))
        rename_layout.addWidget(self.rename_presets)
        rename_layout.addWidget(QLabel("Шаблон:"))
        rename_layout.addWidget(self.rename_template, 1)
        rename_layout.addWidget(save_template)
        rename_layout.addWidget(delete_template)
        self.rename_folder = QCheckBox("Переименовать папку после записи тегов")
        self.folder_template = QLineEdit(DEFAULT_FOLDER_TEMPLATE)
        self.folder_template.textEdited.connect(
            lambda _text: self.rename_folder.setChecked(True)
        )
        self.folder_template.setToolTip(
            "Доступно: {album}, {year}, {label}, {album_artist}"
        )
        rename_layout.addWidget(self.rename_folder)
        rename_layout.addWidget(QLabel("Шаблон папки:"))
        rename_layout.addWidget(self.folder_template, 1)
        layout.addWidget(rename_box)

        actions = QHBoxLayout()
        for label, handler in (
            ("Очистить всё", self.reset_all),
            ("Сохранить JSON", self.save_json), ("Экспорт CSV", self.save_csv),
            ("Восстановить из backup", self.restore), ("Записать теги", self.write_tags),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(QLabel(f"Версия {__version__}"))
        self.update_button = QPushButton("Проверить обновления")
        self.update_button.clicked.connect(self.check_for_updates)
        actions.addWidget(self.update_button)
        layout.addLayout(actions)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        self.log.setPlaceholderText("Здесь появится журнал выполнения.")
        layout.addWidget(self.log)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Режим preview: файлы не изменяются")

    def _rename_template_edited(self, _text: str):
        self.rename_files.setChecked(True)
        self.statusBar().showMessage(
            "Переименование включено: новый шаблон применится даже без изменений тегов"
        )

    def _template_mapping(self) -> dict[str, str]:
        raw = self.settings.value("rename/templates", "")
        return load_template_mapping(str(raw) if raw else "")

    def _reload_rename_presets(self, selected_name: str | None = None):
        templates = self._template_mapping()
        self.rename_presets.blockSignals(True)
        self.rename_presets.clear()
        names = [DEFAULT_TEMPLATE_NAME] + sorted(
            name for name in templates if name != DEFAULT_TEMPLATE_NAME
        )
        for name in names:
            self.rename_presets.addItem(name, templates[name])
        if selected_name in names:
            self.rename_presets.setCurrentText(selected_name)
        self.rename_presets.blockSignals(False)

    def _apply_rename_preset(self, _name: str):
        template = self.rename_presets.currentData()
        if template:
            self.rename_template.setText(str(template))
            self.rename_files.setChecked(True)
            self._persist_last_template()

    def _persist_last_template(self):
        template = self.rename_template.text().strip() or DEFAULT_RENAME_TEMPLATE
        self.settings.setValue("rename/last_template", template)

    def save_rename_template(self):
        template = self.rename_template.text().strip()
        if not template:
            QMessageBox.warning(self, "Пустой шаблон", "Введите шаблон переименования.")
            return
        name, accepted = QInputDialog.getText(
            self, "Сохранить шаблон", "Название шаблона:",
        )
        name = name.strip()
        if not accepted or not name:
            return
        if name == DEFAULT_TEMPLATE_NAME:
            QMessageBox.warning(
                self, "Зарезервированное имя",
                f"Название «{DEFAULT_TEMPLATE_NAME}» нельзя заменить.",
            )
            return
        templates = self._template_mapping()
        if name in templates and QMessageBox.question(
            self, "Заменить шаблон",
            f"Шаблон «{name}» уже существует. Заменить его?",
        ) != QMessageBox.StandardButton.Yes:
            return
        templates[name] = template
        self.settings.setValue(
            "rename/templates", dump_template_mapping(templates),
        )
        self._persist_last_template()
        self._reload_rename_presets(name)
        self.append_log(f"Шаблон переименования сохранён: {name}.")

    def delete_rename_template(self):
        name = self.rename_presets.currentText()
        if not name or name == DEFAULT_TEMPLATE_NAME:
            QMessageBox.information(
                self, "Шаблон по умолчанию",
                "Шаблон по умолчанию удалить нельзя.",
            )
            return
        if QMessageBox.question(
            self, "Удалить шаблон", f"Удалить сохранённый шаблон «{name}»?",
        ) != QMessageBox.StandardButton.Yes:
            return
        templates = self._template_mapping()
        templates.pop(name, None)
        self.settings.setValue(
            "rename/templates", dump_template_mapping(templates),
        )
        self._reload_rename_presets(DEFAULT_TEMPLATE_NAME)
        self.append_log(f"Шаблон переименования удалён: {name}.")

    def reset_all(self):
        if QMessageBox.question(
            self, "Очистить всё",
            "Очистить загруженный альбом, папку, таблицу, журнал и настройки тегов?\n\n"
            "Текущий шаблон переименования и сохранённые пресеты останутся.",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._reset_application_state()

    def _reset_application_state(self):
        preserved_template = (
            self.rename_template.text().strip() or DEFAULT_RENAME_TEMPLATE
        )
        self.album = None
        self.files = []
        self.matches = []
        self.cover_file = None
        self.url.clear()
        self.folder.clear()
        self.album_title.clear()
        self.album_artist.clear()
        self.album_year.clear()
        self.album_label.clear()
        self.table.setRowCount(0)
        self.log.clear()
        self.cover_label.setText("Обложка: не найдена")
        self.tolerance.setValue(4)
        for checkbox in self.field_checks.values():
            checkbox.setChecked(True)
        self.genre.setChecked(False)
        self.overwrite_empty.setChecked(False)
        self.full_backup.setChecked(False)
        self.write_cover.setChecked(True)
        self.rename_files.setChecked(False)
        self.rename_folder.setChecked(False)
        self.folder_template.setText(DEFAULT_FOLDER_TEMPLATE)
        self.rename_template.setText(preserved_template)
        self.settings.setValue("rename/last_template", preserved_template)
        self.statusBar().showMessage("Режим preview: файлы не изменяются")

    def append_log(self, message: str):
        self.log.appendPlainText(message)
        logging.info(message)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [
                Path(url.toLocalFile())
                for url in event.mimeData().urls()
                if url.isLocalFile()
            ]
            try:
                classify_dropped_paths(paths)
            except ValueError:
                event.ignore()
            else:
                event.acceptProposedAction()
                self.statusBar().showMessage(
                    "Отпустите файл или папку для загрузки"
                )
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.statusBar().showMessage("Готово")
        event.accept()

    def dropEvent(self, event):
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        try:
            html_file, folder = classify_dropped_paths(paths)
        except ValueError as exc:
            QMessageBox.warning(self, "Не удалось обработать", str(exc))
            event.ignore()
            return
        event.acceptProposedAction()
        self._handle_dropped_paths(html_file, folder)

    def _handle_dropped_paths(
        self,
        html_file: Path | None,
        folder: Path | None,
    ):
        if folder:
            self.folder.setText(str(folder))
        if html_file and folder:
            self._load_html_path(html_file, after_load=self.scan)
        elif html_file:
            self._load_html_path(html_file)
        elif folder:
            if self.album:
                self.scan()
            else:
                self.edit_local()

    def run_worker(self, function, on_result, busy_text: str):
        self.statusBar().showMessage(busy_text)
        worker = Worker(function)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(self.worker_error)
        worker.signals.finished.connect(lambda: self.statusBar().showMessage("Готово"))
        self.pool.start(worker)
        return worker

    def worker_error(self, message: str, details: str):
        self.append_log(f"Ошибка: {message}")
        QMessageBox.critical(self, "Ошибка", message or "Операция не выполнена. Подробности записаны в лог.")

    def check_for_updates(self):
        self.update_button.setEnabled(False)
        worker = self.run_worker(
            fetch_latest_release,
            self._update_checked,
            "Проверка обновлений…",
        )
        worker.signals.finished.connect(
            lambda: self.update_button.setEnabled(True)
        )

    def _update_checked(self, release):
        if not is_newer_version(release.version, __version__):
            QMessageBox.information(
                self,
                "Обновления",
                f"Установлена актуальная версия TagStiller {__version__}.",
            )
            return

        if not can_install_automatically():
            answer = QMessageBox.question(
                self,
                "Доступно обновление",
                f"Доступна версия {release.version}.\n\n"
                "Автоматическая установка работает в собранной Windows-версии. "
                "Открыть страницу загрузки?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(release.page_url))
            return

        answer = QMessageBox.question(
            self,
            "Доступно обновление",
            f"Доступна версия {release.version} (сейчас {__version__}).\n\n"
            "Скачать, установить и перезапустить приложение?\n"
            "Несохранённые изменения в окне будут потеряны.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.update_button.setEnabled(False)
        worker = self.run_worker(
            lambda: prepare_update(release),
            self._install_prepared_update,
            "Загрузка и проверка обновления…",
        )
        worker.signals.finished.connect(
            lambda: self.update_button.setEnabled(True)
        )

    def _install_prepared_update(self, update):
        try:
            launch_prepared_update(update)
        except Exception as exc:
            discard_prepared_update(update)
            QMessageBox.critical(
                self,
                "Ошибка обновления",
                f"Не удалось запустить установку: {exc}",
            )
            return
        self.append_log(
            f"Обновление {update.version} подготовлено. Перезапуск приложения…"
        )
        QApplication.instance().quit()

    def load_url(self):
        url = self.url.text().strip()
        if not url:
            QMessageBox.warning(self, "Нет URL", "Вставьте ссылку на альбом Casa Musica.")
            return
        self.run_worker(
            lambda: PlaywrightCasaMusicaProvider().fetch_album(url),
            self.album_loaded, "Загрузка страницы…",
        )

    def load_html(self):
        path, _ = QFileDialog.getOpenFileName(self, "Открыть сохранённую страницу", "", "HTML (*.html *.htm)")
        if path:
            self._load_html_path(Path(path))

    def _load_html_path(self, path: Path, after_load=None):
        def loaded(album):
            self.album_loaded(album)
            if after_load:
                after_load()

        self.run_worker(
            lambda: CasaMusicaHtmlParser().fetch_album(str(path)),
            loaded, "Обработка HTML…",
        )

    def load_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "Открыть результаты", "", "JSON (*.json)")
        if path:
            try:
                self.album_loaded(load_album_json(path))
            except Exception as exc:
                self.worker_error(f"Не удалось загрузить JSON: {exc}", "")

    def album_loaded(self, album: AlbumMetadata):
        for track in album.tracks:
            clean_title, dance_style, dance_tempo = split_title_dance_suffix(track.title)
            track.title = clean_title
            track.dance_style = track.dance_style or dance_style
            track.dance_tempo = track.dance_tempo or dance_tempo
        self.album = album
        self.url.setText(album.source_url)
        self._show_album_metadata(album)
        self.append_log(f"Загружен альбом «{album.title}»: {len(album.tracks)} треков.")
        self.rematch()

    def _show_album_metadata(self, album: AlbumMetadata):
        self.album_title.setText(album.title)
        self.album_artist.setText(album.album_artist)
        self.album_year.setText(album.year)
        self.album_label.setText(album.album_label)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Папка с аудиофайлами")
        if folder:
            self.folder.setText(folder)

    def scan(self):
        folder = self.folder.text().strip()
        if not folder:
            QMessageBox.warning(self, "Нет папки", "Сначала выберите папку с аудиофайлами.")
            return
        self.run_worker(
            lambda: (scan_folder(folder), find_cover_image(folder)),
            self.files_loaded, "Сканирование аудиофайлов…",
        )

    def edit_local(self):
        folder = self.folder.text().strip()
        if not folder:
            QMessageBox.warning(
                self, "Нет папки", "Сначала выберите папку с аудиофайлами.",
            )
            return

        def operation():
            files = scan_folder(folder)
            album, matches = build_local_editing_session(files, self.tags)
            cover = find_cover_image(folder)
            return album, files, matches, cover

        self.run_worker(
            operation, self.local_session_loaded,
            "Чтение существующих тегов…",
        )

    def local_session_loaded(self, result):
        album, files, matches, cover_file = result
        if not files:
            QMessageBox.information(
                self, "Нет файлов", "В выбранной папке не найдено поддерживаемых аудиофайлов.",
            )
            return
        self.album = album
        self.files = files
        self.matches = matches
        self.cover_file = cover_file
        self.url.clear()
        self._show_album_metadata(album)
        self.cover_label.setText(
            f"Обложка: {cover_file.name}" if cover_file else "Обложка: не найдена"
        )
        self.append_log(
            f"Локальный режим: загружено файлов {len(files)}. "
            "Проверьте жёлтые строки и общие поля альбома."
        )
        self.fill_table()

    def files_loaded(self, result):
        files, cover_file = result
        self.files = files
        self.cover_file = cover_file
        self.append_log(f"В папке найдено аудиофайлов: {len(files)}.")
        if cover_file:
            self.cover_label.setText(f"Обложка: {cover_file.name}")
            self.append_log(f"Найдена обложка: {cover_file.name}.")
        else:
            self.cover_label.setText("Обложка: не найдена")
        if self.album and len(files) != len(self.album.tracks):
            self.append_log(
                f"Внимание: в папке найдено {len(files)} файлов, а на странице — {len(self.album.tracks)} треков."
            )
        self.rematch()

    def rematch(self):
        if not self.album:
            return
        self.matches = match_tracks(self.album, self.files, self.tolerance.value())
        self.fill_table()

    @staticmethod
    def _seconds(value):
        if value is None:
            return ""
        minutes, seconds = divmod(round(value), 60)
        return f"{minutes}:{seconds:02d}"

    def fill_table(self):
        self.table.setRowCount(len(self.matches))
        colors = {
            MatchStatus.GREEN: QColor("#c8f7cf"),
            MatchStatus.YELLOW: QColor("#fff3b0"),
            MatchStatus.RED: QColor("#ffc9c9"),
        }
        status_labels = {
            MatchStatus.GREEN: "Надёжно",
            MatchStatus.YELLOW: "Проверить",
            MatchStatus.RED: "Конфликт",
        }
        for row, match in enumerate(self.matches):
            local = match.local_file
            values = [
                "", status_labels[match.status], match.track.disc_number or "",
                match.track.track_number, local.path.name if local else "",
                local.artist if local else "", match.track.artist,
                local.title if local else "", match.track.title,
                match.track.language, match.track.dance_style, match.track.dance_tempo,
                self._seconds(local.duration_seconds if local else None),
                self._seconds(match.track.duration_seconds),
                f"{match.duration_difference:.1f}" if match.duration_difference is not None else "",
                match.note,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if match.enabled and local else Qt.CheckState.Unchecked)
                elif column not in {2, 3, 4, 6, 8, 9, 10, 11}:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setBackground(colors[match.status])
                self.table.setItem(row, column, item)

    def change_file(self, row: int, column: int):
        if column != 4 or row >= len(self.matches):
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл для трека",
            self.folder.text(), "Аудио (*.mp3 *.flac *.m4a *.mp4 *.ogg *.opus)",
        )
        if path:
            local = inspect_audio(Path(path))
            match = self.matches[row]
            match.local_file = local
            match.status = MatchStatus.YELLOW
            match.note = "Файл выбран вручную — проверьте данные"
            match.enabled = True
            self.fill_table()

    def _sync_edits(self):
        if self.album:
            update_album_details(
                self.album,
                title=self.album_title.text(),
                album_artist=self.album_artist.text(),
                year=self.album_year.text(),
                album_label=self.album_label.text(),
            )
        for row, match in enumerate(self.matches):
            match.enabled = self.table.item(row, 0).checkState() == Qt.CheckState.Checked
            disc_text = self.table.item(row, 2).text().strip()
            track_text = self.table.item(row, 3).text().strip()
            if disc_text and (not disc_text.isdigit() or int(disc_text) < 1):
                raise ValueError(f"Строка {row + 1}: номер диска должен быть положительным числом.")
            if not track_text.isdigit() or int(track_text) < 1:
                raise ValueError(f"Строка {row + 1}: номер трека должен быть положительным числом.")
            match.track.disc_number = int(disc_text) if disc_text else None
            match.track.track_number = int(track_text)
            match.track.artist = self.table.item(row, 6).text().strip()
            title, style_from_title, tempo_from_title = split_title_dance_suffix(
                self.table.item(row, 8).text()
            )
            match.track.title = title
            match.track.language = self.table.item(row, 9).text().strip()
            match.track.dance_style = (
                self.table.item(row, 10).text().strip() or style_from_title
            )
            match.track.dance_tempo = (
                self.table.item(row, 11).text().strip() or tempo_from_title
            )
            self.table.item(row, 8).setText(match.track.title)
            self.table.item(row, 10).setText(match.track.dance_style)
            self.table.item(row, 11).setText(match.track.dance_tempo)

    def options(self):
        kwargs = {name: checkbox.isChecked() for name, checkbox in self.field_checks.items()}
        return TagOptions(
            **kwargs,
            write_style_to_genre=self.genre.isChecked(),
            overwrite_empty=self.overwrite_empty.isChecked(),
        )

    def write_tags(self):
        try:
            self._sync_edits()
        except ValueError as exc:
            QMessageBox.critical(self, "Некорректный номер", str(exc))
            return
        selected = [
            match for match in self.matches
            if match.enabled and match.local_file and match.status is not MatchStatus.RED
        ]
        if not selected:
            QMessageBox.information(self, "Нет файлов", "Нет выбранных надёжных или проверенных сопоставлений.")
            return
        options = self.options()
        cover_data = None
        if self.write_cover.isChecked() and self.cover_file:
            try:
                cover_data = load_cover_image(self.cover_file)
            except Exception as exc:
                QMessageBox.critical(self, "Ошибка обложки", str(exc))
                return
        rename_enabled = self.rename_files.isChecked()
        folder_rename_enabled = self.rename_folder.isChecked()
        folder_template = (
            self.folder_template.text().strip() or DEFAULT_FOLDER_TEMPLATE
        )
        rename_template = self.rename_template.text().strip() or DEFAULT_RENAME_TEMPLATE
        rename_count = 0
        if rename_enabled:
            try:
                targets: set[str] = set()
                for match in selected:
                    target_name = build_audio_filename(
                        match.track, match.local_file.path.suffix, rename_template,
                    )
                    target_key = str(
                        match.local_file.path.with_name(target_name).resolve()
                    ).casefold()
                    if target_key in targets:
                        raise ValueError(f"Несколько треков получат имя «{target_name}».")
                    targets.add(target_key)
                    if match.local_file.path.name != target_name:
                        rename_count += 1
            except Exception as exc:
                QMessageBox.critical(self, "Ошибка шаблона", str(exc))
                return
        folder = Path(self.folder.text() or selected[0].local_file.path.parent).resolve()
        folder_target = None
        if folder_rename_enabled:
            try:
                folder_target = album_folder_target(
                    folder, self.album, folder_template,
                )
            except Exception as exc:
                QMessageBox.critical(self, "Ошибка шаблона папки", str(exc))
                return
            if folder_target != folder and folder_target.exists():
                QMessageBox.critical(
                    self, "Папка уже существует",
                    f"Нельзя переименовать папку: «{folder_target.name}» уже существует.",
                )
                return
        total_changes = sum(
            len(build_change_plan(match, self.tags.read_current(match.local_file.path), options))
            for match in selected
        )
        answer = QMessageBox.question(
            self, "Подтверждение записи",
            f"Будут обработаны файлы: {len(selected)}\nИзменений тегов: {total_changes}\n\n"
            f"Обложка: {self.cover_file.name if cover_data else 'не изменяется'}\n"
            f"Переименований: {rename_count}\n\n"
            f"Папка: {folder_target.name if folder_target else 'не изменяется'}\n\n"
            "Перед записью будет создан backup JSON. Продолжить?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = folder / f"tagstiller-backup-{stamp}.json"
        full_backup_dir = folder / f"tagstiller-files-{stamp}" if self.full_backup.isChecked() else None

        def operation():
            operation_backup_path = backup_path
            paths = [match.local_file.path for match in selected]
            self.backups.create(paths, operation_backup_path)
            successes, skipped, errors, renamed, rename_errors = [], [], [], [], []
            path_mapping: dict[str, str] = {}
            for match in selected:
                path = match.local_file.path
                try:
                    current = self.tags.read_current(path)
                    changes = build_change_plan(match, current, options)
                    values = {change.field: change.new_value for change in changes}
                    if cover_data:
                        values["cover_art"] = cover_data
                    if values:
                        self.tags.write_atomic(
                            path, values,
                            full_backup_dir,
                        )
                    new_path = path
                    if rename_enabled:
                        try:
                            new_path = rename_audio_file(path, match.track, rename_template)
                            if new_path != path:
                                path_mapping[str(path)] = str(new_path)
                                match.local_file.path = new_path
                                renamed.append(f"{path.name} → {new_path.name}")
                        except Exception as exc:
                            rename_errors.append(f"{path.name}: {exc}")
                    if values or new_path != path:
                        successes.append(new_path.name)
                    else:
                        skipped.append(path.name)
                except Exception as exc:
                    logging.exception("Не удалось записать %s", path)
                    errors.append(f"{path.name}: {exc}")
            self.backups.remap_paths(operation_backup_path, path_mapping)
            old_folder = folder
            new_folder = folder
            folder_error = ""
            if folder_rename_enabled:
                try:
                    new_folder = rename_album_folder(
                        old_folder, self.album, folder_template,
                    )
                    if new_folder != old_folder:
                        moved_mapping: dict[str, str] = {}
                        for match in selected:
                            current_path = match.local_file.path.resolve()
                            if current_path.is_relative_to(old_folder):
                                moved_path = new_folder / current_path.relative_to(old_folder)
                                moved_mapping[str(current_path)] = str(moved_path)
                        operation_backup_path = (
                            new_folder / operation_backup_path.name
                        )
                        self.backups.remap_paths(
                            operation_backup_path, moved_mapping,
                        )
                except Exception as exc:
                    logging.exception("Не удалось переименовать папку %s", old_folder)
                    folder_error = str(exc)
                    new_folder = old_folder
            return (
                successes, skipped, errors, renamed, rename_errors,
                operation_backup_path,
                old_folder, new_folder, folder_error,
            )

        self.run_worker(operation, self.write_finished, "Запись тегов…")

    def write_finished(self, result):
        (
            successes, skipped, errors, renamed, rename_errors, backup,
            old_folder, new_folder, folder_error,
        ) = result
        if new_folder != old_folder:
            local_objects = self.files + [
                match.local_file for match in self.matches if match.local_file
            ]
            seen: set[int] = set()
            for local in local_objects:
                if id(local) in seen:
                    continue
                seen.add(id(local))
                current = local.path.resolve()
                if current.is_relative_to(old_folder):
                    local.path = new_folder / current.relative_to(old_folder)
            if self.cover_file and self.cover_file.resolve().is_relative_to(old_folder):
                self.cover_file = new_folder / self.cover_file.resolve().relative_to(old_folder)
            self.folder.setText(str(new_folder))
            self.append_log(f"Папка переименована: {old_folder.name} → {new_folder.name}")
        conflicts = sum(match.status is MatchStatus.RED for match in self.matches)
        excluded = sum(not match.enabled for match in self.matches)
        self.append_log(f"Backup тегов: {backup}")
        self.append_log(
            f"Успешно: {len(successes)}; без изменений: {len(skipped)}; "
            f"переименовано: {len(renamed)}; исключено: {excluded}; "
            f"конфликтов: {conflicts}; "
            f"ошибки: {len(errors) + len(rename_errors) + bool(folder_error)}."
        )
        for item in renamed:
            self.append_log(f"Переименовано: {item}")
        for error in rename_errors:
            self.append_log(f"Теги записаны, но файл не переименован: {error}")
        for error in errors:
            self.append_log(f"Файл не был изменён из-за ошибки записи тегов: {error}")
        if folder_error:
            self.append_log(f"Папка не была переименована: {folder_error}")
        self.fill_table()
        QMessageBox.information(
            self, "Итоговый отчёт",
            f"Успешно: {len(successes)}\nБез изменений: {len(skipped)}\n"
            f"Переименовано: {len(renamed)}\n"
            f"Исключено пользователем: {excluded}\nКонфликтов: {conflicts}\n"
            f"Ошибки записи: {len(errors)}\nОшибки переименования: {len(rename_errors)}"
            f"\nПапка: {'переименована' if new_folder != old_folder else 'без изменений'}"
            f"\nОшибка папки: {folder_error or 'нет'}"
            f"\n\nBackup: {backup}",
        )

    def restore(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите backup JSON", "", "JSON (*.json)")
        if not path:
            return
        if QMessageBox.question(
            self, "Восстановление", "Восстановить сохранённые теги? Текущие значения будут заменены."
        ) != QMessageBox.StandardButton.Yes:
            return
        self.run_worker(lambda: self.backups.restore(path), self.restore_finished, "Восстановление тегов…")

    def restore_finished(self, result):
        restored, errors = result
        self.append_log(f"Восстановлено файлов: {len(restored)}; ошибки: {len(errors)}.")
        QMessageBox.information(self, "Восстановление", f"Восстановлено: {len(restored)}\nОшибки: {len(errors)}")

    def save_json(self):
        if not self.album:
            QMessageBox.warning(self, "Нет данных", "Сначала загрузите данные альбома.")
            return
        try:
            self._sync_edits()
        except ValueError as exc:
            QMessageBox.critical(self, "Некорректный номер", str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить JSON", f"{self.album.title}.json", "JSON (*.json)")
        if path:
            save_album_json(self.album, path)
            self.append_log(f"JSON сохранён: {path}")

    def save_csv(self):
        if not self.album:
            QMessageBox.warning(self, "Нет данных", "Сначала загрузите данные альбома.")
            return
        try:
            self._sync_edits()
        except ValueError as exc:
            QMessageBox.critical(self, "Некорректный номер", str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт CSV", f"{self.album.title}.csv", "CSV (*.csv)")
        if path:
            export_album_csv(self.album, path)
            self.append_log(f"CSV сохранён: {path}")

    def install_browser(self):
        if getattr(sys, "frozen", False):
            QMessageBox.information(
                self, "Chromium", "В этой сборке Chromium уже включён. Если он повреждён, скачайте ZIP приложения заново."
            )
            return
        self.run_worker(
            lambda: subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                check=True, capture_output=True, text=True,
            ).stdout,
            lambda _: QMessageBox.information(self, "Chromium", "Chromium успешно установлен."),
            "Установка Chromium…",
        )
