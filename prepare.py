"""Cut our articles out of FineWiki and save them as data/articles-<lang>.parquet.

You do not need to run this: the result is published (see README, step 3).
It is here so you can see how it was made, or make your own topic.

    python prepare.py fi          # the Finnish articles in data/articles-fi.tsv  (~5 min)
    python prepare.py sv en       # the Swedish and English articles on the same topics

Finnish articles are matched by page_id; Swedish and English ones by wikidata_id
(the same topic has the same Wikidata id in every language), so run fi first.

DuckDB reads the Parquet files straight from Hugging Face and fetches only the columns we
ask for: the raw wikitext column, about two thirds of every file, is never downloaded.
Each source file is saved separately in data/cache/, so an interrupted run continues
where it stopped.
"""
import sys, time, pathlib, duckdb, requests

REPO = "HuggingFaceFW/finewiki"
COLUMNS = """page_id, version AS rev_id, wikidata_id, title, url, date_modified, text"""
WAIT = 300      # seconds to wait when Hugging Face says "too many requests"

cache = pathlib.Path("data/cache")
cache.mkdir(parents=True, exist_ok=True)
db = duckdb.connect()
db.sql("SET enable_progress_bar = false")


def source_files(lang):
    """The Parquet files of one language in FineWiki, e.g. data/fiwiki/000_00000.parquet."""
    r = requests.get(f"https://huggingface.co/api/datasets/{REPO}/tree/main/data/{lang}wiki")
    r.raise_for_status()
    return sorted(f["path"] for f in r.json() if f["path"].endswith(".parquet"))


def wanted(lang):
    """A SQL condition that picks our articles in this language."""
    if lang == "fi":
        return "page_id IN (SELECT page_id FROM read_csv('data/articles-fi.tsv', delim='\t'))"
    if not pathlib.Path("data/articles-fi.parquet").exists():
        sys.exit("Run 'python prepare.py fi' first: other languages are matched to the Finnish articles.")
    return ("wikidata_id IN (SELECT wikidata_id FROM 'data/articles-fi.parquet' "
            "WHERE wikidata_id IS NOT NULL)")


for lang in sys.argv[1:] or ["fi"]:
    files = source_files(lang)
    parts = []
    for i, path in enumerate(files, 1):
        part = cache / f"{lang}-{pathlib.Path(path).stem}.parquet"
        parts.append(str(part))
        if part.exists():
            print(f"{lang} {i}/{len(files)} {path}: already done")
            continue
        t = time.time()
        url = f"https://huggingface.co/datasets/{REPO}/resolve/main/{path}"
        tmp = part.with_suffix(".tmp")
        while True:
            try:
                db.sql(f"""COPY (SELECT '{lang}' AS lang, {COLUMNS} FROM read_parquet('{url}')
                                 WHERE {wanted(lang)})
                           TO '{tmp}' (FORMAT parquet)""")
                break
            except duckdb.HTTPException as e:
                # Reading single columns takes ~3,000 small requests per file, and Hugging Face
                # limits how many an anonymous user may make in 5 minutes. Wait and try again.
                if "429" not in str(e):
                    raise
                print(f"  Hugging Face says 'too many requests'. Waiting {WAIT // 60} minutes ...")
                time.sleep(WAIT)
        tmp.rename(part)
        n = db.sql(f"SELECT count(*) FROM '{part}'").fetchone()[0]
        print(f"{lang} {i}/{len(files)} {path}: {n} articles, {time.time() - t:.0f} s")

    # FineWiki sometimes has several versions of one article (e.g. 4 of "Talvisota"): keep the newest.
    out = f"data/articles-{lang}.parquet"
    db.sql(f"""COPY (SELECT * FROM read_parquet({parts})
                     QUALIFY row_number() OVER (PARTITION BY page_id ORDER BY rev_id DESC) = 1
                     ORDER BY page_id)
               TO '{out}' (FORMAT parquet)""")
    n, mb = db.sql(f"SELECT count(*), sum(length(text)) / 1e6 FROM '{out}'").fetchone()
    print(f"Done: {n} {lang} articles, {mb:.0f} MB of text -> {out}")
