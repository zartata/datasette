import asyncio
import contextlib
from pathlib import Path
import threading

from .tracer import trace
from .utils import (
    QueryInterrupted,
    Results,
    detect_fts,
    detect_primary_keys,
    detect_spatialite,
    get_all_foreign_keys,
    get_outbound_foreign_keys,
    sqlite_timelimit,
    sqlite3,
    table_columns,
)
from .inspect import inspect_hash

connections = threading.local()


class Database:
    def __init__(self, ds, path=None, is_mutable=False, is_memory=False):
        self.ds = ds
        self.path = path
        self.is_mutable = is_mutable
        self.is_memory = is_memory
        self.hash = None
        self.cached_size = None
        self.cached_table_counts = None
        if not self.is_mutable:
            p = Path(path)
            self.hash = inspect_hash(p)
            self.cached_size = p.stat().st_size
            # Maybe use self.ds.inspect_data to populate cached_table_counts
            if self.ds.inspect_data and self.ds.inspect_data.get(self.name):
                self.cached_table_counts = {
                    key: value["count"]
                    for key, value in self.ds.inspect_data[self.name]["tables"].items()
                }

    def connect(self):
        if self.is_memory:
            return sqlite3.connect(":memory:")
        # mode=ro or immutable=1?
        if self.is_mutable:
            qs = "mode=ro"
        else:
            qs = "immutable=1"
        return sqlite3.connect(
            "file:{}?{}".format(self.path, qs), uri=True, check_same_thread=False
        )

    async def execute_against_connection_in_thread(self, fn):
        def in_thread():
            conn = getattr(connections, self.name, None)
            if not conn:
                conn = self.connect()
                self.ds.prepare_connection(conn, self.name)
                setattr(connections, self.name, conn)
            return fn(conn)

        return await asyncio.get_event_loop().run_in_executor(
            self.ds.executor, in_thread
        )

    async def execute(
        self,
        sql,
        params=None,
        truncate=False,
        custom_time_limit=None,
        page_size=None,
        log_sql_errors=True,
    ):
        """Executes sql against db_name in a thread"""
        page_size = page_size or self.ds.page_size

        def sql_operation_in_thread(conn):
            time_limit_ms = self.ds.sql_time_limit_ms
            if custom_time_limit and custom_time_limit < time_limit_ms:
                time_limit_ms = custom_time_limit

            with sqlite_timelimit(conn, time_limit_ms):
                try:
                    cursor = conn.cursor()
                    cursor.execute(sql, params or {})
                    max_returned_rows = self.ds.max_returned_rows
                    if max_returned_rows == page_size:
                        max_returned_rows += 1
                    if max_returned_rows and truncate:
                        rows = cursor.fetchmany(max_returned_rows + 1)
                        truncated = len(rows) > max_returned_rows
                        rows = rows[:max_returned_rows]
                    else:
                        rows = cursor.fetchall()
                        truncated = False
                except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
                    if e.args == ("interrupted",):
                        raise QueryInterrupted(e, sql, params)
                    if log_sql_errors:
                        print(
                            "ERROR: conn={}, sql = {}, params = {}: {}".format(
                                conn, repr(sql), params, e
                            )
                        )
                    raise

            if truncate:
                return Results(rows, truncated, cursor.description)

            else:
                return Results(rows, False, cursor.description)

        with trace("sql", database=self.name, sql=sql.strip(), params=params):
            results = await self.execute_against_connection_in_thread(
                sql_operation_in_thread
            )
        return results

    @property
    def size(self):
        if self.is_memory:
            return 0
        if self.cached_size is not None:
            return self.cached_size
        else:
            return Path(self.path).stat().st_size

    async def table_counts(self, limit=10):
        if not self.is_mutable and self.cached_table_counts is not None:
            return self.cached_table_counts
        # Try to get counts for each table, $limit timeout for each count
        counts = {}
        for table in await self.table_names():
            try:
                table_count = (
                    await self.execute(
                        "select count(*) from [{}]".format(table),
                        custom_time_limit=limit,
                    )
                ).rows[0][0]
                counts[table] = table_count
            # In some cases I saw "SQL Logic Error" here in addition to
            # QueryInterrupted - so we catch that too:
            except (QueryInterrupted, sqlite3.OperationalError, sqlite3.DatabaseError):
                counts[table] = None
        if not self.is_mutable:
            self.cached_table_counts = counts
        return counts

    @property
    def mtime_ns(self):
        return Path(self.path).stat().st_mtime_ns

    @property
    def name(self):
        if self.is_memory:
            return ":memory:"
        else:
            return Path(self.path).stem

    async def table_exists(self, table):
        results = await self.execute(
            "select 1 from sqlite_master where type='table' and name=?", params=(table,)
        )
        return bool(results.rows)

    async def table_names(self):
        results = await self.execute(
            "select name from sqlite_master where type='table'"
        )
        return [r[0] for r in results.rows]

    async def table_columns(self, table):
        return await self.execute_against_connection_in_thread(
            lambda conn: table_columns(conn, table)
        )

    async def primary_keys(self, table):
        return await self.execute_against_connection_in_thread(
            lambda conn: detect_primary_keys(conn, table)
        )

    async def fts_table(self, table):
        return await self.execute_against_connection_in_thread(
            lambda conn: detect_fts(conn, table)
        )

    async def label_column_for_table(self, table):
        explicit_label_column = self.ds.table_metadata(self.name, table).get(
            "label_column"
        )
        if explicit_label_column:
            return explicit_label_column
        # If a table has two columns, one of which is ID, then label_column is the other one
        column_names = await self.execute_against_connection_in_thread(
            lambda conn: table_columns(conn, table)
        )
        # Is there a name or title column?
        name_or_title = [c for c in column_names if c in ("name", "title")]
        if name_or_title:
            return name_or_title[0]
        if (
            column_names
            and len(column_names) == 2
            and ("id" in column_names or "pk" in column_names)
        ):
            return [c for c in column_names if c not in ("id", "pk")][0]
        # Couldn't find a label:
        return None

    async def foreign_keys_for_table(self, table):
        return await self.execute_against_connection_in_thread(
            lambda conn: get_outbound_foreign_keys(conn, table)
        )

    async def hidden_table_names(self):
        # Mark tables 'hidden' if they relate to FTS virtual tables
        hidden_tables = [
            r[0]
            for r in (
                await self.execute(
                    """
                select name from sqlite_master
                where rootpage = 0
                and sql like '%VIRTUAL TABLE%USING FTS%'
            """
                )
            ).rows
        ]
        has_spatialite = await self.execute_against_connection_in_thread(
            detect_spatialite
        )
        if has_spatialite:
            # Also hide Spatialite internal tables
            hidden_tables += [
                "ElementaryGeometries",
                "SpatialIndex",
                "geometry_columns",
                "spatial_ref_sys",
                "spatialite_history",
                "sql_statements_log",
                "sqlite_sequence",
                "views_geometry_columns",
                "virts_geometry_columns",
            ] + [
                r[0]
                for r in (
                    await self.execute(
                        """
                        select name from sqlite_master
                        where name like "idx_%"
                        and type = "table"
                    """
                    )
                ).rows
            ]
        # Add any from metadata.json
        db_metadata = self.ds.metadata(database=self.name)
        if "tables" in db_metadata:
            hidden_tables += [
                t
                for t in db_metadata["tables"]
                if db_metadata["tables"][t].get("hidden")
            ]
        # Also mark as hidden any tables which start with the name of a hidden table
        # e.g. "searchable_fts" implies "searchable_fts_content" should be hidden
        for table_name in await self.table_names():
            for hidden_table in hidden_tables[:]:
                if table_name.startswith(hidden_table):
                    hidden_tables.append(table_name)
                    continue

        return hidden_tables

    async def view_names(self):
        results = await self.execute("select name from sqlite_master where type='view'")
        return [r[0] for r in results.rows]

    async def get_all_foreign_keys(self):
        return await self.execute_against_connection_in_thread(get_all_foreign_keys)

    async def get_outbound_foreign_keys(self, table):
        return await self.execute_against_connection_in_thread(
            lambda conn: get_outbound_foreign_keys(conn, table)
        )

    async def get_table_definition(self, table, type_="table"):
        table_definition_rows = list(
            await self.execute(
                "select sql from sqlite_master where name = :n and type=:t",
                {"n": table, "t": type_},
            )
        )
        if not table_definition_rows:
            return None
        bits = [table_definition_rows[0][0] + ";"]
        # Add on any indexes
        index_rows = list(
            await self.execute(
                "select sql from sqlite_master where tbl_name = :n and type='index' and sql is not null",
                {"n": table},
            )
        )
        for index_row in index_rows:
            bits.append(index_row[0] + ";")
        return "\n".join(bits)

    async def get_view_definition(self, view):
        return await self.get_table_definition(view, "view")

    def __repr__(self):
        tags = []
        if self.is_mutable:
            tags.append("mutable")
        if self.is_memory:
            tags.append("memory")
        if self.hash:
            tags.append("hash={}".format(self.hash))
        if self.size is not None:
            tags.append("size={}".format(self.size))
        tags_str = ""
        if tags:
            tags_str = " ({})".format(", ".join(tags))
        return "<Database: {}{}>".format(self.name, tags_str)
