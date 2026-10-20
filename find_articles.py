"""Find every Finnish article in the category "Suomen historia" and its subcategories.

Then adds the main article of every named category one level deeper: famous people and things
have a category of their own, with their article inside it (Luokka:Urho Kekkonen holds the article
Urho Kekkonen). Walking that whole level would double the set with lists of politicians and
councillors; taking only these main articles adds ~460, including the presidents.

Writes three files, takes about 10 minutes:
  data/articles-fi.tsv            page_id, title, level (how deep below the root it was found)
  data/category-links-fi.tsv      parent category, subcategory — the category tree
  data/article-categories-fi.tsv  page_id, category — which categories each article is in
You only need this to rebuild them; the files are in the repo.

Run:  python find_articles.py
"""
import sys, time, requests

API = "https://fi.wikipedia.org/w/api.php"
ROOT = "Luokka:Suomen historia"
LEVELS = 3      # how many levels of subcategories to follow (3 gives about 19,000 articles)
PAUSE = 0.4     # seconds between requests, to stay under Wikipedia's 200 requests/minute

session = requests.Session()
session.headers["User-Agent"] = "mariadb-vector-wikipedia-rag/1.0 (https://github.com/MariaDB/mariadb-vector-wikipedia-rag)"


def api_all(params, key):
    """Call the Wikipedia API and follow 'continue' until the whole list is read."""
    params = dict(params, format="json", formatversion="2")
    while True:
        time.sleep(PAUSE)
        r = session.get(API, params=params, timeout=60)
        if r.status_code != 200:
            wait = int(r.headers.get("Retry-After", 10))
            print(f"  Wikipedia answered {r.status_code}, waiting {wait} s ...", file=sys.stderr)
            time.sleep(wait)
            continue
        data = r.json()
        yield from data["query"][key]
        if "continue" not in data:
            return
        params.update(data["continue"])


def name(title):
    return title.removeprefix("Luokka:")


categories = {ROOT}
articles = {}                   # page_id -> (title, level)
links = set()                   # (parent category, subcategory)
memberships = set()             # (page_id, category)
deeper = {}                     # category one level below the walk -> its parent
this_level = [ROOT]
for level in range(LEVELS + 1):
    next_level = []
    for cat in this_level:
        for m in api_all({"action": "query", "list": "categorymembers", "cmtitle": cat,
                          "cmlimit": "500", "cmprop": "ids|title"}, "categorymembers"):
            if m["ns"] == 14 and level < LEVELS:                                   # a category
                links.add((name(cat), name(m["title"])))
                if m["title"] not in categories:
                    categories.add(m["title"])
                    next_level.append(m["title"])
            elif m["ns"] == 14:                                    # a category one level deeper
                deeper.setdefault(m["title"], cat)
            elif m["ns"] == 0:                                                     # an article
                articles.setdefault(m["pageid"], (m["title"], level))
                memberships.add((m["pageid"], name(cat)))
    print(f"level {level}: {len(categories)} categories, {len(articles)} articles", file=sys.stderr)
    this_level = next_level

# Named categories one level deeper: is there an article with exactly the category's name?
candidates = [c for c in deeper if c not in categories]
named = 0
for i in range(0, len(candidates), 50):
    batch = candidates[i:i + 50]
    for page in api_all({"action": "query", "titles": "|".join(name(c) for c in batch)}, "pages"):
        category = "Luokka:" + page.get("title", "")
        if page.get("missing") or page["ns"] != 0 or page["pageid"] in articles or category not in deeper:
            continue
        articles[page["pageid"]] = (page["title"], LEVELS + 1)
        links.add((name(deeper[category]), page["title"]))
        memberships.add((page["pageid"], page["title"]))
        named += 1
print(f"named categories one level deeper: {named} main articles added", file=sys.stderr)

with open("data/articles-fi.tsv", "w") as f:
    f.write("page_id\ttitle\tlevel\n")
    for page_id, (title, level) in sorted(articles.items()):
        f.write(f"{page_id}\t{title}\t{level}\n")
with open("data/category-links-fi.tsv", "w") as f:
    f.write("parent\tchild\n")
    for parent, child in sorted(links):
        f.write(f"{parent}\t{child}\n")
with open("data/article-categories-fi.tsv", "w") as f:
    f.write("page_id\tcategory\n")
    for page_id, cat in sorted(memberships):
        f.write(f"{page_id}\t{cat}\n")
print(f"Done: {len(articles)} articles, {len(categories)} categories, {len(links)} category links, "
      f"{len(memberships)} article-category pairs -> data/")
