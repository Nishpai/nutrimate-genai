"""Step 3: per-user temporal split.

Each user's ratings are sorted by date. The first 70% go to train, the next 10% to
validation and the last 20% to test. Models only ever see a user's past when they
are scored on that user's future, which is how the app is used.
"""

from __future__ import annotations

import json

import polars as pl

from nutrimate_core.paths import PROCESSED, params


def main():
    p = params()["split"]
    inter = pl.read_parquet(PROCESSED / "interactions.parquet")
    d = inter.sort(["user_id", "ts", "recipe_id"]).with_columns(
        pl.int_range(pl.len()).over("user_id").alias("pos"),
        pl.len().over("user_id").alias("n"),
    )
    train_end = (pl.col("n") * p["train"]).round()
    val_end = (pl.col("n") * (p["train"] + p["val"])).round()
    d = d.with_columns(
        pl.when(pl.col("pos") < train_end).then(pl.lit("train"))
        .when(pl.col("pos") < val_end).then(pl.lit("val"))
        .otherwise(pl.lit("test")).alias("split")
    ).drop(["pos", "n"])
    d.write_parquet(PROCESSED / "split.parquet")
    counts = dict(d["split"].value_counts().iter_rows())
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
