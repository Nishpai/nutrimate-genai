"""Step 1: copy the raw sources into Parquet, and a generic ingester for any large file.

Raw sources (data/raw/):
  foodrs.duckdb                 Food.com recipes and reviews (about 750 MB)
  Anuvaad_INDB_2024.11.xlsx     Indian Nutrient Databank
  usda_sr_legacy/*.csv          USDA FoodData Central SR Legacy

The DuckDB tables are copied with COPY ... TO parquet, which streams and never loads a
whole table into Python. The USDA CSVs go through Polars lazy scans and sink_parquet.

ingest_file() handles CSV, TSV, JSON lines, JSON arrays and Parquet of any size. CSV
and Parquet are read in batches, cleaned batch by batch and written with a Parquet
writer, so memory stays flat however large the file is. It is used by the admin
dataset jobs and was tested on a 1 GB+ CSV (see README).
"""

from __future__ import annotations

import csv
import gzip
import re
import time
from collections.abc import Callable
from pathlib import Path

import duckdb
import pandas as pd
import polars as pl
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from nutrimate_core.paths import INTERIM, RAW

NULL_STRINGS = ["", "na", "n/a", "nan", "null", "none", "-", "--"]
# column names that look like nutrient amounts: cast to float, negatives become null
NUTRIENT_HINT = re.compile(r"kcal|calor|energy|protein|carb|fat|fib(er|re)|sugar|sodium|salt")

ProgressFn = Callable[[float, str], None]


def _noop(p: float, msg: str) -> None:
    pass


def snake(name: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name).strip())
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()
    return s or "column"


