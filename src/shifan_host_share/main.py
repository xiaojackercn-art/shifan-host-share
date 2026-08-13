from .pair_input import install_pair_code_editor

install_pair_code_editor()

from .app import run  # noqa: E402


def main() -> None:
    run()
