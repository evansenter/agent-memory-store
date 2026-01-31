#!/usr/bin/env python3
"""CLI for agent-memory-store."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .storage import MemoryStorage


def get_default_db_path() -> Path:
    """Get the default database path (consistent with MCP server)."""
    db_dir = Path.home() / ".claude" / "contrib" / "agent-memory-store"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "memories.db"


def format_memory(memory, verbose: bool = False) -> str:
    """Format a memory for display."""
    if verbose:
        return json.dumps(
            {
                "id": memory.id,
                "key": memory.key,
                "value": memory.value,
                "namespace": memory.namespace,
                "tags": memory.tags,
                "created_at": memory.created_at.isoformat(),
                "updated_at": memory.updated_at.isoformat(),
                "created_by": memory.created_by,
                "expires_at": memory.expires_at.isoformat() if memory.expires_at else None,
                "access_count": memory.access_count,
                "importance": memory.importance,
            },
            indent=2,
        )
    else:
        tags_str = f" [{', '.join(memory.tags)}]" if memory.tags else ""
        ns_str = f" ({memory.namespace})" if memory.namespace != "global" else ""
        imp_str = f" [!{memory.importance}]" if memory.importance != 5 else ""
        return f"{memory.key}{ns_str}{tags_str}{imp_str}: {memory.value}"


def cmd_store(args, storage: MemoryStorage) -> int:
    """Store a memory."""
    tags = args.tags.split(",") if args.tags else None
    memory = storage.store(
        key=args.key,
        value=args.value,
        namespace=args.namespace,
        tags=tags,
        created_by=args.created_by,
        ttl_days=args.ttl,
        importance=args.importance,
    )
    if args.verbose:
        print(format_memory(memory, verbose=True))
    else:
        print(f"Stored: {memory.key}")
    return 0


def cmd_recall(args, storage: MemoryStorage) -> int:
    """Recall a memory by key or search."""
    if args.search:
        # Full-text search
        tags = args.tags.split(",") if args.tags else None
        memories = storage.search(
            query=args.key,
            namespace=args.namespace if args.namespace != "global" else None,
            tags=tags,
            limit=args.limit,
        )
        if not memories:
            print("No memories found.", file=sys.stderr)
            return 1
        for memory in memories:
            print(format_memory(memory, verbose=args.verbose))
        return 0
    else:
        # Exact key lookup
        memory = storage.recall_by_key(args.key)
        if not memory:
            print(f"Memory not found: {args.key}", file=sys.stderr)
            return 1
        if args.value_only:
            print(memory.value)
        else:
            print(format_memory(memory, verbose=args.verbose))
        return 0


def cmd_forget(args, storage: MemoryStorage) -> int:
    """Forget (delete) a memory."""
    if not args.force:
        memory = storage.recall_by_key(args.key)
        if memory:
            print(f"Will delete: {format_memory(memory)}")
            confirm = input("Confirm? [y/N] ").strip().lower()
            if confirm != "y":
                print("Aborted.")
                return 1

    if storage.forget(args.key):
        print(f"Forgot: {args.key}")
        return 0
    else:
        print(f"Memory not found: {args.key}", file=sys.stderr)
        return 1


def cmd_list(args, storage: MemoryStorage) -> int:
    """List memories."""
    tags = args.tags.split(",") if args.tags else None
    since = None
    if args.since:
        since = datetime.fromisoformat(args.since)

    memories = storage.list_memories(
        namespace=args.namespace if args.namespace != "global" else None,
        tags=tags,
        since=since,
        limit=args.limit,
    )

    if not memories:
        print("No memories found.")
        return 0

    if args.keys_only:
        for memory in memories:
            print(memory.key)
    elif args.json:
        output = [
            {
                "key": m.key,
                "value": m.value,
                "namespace": m.namespace,
                "tags": m.tags,
                "importance": m.importance,
                "updated_at": m.updated_at.isoformat(),
            }
            for m in memories
        ]
        print(json.dumps(output, indent=2))
    else:
        for memory in memories:
            print(format_memory(memory, verbose=args.verbose))

    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="memory",
        description="CLI for agent-memory-store - persistent memory for AI agents",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to database file (default: ~/.claude/contrib/agent-memory-store/memories.db)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output (show all fields)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # store command
    store_parser = subparsers.add_parser("store", help="Store a memory")
    store_parser.add_argument("key", help="Memory key")
    store_parser.add_argument("value", help="Memory value")
    store_parser.add_argument("-n", "--namespace", default="global", help="Namespace")
    store_parser.add_argument("-t", "--tags", help="Comma-separated tags")
    store_parser.add_argument("--created-by", help="Creator identifier")
    store_parser.add_argument("--ttl", type=int, help="Time-to-live in days")
    store_parser.add_argument(
        "-i", "--importance", type=int, default=5,
        help="Importance (1-10, default 5)"
    )

    # recall command
    recall_parser = subparsers.add_parser("recall", help="Recall a memory")
    recall_parser.add_argument("key", help="Memory key or search query")
    recall_parser.add_argument("-s", "--search", action="store_true", help="Use full-text search")
    recall_parser.add_argument("-n", "--namespace", default="global", help="Namespace filter")
    recall_parser.add_argument("-t", "--tags", help="Comma-separated tags filter")
    recall_parser.add_argument("-l", "--limit", type=int, default=10, help="Max results for search")
    recall_parser.add_argument("--value-only", action="store_true", help="Print only the value")

    # forget command
    forget_parser = subparsers.add_parser("forget", help="Forget (delete) a memory")
    forget_parser.add_argument("key", help="Memory key to delete")
    forget_parser.add_argument("-f", "--force", action="store_true", help="Skip confirmation")

    # list command
    list_parser = subparsers.add_parser("list", help="List memories")
    list_parser.add_argument("-n", "--namespace", default="global", help="Namespace filter")
    list_parser.add_argument("-t", "--tags", help="Comma-separated tags filter")
    list_parser.add_argument("-l", "--limit", type=int, default=20, help="Max results")
    list_parser.add_argument("--since", help="Only memories created after (ISO datetime)")
    list_parser.add_argument("--keys-only", action="store_true", help="Print only keys")
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args(argv)

    # Initialize storage
    db_path = args.db or get_default_db_path()
    storage = MemoryStorage(db_path)

    # Dispatch to command handler
    handlers = {
        "store": cmd_store,
        "recall": cmd_recall,
        "forget": cmd_forget,
        "list": cmd_list,
    }

    return handlers[args.command](args, storage)


if __name__ == "__main__":
    sys.exit(main())
