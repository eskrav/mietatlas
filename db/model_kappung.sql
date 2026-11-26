-- Example model: the Kappungsgrenze for rent increases in existing tenancies (§ 558 Abs. 3 BGB)
-- and two freely chosen example scenarios that lower it.
--
-- Rent after the horizon = rent today × min((1 + market growth)^horizon, 1 + Kappungsgrenze),
-- where the lower Kappungsgrenze applies in Kreise counted as tight.
--
-- Inputs: the real Kreis rents (Zensus 2022) from atlas.observations. Assumptions, stored as
-- parameters: market growth, the threshold that marks a Kreis as tight (a proxy; the real
-- areas are designated per Gemeinde by the Länder) and the size of the model flat.
-- This is a mechanical upper-bound scenario, not a forecast: it assumes every rent rises
-- as far as market growth and the cap allow.
--
-- Run after load_db.py and db/model_schema.sql:
--   psql -d mietatlas -f db/model_kappung.sql
-- Safe to run repeatedly: the model tables are emptied first.

BEGIN;

TRUNCATE atlas.results, atlas.run_parameters, atlas.model_runs, atlas.scenario_overrides,
         atlas.scenarios, atlas.parameters, atlas.household_types RESTART IDENTITY CASCADE;

INSERT INTO atlas.sources (source_id, name, publisher, url, licence) VALUES
  ('bgb_558', '§ 558 BGB, Mieterhöhung bis zur ortsüblichen Vergleichsmiete',
   'Bundesministerium der Justiz', 'https://www.gesetze-im-internet.de/bgb/__558.html',
   'amtliches Werk')
ON CONFLICT (source_id) DO NOTHING;

INSERT INTO atlas.indicators (indicator_id, name, unit, description) VALUES
  ('nettokaltmiete_szenario', 'Nettokaltmiete nach Ablauf des Szenarios', 'EUR/m²',
   'Modellergebnis: Obergrenze der Bestandsmiete nach Marktentwicklung und Kappungsgrenze'),
  ('monatsmiete_musterwohnung', 'Monatliche Nettokaltmiete der Musterwohnung', 'EUR/Monat',
   'Modellergebnis: Nettokaltmiete nach Ablauf des Szenarios × Wohnfläche der Musterwohnung')
ON CONFLICT (indicator_id) DO UPDATE
SET name = EXCLUDED.name, unit = EXCLUDED.unit, description = EXCLUDED.description;

-- One model household: in this model the effect per m² does not depend on the household
INSERT INTO atlas.household_types (household_type_id, label) VALUES
  ('musterhaushalt', 'Musterhaushalt (Wohnfläche siehe Parameter wohnflaeche)');

INSERT INTO atlas.parameters
    (parameter_id, name, unit, baseline_value, kind, source_id, valid_min, valid_max) VALUES
  ('kappung_allgemein',   'Kappungsgrenze, allgemein',               'Anteil in 3 Jahren', 0.20, 'lever',        'bgb_558', 0,   0.30),
  ('kappung_angespannt',  'Kappungsgrenze, angespannte Märkte',      'Anteil in 3 Jahren', 0.15, 'lever',        'bgb_558', 0,   0.30),
  ('horizont',            'Betrachtungszeitraum',                    'Jahre',              3,    'definitional', 'bgb_558', 3,   3),
  ('marktwachstum',       'Anstieg der Vergleichsmiete pro Jahr',    'Anteil pro Jahr',    0.06, 'assumption',   NULL,      0,   0.15),
  ('schwelle_angespannt', 'Kreis gilt als angespannt ab Miete ≥ Schwelle × Bundeswert',
                                                                      'Faktor',             1.0,  'assumption',   NULL,      0.5, 2.0),
  ('wohnflaeche',         'Wohnfläche der Musterwohnung',            'm²',                 70,   'assumption',   NULL,      20,  200);

INSERT INTO atlas.scenarios (scenario_id, name, description, is_baseline, is_published) VALUES
  ('geltendes_recht', 'Geltendes Recht',
   '20 % in drei Jahren, 15 % in angespannten Märkten (§ 558 Abs. 3 BGB)', true, true),
  ('kappung_10', 'Kappungsgrenze 10 % in angespannten Märkten',
   'Beispielszenario: angespannte Märkte 10 % in drei Jahren, sonst unverändert 20 %', false, true),
  ('kappung_15_ueberall', 'Kappungsgrenze 15 % überall',
   'Beispielszenario: 15 % in drei Jahren in allen Kreisen, nicht nur in angespannten Märkten', false, true),
  ('schwelle_120', 'Engere Abgrenzung angespannter Märkte (Entwurf)',
   'Wie geltendes Recht, aber angespannt erst ab 120 % des Bundeswerts; intern, nicht veröffentlicht',
   false, false);

