# SOP 05 — Control de Acceso
## SADIMEX Sales Intelligence | Layer 1: Architecture

**Última actualización:** 2026-02-21
**Referencia DB:** `migrations/001_initial_schema.sql` (Sección RLS)

---

## Objetivo
Garantizar que los datos de cada ciudad sean accesibles únicamente por los usuarios autorizados. La seguridad es multicapa: BD (RLS) + Backend (API) + Frontend (rutas protegidas).

## Matriz de Acceso

| Recurso | Gerente (ALL) | Supervisor (ciudad propia) | Vendedor |
|---------|:---:|:---:|:---:|
| `audio_records` (todas las ciudades) | ✅ lectura | ❌ | ❌ |
| `audio_records` (su ciudad) | ✅ | ✅ lectura | ❌ |
| `visit_analyses` (su ciudad) | ✅ | ✅ lectura | Solo las propias |
| `weekly_scorecards` (su ciudad) | ✅ | ✅ lectura | Solo el propio |
| Configuración del sistema | ❌ | ❌ | ❌ |
| Editar `knowledge.json` | Admin del sistema | ❌ | ❌ |

## Capas de Seguridad

### Capa 1: Supabase RLS (Base de Datos)
Las políticas están definidas en `migrations/001_initial_schema.sql`.
Funcionan con `auth.uid()` del token JWT de Supabase.
- Los `INSERT` se realizan con `service_role_key` desde el backend Python (bypassa RLS).
- Los `SELECT` del cliente React usan `anon_key` + JWT del usuario (respeta RLS).

### Capa 2: Backend API (FastAPI)
Cada endpoint que devuelve datos filtra adicionalmente por ciudad:

```python
# Pseudocódigo del filtro en el backend
current_user = get_current_user(token)  # Extrae rol y ciudad del JWT
if current_user.rol == "supervisor":
    query = query.eq("ciudad", current_user.ciudad)
elif current_user.rol == "vendedor":
    query = query.eq("vendedor_id", current_user.id)
# gerente: sin filtro adicional
```

### Capa 3: Frontend React (Rutas protegidas)
- `GerenciaView` → solo accesible si `rol === 'gerente'`
- `SupervisorView` → solo accesible si `rol === 'supervisor'`
- `VendedorView` → solo accesible si `rol === 'vendedor'`

## Reglas Absolutas
1. **El control de ciudad es el backend**, no el frontend. El frontend solo muestra; nunca filtra datos de seguridad.
2. **El Gerente no puede editar configuración.** Si intenta llamar un endpoint de escritura de configuración → `403 Forbidden`.
3. **Los supervisores no comparten datos entre ciudades.** Un supervisor de CBBA que intente acceder a datos de LPZ vía URL manipulation → 0 resultados (RLS lo garantiza a nivel BD).
4. **Logs de acceso:** Todo intento de acceso cross-ciudad se registra en la tabla de logs de Supabase (a implementar en versión 2).

## Tokens JWT
- Generados por Supabase Auth al login.
- Contienen `rol` y `ciudad` como custom claims.
- Expiración: 1 hora. Refresh token: 7 días.
