import argparse
import sys

from .store import TaskStore
from .display import format_task, format_table


def _get_store(args) -> TaskStore:
    path = getattr(args, "store", None)
    return TaskStore(path)


def cmd_add(args):
    store = _get_store(args)
    tags = args.tags.split(",") if args.tags else []
    task = store.add(title=args.title, priority=args.priority, tags=tags)
    print(f"Added task {task.id}: {task.title}")
    return 0


def cmd_list(args):
    store = _get_store(args)
    status = args.status if args.status else None
    tasks = store.list(status=status)
    print(format_table(tasks))
    return 0


def cmd_done(args):
    store = _get_store(args)
    task = store.get(args.id)
    if task.status == "done":
        print(f"Task {args.id} is already done.")
        return 0
    task = store.update(args.id, status="done")
    print(f"Marked task {task.id} as done.")
    return 0


def cmd_remove(args):
    store = _get_store(args)
    if store.remove(args.id):
        print(f"Removed task {args.id}.")
        return 0
    print(f"Task {args.id} not found.", file=sys.stderr)
    return 1


def cmd_edit(args):
    store = _get_store(args)
    fields = {}
    if args.title is not None:
        fields["title"] = args.title
    if args.priority is not None:
        fields["priority"] = args.priority
    if not fields:
        print("Nothing to edit. Use --title or --priority.", file=sys.stderr)
        return 2
    task = store.update(args.id, **fields)
    if task is None:
        print(f"Task {args.id} not found.", file=sys.stderr)
        return 1
    print(f"Updated task {task.id}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="taskboard", description="CLI task manager")
    parser.add_argument("--store", help="Path to task store JSON file", default=None)
    sub = parser.add_subparsers(dest="command")

    # add
    p_add = sub.add_parser("add", help="Add a new task")
    p_add.add_argument("title", help="Task title")
    p_add.add_argument("--priority", "-p", type=int, default=1, help="Priority (1-3)")
    p_add.add_argument("--tags", "-t", default="", help="Comma-separated tags")

    # list
    p_list = sub.add_parser("list", help="List tasks")
    p_list.add_argument("--status", "-s", choices=["todo", "done"], default=None)

    # done
    p_done = sub.add_parser("done", help="Mark a task as done")
    p_done.add_argument("id", type=int, help="Task ID")

    # remove
    p_rm = sub.add_parser("remove", help="Remove a task")
    p_rm.add_argument("id", type=int, help="Task ID")

    # edit
    p_edit = sub.add_parser("edit", help="Edit a task")
    p_edit.add_argument("id", type=int, help="Task ID")
    p_edit.add_argument("--title", default=None)
    p_edit.add_argument("--priority", "-p", type=int, default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 2

    commands = {
        "add": cmd_add,
        "list": cmd_list,
        "done": cmd_done,
        "remove": cmd_remove,
        "edit": cmd_edit,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
