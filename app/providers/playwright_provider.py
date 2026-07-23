from __future__ import annotations

import tempfile
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from app.models import AlbumMetadata
from app.providers.base import CasaMusicaProvider, ProviderError
from app.providers.html_parser import CasaMusicaHtmlParser


class PlaywrightCasaMusicaProvider(CasaMusicaProvider):
    def __init__(self, timeout_ms: int = 45_000):
        self.timeout_ms = timeout_ms
        self.parser = CasaMusicaHtmlParser()

    def fetch_album(self, source: str) -> AlbumMetadata:
        if not source.lower().startswith(("http://", "https://")):
            raise ProviderError("Введите корректный URL Casa Musica.")
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(locale="en-US")
                page.goto(source, wait_until="domcontentloaded", timeout=self.timeout_ms)
                self._accept_cookies(page)
                try:
                    page.wait_for_selector("table", timeout=self.timeout_ms)
                except PlaywrightError:
                    pass
                html = page.content()
                browser.close()
        except PlaywrightError as exc:
            message = str(exc)
            if "Executable doesn't exist" in message:
                raise ProviderError(
                    "Браузер Chromium не установлен. Нажмите «Установить Chromium»."
                ) from exc
            raise ProviderError(
                "Не удалось открыть страницу. Проверьте интернет, URL или используйте локальный HTML."
            ) from exc
        if "Just a moment" in html and "challenge-platform" in html:
            raise ProviderError(
                "Сайт запросил дополнительную проверку. Сохраните страницу в браузере как HTML и загрузите её."
            )
        return self.parser.parse(html, source)

    @staticmethod
    def _accept_cookies(page) -> None:
        for label in ("Accept", "Accept all", "Allow all", "I agree"):
            try:
                page.get_by_role("button", name=label, exact=False).click(timeout=1200)
                return
            except PlaywrightError:
                continue

