/* =====================================================================
   flashcards-data.js — study deck for a working data analyst.
   Real material: SQL, statistics, pandas, warehousing, viz.
   Edit/extend freely; modes.js renders whatever is here.
   ===================================================================== */
window.FLASHCARDS = [
  /* ---------------- SQL ---------------- */
  { cat: 'SQL', front: 'INNER JOIN vs LEFT JOIN',
    back: 'INNER JOIN keeps only rows with a match in both tables. LEFT JOIN keeps every row from the left table, filling unmatched right-side columns with NULL.' },
  { cat: 'SQL', front: 'WHERE vs HAVING',
    back: 'WHERE filters individual rows before aggregation. HAVING filters groups after GROUP BY, so it can reference aggregate functions like COUNT() or SUM().' },
  { cat: 'SQL', front: 'What does GROUP BY do?',
    back: 'Collapses rows that share values in the listed columns into one row per group, so aggregate functions (SUM, AVG, COUNT) compute per group.' },
  { cat: 'SQL', front: 'Window function vs GROUP BY',
    back: 'A window function (OVER (...)) computes across a set of rows but returns a value for every row — no collapsing. GROUP BY reduces rows to one per group.' },
  { cat: 'SQL', front: 'ROW_NUMBER vs RANK vs DENSE_RANK',
    back: 'ROW_NUMBER: unique 1..n, no ties. RANK: ties share a rank, then skips (1,1,3). DENSE_RANK: ties share a rank, no gap (1,1,2).' },
  { cat: 'SQL', front: 'What is a CTE?',
    back: 'A Common Table Expression — a named temporary result set defined with WITH name AS (...). Improves readability and enables recursion; scoped to the single query.' },
  { cat: 'SQL', front: 'SQL logical execution order',
    back: 'FROM → WHERE → GROUP BY → HAVING → SELECT → DISTINCT → ORDER BY → LIMIT. (You write SELECT first, but it runs after filtering and grouping.)' },
  { cat: 'SQL', front: 'COUNT(*) vs COUNT(col)',
    back: 'COUNT(*) counts all rows. COUNT(col) counts only rows where col IS NOT NULL. COUNT(DISTINCT col) counts unique non-null values.' },
  { cat: 'SQL', front: 'How do NULLs behave in comparisons?',
    back: 'Any comparison with NULL yields UNKNOWN, not TRUE — so col = NULL never matches. Use IS NULL / IS NOT NULL, or COALESCE() to substitute a value.' },
  { cat: 'SQL', front: 'What does an index do?',
    back: 'Stores a sorted lookup structure (often a B-tree) so the engine finds rows without scanning the whole table. Speeds reads/joins; costs storage and slows writes.' },

  /* ---------------- Statistics ---------------- */
  { cat: 'Statistics', front: 'What is a p-value?',
    back: 'The probability of observing a result at least as extreme as yours if the null hypothesis were true. Small p (<0.05 conventionally) = evidence against the null.' },
  { cat: 'Statistics', front: 'Type I vs Type II error',
    back: 'Type I (α): rejecting a true null — a false positive. Type II (β): failing to reject a false null — a false negative. Power = 1 − β.' },
  { cat: 'Statistics', front: 'Mean vs median — when to use which?',
    back: 'Mean uses every value but is dragged by outliers/skew. Median is the middle value, robust to outliers — prefer it for skewed data like income.' },
  { cat: 'Statistics', front: 'What is a confidence interval?',
    back: 'A range that would contain the true parameter in X% of repeated samples. A 95% CI reflects estimate precision — wider means more uncertainty.' },
  { cat: 'Statistics', front: 'Correlation vs causation',
    back: 'Correlation measures how two variables move together. It does not imply one causes the other — confounders or reverse causation may explain it.' },
  { cat: 'Statistics', front: 'What is statistical power?',
    back: 'The probability a test correctly detects a real effect (1 − β). Rises with larger samples, bigger effect sizes, and lower variance.' },
  { cat: 'Statistics', front: 'Central Limit Theorem',
    back: 'The distribution of sample means approaches normal as sample size grows, regardless of the population shape — the basis for many tests and CIs.' },

  /* ---------------- A/B & Experiments ---------------- */
  { cat: 'Experiments', front: 'What makes an A/B test valid?',
    back: 'Random assignment, a single changed variable, a pre-chosen metric and sample size, no peeking before the horizon, and enough power to detect the effect.' },
  { cat: 'Experiments', front: 'What is the "peeking problem"?',
    back: 'Repeatedly checking results and stopping when significant inflates the false-positive rate. Fix with a fixed horizon or sequential testing corrections.' },
  { cat: 'Experiments', front: 'Why segment A/B results carefully?',
    back: 'Slicing by many subgroups multiplies comparisons and surfaces false positives (multiple-comparisons problem). Pre-register segments or correct (e.g. Bonferroni).' },

  /* ---------------- Pandas / Python ---------------- */
  { cat: 'Pandas', front: '.loc vs .iloc',
    back: '.loc selects by label (row/column names, boolean masks). .iloc selects by integer position. df.loc[df.x > 5, "y"] is the idiomatic conditional select.' },
  { cat: 'Pandas', front: 'groupby().agg() pattern',
    back: 'df.groupby("k").agg(total=("amt","sum"), n=("id","count")) — split rows by key, apply named aggregations, combine into one row per key.' },
  { cat: 'Pandas', front: 'merge vs join vs concat',
    back: 'merge: SQL-style joins on columns/keys. join: merge on the index for convenience. concat: stack frames along an axis (rows or columns).' },
  { cat: 'Pandas', front: 'How to handle missing values?',
    back: 'Detect with isna(); drop with dropna(); fill with fillna(value/method). Choose by why data is missing — imputation can bias if missingness is informative.' },
  { cat: 'Pandas', front: 'pivot_table vs groupby',
    back: 'pivot_table reshapes long→wide with an aggregation across an index/columns grid. groupby aggregates but keeps a long layout. pivot_table = groupby + unstack.' },

  /* ---------------- Data Concepts ---------------- */
  { cat: 'Concepts', front: 'Normalization vs denormalization',
    back: 'Normalization splits data to remove redundancy (good for write integrity, OLTP). Denormalization duplicates for fewer joins and faster reads (analytics, OLAP).' },
  { cat: 'Concepts', front: 'Star schema',
    back: 'A central fact table (measures, foreign keys) surrounded by dimension tables (descriptive attributes). The standard warehouse model for fast aggregations.' },
  { cat: 'Concepts', front: 'OLTP vs OLAP',
    back: 'OLTP: many small transactions, row-oriented, normalized (apps). OLAP: large analytical scans, column-oriented, denormalized (dashboards, reporting).' },
  { cat: 'Concepts', front: 'Cardinality',
    back: 'The number of distinct values in a column. High cardinality = many uniques (user_id); low = few (boolean). It guides indexing and join strategy.' },
  { cat: 'Concepts', front: 'Idempotent pipeline',
    back: 'Re-running it produces the same result without duplicates or drift — achieved with upserts/MERGE, partition overwrites, and deterministic transforms.' },

  /* ---------------- Visualization ---------------- */
  { cat: 'Visualization', front: 'When NOT to use a pie chart',
    back: 'When comparing more than ~3 slices or precise values matter — humans judge angles poorly. A sorted bar chart almost always reads more clearly.' },
  { cat: 'Visualization', front: 'Bar chart axis rule',
    back: 'Bar charts must start the value axis at zero, because the bar length encodes magnitude. Truncating the axis exaggerates differences and misleads.' },
  { cat: 'Visualization', front: 'Choosing a chart type',
    back: 'Trend over time → line. Compare categories → bar. Relationship → scatter. Part-to-whole → stacked bar/treemap. Distribution → histogram/box plot.' },
];
