"""Load the data in data/ into MariaDB.

    python load.py              # articles and categories
    python load.py --vectors    # ... and the ready-made vectors, so you can skip embed.py

The vector files (110 MB) are not in the git repo; --vectors downloads them from the
repository's GitHub release the first time.

Safe to run again: rows already in a table are skipped.
"""
import argparse, csv, glob, os, struct, time
import requests
import pyarrow.parquet as pq
from common import connect, MODEL

BATCH = 200
RELEASE = "https://github.com/robertsilen/mariadb-vector-wikipedia-rag/releases/download/data-v1"

parser = argparse.ArgumentParser()
parser.add_argument("--vectors", action="store_true", help=f"also load data/vectors-{MODEL}-*.parquet")
args = parser.parse_args()

con = connect()
cur = con.cursor()


def insert(sql, rows):
    for i in range(0, len(rows), BATCH):
        cur.executemany(sql, rows[i:i + BATCH])
        con.commit()


def count(table):
    cur.execute(f"SELECT lang, COUNT(*) FROM {table} GROUP BY lang")
    return dict(cur.fetchall())


# 1. Articles
for path in sorted(glob.glob("data/articles-*.parquet")):
    rows = [(r["lang"], r["page_id"], r["rev_id"], r["wikidata_id"], r["title"], r["url"],
             r["date_modified"], r["text"]) for r in pq.read_table(path).to_pylist()]
    insert("""INSERT IGNORE INTO article
              (lang, page_id, rev_id, wikidata_id, title, url, date_modified, text)
              VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", rows)
    print(f"{path}: {len(rows)} articles")
print("Articles in the table:", count("article"))

# 2. Categories: the tree, and the Finnish articles' categories ...
with open("data/category-links-fi.tsv") as f:
    insert("INSERT IGNORE INTO category_link (parent, child) VALUES (?, ?)",
           [(r["parent"], r["child"]) for r in csv.DictReader(f, delimiter="\t")])
cur.execute("SELECT page_id FROM article WHERE lang = 'fi'")
finnish = {page_id for (page_id,) in cur.fetchall()}
with open("data/article-categories-fi.tsv") as f:
    insert("INSERT IGNORE INTO article_category (lang, page_id, category) VALUES ('fi', ?, ?)",
           [(int(r["page_id"]), r["category"]) for r in csv.DictReader(f, delimiter="\t")
            if int(r["page_id"]) in finnish])
# ... which the Swedish and English articles on the same topic inherit.
cur.execute("""INSERT IGNORE INTO article_category (lang, page_id, category)
               SELECT other.lang, other.page_id, c.category
               FROM article_category c
               JOIN article fi    ON fi.lang = 'fi' AND fi.page_id = c.page_id
               JOIN article other ON other.wikidata_id = fi.wikidata_id AND other.lang <> 'fi'
               WHERE c.lang = 'fi'""")
con.commit()
cur.execute("SELECT COUNT(*) FROM category_link")
print(f"Category links: {cur.fetchone()[0]}. Article-category pairs:", count("article_category"))

# 3. Ready-made vectors (optional): replaces step 4, embed.py.
if args.vectors:
    for lang in ("en", "fi", "sv"):
        path = f"data/vectors-{MODEL}-{lang}.parquet"
        if not os.path.exists(path):
            print(f"Downloading {path} ...")
            with requests.get(f"{RELEASE}/{os.path.basename(path)}", stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(path + ".part", "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            os.rename(path + ".part", path)
        t = time.time()
        table = pq.read_table(path)
        # MariaDB takes a VECTOR as raw bytes: 1024 float32 numbers, little-endian.
        rows = [(r["lang"], r["page_id"], r["model"], r["truncated"],
                 struct.pack(f"<{len(r['embedding'])}f", *r["embedding"]))
                for r in table.to_pylist()]
        insert("""INSERT IGNORE INTO article_vector (lang, page_id, model, truncated, embedding)
                  VALUES (?, ?, ?, ?, ?)""", rows)
        print(f"{path}: {len(rows)} vectors, {time.time() - t:.0f} s")
    print("Vectors in the table:", count("article_vector"))
con.close()
