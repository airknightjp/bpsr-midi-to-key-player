from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app_controller import AppController
from qt_main_window import MidiMainWindow
from single_instance import SingleInstance
from software_synth import shutdown_software_synth


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
    single_instance.start_activation_listener(window.activation_requested.emit)

    try:
        return application.exec()
    finally:
        single_instance.close()
        controller.shutdown()
        shutdown_software_synth()

if __name__ == "__main__":
    raise SystemExit(main())
