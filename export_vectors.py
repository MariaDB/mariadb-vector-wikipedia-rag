"""Save the computed vectors as data/vectors-bge-m3-<lang>.parquet, so others can skip embedding.

    python export_vectors.py

You do not need to run this: the files are published (see README, step 3). load.py reads them.
Each row: lang, page_id, model, truncated, embedding (1024 float32 numbers).
"""
import pyarrow as pa, pyarrow.parquet as pq
from common import connect, MODEL

DIMENSIONS = 1024

con = connect()
cur = con.cursor()
for lang in ("fi", "sv", "en"):
    cur.execute("SELECT page_id, model, truncated, embedding FROM article_vector "
                "WHERE lang = ? ORDER BY page_id", (lang,))
    rows = cur.fetchall()
    # MariaDB returns a VECTOR as raw bytes: 1024 float32 numbers, little-endian.
    values = pa.Array.from_buffers(pa.float32(), len(rows) * DIMENSIONS,
                                   [None, pa.py_buffer(b"".join(bytes(r[3]) for r in rows))])
    table = pa.table({
        "lang": [lang] * len(rows),
        "page_id": pa.array([r[0] for r in rows], pa.uint32()),
        "model": [r[1] for r in rows],
        "truncated": [bool(r[2]) for r in rows],
        "embedding": pa.FixedSizeListArray.from_arrays(values, DIMENSIONS),
    })
    path = f"data/vectors-{MODEL}-{lang}.parquet"
    pq.write_table(table, path, compression="zstd")
    print(f"{path}: {len(rows)} vectors")
con.close()
