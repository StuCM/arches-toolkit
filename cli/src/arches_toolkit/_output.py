"""User-facing CLI output helpers.

Default output is short stage lines plus per-step results; the full
subprocess command lines appear only under the global ``--verbose`` flag
(set once in main's root callback, which also raises the logging level).
"""

from __future__ import annotations

import typer

_verbose = False


def set_verbose(value: bool) -> None:
    global _verbose
    _verbose = value


def is_verbose() -> bool:
    return _verbose


def stage(message: str) -> None:
    """Top-level progress line — always shown."""
    typer.secho(f"==> {message}", bold=True)


def cmd(argv: list[str] | str) -> None:
    """Echo a full command line — verbose only."""
    if _verbose:
        text = argv if isinstance(argv, str) else " ".join(str(a) for a in argv)
        typer.echo(f"+ {text}")
