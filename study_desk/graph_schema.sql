-- Serialize first-time graph schema setup across request threads.
SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':graph-schema', 0));

CREATE TABLE IF NOT EXISTS graph_build (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model TEXT NOT NULL, fingerprint TEXT NOT NULL, data JSONB NOT NULL,
    UNIQUE(model, fingerprint)
);
CREATE TABLE IF NOT EXISTS graph_input (
    build_id BIGINT REFERENCES graph_build(id) ON DELETE CASCADE,
    video_id BIGINT REFERENCES video_intake(id), model TEXT NOT NULL, run_number INTEGER NOT NULL,
    snapshot JSONB NOT NULL,
    PRIMARY KEY(build_id,video_id),
    FOREIGN KEY(video_id,model,run_number) REFERENCES study_run_history(video_id,model,run_number)
);
CREATE TABLE IF NOT EXISTS evidence_span (
    id TEXT PRIMARY KEY, video_id BIGINT REFERENCES video_intake(id) ON DELETE CASCADE,
    source_hash TEXT NOT NULL, source_id TEXT NOT NULL,
    start_s DOUBLE PRECISION, end_s DOUBLE PRECISION,
    start_char INTEGER NOT NULL, end_char INTEGER NOT NULL, text_content TEXT NOT NULL,
    embedding REAL[] NOT NULL CHECK(cardinality(embedding)=768),
    embedding_model TEXT NOT NULL, embedding_revision TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS graph_claim (
    build_id BIGINT REFERENCES graph_build(id) ON DELETE CASCADE, id TEXT NOT NULL,
    video_id BIGINT NOT NULL, extraction_id TEXT NOT NULL, claim_text TEXT NOT NULL,
    original JSONB NOT NULL, PRIMARY KEY(build_id,id),
    FOREIGN KEY(build_id,video_id) REFERENCES graph_input(build_id,video_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS claim_evidence (
    build_id BIGINT, claim_id TEXT, span_id TEXT REFERENCES evidence_span(id),
    PRIMARY KEY(build_id,claim_id,span_id),
    FOREIGN KEY(build_id,claim_id) REFERENCES graph_claim(build_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS concept (
    build_id BIGINT REFERENCES graph_build(id) ON DELETE CASCADE, id INTEGER NOT NULL,
    label TEXT NOT NULL, description TEXT NOT NULL, merged_into_id INTEGER,
    embedding REAL[] NOT NULL CHECK(cardinality(embedding)=768),
    embedding_model TEXT NOT NULL, embedding_revision TEXT NOT NULL,
    PRIMARY KEY(build_id,id), CHECK(merged_into_id IS NULL OR merged_into_id <> id),
    FOREIGN KEY(build_id,merged_into_id) REFERENCES concept(build_id,id)
);
CREATE TABLE IF NOT EXISTS concept_alias (
    build_id BIGINT, concept_id INTEGER, alias TEXT,
    PRIMARY KEY(build_id,concept_id,alias),
    FOREIGN KEY(build_id,concept_id) REFERENCES concept(build_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS claim_concept (
    build_id BIGINT, claim_id TEXT, concept_id INTEGER,
    PRIMARY KEY(build_id,claim_id,concept_id),
    FOREIGN KEY(build_id,claim_id) REFERENCES graph_claim(build_id,id) ON DELETE CASCADE,
    FOREIGN KEY(build_id,concept_id) REFERENCES concept(build_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS concept_resolution (
    build_id BIGINT, candidate_id INTEGER, matched_id INTEGER,
    decision TEXT NOT NULL, rationale TEXT NOT NULL, response_path TEXT NOT NULL,
    PRIMARY KEY(build_id,candidate_id,matched_id),
    FOREIGN KEY(build_id,candidate_id) REFERENCES concept(build_id,id) ON DELETE CASCADE,
    FOREIGN KEY(build_id,matched_id) REFERENCES concept(build_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS subject_area (
    build_id BIGINT REFERENCES graph_build(id) ON DELETE CASCADE, id INTEGER,
    label TEXT NOT NULL, description TEXT NOT NULL, PRIMARY KEY(build_id,id)
);
CREATE TABLE IF NOT EXISTS concept_subject_area (
    build_id BIGINT, concept_id INTEGER, area_id INTEGER,
    PRIMARY KEY(build_id,concept_id,area_id),
    FOREIGN KEY(build_id,concept_id) REFERENCES concept(build_id,id) ON DELETE CASCADE,
    FOREIGN KEY(build_id,area_id) REFERENCES subject_area(build_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS concept_edge (
    build_id BIGINT, id INTEGER, source_id INTEGER, target_id INTEGER,
    predicate TEXT NOT NULL, rationale TEXT NOT NULL, claim_ids JSONB NOT NULL,
    PRIMARY KEY(build_id,id), CHECK(source_id<>target_id),
    FOREIGN KEY(build_id,source_id) REFERENCES concept(build_id,id) ON DELETE CASCADE,
    FOREIGN KEY(build_id,target_id) REFERENCES concept(build_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS edge_evidence (
    build_id BIGINT, edge_id INTEGER, span_id TEXT REFERENCES evidence_span(id),
    PRIMARY KEY(build_id,edge_id,span_id),
    FOREIGN KEY(build_id,edge_id) REFERENCES concept_edge(build_id,id) ON DELETE CASCADE
);

-- A queued worker must not overwrite an explicit hold, including workers
-- already running older code when the user places the build on hold.
DO $install$ BEGIN
IF to_regprocedure('protect_graph_hold()') IS NULL THEN
EXECUTE $definition$
CREATE FUNCTION protect_graph_hold() RETURNS trigger LANGUAGE plpgsql AS $body$
BEGIN
    IF OLD.data->>'status' = 'held' THEN
        IF NEW.data->>'status' = 'running' THEN
            RAISE EXCEPTION 'Graph build % is on hold at the user request', OLD.id;
        ELSIF NEW.data->>'status' IN ('error', 'complete') THEN
            RETURN OLD;
        END IF;
    END IF;
    RETURN NEW;
END;
$body$;
$definition$;
END IF;
END $install$;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='graph_hold_guard' AND tgrelid='graph_build'::regclass) THEN
        CREATE TRIGGER graph_hold_guard BEFORE UPDATE ON graph_build
        FOR EACH ROW EXECUTE FUNCTION protect_graph_hold();
    END IF;
END $$;
