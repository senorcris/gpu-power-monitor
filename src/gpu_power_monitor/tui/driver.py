"""Terminal cleanup for the full-screen Linux dashboard."""

from textual.drivers.linux_driver import LinuxDriver


class CleanExitLinuxDriver(LinuxDriver):
    def stop_application_mode(self) -> None:
        # Erase the dashboard BEFORE restoring the main screen. Some terminal
        # clients retain the alternate-screen frame on exit. Clearing afterward
        # would erase the user's shell contents instead.
        self.write("\x1b[?2026l\x1b[0m\x1b[2J\x1b[H")
        super().stop_application_mode()
