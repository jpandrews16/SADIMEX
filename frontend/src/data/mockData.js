// Mock data seeded from real pipeline demo results (2026-02-21)
// In production, this comes from the FastAPI backend / Supabase

export const mockVendedores = [
  { id: "v-001", nombre: "Juan Mamani", ciudad: "LPZ", supervisor_id: "s-001", activo: true },
  { id: "v-002", nombre: "Carmen Quispe", ciudad: "LPZ", supervisor_id: "s-001", activo: true },
  { id: "v-003", nombre: "Roberto Flores", ciudad: "LPZ", supervisor_id: "s-001", activo: true },
  { id: "v-004", nombre: "Ana Condori", ciudad: "LPZ", supervisor_id: "s-001", activo: true },
  { id: "v-005", nombre: "Pedro Chávez", ciudad: "CBBA", supervisor_id: "s-002", activo: true },
  { id: "v-006", nombre: "Lucía Vásquez", ciudad: "CBBA", supervisor_id: "s-002", activo: true },
  { id: "v-007", nombre: "Miguel Torrez", ciudad: "CBBA", supervisor_id: "s-002", activo: true },
  { id: "v-008", nombre: "Rosa Sánchez", ciudad: "CBBA", supervisor_id: "s-002", activo: true },
  { id: "v-009", nombre: "Carlos Medina", ciudad: "SCZ", supervisor_id: "s-003", activo: true },
  { id: "v-010", nombre: "Patricia Luna", ciudad: "SCZ", supervisor_id: "s-003", activo: true },
  { id: "v-011", nombre: "Ernesto Peña", ciudad: "SCZ", supervisor_id: "s-003", activo: true },
  { id: "v-012", nombre: "Gloria Rojas", ciudad: "SCZ", supervisor_id: "s-003", activo: true },
  { id: "v-013", nombre: "Sergio Vargas", ciudad: "SCZ", supervisor_id: "s-003", activo: true },
];

export const mockSupervisores = [
  { id: "s-001", nombre: "Ingrid Salazar", ciudad: "LPZ", rol: "supervisor" },
  { id: "s-002", nombre: "Marco Castro",   ciudad: "CBBA", rol: "supervisor" },
  { id: "s-003", nombre: "Nadia Moreno",   ciudad: "SCZ",  rol: "supervisor" },
];

export const mockScorecardsLPZ = [
  { vendedor_id:"v-001", nombre:"Juan Mamani", score:75, semaforo:"amarillo", tasa_cierre:0.8, visitas:6, marcas_brecha:[], vp_rate:0.33, tendencia:"estable" },
  { vendedor_id:"v-002", nombre:"Carmen Quispe", score:88, semaforo:"verde",    tasa_cierre:0.9, visitas:7, marcas_brecha:[], vp_rate:0.71, tendencia:"mejorando" },
  { vendedor_id:"v-003", nombre:"Roberto Flores", score:54, semaforo:"rojo",   tasa_cierre:0.5, visitas:5, marcas_brecha:["Wild Protein"], vp_rate:0.0, tendencia:"deteriorando" },
  { vendedor_id:"v-004", nombre:"Ana Condori", score:91, semaforo:"verde",      tasa_cierre:1.0, visitas:8, marcas_brecha:[], vp_rate:0.87, tendencia:"mejorando" },
];

export const mockScoreCardsCBBA = [
  { vendedor_id:"v-005", nombre:"Pedro Chávez", score:82, semaforo:"verde",     tasa_cierre:0.85, visitas:6, marcas_brecha:[], vp_rate:0.5, tendencia:"estable" },
  { vendedor_id:"v-006", nombre:"Lucía Vásquez", score:67, semaforo:"amarillo", tasa_cierre:0.7,  visitas:7, marcas_brecha:["Noel"], vp_rate:0.28, tendencia:"estable" },
  { vendedor_id:"v-007", nombre:"Miguel Torrez", score:48, semaforo:"rojo",     tasa_cierre:0.43, visitas:5, marcas_brecha:["Wild Protein","Noel"], vp_rate:0.0, tendencia:"deteriorando" },
  { vendedor_id:"v-008", nombre:"Rosa Sánchez", score:93, semaforo:"verde",     tasa_cierre:1.0,  visitas:8, marcas_brecha:[], vp_rate:0.87, tendencia:"mejorando" },
];

