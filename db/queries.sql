-- Example queries on the loaded data (after python load_db.py):
--   psql -d mietatlas -f db/queries.sql
-- Each query starts with a "-- name:" line; tests/test_queries.py runs all of them,
-- and every query named check_* must return no rows.

SET search_path TO atlas;

-- name: most_expensive_kreis_per_land
-- Most expensive Kreis in each Land, and its distance from the national value
WITH kreise AS (
    SELECT r.region_id, r.name, r.parent_id, o.value,
           rank() OVER (PARTITION BY r.parent_id ORDER BY o.value DESC) AS rang_im_land
    FROM regions r
    JOIN observations o ON o.region_id = r.region_id
    WHERE r.level = 'kreis'
      AND o.indicator_id = 'nettokaltmiete'
      AND o.year = 2022
),
bund AS (
    SELECT value FROM observations
    WHERE region_id = 'DE' AND indicator_id = 'nettokaltmiete' AND year = 2022
)
SELECT l.name                         AS land,
       k.name                         AS teuerster_kreis,
       k.value                        AS miete,
       round(k.value - bund.value, 2) AS abstand_zum_bund
FROM kreise k
JOIN regions l ON l.region_id = k.parent_id
CROSS JOIN bund
WHERE k.rang_im_land = 1
ORDER BY k.value DESC;

-- name: spread_within_land
-- Spread of Kreis values within each Land. Deliberately no mean of the Kreis values:
-- Kreise have very different numbers of rented flats, so an unweighted mean would
-- not be a Land value.
SELECT l.name                                                              AS land,
       count(*)                                                            AS kreise,
       min(o.value)                                                        AS min,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY o.value)::numeric(5, 2) AS median,
       max(o.value)                                                        AS max,
       max(o.value) - min(o.value)                                         AS spannweite
FROM regions k
JOIN regions l      ON l.region_id = k.parent_id
JOIN observations o ON o.region_id = k.region_id
WHERE k.level = 'kreis'
  AND o.indicator_id = 'nettokaltmiete'
  AND o.year = 2022
GROUP BY l.name
ORDER BY spannweite DESC;

-- name: kreise_below_national_value
-- How many Kreise lie below the national value, overall and per Land. The national
-- value is weighted by rented flats, so it is pulled up by the large, expensive cities.
WITH bund AS (
    SELECT value FROM observations
    WHERE region_id = 'DE' AND indicator_id = 'nettokaltmiete' AND year = 2022
)
SELECT coalesce(l.name, 'Deutschland')                  AS land,
       count(*)                                         AS kreise,
       count(*) FILTER (WHERE o.value < bund.value)     AS unter_bundeswert,
       round(100.0 * count(*) FILTER (WHERE o.value < bund.value) / count(*), 1)
                                                        AS anteil_prozent
FROM regions k
JOIN regions l      ON l.region_id = k.parent_id
JOIN observations o ON o.region_id = k.region_id
CROSS JOIN bund
WHERE k.level = 'kreis'
  AND o.indicator_id = 'nettokaltmiete'
  AND o.year = 2022
GROUP BY ROLLUP (l.name)
ORDER BY (l.name IS NULL) DESC, anteil_prozent DESC;

-- name: check_kreise_without_value
-- Kreise without a value for the indicator (expected: no rows)
SELECT r.region_id, r.name
FROM regions r
WHERE r.level = 'kreis'
  AND NOT EXISTS (
      SELECT 1 FROM observations o
      WHERE o.region_id = r.region_id
        AND o.indicator_id = 'nettokaltmiete'
        AND o.year = 2022
  );

-- name: check_hierarchy
-- Every Kreis must sit under the Land whose code matches its first two AGS digits
-- (expected: no rows)
SELECT k.region_id, k.name, k.parent_id, p.level AS parent_level
FROM regions k
JOIN regions p ON p.region_id = k.parent_id
WHERE k.level = 'kreis'
  AND (p.level <> 'land' OR left(k.region_id, 2) <> p.region_id);

-- name: check_lands_without_kreise
-- Every Land must have at least one Kreis (expected: no rows)
SELECT l.region_id, l.name
FROM regions l
WHERE l.level = 'land'
  AND NOT EXISTS (SELECT 1 FROM regions k WHERE k.parent_id = l.region_id);
