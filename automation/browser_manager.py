"""Gerenciamento de instâncias do navegador com Playwright + Stealth Mode."""

import os
from pathlib import Path
from typing import Optional
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
USER_DATA_DIR = BASE_DIR / "data" / "browser_profile"


# JavaScript de evasão injetado em cada página para evitar detecção de automação
STEALTH_JS = """
// Remove navigator.webdriver flag
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Falsifica plugins (Chrome real tem plugins)
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
        { name: 'Native Client', filename: 'internal-nacl-plugin' },
    ]
});

// Falsifica languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['pt-BR', 'pt', 'en-US', 'en']
});

// Remove vestígios do Playwright/Puppeteer no Chrome
if (window.chrome) {
    window.chrome.runtime = { id: undefined };
} else {
    window.chrome = { runtime: { id: undefined } };
}

// Falsifica permissões
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);

// Falsifica hardware concurrency (máquinas reais têm 4+)
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });

// Falsifica device memory
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
"""


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

        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
        ]
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )

        try:
            # Cria contexto persistente para reter cookies e parecer um navegador real
            self.context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(USER_DATA_DIR),
                headless=self.headless,
                viewport={"width": 1280, "height": 850},
                user_agent=ua,
                locale="pt-BR",
                args=browser_args,
            )
        except Exception:
            # Fallback caso a pasta de perfil esteja bloqueada por outra aba/instância
            browser = self._playwright.chromium.launch(headless=self.headless, args=browser_args)
            self.context = browser.new_context(
                viewport={"width": 1280, "height": 850},
                user_agent=ua,
                locale="pt-BR",
            )

        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = self.context.new_page()

        # Injeta stealth script em cada página
        self.context.add_init_script(STEALTH_JS)
        # Re-injeta na página atual (já aberta antes do add_init_script)
        try:
            self.page.evaluate(STEALTH_JS)
        except Exception:
            pass

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
