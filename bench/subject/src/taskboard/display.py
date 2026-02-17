import sys

from .models import Task

# ANSI color codes
_RESET = "\033[0m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_DIM = "\033[2m"


def _use_color() -> bool:
    return sys.stdout.isatty()


def _colorize(text: str, code: str) -> str:
    if _use_color():
        return f"{code}{text}{_RESET}"
    return text


def _status_icon(status: str) -> str:
    if status == "done":
        return _colorize("[x]", _GREEN)
    return _colorize("[ ]", _YELLOW)


def _priority_stars(priority: int) -> str:
    stars = "*" * min(priority, 3)
    if priority >= 3:
        return _colorize(stars, _RED)
    elif priority >= 2:
        return _colorize(stars, _YELLOW)
    return stars


def format_task(task: Task) -> str:
    icon = _status_icon(task.status)
    pri = _priority_stars(task.priority)
    tags_str = ""
    if task.tags:
        tags_str = " " + _colorize(" ".join(f"#{t}" for t in task.tags), _DIM)
    return f"{icon} {task.id:>3}  {pri:<3}  {task.title}{tags_str}"


def format_table(tasks: list[Task]) -> str:
    if not tasks:
        return "No tasks."
    lines = [format_task(t) for t in tasks]
    return "\n".join(lines)
