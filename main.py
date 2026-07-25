from __future__ import annotations

import multiprocessing
import os
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app_controller import AppController
from process_lifecycle import initialize_process_job
from qt_main_window import MidiMainWindow
from single_instance import SingleInstance
from software_synth import shutdown_software_synth


APP_WINDOW_TITLE = "BPSR MIDI to KEY Player"
UPDATE_RESTART_ENV = "BPSR_UPDATE_RESTART"


def consume_update_restart_request() -> bool:
    return os.environ.pop(UPDATE_RESTART_ENV, "") == "1"


def main() -> int:
    initialize_process_job()
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
    if consume_update_restart_request():
        QTimer.singleShot(0, window._restore_from_tray)
    controller.start()
    single_instance.start_activation_listener(window.activation_requested.emit)
    QTimer.singleShot(0, window.run_startup_tasks)

    try:
        return application.exec()
    finally:
        single_instance.close()
        controller.shutdown()
        shutdown_software_synth()

if __name__ == "__main__":
    raise SystemExit(main())