INSERT INTO atlas.scenario_overrides (scenario_id, parameter_id, value) VALUES
  ('kappung_10',          'kappung_angespannt',  0.10),
  ('kappung_15_ueberall', 'kappung_allgemein',   0.15),
  ('schwelle_120',        'schwelle_angespannt', 1.2);

-- One model run: copy the parameter set, then compute the results from the real Kreis rents
CREATE OR REPLACE FUNCTION atlas.run_kappung_model(
    p_scenario_id text, p_model_version text, p_data_release text
) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
    v_run_id integer;
BEGIN
    -- clock_timestamp(): the actual time, even when several runs share one transaction
    INSERT INTO atlas.model_runs (scenario_id, model_version, data_release, run_at)
    VALUES (p_scenario_id, p_model_version, p_data_release, clock_timestamp())
    RETURNING run_id INTO v_run_id;

    INSERT INTO atlas.run_parameters (run_id, parameter_id, value)
    SELECT v_run_id, parameter_id, value
    FROM atlas.effective_parameters
    WHERE scenario_id = p_scenario_id;

    -- Results use only the copied parameter values, never the live parameter tables
    WITH p AS (
        SELECT max(value) FILTER (WHERE parameter_id = 'kappung_allgemein')   AS kappung_allgemein,
               max(value) FILTER (WHERE parameter_id = 'kappung_angespannt')  AS kappung_angespannt,
               max(value) FILTER (WHERE parameter_id = 'horizont')            AS horizont,
               max(value) FILTER (WHERE parameter_id = 'marktwachstum')       AS marktwachstum,
               max(value) FILTER (WHERE parameter_id = 'schwelle_angespannt') AS schwelle,
               max(value) FILTER (WHERE parameter_id = 'wohnflaeche')         AS wohnflaeche
        FROM atlas.run_parameters
        WHERE run_id = v_run_id
    ),
    bund AS (
        SELECT value FROM atlas.observations
        WHERE region_id = 'DE' AND indicator_id = 'nettokaltmiete' AND year = 2022
    ),
    kreise AS (
        SELECT o.region_id,
               o.year,
               round(o.value * least(power(1 + p.marktwachstum, p.horizont),
                                     1 + CASE WHEN o.value >= p.schwelle * bund.value
                                              THEN p.kappung_angespannt
                                              ELSE p.kappung_allgemein END), 2) AS miete_neu,
               p.wohnflaeche,
               p.horizont
        FROM atlas.observations o
        JOIN atlas.regions r USING (region_id)
        CROSS JOIN p
        CROSS JOIN bund
        WHERE r.level = 'kreis'
          AND o.indicator_id = 'nettokaltmiete'
          AND o.year = 2022
    )
    INSERT INTO atlas.results (run_id, region_id, household_type_id, indicator_id, year, value)
    SELECT v_run_id, region_id, 'musterhaushalt', 'nettokaltmiete_szenario',
           year + horizont::integer, miete_neu
    FROM kreise
    UNION ALL
    SELECT v_run_id, region_id, 'musterhaushalt', 'monatsmiete_musterwohnung',
           year + horizont::integer, round(miete_neu * wohnflaeche, 0)
    FROM kreise;

    RETURN v_run_id;
END;
$$;

-- An earlier run with 5 % market growth, as if that assumption was changed later;
-- run_parameters keeps the old value, so the earlier results stay explainable.
UPDATE atlas.parameters SET baseline_value = 0.05 WHERE parameter_id = 'marktwachstum';
SELECT atlas.run_kappung_model('geltendes_recht', 'v0.1.0', 'zensus2022');
UPDATE atlas.parameters SET baseline_value = 0.06 WHERE parameter_id = 'marktwachstum';

-- Current runs for every scenario
SELECT atlas.run_kappung_model(scenario_id, 'v0.2.0', 'zensus2022')
FROM atlas.scenarios
ORDER BY is_baseline DESC, scenario_id;

COMMIT;