def unique_names(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        base = snake(n)
        k = seen.get(base, 0)
        out.append(base if k == 0 else f"{base}_{k}")
        seen[base] = k + 1
    return out


def clean_frame(df: pl.DataFrame) -> pl.DataFrame:
    """Same rules for every batch: trimmed strings, null markers to null, nutrient columns
    to float with negative values set to null. Missing values are never filled with 0."""
    df = df.rename(dict(zip(df.columns, unique_names(df.columns))))
    exprs = []
    for name, dtype in zip(df.columns, df.dtypes):
        col = pl.col(name)
        if dtype == pl.String:
            col = col.str.strip_chars()
            col = pl.when(col.str.to_lowercase().is_in(NULL_STRINGS)).then(None).otherwise(col)
            if NUTRIENT_HINT.search(name):
                col = col.str.replace_all(",", "").cast(pl.Float64, strict=False)
        if NUTRIENT_HINT.search(name) and (dtype.is_numeric() or dtype == pl.String):
            col = col.cast(pl.Float64, strict=False)
            col = pl.when(col < 0).then(None).otherwise(col)
        exprs.append(col.alias(name))
    return df.select(exprs)


def detect_format(path: Path) -> str:
    name = path.name.lower()
    if name.endswith((".parquet", ".pq")):
        return "parquet"
    if name.endswith((".jsonl", ".ndjson")):
        return "jsonl"
    if name.endswith(".json"):
        with open(path, "rb") as f:
            head = f.read(2048).lstrip()
        return "json_array" if head[:1] == b"[" else "jsonl"
    if name.endswith((".tsv", ".tab")):
        return "tsv"
    if name.endswith((".csv", ".csv.gz", ".txt")):
        return "csv"
    raise ValueError(f"unsupported file type: {path.name} (use CSV, TSV, JSON, JSON lines or Parquet)")


CSV_BLOCK_BYTES = 4 << 20
CSV_BATCH_BYTES = 64 << 20


def _csv_header(path: Path, sep: str) -> list[str]:
    opener = gzip.open if path.name.lower().endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace", newline="") as f:
        header = next(csv.reader(f, delimiter=sep), [])
    if not header:
        raise ValueError("the file has no header row")
    header[0] = header[0].lstrip("\ufeff")
    return unique_names([h.strip() or f"column_{i + 1}" for i, h in enumerate(header)])


def _csv_batches(path: Path, sep: str, size: int, stats: dict):
    """Stream a CSV with the Arrow reader in 4 MB blocks, grouped into batches of about 64 MB. Every column is read
    as text, so a bad value in row 5 million can not break the schema; types are
    inferred per column after cleaning. Rows with the wrong number of fields are skipped
    and counted rather than failing the whole file."""
    names = _csv_header(path, sep)
    stats["skipped_rows"] = 0

    def on_invalid(_row):
        stats["skipped_rows"] += 1
        return "skip"

    with open(path, "rb") as raw:
        gz = path.name.lower().endswith(".gz")
        stream = pa.CompressedInputStream(pa.PythonFile(raw, mode="r"), "gzip") if gz else raw
        reader = pacsv.open_csv(
            stream,
            read_options=pacsv.ReadOptions(column_names=names, skip_rows=1, block_size=CSV_BLOCK_BYTES,
                                           encoding="utf8"),
            parse_options=pacsv.ParseOptions(delimiter=sep, newlines_in_values=True,
                                             invalid_row_handler=on_invalid),
            convert_options=pacsv.ConvertOptions(column_types={n: pa.string() for n in names},
                                                 strings_can_be_null=False),
        )
        # small parse blocks keep the reader's read-ahead small; they are grouped into
        # batches of about CSV_BATCH_BYTES so each cleaning step still sees many rows
        pending, pending_bytes = [], 0
        for batch in reader:
            if batch.num_rows:
                pending.append(batch)
                pending_bytes += batch.nbytes
            if pending_bytes >= CSV_BATCH_BYTES:
                yield pl.from_arrow(pa.Table.from_batches(pending)), min(raw.tell() / size, 0.99)
                pending, pending_bytes = [], 0
        if pending:
            yield pl.from_arrow(pa.Table.from_batches(pending)), 0.99


def _batches(path: Path, fmt: str, batch_rows: int, stats: dict | None = None):
    """Yield (polars batch, fraction of input read)."""
    size = max(path.stat().st_size, 1)
    if fmt in ("csv", "tsv"):
        yield from _csv_batches(path, "\t" if fmt == "tsv" else ",", size, stats if stats is not None else {})
    elif fmt == "parquet":
        pf = pq.ParquetFile(path)
        n = max(pf.num_row_groups, 1)
        for i in range(pf.num_row_groups):
            yield pl.from_arrow(pf.read_row_group(i)), (i + 1) / n
    elif fmt == "jsonl":
        # read line blocks so the whole file is never in memory
        with open(path, "rb") as f:
            done = 0
            while True:
                lines = f.readlines(64 << 20)
                if not lines:
                    break
                done += sum(len(x) for x in lines)
                yield pl.read_ndjson(b"".join(lines)), min(done / size, 0.99)
    elif fmt == "json_array":
        # DuckDB parses a top-level JSON array in a streaming way; it is converted to a
        # temporary Parquet file first and then read back row group by row group
        tmp = path.with_name(path.name + ".tmp.parquet")
        con = duckdb.connect()
        src = str(path).replace("'", "''")
        con.execute(f"COPY (SELECT * FROM read_json_auto('{src}')) TO '{tmp.as_posix()}' (FORMAT parquet)")
        con.close()
        try:
            yield from _batches(tmp, "parquet", batch_rows)
        finally:
            tmp.unlink(missing_ok=True)


def _unify(df: pl.DataFrame, schema: dict | None) -> pl.DataFrame:
    """Make later batches match the first batch's column types."""
    if schema is None:
        return df
    cols = []
    for name, dtype in schema.items():
        if name in df.columns:
            cols.append(pl.col(name).cast(dtype, strict=False))
        else:
            cols.append(pl.lit(None, dtype=dtype).alias(name))
    return df.select(cols)


def _infer_types(df: pl.DataFrame) -> pl.DataFrame:
    """Columns read as text become numbers when every non-null value parses as one."""
    out = []
    for name, dtype in zip(df.columns, df.dtypes):
        if dtype == pl.String:
            as_num = df[name].cast(pl.Float64, strict=False)
            if as_num.null_count() == df[name].null_count() and df[name].null_count() < len(df):
                out.append(as_num.alias(name))
                continue
        out.append(df[name])
    return pl.DataFrame(out)


def ingest_file(src: Path, dest: Path, batch_rows: int = 250_000,
                progress: ProgressFn = _noop) -> dict:
    """Clean any supported file into one Parquet file, batch by batch. Returns a profile."""
    src, dest = Path(src), Path(dest)
    fmt = detect_format(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    t0 = time.time()
    writer, schema, rows, stats = None, None, 0, {}
    progress(0.01, f"reading {fmt}")
    try:
        for batch, frac in _batches(src, fmt, batch_rows, stats):
            batch = clean_frame(batch)
            if schema is None:
                batch = _infer_types(batch)
                schema = dict(zip(batch.columns, batch.dtypes))
            batch = _unify(batch, schema)
            table = batch.to_arrow()
            if writer is None:
                writer = pq.ParquetWriter(tmp, table.schema, compression="zstd")
            writer.write_table(table.cast(writer.schema))
            rows += len(batch)
            progress(0.05 + 0.75 * frac, f"cleaned {rows:,} rows")
    finally:
        if writer is not None:
            writer.close()
    if writer is None:
        raise ValueError("the file has no rows")
    tmp.replace(dest)
    progress(0.85, "profiling columns")
    prof = profile_parquet(dest)
    prof.update({"source_format": fmt, "source_bytes": src.stat().st_size,
                 "skipped_rows": stats.get("skipped_rows", 0),
                 "output_bytes": dest.stat().st_size, "seconds": round(time.time() - t0, 1)})
    progress(1.0, "done")
    return prof


def profile_parquet(path: Path) -> dict:
    """Row count, nulls and ranges per column. They are read from the Parquet row group
    statistics, so no column data is loaded; Polars is used only when a file has none."""
    md = pq.ParquetFile(path).metadata
    schema = pl.scan_parquet(path).collect_schema()
    names = list(schema.keys())
    acc = {n: {"nulls": 0, "min": None, "max": None, "ok": True} for n in names}
    for g in range(md.num_row_groups):
        rg = md.row_group(g)
        for i in range(rg.num_columns):
            col = rg.column(i)
            name = col.path_in_schema
            if name not in acc:
                continue
            st, a = col.statistics, acc[name]
            if st is None or not st.has_null_count:
                a["ok"] = False
                continue
            a["nulls"] += st.null_count
            if schema[name].is_numeric() and st.has_min_max:
                a["min"] = st.min if a["min"] is None else min(a["min"], st.min)
                a["max"] = st.max if a["max"] is None else max(a["max"], st.max)
    if not all(a["ok"] for a in acc.values()):
        return _profile_parquet_scan(path)
    n = md.num_rows
    cols = []
    for name, dtype in schema.items():
        a = acc[name]
        c = {"name": name, "type": str(dtype), "nulls": int(a["nulls"]),
             "null_pct": round(100 * a["nulls"] / n, 2) if n else 0.0}
        if dtype.is_numeric():
            c["min"], c["max"] = a["min"], a["max"]
        cols.append(c)
    return {"rows": n, "columns": cols}


def _profile_parquet_scan(path: Path) -> dict:
    lf = pl.scan_parquet(path)
    schema = lf.collect_schema()
    aggs = [pl.len().alias("__rows")]
    for name, dtype in schema.items():
        aggs.append(pl.col(name).null_count().alias(f"{name}__nulls"))
        if dtype.is_numeric():
            aggs += [pl.col(name).min().alias(f"{name}__min"), pl.col(name).max().alias(f"{name}__max")]
    r = lf.select(aggs).collect(engine="streaming").row(0, named=True)
    n = int(r["__rows"])
    cols = []
    for name, dtype in schema.items():
        c = {"name": name, "type": str(dtype), "nulls": int(r[f"{name}__nulls"]),
             "null_pct": round(100 * r[f"{name}__nulls"] / n, 2) if n else 0.0}
        if dtype.is_numeric():
            c["min"], c["max"] = r[f"{name}__min"], r[f"{name}__max"]
        cols.append(c)
    return {"rows": n, "columns": cols}


# --------------------------------------------------------------------- raw sources
def ingest_raw() -> None:
    INTERIM.mkdir(parents=True, exist_ok=True)
    db = RAW / "foodrs.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    for table in ("recipes_raw", "reviews_raw"):
        out = INTERIM / f"{table}.parquet"
        t0 = time.time()
        con.execute(f"COPY (SELECT * FROM {table}) TO '{out.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
        n = con.execute(f"SELECT count(*) FROM '{out.as_posix()}'").fetchone()[0]
        print(f"{table}: {n:,} rows -> {out.name} in {time.time() - t0:.1f}s")
    con.close()

    indb = pd.read_excel(RAW / "Anuvaad_INDB_2024.11.xlsx")
    indb = indb.astype({c: "string" for c in indb.columns if indb[c].dtype == object})
    pl.from_pandas(indb).write_parquet(INTERIM / "indb.parquet")
    print(f"indb: {len(indb):,} rows")

    base = next(RAW.glob("usda_sr_legacy/**/food.csv")).parent
    for name in ("food", "food_nutrient", "nutrient"):
        out = INTERIM / f"usda_{name}.parquet"
        pl.scan_csv(base / f"{name}.csv", infer_schema_length=10000).sink_parquet(out)
        print(f"usda {name}: {pl.scan_parquet(out).select(pl.len()).collect().item():,} rows")


if __name__ == "__main__":
    ingest_raw()
