from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from chartagent.envelope import Envelope
from chartagent.errors import RasterisationError
from chartagent.rasterise import BrowserRasteriser, load_vendored_renderers
from chartagent.recipe import BoundDocument

from studio.config import Settings, StudioConfigurationError


class ThreadConfinedRasteriser:
    """Owns a `BrowserRasteriser` on one dedicated thread.

    Playwright's sync API is bound to the thread that started it, but Studio
    builds at boot, rasterises from threadpool workers (sync `def` routes) and
    closes from the lifespan. Every call is marshalled onto the one thread
    that built the browser, which also serialises use of the single browser.
    """

    def __init__(self, settings: Settings) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="rasteriser"
        )
        try:
            self._inner: BrowserRasteriser = self._executor.submit(
                _build_browser_rasteriser, settings
            ).result()
        except BaseException:
            self._executor.shutdown()
            raise

    def rasterise(
        self, target: Envelope | BoundDocument, *, format: Literal["png"] = "png"
    ) -> bytes:
        return self._executor.submit(
            self._inner.rasterise, target, format=format
        ).result()

    def close(self) -> None:
        try:
            self._executor.submit(self._inner.close).result()
        finally:
            self._executor.shutdown()


def _build_browser_rasteriser(settings: Settings) -> BrowserRasteriser:
    try:
        renderers = load_vendored_renderers(settings.renderer_vendor_dir)
    except RasterisationError as exc:
        raise StudioConfigurationError(
            f"RENDERER_VENDOR_DIR={str(settings.renderer_vendor_dir)!r} "
            f"is unusable: {exc}"
        ) from exc
    return BrowserRasteriser(renderers)


def build_rasteriser(settings: Settings) -> ThreadConfinedRasteriser:
    """The one reference rasteriser the app owns (closed at shutdown).

    A missing vendor directory or a sha mismatch is the operator's to fix, so
    it surfaces as a configuration error naming the setting. A missing
    `review` extra propagates as the library's own error.
    """
    return ThreadConfinedRasteriser(settings)
