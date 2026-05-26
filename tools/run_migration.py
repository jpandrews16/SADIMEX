#!/usr/bin/env python3
"""Direct Postgres migration runner for SADIMEX.
Connects to Supabase Postgres via connection pooler.
"""
import psycopg2
import sys

# Supabase connection via Transaction pooler (port 6543)
# The password is the database password set when the project was created
# If this doesn't work, user needs to provide their database password
# from Supabase Dashboard > Settings > Database > Connection String

# Try multiple connection methods
CONNECTION_STRINGS = [
    # Method 1: Direct connection via IPv4
    "postgresql://postgres.rdhderpzkbhsargdvlvc:sadimex2026@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
    # Method 2: Session mode pooler
    "postgresql://postgres.rdhderpzkbhsargdvlvc:sadimex2026@aws-0-us-east-1.pooler.supabase.com:5432/postgres",
    # Method 3: Direct (no pooler)
    "postgresql://postgres:sadimex2026@db.rdhderpzkbhsargdvlvc.supabase.co:5432/postgres",
]

MIGRATION_SQL = """
-- audio_records
CREATE TABLE IF NOT EXISTS public.audio_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vendedor_id UUID NOT NULL REFERENCES public.sadimex_profiles(id) ON DELETE CASCADE,
    ciudad TEXT NOT NULL CHECK (ciudad IN ('LPZ','CBBA','SCZ')),
    fecha_visita TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cliente_nombre TEXT NOT NULL DEFAULT 'Desconocido',
    archivo_storage_path TEXT,
    duracion_segundos INTEGER,
    file_size_bytes BIGINT,
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente','procesando','diarizado','completado','error')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- visit_analyses
CREATE TABLE IF NOT EXISTS public.visit_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audio_id UUID NOT NULL REFERENCES public.audio_records(id) ON DELETE CASCADE,
    vendedor_id UUID NOT NULL REFERENCES public.sadimex_profiles(id) ON DELETE CASCADE,
    ciudad TEXT NOT NULL CHECK (ciudad IN ('LPZ','CBBA','SCZ')),
    fecha_analisis TIMESTAMPTZ DEFAULT NOW(),
    kpis JSONB NOT NULL DEFAULT '{}',
    coaching_insights JSONB NOT NULL DEFAULT '[]',
    resumen_ejecutivo TEXT,
    score_visita SMALLINT CHECK (score_visita BETWEEN 0 AND 100),
    semaforo TEXT CHECK (semaforo IN ('verde','amarillo','rojo')),
    segmentos JSONB DEFAULT '[]',
    confianza_diarizacion TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- weekly_scorecards
CREATE TABLE IF NOT EXISTS public.weekly_scorecards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vendedor_id UUID NOT NULL REFERENCES public.sadimex_profiles(id) ON DELETE CASCADE,
    supervisor_id UUID REFERENCES public.sadimex_profiles(id) ON DELETE SET NULL,
    ciudad TEXT NOT NULL CHECK (ciudad IN ('LPZ','CBBA','SCZ')),
    semana_inicio DATE NOT NULL,
    semana_fin DATE NOT NULL,
    metricas_semana JSONB NOT NULL DEFAULT '{}',
    tendencia TEXT DEFAULT 'estable' CHECK (tendencia IN ('mejorando','estable','deteriorando')),
    coaching_prioritario JSONB DEFAULT '[]',
    semaforo_semana TEXT CHECK (semaforo_semana IN ('verde','amarillo','rojo')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(vendedor_id, semana_inicio)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_audio_vendedor ON public.audio_records(vendedor_id);
CREATE INDEX IF NOT EXISTS idx_audio_estado ON public.audio_records(estado);
CREATE INDEX IF NOT EXISTS idx_audio_fecha ON public.audio_records(fecha_visita DESC);
CREATE INDEX IF NOT EXISTS idx_va_vendedor ON public.visit_analyses(vendedor_id);
CREATE INDEX IF NOT EXISTS idx_va_ciudad ON public.visit_analyses(ciudad);
CREATE INDEX IF NOT EXISTS idx_va_fecha ON public.visit_analyses(fecha_analisis DESC);
CREATE INDEX IF NOT EXISTS idx_ws_vendedor ON public.weekly_scorecards(vendedor_id);
CREATE INDEX IF NOT EXISTS idx_ws_semana ON public.weekly_scorecards(semana_inicio DESC);

-- RLS
ALTER TABLE public.audio_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.visit_analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.weekly_scorecards ENABLE ROW LEVEL SECURITY;

-- Policies: Vendedor (own data)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'vendedor_audio') THEN
    CREATE POLICY "vendedor_audio" ON public.audio_records FOR SELECT USING (vendedor_id = auth.uid());
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'vendedor_analyses') THEN
    CREATE POLICY "vendedor_analyses" ON public.visit_analyses FOR SELECT USING (vendedor_id = auth.uid());
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'vendedor_scorecards') THEN
    CREATE POLICY "vendedor_scorecards" ON public.weekly_scorecards FOR SELECT USING (vendedor_id = auth.uid());
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'vendedor_insert_audio') THEN
    CREATE POLICY "vendedor_insert_audio" ON public.audio_records FOR INSERT WITH CHECK (vendedor_id = auth.uid());
  END IF;
END $$;

-- Policies: Supervisor (city-scoped)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'supervisor_audio') THEN
    CREATE POLICY "supervisor_audio" ON public.audio_records FOR SELECT USING (
      EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'supervisor' AND p.ciudad = audio_records.ciudad)
    );
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'supervisor_analyses') THEN
    CREATE POLICY "supervisor_analyses" ON public.visit_analyses FOR SELECT USING (
      EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'supervisor' AND p.ciudad = visit_analyses.ciudad)
    );
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'supervisor_scorecards') THEN
    CREATE POLICY "supervisor_scorecards" ON public.weekly_scorecards FOR SELECT USING (
      EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'supervisor' AND p.ciudad = weekly_scorecards.ciudad)
    );
  END IF;
END $$;

-- Policies: Gerente (all data)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'gerente_audio') THEN
    CREATE POLICY "gerente_audio" ON public.audio_records FOR SELECT USING (
      EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'gerente')
    );
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'gerente_analyses') THEN
    CREATE POLICY "gerente_analyses" ON public.visit_analyses FOR SELECT USING (
      EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'gerente')
    );
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'gerente_scorecards') THEN
    CREATE POLICY "gerente_scorecards" ON public.weekly_scorecards FOR SELECT USING (
      EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'gerente')
    );
  END IF;
END $$;

-- Policies: Admin (all data)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'admin_audio') THEN
    CREATE POLICY "admin_audio" ON public.audio_records FOR SELECT USING (
      EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'admin')
    );
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'admin_analyses') THEN
    CREATE POLICY "admin_analyses" ON public.visit_analyses FOR SELECT USING (
      EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'admin')
    );
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'admin_scorecards') THEN
    CREATE POLICY "admin_scorecards" ON public.weekly_scorecards FOR SELECT USING (
      EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'admin')
    );
  END IF;
END $$;

-- Service role INSERT/UPDATE policies for backend
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'service_insert_audio') THEN
    CREATE POLICY "service_insert_audio" ON public.audio_records FOR INSERT WITH CHECK (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'service_update_audio') THEN
    CREATE POLICY "service_update_audio" ON public.audio_records FOR UPDATE USING (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'service_insert_analyses') THEN
    CREATE POLICY "service_insert_analyses" ON public.visit_analyses FOR INSERT WITH CHECK (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'service_insert_scorecards') THEN
    CREATE POLICY "service_insert_scorecards" ON public.weekly_scorecards FOR INSERT WITH CHECK (true);
  END IF;
END $$;
"""

