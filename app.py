"""The search page.

    python app.py               # then open http://localhost:8000
    python app.py --port 8001   # another port

Works while embed.py is running: it searches whatever is embedded so far.
"""
import argparse, time
from flask import Flask, request, render_template_string
from common import connect, search, other_languages

app = Flask(__name__)

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wikipedia RAG with MariaDB Vector</title>
<style>
  body { font: 16px/1.5 system-ui, sans-serif; max-width: 52rem; margin: 2rem auto; padding: 0 1rem;
         color: #1d2329; background: #fff; }
  h1 { font-size: 1.4rem; margin-bottom: .2rem; }
  .muted { color: #667; font-size: .9rem; }
  form { display: flex; flex-wrap: wrap; gap: .5rem; margin: 1rem 0; align-items: center; }
  input[type=text] { flex: 1 1 20rem; font-size: 1rem; padding: .5rem; }
  button { font-size: 1rem; padding: .5rem 1rem; }
  ol { padding-left: 1.5rem; }
  li { margin-bottom: .8rem; }
  .lang { display: inline-block; font-size: .75rem; font-weight: 600; text-transform: uppercase;
          background: #e8edf2; border-radius: 3px; padding: 0 .35rem; margin-right: .3rem; }
  .score { font-variant-numeric: tabular-nums; color: #667; font-size: .85rem; margin-left: .4rem; }
  .also { font-size: .85rem; color: #667; }
  pre { background: #f4f6f8; padding: .8rem; overflow-x: auto; font-size: .8rem; }
  @media (prefers-color-scheme: dark) {
    body { color: #e3e6ea; background: #15191d; } .muted, .score, .also { color: #9aa3ad; }
    .lang { background: #2a3139; } pre { background: #1e242a; } a { color: #8ab4f8; }
  }
</style></head><body>
<h1>Wikipedia RAG with MariaDB Vector</h1>
<div class="muted">History of Finland in Finnish, English and Swedish ·
  {{ embedded }} of {{ total }} articles embedded</div>

<form>
  <input type="text" name="q" value="{{ q }}" placeholder="Ask in English, Finnish or Swedish" autofocus>
  <select name="lang">
    <option value="">all languages</option>
    {% for l in ["fi", "en", "sv"] %}<option {{ "selected" if l == lang }}>{{ l }}</option>{% endfor %}
  </select>
  <input type="text" name="category" value="{{ category or "" }}" list="categories"
         placeholder="any category" style="flex: 0 1 14rem">
  <datalist id="categories">{% for c, n in categories %}<option value="{{ c }}">{{ n }} articles</option>{% endfor %}</datalist>
  <label><input type="radio" name="mode" value="vector" {{ "checked" if mode != "keyword" }}> Vector</label>
  <label><input type="radio" name="mode" value="keyword" {{ "checked" if mode == "keyword" }}> Keyword</label>
  <button>Search</button>
</form>

{% if q %}
  <div class="muted">{{ rows|length }} results in {{ ms }} ms
    ({{ "smaller distance = closer" if mode != "keyword" else "higher score = better match" }})</div>
  <ol>
  {% for r in rows %}
    <li><span class="lang">{{ r.lang }}</span><a href="{{ r.url }}">{{ r.title }}</a>
      <span class="score">{{ "%.4f"|format(r.distance if mode != "keyword" else r.score) }}</span>
      {% set others = also.get(r.wikidata_id, [])|rejectattr(0, "equalto", r.lang)|list %}
      {% if others %}<div class="also">also in:
        {% for l, title, url in others %}<a href="{{ url }}">{{ l }}: {{ title }}</a>{{ " · " if not loop.last }}{% endfor %}
      </div>{% endif %}
    </li>
  {% endfor %}
  </ol>
  <details><summary>The SQL that produced this</summary><pre>{{ sql }}</pre></details>
{% endif %}
</body></html>"""


@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    mode = request.args.get("mode", "vector")
    lang = request.args.get("lang") or None
    category = request.args.get("category", "").strip() or None
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT category, COUNT(*) FROM article_category GROUP BY category ORDER BY category")
    categories = cur.fetchall()
    cur.execute("SELECT (SELECT COUNT(*) FROM article_vector), (SELECT COUNT(*) FROM article)")
    embedded, total = cur.fetchone()
    rows, sql, also, ms = [], "", {}, 0
    if q:
        t = time.time()
        sql, rows = search(cur, q, mode=mode, lang=lang, category=category)
        ms = round((time.time() - t) * 1000)
        also = other_languages(cur, rows)
        if mode != "keyword":
            sql = sql.replace("VEC_FromText(?)", "VEC_FromText('[0.0213, -0.0458, … 1024 numbers]')")
        if category:   # for display only: the query itself sends the category as a parameter
            sql = sql.replace("CAST(? AS", "CAST('" + category.replace("'", "''") + "' AS")
    con.close()
    return render_template_string(PAGE, q=q, mode=mode, lang=lang, category=category,
                                  categories=categories, rows=rows, sql=sql, also=also,
                                  ms=ms, embedded=f"{embedded:,}", total=f"{total:,}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    app.run(port=parser.parse_args().port)
