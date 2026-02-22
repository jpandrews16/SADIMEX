-- =====================================================
-- SADIMEX SALES INTELLIGENCE — Initial Schema
-- Migration: 001_initial_schema.sql
-- Date: 2026-02-21
-- =====================================================

-- Habilitar extensiones
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =====================================================
-- TABLA: users (Jerarquía de usuarios)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.users (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nombre      TEXT NOT NULL,
    email       TEXT UNIQUE NOT NULL,
    rol         TEXT NOT NULL CHECK (rol IN ('gerente', 'supervisor', 'vendedor')),
    ciudad      TEXT CHECK (ciudad IN ('LPZ', 'CBBA', 'SCZ', 'ALL')),
    supervisor_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
    activo      BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE public.users IS 'Jerarquía de usuarios: gerente (ALL), supervisor (ciudad), vendedor (ciudad)';

-- =====================================================
-- TABLA: audio_records (Registros de audio de visitas)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.audio_records (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vendedor_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    ciudad              TEXT NOT NULL CHECK (ciudad IN ('LPZ', 'CBBA', 'SCZ')),
    fecha_visita        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cliente_nombre      TEXT NOT NULL DEFAULT 'Desconocido',
    archivo_local_path  TEXT,
    duracion_segundos   INTEGER,
    file_size_bytes     BIGINT,
    estado              TEXT NOT NULL DEFAULT 'pendiente'
                        CHECK (estado IN ('pendiente', 'procesando', 'diarizado', 'completado', 'error')),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE public.audio_records IS 'Registro de cada audio de visita de campo capturado por los vendedores';

-- =====================================================
-- TABLA: visit_analyses (Análisis individual por visita)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.visit_analyses (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    audio_id                UUID NOT NULL REFERENCES public.audio_records(id) ON DELETE CASCADE,
    vendedor_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    ciudad                  TEXT NOT NULL CHECK (ciudad IN ('LPZ', 'CBBA', 'SCZ')),
    fecha_analisis          TIMESTAMPTZ DEFAULT NOW(),
    kpis                    JSONB NOT NULL DEFAULT '{}',
    coaching_insights       JSONB NOT NULL DEFAULT '[]',
    resumen_ejecutivo       TEXT,
    score_visita            SMALLINT CHECK (score_visita BETWEEN 0 AND 100),
    semaforo                TEXT CHECK (semaforo IN ('verde', 'amarillo', 'rojo')),
    tendencia_relacion_cliente TEXT CHECK (tendencia_relacion_cliente IN ('positiva', 'neutral', 'negativa')),
    confianza_diarizacion   TEXT CHECK (confianza_diarizacion IN ('alta', 'media', 'baja', 'desconocida')),
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE public.visit_analyses IS 'Análisis de KPIs y coaching generado por IA para cada visita diarizada';
COMMENT ON COLUMN public.visit_analyses.kpis IS 'Schema: {saludo_adecuado, marcas_mencionadas[], marcas_faltantes[], cierre_exitoso, tecnica_cierre_usada, quiebre_de_stock_detectado, precio_correcto, venta_perfecta_score}';
COMMENT ON COLUMN public.visit_analyses.coaching_insights IS 'Array de {categoria, observacion, sugerencia_tactica}';

-- =====================================================
-- TABLA: weekly_scorecards (Scorecard semanal por vendedor)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.weekly_scorecards (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vendedor_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    supervisor_id       UUID REFERENCES public.users(id) ON DELETE SET NULL,
    ciudad              TEXT NOT NULL CHECK (ciudad IN ('LPZ', 'CBBA', 'SCZ')),
    semana_inicio       DATE NOT NULL,
    semana_fin          DATE NOT NULL,
    metricas_semana     JSONB NOT NULL DEFAULT '{}',
    tendencia           TEXT DEFAULT 'estable' CHECK (tendencia IN ('mejorando', 'estable', 'deteriorando')),
    coaching_prioritario JSONB DEFAULT '[]',
    semaforo_semana     TEXT CHECK (semaforo_semana IN ('verde', 'amarillo', 'rojo')),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (vendedor_id, semana_inicio)
);

COMMENT ON TABLE public.weekly_scorecards IS 'Scorecard semanal agregado por vendedor. Un registro por vendedor por semana.';
COMMENT ON COLUMN public.weekly_scorecards.metricas_semana IS 'Schema: {total_visitas, visitas_analizadas, score_promedio, marcas_con_brecha[], tasa_cierre, quiebres_detectados, venta_perfecta_rate}';

-- =====================================================
-- TABLA: knowledge_base_versions (Control de versiones del catálogo)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.knowledge_base_versions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    version     TEXT NOT NULL,
    contenido   JSONB NOT NULL,
    activa      BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    created_by  UUID REFERENCES public.users(id)
);

COMMENT ON TABLE public.knowledge_base_versions IS 'Control de versiones del catálogo Sadimex (marcas, precios, criterios de Venta Perfecta)';

-- =====================================================
-- ÍNDICES DE PERFORMANCE
-- =====================================================
CREATE INDEX IF NOT EXISTS idx_audio_records_vendedor ON public.audio_records(vendedor_id);
CREATE INDEX IF NOT EXISTS idx_audio_records_ciudad ON public.audio_records(ciudad);
CREATE INDEX IF NOT EXISTS idx_audio_records_estado ON public.audio_records(estado);
CREATE INDEX IF NOT EXISTS idx_audio_records_fecha ON public.audio_records(fecha_visita DESC);

CREATE INDEX IF NOT EXISTS idx_visit_analyses_vendedor ON public.visit_analyses(vendedor_id);
CREATE INDEX IF NOT EXISTS idx_visit_analyses_ciudad ON public.visit_analyses(ciudad);
CREATE INDEX IF NOT EXISTS idx_visit_analyses_fecha ON public.visit_analyses(fecha_analisis DESC);
CREATE INDEX IF NOT EXISTS idx_visit_analyses_semaforo ON public.visit_analyses(semaforo);

CREATE INDEX IF NOT EXISTS idx_weekly_scorecards_vendedor ON public.weekly_scorecards(vendedor_id);
CREATE INDEX IF NOT EXISTS idx_weekly_scorecards_ciudad ON public.weekly_scorecards(ciudad);
CREATE INDEX IF NOT EXISTS idx_weekly_scorecards_semana ON public.weekly_scorecards(semana_inicio DESC);

-- =====================================================
-- ROW LEVEL SECURITY (RLS)
-- Regla fundamental: acceso estrictamente por ciudad
-- =====================================================

ALTER TABLE public.audio_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.visit_analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.weekly_scorecards ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

-- Política: Vendedor ve solo sus propios registros
CREATE POLICY "vendedor_own_audio" ON public.audio_records
    FOR SELECT USING (
        vendedor_id = auth.uid()
    );

CREATE POLICY "vendedor_own_analyses" ON public.visit_analyses
    FOR SELECT USING (
        vendedor_id = auth.uid()
    );

CREATE POLICY "vendedor_own_scorecards" ON public.weekly_scorecards
    FOR SELECT USING (
        vendedor_id = auth.uid()
    );

-- Política: Supervisor ve solo su ciudad
-- (El campo ciudad en users del supervuisor debe coincidir)
CREATE POLICY "supervisor_ciudad_audio" ON public.audio_records
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.users u
            WHERE u.id = auth.uid()
            AND u.rol = 'supervisor'
            AND u.ciudad = audio_records.ciudad
        )
    );

