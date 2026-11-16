"""Gerenciamento de instâncias do navegador com Playwright."""

import os
from pathlib import Path
from typing import Optional
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
USER_DATA_DIR = BASE_DIR / "data" / "browser_profile"


class BrowserManager:
    def __init__(self, headless: Optional[bool] = None):
        if headless is None:
            env_headless = os.getenv("BROWSER_HEADLESS", "false").lower()
            self.headless = env_headless in ["true", "1", "yes"]
        else:
            self.headless = headless

        self._playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    def start(self) -> Page:
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()

        # Cria contexto persistente para reter cookies e parecer um navegador real
        self.context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=self.headless,
            viewport={"width": 1280, "height": 850},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="pt-BR",
            args=["--disable-blink-features=AutomationControlled"],
        )

        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = self.context.new_page()

        # Timeout padrão razoável de 30 segundos
        self.page.set_default_timeout(30000)
        return self.page

    def take_screenshot(self, filename: str = "debug_screenshot.png") -> Path:
        out_path = BASE_DIR / "data" / filename
        if self.page:
            self.page.screenshot(path=str(out_path), full_page=True)
        return out_path

    def stop(self):
        try:
            if self.context:
                self.context.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
