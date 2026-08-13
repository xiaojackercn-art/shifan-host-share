from .pair_input import install_pair_code_editor

install_pair_code_editor()

from . import app  # noqa: E402
from .ui_v06 import install_v06_ui  # noqa: E402

install_v06_ui(app)


def main() -> None:
    app.run()