CREATE POLICY "supervisor_ciudad_analyses" ON public.visit_analyses
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.users u
            WHERE u.id = auth.uid()
            AND u.rol = 'supervisor'
            AND u.ciudad = visit_analyses.ciudad
        )
    );

CREATE POLICY "supervisor_ciudad_scorecards" ON public.weekly_scorecards
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.users u
            WHERE u.id = auth.uid()
            AND u.rol = 'supervisor'
            AND u.ciudad = weekly_scorecards.ciudad
        )
    );

-- Política: Gerente ve todo (solo lectura)
CREATE POLICY "gerente_all_audio" ON public.audio_records
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.users u
            WHERE u.id = auth.uid()
            AND u.rol = 'gerente'
        )
    );

CREATE POLICY "gerente_all_analyses" ON public.visit_analyses
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.users u
            WHERE u.id = auth.uid()
            AND u.rol = 'gerente'
        )
    );

CREATE POLICY "gerente_all_scorecards" ON public.weekly_scorecards
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.users u
            WHERE u.id = auth.uid()
            AND u.rol = 'gerente'
        )
    );

-- Política: INSERT solo para el backend (service role key bypasses RLS)
-- Los inserts se realizan desde Python con service_role_key, no desde el cliente

-- =====================================================
-- TRIGGER: updated_at automático
-- =====================================================
CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON public.users
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER trg_audio_records_updated_at
    BEFORE UPDATE ON public.audio_records
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
