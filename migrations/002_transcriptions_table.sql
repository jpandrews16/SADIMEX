-- =====================================================
-- SADIMEX SALES INTELLIGENCE — Transcriptions Table
-- Migration: 002_transcriptions_table.sql
-- Date: 2026-05-24
-- =====================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS public.transcriptions (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at        TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    source            TEXT NOT NULL CHECK (source IN ('file', 'microphone')),
    duration_seconds  NUMERIC(10, 2),
    raw_text          TEXT NOT NULL DEFAULT '',
    language          TEXT DEFAULT 'es',
    confidence_score  NUMERIC(4, 3) CHECK (confidence_score BETWEEN 0 AND 1),
    audio_file_path   TEXT,
    metadata          JSONB NOT NULL DEFAULT '{}',
    user_id           UUID REFERENCES auth.users(id) ON DELETE SET NULL
);

-- Indexes for heavy analytics queries
CREATE INDEX IF NOT EXISTS idx_transcriptions_created_at
    ON public.transcriptions(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_transcriptions_source
    ON public.transcriptions(source);

CREATE INDEX IF NOT EXISTS idx_transcriptions_user_id
    ON public.transcriptions(user_id);

CREATE INDEX IF NOT EXISTS idx_transcriptions_metadata
    ON public.transcriptions USING GIN(metadata);

-- RLS
ALTER TABLE public.transcriptions ENABLE ROW LEVEL SECURITY;

-- Cada usuario ve solo sus propias transcripciones
CREATE POLICY "users_own_transcriptions_select" ON public.transcriptions
    FOR SELECT USING (user_id = auth.uid());

-- Inserts vienen desde la Edge Function con service_role (bypasses RLS)
-- Los admins pueden ver todo
CREATE POLICY "admin_all_transcriptions" ON public.transcriptions
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.sadimex_profiles p
            WHERE p.id = auth.uid() AND p.rol = 'admin'
        )
    );
