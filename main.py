from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app_controller import AppController
from qt_main_window import MidiMainWindow
from single_instance import SingleInstance


APP_WINDOW_TITLE = "BPSR MIDI to KEY Player"


def main() -> int:
    single_instance = SingleInstance(APP_WINDOW_TITLE)
    if not single_instance.is_primary:
        single_instance.notify_existing()
        single_instance.close()
        return 0

    application = QApplication(sys.argv)
    application.setApplicationName(APP_WINDOW_TITLE)
    application.setOrganizationName("airknightjp")
    application.setStyle("Fusion")
    controller = AppController()
    window = MidiMainWindow(controller)
    window.resize(controller.state.window_width, controller.state.window_height)
    window.show()
    controller.start()

    activation_timer = QTimer()
    activation_timer.setInterval(100)
    activation_timer.timeout.connect(
        lambda: window._restore_from_tray()
        if single_instance.consume_activation_request()
        else None
    )
    activation_timer.start()

    try:
        return application.exec()
    finally:
        activation_timer.stop()
        controller.shutdown()
        single_instance.close()

if __name__ == "__main__":
    raise SystemExit(main())
