-- Example model: the Kappungsgrenze for rent increases in existing tenancies (§ 558 Abs. 3 BGB)
-- and two freely chosen example scenarios that lower it.
--
-- The Kappungsgrenze matters for tenancies whose rent lies well below the local comparison rent
-- (ortsübliche Vergleichsmiete), typically long tenancies without recent increases. For such a
-- tenancy, the highest rent the landlord may ask after three years is
--   rent today × min(1 + gap to the comparison rent, 1 + Kappungsgrenze),
-- where the lower Kappungsgrenze applies in Kreise counted as tight.
--
-- For comparison, each run also computes the rent under average rent growth (Destatis rent
-- index). At that pace the cap does not bind, so this value is the same in every scenario.
--
-- Inputs: the real Kreis rents (Zensus 2022) from atlas.observations. Assumptions, stored as
-- parameters: the gap to the comparison rent, the threshold that marks a Kreis as tight (a
-- proxy; the real areas are designated per Gemeinde by the Länder) and the size of the model
-- flat. The main result is an upper bound for a stylised tenancy, not a forecast.
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
   'amtliches Werk'),
  ('destatis_vpi_2024', 'Verbraucherpreisindex, Jahr 2024: Nettokaltmieten +2,1 %',
   'Statistisches Bundesamt',
   'https://www.destatis.de/DE/Presse/Pressemitteilungen/2025/01/PD25_020_611.html',
   'dl-de/by-2-0')
ON CONFLICT (source_id) DO NOTHING;

INSERT INTO atlas.indicators (indicator_id, name, unit, description) VALUES
  ('nettokaltmiete_szenario', 'Nettokaltmiete nach Ablauf des Szenarios', 'EUR/m²',
   'Modellergebnis: höchstmögliche Miete nach drei Jahren für ein Mietverhältnis mit Abstand zur Vergleichsmiete'),
  ('monatsmiete_musterwohnung', 'Monatliche Nettokaltmiete der Musterwohnung', 'EUR/Monat',
   'Modellergebnis: Nettokaltmiete nach Ablauf des Szenarios × Wohnfläche der Musterwohnung'),
  ('monatsmiete_durchschnitt', 'Monatliche Nettokaltmiete der Musterwohnung bei durchschnittlicher Mietentwicklung', 'EUR/Monat',
   'Modellergebnis: Miete heute × (1 + Mietindex-Anstieg)^Jahre, höchstens bis zur Kappungsgrenze, × Wohnfläche')
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
  ('rueckstand',          'Abstand der Miete zur ortsüblichen Vergleichsmiete', 'Anteil', 0.20, 'assumption', NULL,  0,   0.5),
  ('mietindex_anstieg',   'Durchschnittlicher Anstieg der Nettokaltmieten pro Jahr', 'Anteil pro Jahr', 0.021, 'empirical', 'destatis_vpi_2024', 0, 0.1),
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
               max(value) FILTER (WHERE parameter_id = 'rueckstand')          AS rueckstand,
               max(value) FILTER (WHERE parameter_id = 'mietindex_anstieg')   AS mietindex_anstieg,
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
               o.value,
               1 + CASE WHEN o.value >= p.schwelle * bund.value
                        THEN p.kappung_angespannt
                        ELSE p.kappung_allgemein END AS kappung_faktor,
               p.rueckstand,
               p.mietindex_anstieg,
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
    ,
    berechnet AS (
        SELECT region_id, year, horizont, wohnflaeche,
               -- highest rent for a tenancy that lies rueckstand below the comparison rent
               round(value * least(1 + rueckstand, kappung_faktor), 2) AS miete_hoechstens,
               -- rent under average growth, also limited by the cap
               round(value * least(power(1 + mietindex_anstieg, horizont), kappung_faktor), 2)
                                                                       AS miete_durchschnitt
        FROM kreise
    )
    INSERT INTO atlas.results (run_id, region_id, household_type_id, indicator_id, year, value)
    SELECT v_run_id, region_id, 'musterhaushalt', 'nettokaltmiete_szenario',
           year + horizont::integer, miete_hoechstens
    FROM berechnet
    UNION ALL
    SELECT v_run_id, region_id, 'musterhaushalt', 'monatsmiete_musterwohnung',
           year + horizont::integer, round(miete_hoechstens * wohnflaeche, 0)
    FROM berechnet
    UNION ALL
    SELECT v_run_id, region_id, 'musterhaushalt', 'monatsmiete_durchschnitt',
           year + horizont::integer, round(miete_durchschnitt * wohnflaeche, 0)
    FROM berechnet;

    RETURN v_run_id;
END;
$$;

-- An earlier run with a 15 % gap, as if that assumption was changed later;
-- run_parameters keeps the old value, so the earlier results stay explainable.
UPDATE atlas.parameters SET baseline_value = 0.15 WHERE parameter_id = 'rueckstand';
SELECT atlas.run_kappung_model('geltendes_recht', 'v0.1.0', 'zensus2022');
UPDATE atlas.parameters SET baseline_value = 0.20 WHERE parameter_id = 'rueckstand';

-- Current runs for every scenario
SELECT atlas.run_kappung_model(scenario_id, 'v0.2.0', 'zensus2022')
FROM atlas.scenarios
ORDER BY is_baseline DESC, scenario_id;

COMMIT;
