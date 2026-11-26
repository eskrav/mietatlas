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
-- This file is the model code: one function that performs a model run. It reads its
-- parameter values only from the copy stored for the run, records which data load it used,
-- and stores how it treated each Kreis. The scenarios and the example runs are in
-- db/kappung_demo.sql. run_model.py executes both, after db/model_schema.sql.

-- One model run: copy the parameter set, then compute the results from the real Kreis rents
CREATE OR REPLACE FUNCTION atlas.run_kappung_model(
    p_scenario_id text, p_model_version text, p_data_release text
) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
    v_run_id  integer;
    v_load_id integer;
BEGIN
    -- The input data: the latest load of the Zensus rent table
    SELECT load_id INTO v_load_id
    FROM atlas.data_loads
    WHERE source_id = 'zensus2022_4000W-0004'
    ORDER BY loaded_at DESC, load_id DESC
    LIMIT 1;
    IF v_load_id IS NULL THEN
        RAISE EXCEPTION 'no data load found for the Zensus rent table; run load_db.py first';
    END IF;

    -- clock_timestamp(): the actual time, even when several runs share one transaction
    INSERT INTO atlas.model_runs (scenario_id, model_version, data_release, load_id, run_at)
    VALUES (p_scenario_id, p_model_version, p_data_release, v_load_id, clock_timestamp())
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
               (o.value >= p.schwelle * bund.value) AS angespannt,
               CASE WHEN o.value >= p.schwelle * bund.value
                    THEN p.kappung_angespannt
                    ELSE p.kappung_allgemein END AS kappung,
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
        SELECT region_id, year, horizont, wohnflaeche, angespannt, kappung,
               least(rueckstand, kappung)                              AS anstieg,
               -- highest rent for a tenancy that lies rueckstand below the comparison rent
               round(value * (1 + least(rueckstand, kappung)), 2)      AS miete_hoechstens,
               -- rent under average growth, also limited by the cap
               round(value * least(power(1 + mietindex_anstieg, horizont), 1 + kappung), 2)
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
    FROM berechnet
    -- How each Kreis was treated, stored with the results so that neither the website
    -- nor a later reader has to re-derive it from the parameters
    UNION ALL
    SELECT v_run_id, region_id, 'musterhaushalt', 'markt_angespannt',
           year + horizont::integer, angespannt::integer
    FROM berechnet
    UNION ALL
    SELECT v_run_id, region_id, 'musterhaushalt', 'kappungsgrenze_angewendet',
           year + horizont::integer, kappung
    FROM berechnet
    UNION ALL
    SELECT v_run_id, region_id, 'musterhaushalt', 'anstieg_hoechstens',
           year + horizont::integer, anstieg
    FROM berechnet;

    RETURN v_run_id;
END;
$$;
