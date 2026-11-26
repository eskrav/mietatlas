-- Queries on the Kappungsgrenze model (after db/model_schema.sql and db/model_kappung.sql):
--   psql -d mietatlas -f db/model_queries.sql
-- Same convention as db/queries.sql: each query starts with a "-- name:" line,
-- and every query named check_* must return no rows.

SET search_path TO atlas;

-- name: scenario_overview
-- Per published scenario: how many Kreise are affected compared with current law,
-- and by how much the monthly rent of the model flat changes there on average
-- (unweighted mean over the affected Kreise)
WITH basis AS (
    SELECT region_id, value FROM published_results
    WHERE scenario_id = 'geltendes_recht' AND indicator_id = 'monatsmiete_musterwohnung'
)
SELECT s.name                                                          AS szenario,
       count(*) FILTER (WHERE p.value <> b.value)                      AS betroffene_kreise,
       round(avg(p.value - b.value) FILTER (WHERE p.value <> b.value)) AS mittlere_aenderung_eur,
       min(p.value - b.value)                                          AS staerkste_aenderung_eur,
       s.description                                                   AS beschreibung
FROM published_results p
JOIN basis b     USING (region_id)
JOIN scenarios s USING (scenario_id)
WHERE p.indicator_id = 'monatsmiete_musterwohnung'
GROUP BY s.scenario_id, s.name, s.description
ORDER BY betroffene_kreise, mittlere_aenderung_eur DESC;

-- name: kreis_lookup
-- One Kreis across all published scenarios: what an interface would show (Berlin)
SELECT s.name                                                              AS szenario,
       max(p.value) FILTER (WHERE p.indicator_id = 'nettokaltmiete_szenario')   AS eur_je_m2,
       max(p.value) FILTER (WHERE p.indicator_id = 'monatsmiete_musterwohnung') AS eur_je_monat,
       max(p.value) FILTER (WHERE p.indicator_id = 'monatsmiete_musterwohnung')
         - max(b.value)                                                    AS gegenueber_geltendem_recht
FROM published_results p
JOIN scenarios s USING (scenario_id)
JOIN published_results b
  ON b.scenario_id = 'geltendes_recht'
 AND b.region_id = p.region_id
 AND b.indicator_id = 'monatsmiete_musterwohnung'
WHERE p.region_id = '11000'
GROUP BY s.scenario_id, s.name
ORDER BY eur_je_monat DESC;

-- name: most_affected_kreise
-- The ten Kreise where a 10 % Kappungsgrenze in tight markets would lower the model rent the most
SELECT r.name                AS kreis,
       b.value               AS geltendes_recht_eur,
       p.value               AS kappung_10_eur,
       p.value - b.value     AS aenderung_eur
FROM published_results p
JOIN published_results b
  ON b.scenario_id = 'geltendes_recht'
 AND b.region_id = p.region_id
 AND b.indicator_id = p.indicator_id
JOIN regions r ON r.region_id = p.region_id
WHERE p.scenario_id = 'kappung_10'
  AND p.indicator_id = 'monatsmiete_musterwohnung'
ORDER BY aenderung_eur, r.name
LIMIT 10;

-- name: trace_published_number
-- Where does one published number come from? Berlin, Kappungsgrenze 10 % in tight markets:
-- run, model version, data release and every parameter value used
WITH published_run AS (
    SELECT DISTINCT ON (scenario_id) run_id, scenario_id, model_version, data_release
    FROM model_runs
    WHERE scenario_id = 'kappung_10'
    ORDER BY scenario_id, run_at DESC, run_id DESC
)
SELECT res.value                      AS veroeffentlichter_wert,
       pr.run_id,
       pr.model_version,
       pr.data_release,
       rp.parameter_id,
       rp.value                       AS verwendeter_wert,
       p.unit,
       p.kind,
       rp.value <> p.baseline_value   AS weicht_von_basis_ab,
       src.name                       AS quelle
