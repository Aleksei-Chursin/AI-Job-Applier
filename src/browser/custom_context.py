import json
import logging
import os

from browser_use.browser.browser import Browser, IN_DOCKER
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import BrowserContext as PlaywrightBrowserContext
from typing import Optional
from browser_use.browser.context import BrowserContextState

logger = logging.getLogger(__name__)


class CustomBrowserContext(BrowserContext):
    def __init__(
            self,
            browser: 'Browser',
            config: BrowserContextConfig | None = None,
            state: Optional[BrowserContextState] = None,
    ):
        super(CustomBrowserContext, self).__init__(browser=browser, config=config, state=state)
        # Firefox does not support clipboard permissions in Playwright
        if browser.config.browser_class == 'firefox' and self.config.permissions:
            self.config.permissions = [p for p in self.config.permissions if 'clipboard' not in p]
