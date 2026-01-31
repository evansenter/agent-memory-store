#!/usr/bin/env python3
"""CLI for agent-memory-store."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .storage import MemoryStorage, QueryFilters


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


def cmd_query(args, storage: MemoryStorage) -> int:
    """Execute structured query with symbolic filters."""
    filters = QueryFilters(
        key_pattern=args.key_pattern,
        value_pattern=args.value_pattern,
        text_contains=args.contains,
        namespace=args.namespace if args.namespace != "global" else None,
        tags=args.tags.split(",") if args.tags else None,
        has_all_tags=args.all_tags.split(",") if args.all_tags else None,
        min_importance=args.min_importance,
        max_importance=args.max_importance,
        min_access_count=args.min_access,
        never_accessed=args.never_accessed,
        order_by=args.order_by,
        order_desc=not args.asc,
        limit=args.limit,
        offset=args.offset,
    )

    if args.created_after:
        filters.created_after = datetime.fromisoformat(args.created_after)
    if args.created_before:
        filters.created_before = datetime.fromisoformat(args.created_before)
    if args.updated_after:
        filters.updated_after = datetime.fromisoformat(args.updated_after)

    memories = storage.query(filters)

    if not memories:
        print("No memories found.")
        return 0

    if args.json:
        output = [
            {
                "key": m.key,
                "value": m.value,
                "namespace": m.namespace,
                "tags": m.tags,
                "importance": m.importance,
                "created_at": m.created_at.isoformat(),
                "updated_at": m.updated_at.isoformat(),
                "access_count": m.access_count,
            }
            for m in memories
        ]
        print(json.dumps(output, indent=2))
    elif args.keys_only:
        for m in memories:
            print(m.key)
    else:
        for memory in memories:
            print(format_memory(memory, verbose=args.verbose))

    return 0


def cmd_explore(args, storage: MemoryStorage) -> int:
    """Show memory store statistics."""
    stats = storage.explore()

    if args.json:
        print(
            json.dumps(
                {
                    "total_count": stats.total_count,
                    "namespaces": stats.namespaces,
                    "top_tags": stats.tags,
                    "importance_distribution": stats.importance_distribution,
                    "date_range": {
                        "oldest": stats.date_range[0].isoformat() if stats.date_range[0] else None,
                        "newest": stats.date_range[1].isoformat() if stats.date_range[1] else None,
                    },
                    "avg_importance": stats.avg_importance,
                    "total_access_count": stats.total_access_count,
                    "semantic_available": stats.semantic_available,
                },
                indent=2,
            )
        )
    else:
        print(f"Total memories: {stats.total_count}")
        print(f"Average importance: {stats.avg_importance}")
        print(f"Total accesses: {stats.total_access_count}")
        print(f"Semantic search: {'available' if stats.semantic_available else 'unavailable'}")
        if stats.date_range[0]:
            print(f"Date range: {stats.date_range[0].date()} to {stats.date_range[1].date()}")
        print()
        if stats.namespaces:
            print("Namespaces:")
            for ns, count in stats.namespaces.items():
                print(f"  {ns}: {count}")
        if stats.importance_distribution:
            print("\nImportance distribution:")
            for imp in sorted(stats.importance_distribution.keys()):
                count = stats.importance_distribution[imp]
                bar = "█" * (count * 20 // max(stats.importance_distribution.values()))
                print(f"  {imp:2d}: {bar} ({count})")
        if stats.tags:
            print("\nTop tags:")
            for tag, count in list(stats.tags.items())[:10]:
                print(f"  {tag}: {count}")

    return 0


def cmd_search_weighted(args, storage: MemoryStorage) -> int:
    """Search with recency × importance × relevance scoring."""
    results = storage.search_weighted(
        query=args.query,
        namespace=args.namespace if args.namespace != "global" else None,
        tags=args.tags.split(",") if args.tags else None,
        limit=args.limit,
        recency_weight=args.recency_weight,
        importance_weight=args.importance_weight,
        relevance_weight=args.relevance_weight,
        recency_decay_days=args.decay_days,
    )

    if not results:
        print("No memories found.")
        return 0

    if args.json:
        output = [
            {
                "key": sm.memory.key,
                "value": sm.memory.value,
                "namespace": sm.memory.namespace,
                "tags": sm.memory.tags,
                "importance": sm.memory.importance,
                "score": round(sm.score, 4),
                "recency_score": round(sm.recency_score, 4),
                "importance_score": round(sm.importance_score, 4),
                "relevance_score": round(sm.relevance_score, 4),
            }
            for sm in results
        ]
        print(json.dumps(output, indent=2))
    else:
        for sm in results:
            scores = (
                f"[score={sm.score:.2f} r={sm.recency_score:.2f} "
                f"i={sm.importance_score:.2f} rel={sm.relevance_score:.2f}]"
            )
            print(f"{sm.memory.key} {scores}: {sm.memory.value[:80]}...")

    return 0


def cmd_aggregate(args, storage: MemoryStorage) -> int:
    """Aggregate memories by dimension."""
    filters = None
    if args.namespace or args.min_importance:
        filters = QueryFilters(
            namespace=args.namespace if args.namespace != "global" else None,
            min_importance=args.min_importance,
            limit=10000,
        )

    result = storage.aggregate(group_by=args.group_by, filters=filters)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Grouped by: {result['group_by']}")
        print(f"Total: {result['total']}")
        print()
        for key, count in result["groups"].items():
            bar = "█" * (count * 30 // max(result["groups"].values())) if result["groups"] else ""
            print(f"  {key}: {bar} ({count})")

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
        "-v",
        "--verbose",
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
        "-i", "--importance", type=int, default=5, help="Importance (1-10, default 5)"
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

    # query command (symbolic filtering)
    query_parser = subparsers.add_parser("query", help="Structured query with symbolic filters")
    query_parser.add_argument("--key-pattern", help="Regex pattern for keys")
    query_parser.add_argument("--value-pattern", help="Regex pattern for values")
    query_parser.add_argument("-c", "--contains", help="Substring to find in key or value")
    query_parser.add_argument("-n", "--namespace", default="global", help="Namespace filter")
    query_parser.add_argument("-t", "--tags", help="Match any of these tags (comma-separated)")
    query_parser.add_argument("--all-tags", help="Match ALL of these tags (comma-separated)")
    query_parser.add_argument("--min-importance", type=int, help="Minimum importance (1-10)")
    query_parser.add_argument("--max-importance", type=int, help="Maximum importance (1-10)")
    query_parser.add_argument("--created-after", help="Created after (ISO datetime)")
    query_parser.add_argument("--created-before", help="Created before (ISO datetime)")
    query_parser.add_argument("--updated-after", help="Updated after (ISO datetime)")
    query_parser.add_argument("--min-access", type=int, help="Minimum access count")
    query_parser.add_argument(
        "--never-accessed", action="store_true", help="Only never-accessed memories"
    )
    query_parser.add_argument(
        "--order-by",
        default="updated_at",
        choices=["created_at", "updated_at", "importance", "access_count", "key"],
        help="Sort field",
    )
    query_parser.add_argument(
        "--asc", action="store_true", help="Sort ascending (default: descending)"
    )
    query_parser.add_argument("-l", "--limit", type=int, default=50, help="Max results")
    query_parser.add_argument("--offset", type=int, default=0, help="Skip first N results")
    query_parser.add_argument("--keys-only", action="store_true", help="Print only keys")
    query_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # explore command
    explore_parser = subparsers.add_parser("explore", help="Show memory store statistics")
    explore_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # search command (weighted)
    search_parser = subparsers.add_parser(
        "search", help="Weighted search (recency × importance × relevance)"
    )
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("-n", "--namespace", default="global", help="Namespace filter")
    search_parser.add_argument("-t", "--tags", help="Comma-separated tags filter")
    search_parser.add_argument("-l", "--limit", type=int, default=10, help="Max results")
    search_parser.add_argument(
        "--recency-weight", type=float, default=1.0, help="Weight for recency"
    )
    search_parser.add_argument(
        "--importance-weight", type=float, default=1.0, help="Weight for importance"
    )
    search_parser.add_argument(
        "--relevance-weight", type=float, default=1.0, help="Weight for relevance"
    )
    search_parser.add_argument(
        "--decay-days", type=float, default=30.0, help="Days until recency decays to ~37%%"
    )
    search_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # aggregate command
    agg_parser = subparsers.add_parser("aggregate", help="Aggregate memories by dimension")
    agg_parser.add_argument(
        "group_by",
        nargs="?",
        default="namespace",
        choices=["namespace", "tag", "importance", "date"],
        help="Dimension to group by",
    )
    agg_parser.add_argument("-n", "--namespace", help="Filter by namespace before aggregating")
    agg_parser.add_argument(
        "--min-importance", type=int, help="Filter by min importance before aggregating"
    )
    agg_parser.add_argument("--json", action="store_true", help="Output as JSON")

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
        "query": cmd_query,
        "explore": cmd_explore,
        "search": cmd_search_weighted,
        "aggregate": cmd_aggregate,
    }

    return handlers[args.command](args, storage)


if __name__ == "__main__":
    sys.exit(main())