def main():
    print("🚀 SADIMEX Direct Postgres Migration\n")

    conn = None
    for cs in CONNECTION_STRINGS:
        masked = cs.split("@")[1] if "@" in cs else cs
        print(f"  Trying: ...@{masked}")
        try:
            conn = psycopg2.connect(cs, connect_timeout=10)
            conn.autocommit = True
            print(f"  ✅ Connected!\n")
            break
        except Exception as e:
            print(f"  ❌ {e}\n")
            continue

    if not conn:
        print("=" * 60)
        print("❌ Could not connect to Postgres.")
        print("   Please provide your database password.")
        print("   Find it at: Supabase Dashboard → Settings → Database")
        print("   Then update this script's CONNECTION_STRINGS.")
        return False

    try:
        cur = conn.cursor()
        print("📦 Running migration SQL...")
        cur.execute(MIGRATION_SQL)
        print("\n✅ All tables, indexes, and policies created successfully!")

        # Verify
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name IN ('audio_records', 'visit_analyses', 'weekly_scorecards')
            ORDER BY table_name
        """)
        tables = [r[0] for r in cur.fetchall()]
        print(f"\n📊 Verified tables: {', '.join(tables)}")

        if len(tables) == 3:
            print("🎉 Migration complete — all 3 tables exist!")
        else:
            print(f"⚠️  Expected 3 tables, found {len(tables)}")

        cur.close()
        conn.close()
        return True

    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        if conn:
            conn.close()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