export const mockScorecardsSCZ = [
  { vendedor_id:"v-009", nombre:"Carlos Medina", score:77, semaforo:"amarillo", tasa_cierre:0.75, visitas:6, marcas_brecha:[], vp_rate:0.33, tendencia:"mejorando" },
  { vendedor_id:"v-010", nombre:"Patricia Luna", score:85, semaforo:"verde",    tasa_cierre:0.9,  visitas:7, marcas_brecha:[], vp_rate:0.57, tendencia:"estable" },
  { vendedor_id:"v-011", nombre:"Ernesto Peña", score:61, semaforo:"amarillo",  tasa_cierre:0.6,  visitas:5, marcas_brecha:["Wild Protein"], vp_rate:0.2, tendencia:"estable" },
  { vendedor_id:"v-012", nombre:"Gloria Rojas", score:90, semaforo:"verde",     tasa_cierre:0.95, visitas:8, marcas_brecha:[], vp_rate:0.75, tendencia:"mejorando" },
  { vendedor_id:"v-013", nombre:"Sergio Vargas", score:55, semaforo:"rojo",     tasa_cierre:0.5,  visitas:4, marcas_brecha:["Noel"], vp_rate:0.0, tendencia:"deteriorando" },
];

// Real analysis from pipeline demo (04f0b4c8-...)
export const mockVisitaDemo = {
  id: "04f0b4c8-1c25-4979-9f5c-29a9eb1ae295",
  cliente: "Tienda Demo - Canal Tradicional",
  fecha: "2026-02-21",
  ciudad: "LPZ",
  score_visita: 75,
  semaforo: "amarillo",
  kpis: {
    saludo_adecuado: true,
    marcas_mencionadas: ["Noel", "Wild Protein"],
    marcas_faltantes: [],
    cierre_exitoso: true,
    tecnica_cierre_usada: "Solicitud directa de pedido",
    quiebre_de_stock_detectado: true,
    precio_correcto: true,
    venta_perfecta_score: 75,
  },
  coaching_insights: [
    {
      categoria: "portafolio",
      observacion: "El vendedor mencionó 'novedades' pero no presentó específicamente cada novedad",
      sugerencia_tactica: "Después de mencionar las novedades, presentar brevemente una novedad de Noel (ej. nuevo sabor Festival) y otra de Wild Protein, destacando sus beneficios clave.",
    },
    {
      categoria: "cierre",
      observacion: "El cliente aceptó la propuesta inicial sin resistencia",
      sugerencia_tactica: "Intentar upsell con beneficio de volumen: 'Con una caja más de Festival, se lleva una Saltín de regalo' o sugerir un producto complementario.",
    },
    {
      categoria: "relacion_cliente",
      observacion: "Excelente rapport genuino con la caserita, uso de jerga local identificado",
      sugerencia_tactica: "Continuar cultivando este rapport. Complementar con una pregunta casual sobre el negocio para mostrar interés más allá de la venta.",
    },
  ],
  resumen_ejecutivo: "Juan de Sadimex realizó una visita comercial efectiva en el canal tradicional, demostrando excelente manejo del saludo, verificación de stock y cierre exitoso. Se evidenció fuerte rapport con la clienta mediante uso de jerga local. Existen oportunidades para estructurar mejor la oferta del portafolio y maximizar el valor del pedido durante el cierre.",
  segmentos: [
    { speaker: "VENDEDOR", texto: "Buenos días caserita, soy Juan de Sadimex. ¿Cómo le va hoy?" },
    { speaker: "CLIENTE",  texto: "Bien no más. ¿Qué me trae?" },
    { speaker: "VENDEDOR", texto: "Le traigo las novedades de Noel y Wild Protein. ¿Cómo está su stock de galletas Festival?" },
    { speaker: "CLIENTE",  texto: "Ya se me acabó, no hay caso, se venden rápido." },
    { speaker: "VENDEDOR", texto: "Perfecto, ¿le dejo dos cajas de Festival y una de Saltín? También tengo Wild Protein a precio especial." },
    { speaker: "CLIENTE",  texto: "¿Cuánto me sale todo?" },
    { speaker: "VENDEDOR", texto: "Festival dos cajas a 45 bolivianos cada una, Saltín 40, y Wild Protein 35. En total 165 bolivianos." },
    { speaker: "CLIENTE",  texto: "Ya pues, déjeme eso nomás." },
    { speaker: "VENDEDOR", texto: "¡Excelente! Le anoto el pedido. ¿Le puedo visitar el próximo miércoles también?" },
    { speaker: "CLIENTE",  texto: "Sí, venga nomás." },
    { speaker: "VENDEDOR", texto: "Muchas gracias caserita, hasta el miércoles entonces." },
  ],
};

export const cityStats = {
  LPZ:  { score: 77, verde: 2, amarillo: 1, rojo: 1, vendedores: 4, quiebres: 2 },
  CBBA: { score: 72, verde: 2, amarillo: 1, rojo: 1, vendedores: 4, quiebres: 3 },
  SCZ:  { score: 73, verde: 2, amarillo: 2, rojo: 1, vendedores: 5, quiebres: 4 },
};
