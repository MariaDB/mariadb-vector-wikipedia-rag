"""Measure how well search finds the right article, and how fast.

    python evaluate.py                    # vector and keyword search, 3 runs each
    python evaluate.py --runs 5 --misses  # more runs, and list the questions that failed

Reads data/test-questions.tsv: a question in fi, sv or en, and the Finnish title of the article
that answers it. A hit is that article in ANY language — the Finnish, Swedish or English version
of the same topic (same wikidata_id) all count.

Reports, per search mode:
  hit@1, hit@5, hit@10   share of questions where the answer is in the top 1, 5, 10 results
  MRR                    mean reciprocal rank: 1 for first place, 1/2 for second, ... 0 if not in top 10
  latency                median and slowest of all runs, split into embedding the question and the SQL
"""
import argparse, csv, statistics, time
from common import connect, embed, search

parser = argparse.ArgumentParser()
parser.add_argument("--runs", type=int, default=3, help="repeat each search this many times for timing")
parser.add_argument("--modes", default="vector,keyword")
parser.add_argument("--misses", action="store_true", help="list questions whose answer was not in the top 5")
args = parser.parse_args()

con = connect()
cur = con.cursor()
with open("data/test-questions.tsv") as f:
    questions = list(csv.DictReader(f, delimiter="\t"))

# The answer as a topic: its wikidata_id, or its page_id if it has none.
for q in questions:
    cur.execute("SELECT wikidata_id, page_id FROM article WHERE lang = 'fi' AND title = ?",
                (q["expected_fi_title"],))
    q["wikidata_id"], q["page_id"] = cur.fetchone()


def rank_of_answer(q, rows):
    for i, r in enumerate(rows, 1):
        if (q["wikidata_id"] and r["wikidata_id"] == q["wikidata_id"]) or \
           (r["lang"] == "fi" and r["page_id"] == q["page_id"]):
            return i
    return None


def summary(group):
    ranks = [q["rank"] for q in group]
    hit = lambda k: sum(1 for r in ranks if r and r <= k) / len(ranks)
    mrr = sum(1 / r for r in ranks if r) / len(ranks)
    return f"{len(group):>3} | {hit(1):5.0%} | {hit(5):5.0%} | {hit(10):5.0%} | {mrr:.2f}"


for mode in args.modes.split(","):
    embed_ms, sql_ms = [], []
    for q in questions:
        for run in range(args.runs):
            vector = None
            if mode == "vector":
                t = time.perf_counter()
                [vector], _ = embed([q["question"]])
                embed_ms.append((time.perf_counter() - t) * 1000)
            t = time.perf_counter()
            _, rows = search(cur, q["question"], mode, limit=10, vector=vector)
            sql_ms.append((time.perf_counter() - t) * 1000)
        q["rank"] = rank_of_answer(q, rows)
        q["top"] = rows[0]["title"] if rows else "-"

    print(f"\n## {mode} search — {len(questions)} questions, {args.runs} runs each\n")
    print("| Questions | n | hit@1 | hit@5 | hit@10 | MRR |")
    print("|---|---|---|---|---|---|")
    print(f"| all | {summary(questions)} |")
    for lang in ("en", "sv", "fi"):
        print(f"| in {lang} | {summary([q for q in questions if q['lang'] == lang])} |")
    only_fi = [q for q in questions if q["article_exists_in"] == "fi"]
    print(f"| answer only in Finnish | {summary(only_fi)} |")
    print()
    if embed_ms:
        print(f"Embedding the question: median {statistics.median(embed_ms):.0f} ms, "
              f"slowest {max(embed_ms):.0f} ms")
    print(f"SQL query: median {statistics.median(sql_ms):.1f} ms, slowest {max(sql_ms):.1f} ms")
    if args.misses:
        print("\nNot in the top 5:")
        for q in questions:
            if not q["rank"] or q["rank"] > 5:
                print(f"- [{q['lang']}] {q['question']} → expected {q['expected_fi_title']}, "
                      f"rank {q['rank'] or '>10'}, top result: {q['top']}")
con.close()
