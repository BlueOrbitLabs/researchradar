-- Owlume Phase 12e: Atomic replacement of user interests and subtopics
-- SECURITY INVOKER: runs as the calling (authenticated) user, so RLS applies.
-- Explicit auth.uid() checks provide defense-in-depth and clear errors.
-- All input validation completes BEFORE any DELETE, so invalid input
-- preserves existing records.
-- Apply only after 001_initial_schema.sql. Do not apply to production without review.

-- Atomic replacement of all interests for the authenticated user.
-- NULL input is rejected before modification.
-- An empty array intentionally clears all existing interests.
-- NULL elements, empty strings and whitespace-only values are rejected.
CREATE OR REPLACE FUNCTION public.replace_user_interests(p_topics text[])
RETURNS void
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    t text;
BEGIN
    IF auth.uid() IS NULL THEN
        RAISE EXCEPTION 'not authenticated';
    END IF;
    -- Validate the entire input before modifying any data.
    IF p_topics IS NULL THEN
        RAISE EXCEPTION 'p_topics must not be null';
    END IF;
    FOREACH t IN ARRAY p_topics LOOP
        IF t IS NULL THEN
            RAISE EXCEPTION 'p_topics must not contain null elements';
        END IF;
        IF btrim(t) = '' THEN
            RAISE EXCEPTION 'p_topics must not contain empty or whitespace-only values';
        END IF;
    END LOOP;
    -- Validation complete; now perform the atomic replacement.
    DELETE FROM public.user_interests WHERE user_id = auth.uid();
    IF array_length(p_topics, 1) > 0 THEN
        INSERT INTO public.user_interests (user_id, topic)
        SELECT auth.uid(), t FROM unnest(p_topics) AS t
        ON CONFLICT (user_id, topic) DO NOTHING;
    END IF;
END;
$$;

-- Atomic replacement of all subtopics for the authenticated user.
-- p_subtopics is a JSON array of objects: [{"topic": "...", "subtopic": "..."}, ...]
-- NULL or non-array input is rejected before modification.
-- An empty JSON array intentionally clears all existing subtopics.
-- Elements must be objects with non-empty string topic and subtopic properties.
CREATE OR REPLACE FUNCTION public.replace_user_subtopics(p_subtopics jsonb)
RETURNS void
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    elem jsonb;
    v_topic text;
    v_subtopic text;
BEGIN
    IF auth.uid() IS NULL THEN
        RAISE EXCEPTION 'not authenticated';
    END IF;
    -- Validate the entire input before modifying any data.
    IF p_subtopics IS NULL THEN
        RAISE EXCEPTION 'p_subtopics must not be null';
    END IF;
    IF jsonb_typeof(p_subtopics) <> 'array' THEN
        RAISE EXCEPTION 'p_subtopics must be a JSON array';
    END IF;
    FOR elem IN SELECT jsonb_array_elements(p_subtopics) LOOP
        IF jsonb_typeof(elem) <> 'object' THEN
            RAISE EXCEPTION 'p_subtopics elements must be objects';
        END IF;
        IF NOT (elem ? 'topic') OR NOT (elem ? 'subtopic') THEN
            RAISE EXCEPTION 'p_subtopics elements must have topic and subtopic';
        END IF;
        IF jsonb_typeof(elem->'topic') <> 'string' OR jsonb_typeof(elem->'subtopic') <> 'string' THEN
            RAISE EXCEPTION 'topic and subtopic must be strings';
        END IF;
        v_topic := elem->>'topic';
        v_subtopic := elem->>'subtopic';
        IF v_topic IS NULL OR v_subtopic IS NULL THEN
            RAISE EXCEPTION 'topic and subtopic must not be null';
        END IF;
        IF btrim(v_topic) = '' OR btrim(v_subtopic) = '' THEN
            RAISE EXCEPTION 'topic and subtopic must not be empty or whitespace-only';
        END IF;
    END LOOP;
    -- Validation complete; now perform the atomic replacement.
    DELETE FROM public.user_subtopics WHERE user_id = auth.uid();
    IF jsonb_array_length(p_subtopics) > 0 THEN
        FOR elem IN SELECT jsonb_array_elements(p_subtopics) LOOP
            INSERT INTO public.user_subtopics (user_id, topic, subtopic)
            VALUES (auth.uid(), elem->>'topic', elem->>'subtopic')
            ON CONFLICT (user_id, topic, subtopic) DO NOTHING;
        END LOOP;
    END IF;
END;
$$;

-- Allow authenticated users to execute (RLS still governs the underlying tables).
GRANT EXECUTE ON FUNCTION public.replace_user_interests(text[]) TO authenticated;
GRANT EXECUTE ON FUNCTION public.replace_user_subtopics(jsonb) TO authenticated;

-- Revoke from anon/public to prevent unauthenticated calls.
REVOKE EXECUTE ON FUNCTION public.replace_user_interests(text[]) FROM anon, public;
REVOKE EXECUTE ON FUNCTION public.replace_user_subtopics(jsonb) FROM anon, public;
