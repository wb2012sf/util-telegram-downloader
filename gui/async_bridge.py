"""
gui/async_bridge.py

Runs asyncio coroutines (Telethon calls) on a background thread with its
own persistent event loop, and delivers results back to the Qt GUI thread
via signals -- so a slow or rate-limited Telegram API call never freezes
the window. This avoids adding a third-party asyncio/Qt integration
dependency: PySide6 already marshals a signal emitted from a background
thread onto the thread its receiving slot lives on.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, Coroutine

from PySide6.QtCore import QObject, Signal


class AsyncBridge(QObject):
    """Owns a background thread running its own asyncio event loop.

    Call `submit(coro, on_done, on_error)` from the GUI thread; `on_done`
    or `on_error` is invoked back on the GUI thread once the coroutine
    finishes. Not unit tested directly -- it's GUI infrastructure exercised
    by the manual test checklist, per the project's testing conventions for
    GUI/event-loop code.
    """

    _result_ready = Signal(int, object)
    _error_ready = Signal(int, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="telegram-async-bridge")
        self._thread.start()
        self._loop_ready.wait()

        self._callbacks: dict[int, tuple[Callable[[Any], None], Callable[[BaseException], None]]] = {}
        self._next_tag = 0

        self._result_ready.connect(self._dispatch_result)
        self._error_ready.connect(self._dispatch_error)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop_ready.set()
        self._loop.run_forever()

    def submit(
        self,
        coro: Coroutine[Any, Any, Any],
        on_done: Callable[[Any], None],
        on_error: Callable[[BaseException], None],
    ) -> None:
        """Schedule `coro` on the background loop; deliver its outcome on the GUI thread."""
        assert self._loop is not None, "background event loop not started"

        tag = self._next_tag
        self._next_tag += 1
        self._callbacks[tag] = (on_done, on_error)

        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        future.add_done_callback(lambda fut: self._on_future_done(tag, fut))

    def _on_future_done(self, tag: int, future: "asyncio.Future[Any]") -> None:
        # Runs on the background thread; emitting is safe from any thread.
        try:
            result = future.result()
        except BaseException as exc:  # noqa: BLE001 -- forwarded to on_error, not swallowed
            self._error_ready.emit(tag, exc)
        else:
            self._result_ready.emit(tag, result)

    def _dispatch_result(self, tag: int, result: Any) -> None:
        on_done, _ = self._callbacks.pop(tag)
        on_done(result)

    def _dispatch_error(self, tag: int, exc: BaseException) -> None:
        _, on_error = self._callbacks.pop(tag)
        on_error(exc)

    def shutdown(self) -> None:
        """Stop the background event loop and join its thread."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)