FROM published_run pr
JOIN results res
  ON res.run_id = pr.run_id
 AND res.region_id = '11000'
 AND res.indicator_id = 'monatsmiete_musterwohnung'
JOIN run_parameters rp ON rp.run_id = pr.run_id
JOIN parameters p      ON p.parameter_id = rp.parameter_id
LEFT JOIN sources src  ON src.source_id = p.source_id
ORDER BY weicht_von_basis_ab DESC, rp.parameter_id;

-- name: changes_between_runs
-- Same scenario, consecutive runs: which parameter values differ?
WITH runs AS (
    SELECT run_id, scenario_id, model_version,
           lag(run_id) OVER (PARTITION BY scenario_id ORDER BY run_at, run_id) AS previous_run_id
    FROM model_runs
)
SELECT r.scenario_id,
       r.previous_run_id,
       r.run_id,
       r.model_version,
       cur.parameter_id,
       prev.value AS vorher,
       cur.value  AS nachher
FROM runs r
JOIN run_parameters cur  ON cur.run_id = r.run_id
JOIN run_parameters prev ON prev.run_id = r.previous_run_id
                        AND prev.parameter_id = cur.parameter_id
WHERE cur.value IS DISTINCT FROM prev.value
ORDER BY r.scenario_id, r.run_id, cur.parameter_id;

-- name: check_overrides_outside_valid_range
-- Scenario values outside the range the model is validated for (expected: no rows)
SELECT o.scenario_id, o.parameter_id, o.value, p.valid_min, p.valid_max
FROM scenario_overrides o
JOIN parameters p USING (parameter_id)
WHERE o.value < p.valid_min OR o.value > p.valid_max;

-- name: check_baseline_with_overrides
-- The baseline scenario must not change any parameter (expected: no rows)
SELECT o.scenario_id, o.parameter_id
FROM scenario_overrides o
JOIN scenarios s USING (scenario_id)
WHERE s.is_baseline;

-- name: check_published_scenarios_without_run
-- Every published scenario needs at least one model run (expected: no rows)
SELECT s.scenario_id
FROM scenarios s
WHERE s.is_published
  AND NOT EXISTS (SELECT 1 FROM model_runs r WHERE r.scenario_id = s.scenario_id);

-- name: check_runs_without_full_parameter_copy
-- Every run must have stored a value for every parameter (expected: no rows)
SELECT r.run_id, count(rp.parameter_id) AS gespeichert,
       (SELECT count(*) FROM parameters) AS erwartet
FROM model_runs r
LEFT JOIN run_parameters rp USING (run_id)
GROUP BY r.run_id
HAVING count(rp.parameter_id) <> (SELECT count(*) FROM parameters);

-- name: check_results_outside_bounds
-- A scenario rent must lie between today's rent and today's rent plus the full gap to the
-- comparison rent (expected: no rows; 0.01 tolerance for rounding)
WITH p AS (
    SELECT run_id, max(value) FILTER (WHERE parameter_id = 'rueckstand') AS rueckstand
    FROM run_parameters
    GROUP BY run_id
)
SELECT res.run_id, res.region_id, o.value AS heute, res.value AS szenario
FROM results res
JOIN p USING (run_id)
JOIN observations o
  ON o.region_id = res.region_id
 AND o.indicator_id = 'nettokaltmiete'
 AND o.year = 2022
WHERE res.indicator_id = 'nettokaltmiete_szenario'
  AND (res.value < o.value - 0.01 OR res.value > o.value * (1 + p.rueckstand) + 0.01);

-- name: check_average_differs_between_scenarios
-- Under average rent growth the cap should not bind, so that value must be the same in every
-- published scenario (expected: no rows; a row here means the cap binds at average growth)
SELECT region_id, min(value) AS min_wert, max(value) AS max_wert
FROM published_results
WHERE indicator_id = 'monatsmiete_durchschnitt'
GROUP BY region_id
HAVING min(value) <> max(value);
