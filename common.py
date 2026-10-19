"""Settings and small helpers shared by the scripts. You do not run this file."""
import os, json, mariadb, requests

# --- Settings can be overridden in a file called .env next to this one, e.g. DB_PORT=3306
# for a MariaDB installed on your machine instead of the one in docker-compose.yml.
_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env):
    for line in open(_env):
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.strip().split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

# --- Database. The defaults match docker-compose.yml (port 3307, so it does not collide with
# a MariaDB already running on the usual port 3306). ---
DB = dict(host=os.environ.get("DB_HOST", "127.0.0.1"),
          port=int(os.environ.get("DB_PORT", 3307)),
          user=os.environ.get("DB_USER", "wikirag"),
          password=os.environ.get("DB_PASSWORD", "wikirag"),
          database=os.environ.get("DB_NAME", "wikirag"))

# --- Embedding model, run by Ollama on this machine. ---
OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = "bge-m3"
CONTEXT = 8192   # tokens bge-m3 can read.
# Ollama needs both settings: num_ctx alone is not enough. An embedding must fit in one
# batch, and Ollama's default batch is 2,048 tokens, so longer texts are refused or cut.
OPTIONS = {"num_ctx": CONTEXT, "num_batch": CONTEXT}


# How many candidates a vector index search looks at (default 20). With M=16, 80 found 100% of
# the exact top 10 for our test questions in ~5 ms (index_recall.py).
EF_SEARCH = 80


def connect():
    con = mariadb.connect(**DB, autocommit=False)
    con.cursor().execute(f"SET mhnsw_ef_search = {EF_SEARCH}")
    return con


def embed(texts, truncate=True):
    """Turn a list of texts into vectors with the embedding model.

    With truncate=False, Ollama refuses texts longer than CONTEXT instead of cutting them,
    which is how embed.py finds out which articles are too long.
    Returns (vectors, number of tokens read).
    """
    r = requests.post(f"{OLLAMA}/api/embed", timeout=600, json={
        "model": MODEL, "input": texts, "truncate": truncate,
        "options": OPTIONS})
    if r.status_code != 200:
        raise ValueError(r.text)
    data = r.json()
    return data["embeddings"], data.get("prompt_eval_count", 0)


def vector_text(vector):
    """MariaDB reads a vector from text like '[0.1,0.2,...]' with VEC_FromText()."""
    return json.dumps(vector)


# --- The searches. search.py, app.py and evaluate.py all use these. ---

# Vector search, no category. The vector search stands alone in a subquery: ORDER BY the
# distance, LIMIT, on article_vector only. That is the shape in which MariaDB uses the vector
# index (~5 ms). Written as one flat JOIN, the same query read ~22,000 rows and took ~50 ms.
VECTOR_SQL = """
SELECT a.lang, a.page_id, a.wikidata_id, a.title, a.url, v.distance
FROM (SELECT lang, page_id, VEC_DISTANCE_COSINE(embedding, VEC_FromText(?)) AS distance
      FROM article_vector
      {where}
      ORDER BY distance
      LIMIT ?) AS v
JOIN article a USING (lang, page_id)
ORDER BY v.distance"""

# A category and all its subcategories, found by walking the category tree (recursive CTE).
# CAST: the first row sets the column size, and subcategory names can be longer.
CATEGORY_TREE = """
WITH RECURSIVE cats AS (
  SELECT CAST(? AS VARCHAR(255)) AS name
  UNION
  SELECT l.child FROM category_link l JOIN cats ON l.parent = cats.name)"""

IN_CATEGORY = """EXISTS (SELECT 1 FROM article_category c JOIN cats ON c.category = cats.name
              WHERE c.lang = a.lang AND c.page_id = a.page_id)"""

# Vector search inside a category: one statement. MariaDB picks the category's articles first
# and compares only those, exactly - fast for small categories, slower for big ones (README).
VECTOR_IN_CATEGORY_SQL = CATEGORY_TREE + """
SELECT a.lang, a.page_id, a.wikidata_id, a.title, a.url,
       VEC_DISTANCE_COSINE(v.embedding, VEC_FromText(?)) AS distance
FROM article_vector v
JOIN article a USING (lang, page_id)
WHERE """ + IN_CATEGORY + """
  {and_lang}
ORDER BY distance
LIMIT ?"""

KEYWORD_SQL = """{tree}
SELECT a.lang, a.page_id, a.wikidata_id, a.title, a.url,
       MATCH(a.title, a.text) AGAINST (?) AS score
FROM article a
WHERE MATCH(a.title, a.text) AGAINST (?) {and_lang} {and_category}
ORDER BY score DESC
LIMIT ?"""


def search(cur, question, mode="vector", lang=None, category=None, limit=10, vector=None):
    """Run one search. Returns (sql, rows); each row is a dict.

    mode "vector": semantic search - the question is embedded with the same model as the
    articles, and MariaDB returns the closest vectors (smaller distance = closer).
    Pass vector= to skip embedding the question (evaluate.py does, to time the two apart).
    mode "keyword": MariaDB's ordinary full-text search (higher score = better match).
    lang: only fi, sv or en. category: only this Finnish category and its subcategories.
    """
    if mode == "keyword":
        sql = KEYWORD_SQL.format(tree=CATEGORY_TREE if category else "",
                                 and_lang="AND a.lang = ?" if lang else "",
                                 and_category="AND " + IN_CATEGORY if category else "")
        params = ([category] if category else []) + [question, question] + ([lang] if lang else []) + [limit]
    else:
        if vector is None:
            [vector], _ = embed([question])
        if category:
            sql = VECTOR_IN_CATEGORY_SQL.format(and_lang="AND a.lang = ?" if lang else "")
            params = [category, vector_text(vector)] + ([lang] if lang else []) + [limit]
        else:
            sql = VECTOR_SQL.format(where="WHERE lang = ?" if lang else "")
            params = [vector_text(vector)] + ([lang] if lang else []) + [limit]
    cur.execute(sql, params)
    columns = [d[0] for d in cur.description]
    return sql.strip(), [dict(zip(columns, row)) for row in cur.fetchall()]


def other_languages(cur, rows):
    """For each result, the same topic in the other languages: {wikidata_id: [(lang, title, url)]}."""
    ids = {r["wikidata_id"] for r in rows if r["wikidata_id"]}
    if not ids:
        return {}
    cur.execute(f"SELECT wikidata_id, lang, title, url FROM article WHERE wikidata_id IN "
                f"({', '.join('?' * len(ids))}) ORDER BY lang", list(ids))
    found = {}
    for wikidata_id, lang, title, url in cur.fetchall():
        found.setdefault(wikidata_id, []).append((lang, title, url))
    return found
