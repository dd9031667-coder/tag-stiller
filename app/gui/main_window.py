from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDoubleSpinBox, QFileDialog,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QPlainTextEdit, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.audio.scanner import inspect_audio, scan_folder
from app.audio.tags import TagOptions, TagService
from app.matching import match_tracks
from app.models import AlbumMetadata, MatchStatus, TrackMatch
from app.providers.html_parser import CasaMusicaHtmlParser
from app.providers.playwright_provider import PlaywrightCasaMusicaProvider
from app.services.album_io import (
    export_album_csv, load_album_json, save_album_json, update_album_title,
)
from app.services.backup import BackupService
from app.services.renaming import (
    DEFAULT_RENAME_TEMPLATE, build_audio_filename, rename_audio_file,
)
from app.services.tagging import build_change_plan
from app.gui.worker import Worker
from app.utils.text import split_title_dance_suffix


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
        self.album: AlbumMetadata | None = None
        self.files = []
        self.matches: list[TrackMatch] = []
        self.pool = QThreadPool.globalInstance()
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
        layout.addWidget(source_box)

        folder_box = QGroupBox("2. Локальные аудиофайлы")
        folder_layout = QHBoxLayout(folder_box)
        self.folder = QLineEdit()
        choose = QPushButton("Выбрать папку")
        choose.clicked.connect(self.choose_folder)
        scan = QPushButton("Сканировать папку")
        scan.clicked.connect(self.scan)
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setRange(0, 60)
        self.tolerance.setValue(4)
        self.tolerance.setSuffix(" с")
        folder_layout.addWidget(self.folder, 1)
        folder_layout.addWidget(choose)
        folder_layout.addWidget(scan)
        folder_layout.addWidget(QLabel("Допуск длительности:"))
        folder_layout.addWidget(self.tolerance)
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

        rename_box = QGroupBox("4. Переименование файлов")
        rename_layout = QHBoxLayout(rename_box)
        self.rename_files = QCheckBox("Переименовывать после записи тегов")
        self.rename_template = QLineEdit(DEFAULT_RENAME_TEMPLATE)
        self.rename_template.setToolTip(
            "Доступно: {disc}, {disc_prefix}, {track}, {artist}, {title}, {album}, {year}"
        )
        rename_layout.addWidget(self.rename_files)
        rename_layout.addWidget(QLabel("Шаблон:"))
        rename_layout.addWidget(self.rename_template, 1)
        layout.addWidget(rename_box)

        actions = QHBoxLayout()
        for label, handler in (
            ("Сохранить JSON", self.save_json), ("Экспорт CSV", self.save_csv),
            ("Восстановить из backup", self.restore), ("Записать теги", self.write_tags),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        self.log.setPlaceholderText("Здесь появится журнал выполнения.")
        layout.addWidget(self.log)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Режим preview: файлы не изменяются")

    def append_log(self, message: str):
        self.log.appendPlainText(message)
        logging.info(message)

    def run_worker(self, function, on_result, busy_text: str):
        self.statusBar().showMessage(busy_text)
        worker = Worker(function)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(self.worker_error)
        worker.signals.finished.connect(lambda: self.statusBar().showMessage("Готово"))
        self.pool.start(worker)

    def worker_error(self, message: str, details: str):
        self.append_log(f"Ошибка: {message}")
        QMessageBox.critical(self, "Ошибка", message or "Операция не выполнена. Подробности записаны в лог.")

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
            self.run_worker(
                lambda: CasaMusicaHtmlParser().fetch_album(path),
                self.album_loaded, "Обработка HTML…",
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
        self.album_title.setText(album.title)
        self.append_log(f"Загружен альбом «{album.title}»: {len(album.tracks)} треков.")
        self.rematch()

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
            lambda: scan_folder(folder), self.files_loaded, "Сканирование аудиофайлов…",
        )

    def files_loaded(self, files):
        self.files = files
        self.append_log(f"В папке найдено аудиофайлов: {len(files)}.")
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
                elif column not in {4, 6, 8, 9, 10, 11}:
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
            update_album_title(self.album, self.album_title.text())
        for row, match in enumerate(self.matches):
            match.enabled = self.table.item(row, 0).checkState() == Qt.CheckState.Checked
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
        self._sync_edits()
        selected = [
            match for match in self.matches
            if match.enabled and match.local_file and match.status is not MatchStatus.RED
        ]
        if not selected:
            QMessageBox.information(self, "Нет файлов", "Нет выбранных надёжных или проверенных сопоставлений.")
            return
        options = self.options()
        rename_enabled = self.rename_files.isChecked()
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
        total_changes = sum(
            len(build_change_plan(match, self.tags.read_current(match.local_file.path), options))
            for match in selected
        )
        answer = QMessageBox.question(
            self, "Подтверждение записи",
            f"Будут обработаны файлы: {len(selected)}\nИзменений тегов: {total_changes}\n\n"
            f"Переименований: {rename_count}\n\n"
            "Перед записью будет создан backup JSON. Продолжить?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        folder = Path(self.folder.text() or selected[0].local_file.path.parent)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = folder / f"tagstiller-backup-{stamp}.json"
        full_backup_dir = folder / f"tagstiller-files-{stamp}" if self.full_backup.isChecked() else None

        def operation():
            paths = [match.local_file.path for match in selected]
            self.backups.create(paths, backup_path)
            successes, skipped, errors, renamed, rename_errors = [], [], [], [], []
            path_mapping: dict[str, str] = {}
            for match in selected:
                path = match.local_file.path
                try:
                    current = self.tags.read_current(path)
                    changes = build_change_plan(match, current, options)
                    if changes:
                        self.tags.write_atomic(
                            path, {change.field: change.new_value for change in changes},
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
                    if changes or new_path != path:
                        successes.append(new_path.name)
                    else:
                        skipped.append(path.name)
                except Exception as exc:
                    logging.exception("Не удалось записать %s", path)
                    errors.append(f"{path.name}: {exc}")
            self.backups.remap_paths(backup_path, path_mapping)
            return successes, skipped, errors, renamed, rename_errors, backup_path

        self.run_worker(operation, self.write_finished, "Запись тегов…")

    def write_finished(self, result):
        successes, skipped, errors, renamed, rename_errors, backup = result
        conflicts = sum(match.status is MatchStatus.RED for match in self.matches)
        excluded = sum(not match.enabled for match in self.matches)
        self.append_log(f"Backup тегов: {backup}")
        self.append_log(
            f"Успешно: {len(successes)}; без изменений: {len(skipped)}; "
            f"переименовано: {len(renamed)}; исключено: {excluded}; "
            f"конфликтов: {conflicts}; ошибки: {len(errors) + len(rename_errors)}."
        )
        for item in renamed:
            self.append_log(f"Переименовано: {item}")
        for error in rename_errors:
            self.append_log(f"Теги записаны, но файл не переименован: {error}")
        for error in errors:
            self.append_log(f"Файл не был изменён из-за ошибки записи тегов: {error}")
        self.fill_table()
        QMessageBox.information(
            self, "Итоговый отчёт",
            f"Успешно: {len(successes)}\nБез изменений: {len(skipped)}\n"
            f"Переименовано: {len(renamed)}\n"
            f"Исключено пользователем: {excluded}\nКонфликтов: {conflicts}\n"
            f"Ошибки записи: {len(errors)}\nОшибки переименования: {len(rename_errors)}"
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
        self._sync_edits()
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить JSON", f"{self.album.title}.json", "JSON (*.json)")
        if path:
            save_album_json(self.album, path)
            self.append_log(f"JSON сохранён: {path}")

    def save_csv(self):
        if not self.album:
            QMessageBox.warning(self, "Нет данных", "Сначала загрузите данные альбома.")
            return
        self._sync_edits()
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
