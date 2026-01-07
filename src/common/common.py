import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

T = TypeVar("T")


# Shared helper functions
def retry_with_backoff[T](
    func: Callable[[], T], max_attempts: int = 3, initial_delay: float = 0.5
) -> T:
    """Retry a function with exponential backoff.

    Args:
        func: Function to retry (should be a lambda/callable)
        max_attempts: Maximum number of retry attempts
        initial_delay: Initial delay in seconds (will double each retry)

    Returns:
        Result of the function if successful

    Raises:
        Exception: The last exception encountered if all retries fail
    """
    delay = initial_delay
    last_exception = None

    for attempt in range(max_attempts):
        try:
            return func()
        except Exception as e:
            last_exception = e
            if attempt < max_attempts - 1:
                logger.warning(f"Attempt {attempt + 1} failed: {str(e)}. Retrying in {delay}s...")
                time.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                logger.error(f"All {max_attempts} attempts failed. Last error: {str(e)}")

    if last_exception:
        raise last_exception
    raise Exception("Unknown error in retry_with_backoff")


def extract_file_id(s3key: str) -> str:
    """Extract document_id from s3key by removing path and extension.

    Args:
        s3key: The S3 key string.

    Returns:
        The extracted document_id.
    """
    # Get filename from path
    filename = s3key.split("/")[-1]
    # Remove extension
    document_id = Path(filename).stem
    return document_id


