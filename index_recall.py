"""How close does the vector index get to the exact answer, and how fast?

    python index_recall.py                        # ef_search 20 ... 640 on the current index
    python index_recall.py --ef 20,100 --runs 5

The vector index (HNSW) is approximate: it walks a graph instead of comparing the question with
every vector. For each test question this script gets the exact top 10 (index switched off, all
vectors compared) and the index's top 10, and reports recall@10 = how many of the exact 10 the
index found. Two settings decide it:
  M          links per node in the graph, fixed when the index is built:  VECTOR INDEX (...) M=16
  ef_search  how many candidates a search looks at, per session:          SET mhnsw_ef_search = 100
"""
import argparse, csv, statistics, time
from common import connect, embed, vector_text

parser = argparse.ArgumentParser()
parser.add_argument("--ef", default="20,40,80,160,320,640", help="mhnsw_ef_search values to try")
parser.add_argument("--runs", type=int, default=3, help="repeat each query this many times for timing")
args = parser.parse_args()

# The vector search on its own, with ORDER BY distance LIMIT directly on article_vector:
# the shape the optimizer needs to use the vector index.
INDEXED = """SELECT lang, page_id FROM article_vector
             ORDER BY VEC_DISTANCE_COSINE(embedding, VEC_FromText(?)) LIMIT 10"""
EXACT = """SELECT lang, page_id FROM article_vector IGNORE INDEX (embedding)
           ORDER BY VEC_DISTANCE_COSINE(embedding, VEC_FromText(?)) LIMIT 10"""

con = connect()
cur = con.cursor()
cur.execute("SELECT @@version, @@mhnsw_max_cache_size")
version, cache = cur.fetchone()
cur.execute("SHOW CREATE TABLE article_vector")
index_line = [l.strip() for l in cur.fetchone()[1].splitlines() if "VECTOR KEY" in l][0]
print(f"MariaDB {version}, {index_line}, mhnsw_max_cache_size = {cache / 2**20:.0f} MB\n")

with open("data/test-questions.tsv") as f:
    vectors = [vector_text(embed([q["question"]])[0][0]) for q in csv.DictReader(f, delimiter="\t")]


def timed(sql, v):
    times = []
    for _ in range(args.runs):
        t = time.perf_counter()
        cur.execute(sql, (v,))
        rows = cur.fetchall()
        times.append((time.perf_counter() - t) * 1000)
    return set(rows), times


exact, exact_ms = [], []
for v in vectors:
    rows, ms = timed(EXACT, v)
    exact.append(rows)
    exact_ms += ms
print("| ef_search | recall@10 | worst question | median ms | slowest ms |")
print("|---|---|---|---|---|")
print(f"| exact (no index) | 100% | 100% | {statistics.median(exact_ms):.1f} | {max(exact_ms):.1f} |")
for ef in [int(x) for x in args.ef.split(",")]:
    cur.execute(f"SET mhnsw_ef_search = {ef}")
    recalls, all_ms = [], []
    for v, truth in zip(vectors, exact):
        rows, ms = timed(INDEXED, v)
        recalls.append(len(rows & truth) / len(truth))
        all_ms += ms
    print(f"| {ef} | {statistics.mean(recalls):.0%} | {min(recalls):.0%} "
          f"| {statistics.median(all_ms):.1f} | {max(all_ms):.1f} |")
con.close()
