import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class LogWatcher(FileSystemEventHandler):
    def __init__(self, target):
        self.target = os.path.abspath(target)

    def _handle(self, event):
        if event.is_directory:
            return
        # covers both direct writes and atomic save-then-rename
        paths = [event.src_path, getattr(event, "dest_path", None)]
        if any(p and os.path.abspath(p) == self.target for p in paths):
            print(f"event type: {event.event_type}  path: {self.target}")

    on_modified = _handle
    on_created = _handle
    on_moved = _handle


if __name__ == "__main__":
    log_file_path = os.path.join(os.getcwd(), "data", "application.logs.json")
    watch_dir = os.path.dirname(log_file_path)

    observer = Observer()
    observer.schedule(LogWatcher(log_file_path), path=watch_dir, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()