# DynamoDB reserved words that need to be escaped
DYNAMODB_RESERVED_WORDS = {
    "abort",
    "absolute",
    "action",
    "add",
    "after",
    "agent",
    "aggregate",
    "all",
    "allocate",
    "alter",
    "analyze",
    "and",
    "any",
    "archive",
    "are",
    "array",
    "as",
    "asc",
    "ascii",
    "asensitive",
    "assertion",
    "asymmetric",
    "at",
    "atomic",
    "attach",
    "attribute",
    "auth",
    "authorization",
    "authorize",
    "auto",
    "avg",
    "back",
    "backup",
    "base",
    "batch",
    "before",
    "begin",
    "between",
    "bigint",
    "binary",
    "bit",
    "blob",
    "block",
    "boolean",
    "both",
    "breadth",
    "bucket",
    "bulk",
    "by",
    "byte",
    "call",
    "called",
    "calling",
    "capacity",
    "cascade",
    "cascaded",
    "case",
    "cast",
    "catalog",
    "char",
    "character",
    "check",
    "class",
    "clob",
    "close",
    "cluster",
    "clustered",
    "clustering",
    "clusters",
    "coalesce",
    "collate",
    "collation",
    "collection",
    "column",
    "columns",
    "combine",
    "comment",
    "commit",
    "compact",
    "compile",
    "compress",
    "condition",
    "conflict",
    "connect",
    "connection",
    "consistency",
    "consistent",
    "constraint",
    "constraints",
    "constructor",
    "consumed",
    "continue",
    "convert",
    "copy",
    "corresponding",
    "count",
    "counter",
    "create",
    "cross",
    "cube",
    "current",
    "cursor",
    "cycle",
    "data",
    "database",
    "date",
    "datetime",
    "day",
    "deallocate",
    "dec",
    "decimal",
    "declare",
    "default",
    "deferrable",
    "deferred",
    "define",
    "defined",
    "definition",
    "delete",
    "delimited",
    "depth",
    "deref",
    "desc",
    "describe",
    "descriptor",
    "detach",
    "deterministic",
    "diagnostics",
    "directories",
    "disable",
    "disconnect",
    "distinct",
    "distribute",
    "do",
    "domain",
    "double",
    "drop",
    "dump",
    "duration",
    "dynamic",
    "each",
    "element",
    "else",
    "elseif",
    "empty",
    "enable",
    "end",
    "equal",
    "equals",
    "error",
    "escape",
    "escaped",
    "eval",
    "evaluate",
    "exceeded",
    "except",
    "exception",
    "exceptions",
    "exclusive",
    "exec",
    "execute",
    "exists",
    "exit",
    "explain",
    "explode",
    "export",
    "expression",
    "extended",
    "external",
    "extract",
    "fail",
    "false",
    "family",
    "fetch",
    "fields",
    "file",
    "filter",
    "filtering",
    "final",
    "finish",
    "first",
    "fixed",
    "flattern",
    "float",
    "for",
    "force",
    "foreign",
    "format",
    "forward",
    "found",
    "free",
    "from",
    "full",
    "function",
    "functions",
    "general",
    "generate",
    "get",
    "glob",
    "global",
    "go",
    "goto",
    "grant",
    "greater",
    "group",
    "grouping",
    "handler",
    "hash",
    "have",
    "having",
    "heap",
    "hidden",
    "hold",
    "hour",
    "identified",
    "identity",
    "if",
    "ignore",
    "immediate",
    "import",
    "in",
    "including",
    "inclusive",
    "increment",
    "incremental",
    "index",
    "indexed",
    "indexes",
    "indicator",
    "infinite",
    "initially",
    "inline",
    "inner",
    "innter",
    "inout",
    "input",
    "insensitive",
    "insert",
    "instead",
    "int",
    "integer",
    "intersect",
    "interval",
    "into",
    "invalidate",
    "is",
    "isolation",
    "item",
    "items",
    "iterate",
    "join",
    "key",
    "keys",
    "lag",
    "language",
    "large",
    "last",
    "lateral",
    "lead",
    "leading",
    "leave",
    "left",
    "length",
    "less",
    "level",
    "like",
    "limit",
    "limited",
    "lines",
    "list",
    "load",
    "local",
    "localtime",
    "localtimestamp",
    "location",
    "locator",
    "lock",
    "locks",
    "log",
    "loged",
    "long",
    "loop",
    "lower",
    "map",
    "match",
    "materialized",
    "max",
    "maxlen",
    "member",
    "merge",
    "method",
    "metrics",
    "min",
    "minus",
    "minute",
    "missing",
    "mod",
    "mode",
    "modifies",
    "modify",
    "module",
    "month",
    "multi",
    "multiset",
    "name",
    "names",
    "national",
    "natural",
    "nchar",
    "nclob",
    "new",
    "next",
    "no",
    "none",
    "not",
    "null",
    "nullif",
    "number",
    "numeric",
    "object",
    "of",
    "offline",
    "offset",
    "old",
    "on",
    "online",
    "only",
    "opaque",
    "open",
    "operator",
    "option",
    "or",
    "order",
    "ordinality",
    "other",
    "others",
    "out",
    "outer",
    "output",
    "over",
    "overlaps",
    "override",
    "owner",
    "pad",
    "parallel",
    "parameter",
    "parameters",
    "partial",
    "partition",
    "partitioned",
    "partitions",
    "path",
    "percent",
    "percentile",
    "permission",
    "permissions",
    "pipe",
    "pipelined",
    "plan",
    "pool",
    "position",
    "precision",
    "prepare",
    "preserve",
    "primary",
    "prior",
    "private",
    "privileges",
    "procedure",
    "processed",
    "project",
    "projection",
    "property",
    "provisioning",
    "public",
    "put",
    "query",
    "quit",
    "quorum",
    "raise",
    "random",
    "range",
    "rank",
    "raw",
    "read",
    "reads",
    "real",
    "rebuild",
    "record",
    "recursive",
    "reduce",
    "ref",
    "reference",
    "references",
    "referencing",
    "regexp",
    "region",
    "reindex",
    "relative",
    "release",
    "remainder",
    "rename",
    "repeat",
    "replace",
    "request",
    "reset",
    "resignal",
    "resource",
    "response",
    "restore",
    "restrict",
    "result",
    "return",
    "returning",
    "returns",
    "reverse",
    "revoke",
    "right",
    "role",
    "roles",
    "rollback",
    "rollup",
    "routine",
    "row",
    "rows",
    "rule",
    "rules",
    "sample",
    "satisfies",
    "save",
    "savepoint",
    "scan",
    "schema",
    "scope",
    "scroll",
    "search",
    "second",
    "section",
    "segment",
    "segments",
    "select",
    "self",
    "semi",
    "sensitive",
    "separate",
    "sequence",
    "serializable",
    "session",
    "set",
    "sets",
    "shard",
    "share",
    "shared",
    "short",
    "show",
    "signal",
    "similar",
    "size",
    "skewed",
    "smallint",
    "snapshot",
    "some",
    "source",
    "space",
    "spaces",
    "sparse",
    "specific",
    "specifictype",
    "split",
    "sql",
    "sqlcode",
    "sqlerror",
    "sqlexception",
    "sqlstate",
    "sqlwarning",
    "start",
    "state",
    "static",
    "statistics",
    "status",
    "storage",
    "store",
    "stored",
    "stream",
    "string",
    "struct",
    "style",
    "sub",
    "submultiset",
    "subpartition",
    "substring",
    "subtype",
    "sum",
    "super",
    "symmetric",
    "synonym",
    "system",
    "table",
    "tablesample",
    "temp",
    "temporary",
    "terminated",
    "text",
    "than",
    "then",
    "throughput",
    "time",
    "timestamp",
    "timezone",
    "tinyint",
    "to",
    "token",
    "total",
    "touch",
    "trailing",
    "transaction",
    "transform",
    "translate",
    "translation",
    "treat",
    "trigger",
    "trim",
    "true",
    "truncate",
    "ttl",
    "tuple",
    "type",
    "under",
    "undo",
    "union",
    "unique",
    "unit",
    "unknown",
    "unlogged",
    "unnest",
    "unprocessed",
    "unsigned",
    "until",
    "update",
    "upper",
    "url",
    "usage",
    "use",
    "user",
    "users",
    "using",
    "uuid",
    "vacuum",
    "value",
    "valued",
    "values",
    "varchar",
    "variable",
    "variance",
    "varint",
    "varying",
    "view",
    "views",
    "virtual",
    "void",
    "wait",
    "when",
    "whenever",
    "where",
    "while",
    "window",
    "with",
    "within",
    "without",
    "work",
    "wrapped",
    "write",
    "year",
    "zone",
}


