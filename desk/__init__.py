"""Personal terminal for the Monterey shadow fund."""

__all__ = ["DeskApp"]


def __getattr__(name: str):
    if name == "DeskApp":
        from desk.app import DeskApp

        return DeskApp
    raise AttributeError(name)
