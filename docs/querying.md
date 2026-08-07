# Querying, sorting, filtering, and pagination

ProdKit Storage exposes reusable query mechanics without hiding SQLAlchemy.
Applications define which fields are public and meaningful for each resource.

## Sorting

Declare an allowlist and a stable unique tie-breaker:

```python
from prodkit_storage.database.sorting import (
    NullPlacement,
    SortDirection,
    SortField,
    SortRegistry,
    SortTerm,
)

customer_sorting = SortRegistry(
    name="customer-list-v1",
    fields={
        "created_at": SortField(
            "created_at",
            Customer.created_at,
            default_nulls=NullPlacement.LAST,
        ),
        "name": Customer.name,
        "id": Customer.id,
    },
    default=(SortTerm("created_at", SortDirection.DESC),),
    tie_breaker="id",
)

sort = customer_sorting.parse(["-created_at", "name"])
```

A bare tie-breaker follows the final requested direction. Pass a full
`SortTerm` when its direction must be fixed. Nullable tie-breakers are rejected.

Never map untrusted strings directly to SQL expressions. The registry is the
security and compatibility boundary for public sort names.

## Filtering

```python
from prodkit_storage.database.filtering import (
    FilterField,
    FilterOperator,
    FilterRegistry,
    FilterTerm,
)

filters = FilterRegistry(
    {
        "status": FilterField(
            "status",
            Customer.status,
            frozenset({FilterOperator.EQ, FilterOperator.IN}),
        ),
        "created_at": FilterField(
            "created_at",
            Customer.created_at,
            frozenset({FilterOperator.GTE, FilterOperator.LT}),
        ),
    }
)

statement = filters.apply(
    select(Customer),
    [FilterTerm("status", FilterOperator.EQ, "active")],
)
```

Filtering remains domain-owned: a field that exists in the database is not
automatically safe or useful to expose through an API.

## Cursor pagination

```python
from prodkit_storage.database.pagination import CursorCodec

codec = CursorCodec(settings.cursor_secret_bytes)
page = await repository.paginate_cursor(
    statement,
    sort=sort,
    codec=codec,
    cursor=request_cursor,
    limit=50,
    query_fingerprint="active-customers-v1",
)
```

Version 2 cursors authenticate:

- the resolved sort fields, directions, and null placement;
- the last row's values, including the unique tie-breaker;
- an optional query/filter fingerprint;
- the cursor format version.

Changing the sort or query invalidates an old cursor instead of silently
returning inconsistent results.

## Offset pagination

Use offset pagination when exact totals or direct page navigation matter:

```python
page = await repository.paginate_offset(
    statement,
    page=3,
    limit=50,
    include_total=True,
)
```

With `include_total=False`, the paginator fetches one extra row to determine
`has_next_page`; `total_count` and `total_pages` are `None` rather than a
misleading zero.

Offset pagination is appropriate for bounded administrative datasets. Prefer
cursor pagination for large or frequently changing operational tables.

## Streaming

```python
async for customer in repository.stream(statement, yield_per=1_000):
    await process(customer)
```

Do not use ORM streaming with joined collection eager loading that requires
whole-result de-duplication. Prefer select-in loading or process scalar rows in
bounded batches.

## Row locking

ID retrieval supports `FOR UPDATE`, `NOWAIT`, and `SKIP LOCKED`. The latter two
require an explicit write lock. Use PostgreSQL SQLSTATE helpers to distinguish
lock contention from permanent failures.
