// Quick migration runner — uses Supabase service role key to execute DDL
import { createClient } from '@supabase/supabase-js';

const supabase = createClient(
  'https://rdhderpzkbhsargdvlvc.supabase.co',
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJkaGRlcnB6a2Joc2FyZ2R2bHZjIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTI5NjY3MywiZXhwIjoyMDg2ODcyNjczfQ.GrpMFbI836Vgaf7d6V-rzbDyHlNOl9DnuGwRBY6fRl8'
);

// Execute SQL statements one-by-one via rpc
const sqls = [
  // audio_records
  `CREATE TABLE IF NOT EXISTS public.audio_records (
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
  )`,

  // visit_analyses
  `CREATE TABLE IF NOT EXISTS public.visit_analyses (
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
  )`,

  // weekly_scorecards
  `CREATE TABLE IF NOT EXISTS public.weekly_scorecards (
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
  )`,

  // Indexes
  `CREATE INDEX IF NOT EXISTS idx_audio_vendedor ON public.audio_records(vendedor_id)`,
  `CREATE INDEX IF NOT EXISTS idx_audio_estado ON public.audio_records(estado)`,
  `CREATE INDEX IF NOT EXISTS idx_audio_fecha ON public.audio_records(fecha_visita DESC)`,
  `CREATE INDEX IF NOT EXISTS idx_va_vendedor ON public.visit_analyses(vendedor_id)`,
  `CREATE INDEX IF NOT EXISTS idx_va_ciudad ON public.visit_analyses(ciudad)`,
  `CREATE INDEX IF NOT EXISTS idx_va_fecha ON public.visit_analyses(fecha_analisis DESC)`,
  `CREATE INDEX IF NOT EXISTS idx_ws_vendedor ON public.weekly_scorecards(vendedor_id)`,
  `CREATE INDEX IF NOT EXISTS idx_ws_semana ON public.weekly_scorecards(semana_inicio DESC)`,

  // RLS
  `ALTER TABLE public.audio_records ENABLE ROW LEVEL SECURITY`,
  `ALTER TABLE public.visit_analyses ENABLE ROW LEVEL SECURITY`,
  `ALTER TABLE public.weekly_scorecards ENABLE ROW LEVEL SECURITY`,

  // Policies
  `CREATE POLICY "vendedor_audio" ON public.audio_records FOR SELECT USING (vendedor_id = auth.uid())`,
  `CREATE POLICY "vendedor_analyses" ON public.visit_analyses FOR SELECT USING (vendedor_id = auth.uid())`,
  `CREATE POLICY "vendedor_scorecards" ON public.weekly_scorecards FOR SELECT USING (vendedor_id = auth.uid())`,
  `CREATE POLICY "vendedor_insert_audio" ON public.audio_records FOR INSERT WITH CHECK (vendedor_id = auth.uid())`,
  `CREATE POLICY "supervisor_audio" ON public.audio_records FOR SELECT USING (EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'supervisor' AND p.ciudad = audio_records.ciudad))`,
  `CREATE POLICY "supervisor_analyses" ON public.visit_analyses FOR SELECT USING (EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'supervisor' AND p.ciudad = visit_analyses.ciudad))`,
  `CREATE POLICY "supervisor_scorecards" ON public.weekly_scorecards FOR SELECT USING (EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'supervisor' AND p.ciudad = weekly_scorecards.ciudad))`,
  `CREATE POLICY "gerente_audio" ON public.audio_records FOR SELECT USING (EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'gerente'))`,
  `CREATE POLICY "gerente_analyses" ON public.visit_analyses FOR SELECT USING (EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'gerente'))`,
  `CREATE POLICY "gerente_scorecards" ON public.weekly_scorecards FOR SELECT USING (EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'gerente'))`,
  `CREATE POLICY "admin_audio" ON public.audio_records FOR SELECT USING (EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'admin'))`,
  `CREATE POLICY "admin_analyses" ON public.visit_analyses FOR SELECT USING (EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'admin'))`,
  `CREATE POLICY "admin_scorecards" ON public.weekly_scorecards FOR SELECT USING (EXISTS (SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = 'admin'))`,
];

async function run() {
  console.log('🚀 Running SADIMEX migration...\n');
  let ok = 0, fail = 0;
  for (const sql of sqls) {
    const label = sql.trim().substring(0, 60).replace(/\n/g, ' ');
    const { error } = await supabase.rpc('exec_sql', { query: sql });
    if (error) {
      // Try via raw fetch (pg-meta API)
      console.log(`⚠️  RPC failed for: ${label}... — ${error.message}`);
      fail++;
    } else {
      console.log(`✅ ${label}...`);
      ok++;
    }
  }
  console.log(`\n📊 Results: ${ok} succeeded, ${fail} failed`);
}

run();
