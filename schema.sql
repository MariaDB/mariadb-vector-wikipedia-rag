-- Tables for Wikipedia RAG with MariaDB Vector. Run:  mariadb -u wikirag -pwikirag wikirag < schema.sql

CREATE TABLE IF NOT EXISTS article (
  lang          CHAR(2)      NOT NULL,      -- fi, en, sv
  page_id       INT UNSIGNED NOT NULL,      -- Wikipedia's own id, per language
  rev_id        INT UNSIGNED NOT NULL,      -- the version we have
  wikidata_id   VARCHAR(20),                -- same topic across languages, e.g. Q33 = Finland
  title         VARCHAR(255) NOT NULL,
  url           VARCHAR(500) NOT NULL,
  date_modified DATETIME,                   -- when this version was saved
  text          MEDIUMTEXT   NOT NULL,      -- clean Markdown from FineWiki
  PRIMARY KEY (lang, page_id),
  KEY (wikidata_id),
  FULLTEXT (title, text)                    -- for keyword search
) CHARACTER SET utf8mb4;

-- A vector exists only once it is computed: a VECTOR INDEX column must be NOT NULL.
-- "Has a row here" = "is embedded". That is what makes embed.py resumable.
CREATE TABLE IF NOT EXISTS article_vector (
  lang       CHAR(2)      NOT NULL,
  page_id    INT UNSIGNED NOT NULL,
  model      VARCHAR(50)  NOT NULL,         -- which model made this vector
  truncated  BOOL         NOT NULL,         -- article was longer than the model reads
  embedding  VECTOR(1024) NOT NULL,
  PRIMARY KEY (lang, page_id),
  -- M=16 instead of the default 6: with 1024 dimensions, M=6 found only 79% of the true top 10
  -- (see index_recall.py and the README, step 8).
  VECTOR INDEX (embedding) M=16 DISTANCE=cosine
);

-- The category tree under "Suomen historia" (Finnish category names, without "Luokka:").
CREATE TABLE IF NOT EXISTS category_link (
  parent  VARCHAR(255) NOT NULL,
  child   VARCHAR(255) NOT NULL,
  PRIMARY KEY (parent, child),
  KEY (child)
) CHARACTER SET utf8mb4;

-- Which categories each article is in. Categories come from Finnish Wikipedia; the Swedish and
-- English articles get the categories of the Finnish article on the same topic (same wikidata_id).
CREATE TABLE IF NOT EXISTS article_category (
  lang      CHAR(2)      NOT NULL,
  page_id   INT UNSIGNED NOT NULL,
  category  VARCHAR(255) NOT NULL,
  PRIMARY KEY (lang, page_id, category),
  KEY (category)
) CHARACTER SET utf8mb4;
