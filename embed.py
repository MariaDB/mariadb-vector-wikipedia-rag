"""Compute a vector for every article that does not have one yet.

    python embed.py --limit 100     # 100 articles, then stop
    python embed.py                 # everything that is left

Stop with Ctrl-C at any time and run again to continue: every batch is committed, and the
next run picks up the articles that still have no row in article_vector.

Order: topics that exist in all three languages first, the language versions of one topic
together. So the first 100 articles already give results in fi, en and sv.
"""
import argparse, time
from common import connect, embed, vector_text, MODEL

parser = argparse.ArgumentParser()
parser.add_argument("--limit", type=int, help="stop after this many articles")
parser.add_argument("--batch", type=int, default=8, help="articles per call to Ollama")
args = parser.parse_args()

NEXT = """
SELECT a.lang, a.page_id, a.title, a.text
FROM article a
LEFT JOIN article_vector v USING (lang, page_id)
LEFT JOIN (SELECT wikidata_id, COUNT(*) AS langs FROM article GROUP BY wikidata_id) t
       USING (wikidata_id)
WHERE v.page_id IS NULL
ORDER BY t.langs DESC, a.wikidata_id, a.lang
LIMIT ?"""

SAVE = """INSERT INTO article_vector (lang, page_id, model, truncated, embedding)
          VALUES (?, ?, ?, ?, VEC_FromText(?))"""

con = connect()
cur = con.cursor()
cur.execute("SELECT (SELECT COUNT(*) FROM article), (SELECT COUNT(*) FROM article_vector)")
total, already = cur.fetchone()
goal = min(total - already, args.limit or total)
print(f"{already} of {total} articles already embedded. Embedding {goal} now with {MODEL}.")

done = tokens = 0
start = time.time()
try:
    while done < goal:
        cur.execute(NEXT, (min(args.batch, goal - done),))
        batch = cur.fetchall()
        if not batch:
            break
        texts = [f"{title}\n\n{text}" for _, _, title, text in batch]
        try:
            vectors, n = embed(texts, truncate=False)
            truncated = [False] * len(batch)
        except ValueError:
            # At least one article is longer than the model reads: do them one by one,
            # cutting only the long ones, and remember which were cut.
            vectors, truncated, n = [], [], 0
            for text in texts:
                try:
                    v, k = embed([text], truncate=False)
                    truncated.append(False)
                except ValueError:
                    v, k = embed([text], truncate=True)
                    truncated.append(True)
                vectors += v
                n += k
        cur.executemany(SAVE, [(lang, page_id, MODEL, cut, vector_text(vec))
                               for (lang, page_id, _, _), vec, cut in zip(batch, vectors, truncated)])
        con.commit()
        done += len(batch)
        tokens += n
        mins = (time.time() - start) / 60
        rate = done / mins
        print(f"{already + done}/{total}  {rate:.0f} articles/min  {tokens / mins / 60:.0f} tokens/s"
              f"  ~{(goal - done) / rate:.0f} min left   last: {batch[-1][0]} {batch[-1][2]}")
except KeyboardInterrupt:
    con.rollback()
    print("\nStopped. Run again to continue.")

cur.execute("SELECT COUNT(*), SUM(truncated) FROM article_vector")
n, cut = cur.fetchone()
print(f"Embedded: {n} of {total}. Cut because too long: {cut or 0}.")
con.close()
