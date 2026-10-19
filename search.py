"""Search the articles from the command line.

    python search.py "who led Finland in the Winter War"
    python search.py --lang fi "talvisodan johtajat"
    python search.py --keyword "Mannerheim"        # ordinary full-text search, for comparison
    python search.py --category Talvisota "peace negotiations"   # only in this category

Works while embed.py is running: it searches whatever is embedded so far.
"""
import argparse, time
from common import connect, search

parser = argparse.ArgumentParser()
parser.add_argument("question")
parser.add_argument("--lang", help="only this language: fi, en or sv")
parser.add_argument("--category", help="only this Finnish category and its subcategories")
parser.add_argument("--limit", type=int, default=10)
parser.add_argument("--keyword", action="store_true", help="full-text search instead of vectors")
parser.add_argument("--sql", action="store_true", help="print the SQL statement")
args = parser.parse_args()

con = connect()
cur = con.cursor()
t = time.time()
sql, rows = search(cur, args.question, mode="keyword" if args.keyword else "vector",
                   lang=args.lang, category=args.category, limit=args.limit)
if args.sql:
    print(sql, "\n")
print(f"({len(rows)} results in {(time.time() - t) * 1000:.0f} ms, including embedding the question)\n")
for r in rows:
    score = r.get("distance", r.get("score"))
    print(f"{score:7.4f}  {r['lang']}  {r['title']}\n          {r['url']}")
con.close()
