"""Small scratch directories retained in macOS Trash after use."""
from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile
import uuid


@contextmanager
def scratch_directory(prefix):
    directory = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield directory
    finally:
        trash = Path.home() / '.Trash'
        trash.mkdir(exist_ok=True)
        destination = trash / directory.name
        if destination.exists():
            destination = trash / (directory.name + '-' + uuid.uuid4().hex[:8])
        shutil.move(str(directory), str(destination))