def create_or_update_record(
    table: Any,
    document_id: str,
    record_data: dict[str, Any],
    is_update: bool = False,
    condition_expression: Any | None = None,
) -> Any:
    """Create a new record or update existing record in DynamoDB.

    For new records (is_update=False), uses a conditional expression to prevent
    overwriting existing records, helping to avoid race conditions during concurrent uploads.

    Args:
        table: The DynamoDB Table resource.
        document_id: The primary key of the record.
        record_data: The data to store.
        is_update: True if updating an existing record, False for creation.
        condition_expression: Optional additional condition expression.

    Returns:
        The response from DynamoDB.

    Raises:
        ClientError: If a DynamoDB error occurs.
        Exception: If any other error occurs.
    """
    try:
        if is_update:
            # Build update expression dynamically
            update_expr_parts = []
            expr_attr_values = {}
            expr_attr_names = {}

            for i, (key, value) in enumerate(record_data.items()):
                # Generate a unique placeholder for the attribute name
                attr_name_placeholder = f"#attr{i}"
                # Generate a unique placeholder for the value
                value_placeholder = f":val{i}"

                expr_attr_names[attr_name_placeholder] = key
                expr_attr_values[value_placeholder] = value
                update_expr_parts.append(f"{attr_name_placeholder} = {value_placeholder}")

            update_expression = "SET " + ", ".join(update_expr_parts)

            update_params: dict[str, Any] = {
                "Key": {"document_id": document_id},
                "UpdateExpression": update_expression,
                "ExpressionAttributeValues": expr_attr_values,
            }

            # Only add ExpressionAttributeNames if we have items
            if expr_attr_names:
                update_params["ExpressionAttributeNames"] = expr_attr_names

            if condition_expression:
                update_params["ConditionExpression"] = condition_expression

            return table.update_item(**update_params)
        else:
            # Create new record with conditional expression to prevent overwrites
            item = {"document_id": document_id, **record_data}
            put_params: dict[str, Any] = {"Item": item}

            # Add condition to ensure we don't overwrite an existing record
            # This prevents race conditions during concurrent uploads
            from boto3.dynamodb.conditions import Attr

            put_params["ConditionExpression"] = Attr("document_id").not_exists()

            if condition_expression:
                # If additional condition provided, combine with AND
                put_params["ConditionExpression"] = (
                    put_params["ConditionExpression"] & condition_expression
                )

            return table.put_item(**put_params)

    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.warning(
                f"ConditionalCheckFailedException: Record with document_id '{document_id}' "
                "already exists or condition not met"
            )
        raise e
    except Exception as e:
        logger.error(f"Error creating/updating record for {document_id}: {e}")
        raise e
