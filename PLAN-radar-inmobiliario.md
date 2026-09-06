# Radar Inmobiliario — Plan técnico completo

**Documento único.** Reemplaza cualquier versión anterior.
Preparado para revisión conjunta con un corredor inmobiliario matriculado.

---

## 0. Resumen ejecutivo

Aplicación web personal que monitorea diariamente Zonaprop, Argenprop y Mercado Libre en un grupo de barrios del oeste de CABA, deduplica los avisos repetidos, estima el valor de mercado de cada propiedad contra sus comparables, y calcula **cuánto habría que poner de más para pasarse de la propiedad actual a cada candidata**, neto de comisiones, sellos y escritura.

- **Hosting:** GitHub Pages (estático) + GitHub Actions (cron diario). Costo cero.
- **Zona núcleo:** Vélez Sarsfield y Floresta. Monte Castro entra por ser donde está la propiedad a vender.
- **Horizonte:** dashboard vivo en la primera sesión de desarrollo; estimaciones de cierre confiables a los 90 días de captura.

**Lo que este sistema NO es:** un tasador. Estima precios de *oferta* y les aplica una brecha de negociación estadística. Sobre una unidad individual, el error es de dos dígitos. Sirve para decidir qué visitar y con cuánto margen negociar. No reemplaza el criterio de un corredor que pisa la propiedad.

---

## 1. La propiedad a vender

Dato de partida, provisto por el corredor que hizo la tasación:

| Concepto | Valor |
|---|---|
| Ubicación | Monte Castro, CABA |
| Tipo | Departamento, 3 ambientes |
| Superficie | 72 m² |
| **Precio máximo de venta realista** | **USD 130.000** |
| Precio de publicación sugerido | USD 138.000 – 140.000 |
| USD/m² al valor de venta | **1.806** |
| USD/m² al valor de publicación | 1.917 – 1.944 |
| Margen de negociación cargado | 6,2% – 7,1% |

**Corrección conceptual importante:** los 140.000 no son una valuación, son una **táctica de anclaje**. El número que el sistema tiene que auditar y usar en todos los cálculos es **130.000**. Usar 140.000 como valor de la propiedad sería incorporar el margen de negociación como si fuera patrimonio.

### Lo que el sistema debe verificar sobre esto

1. **¿Los USD 1.806/m² son de mercado para un 3 ambientes de 72 m² en Monte Castro?** Se responde con comparables del propio barrio, no con promedios de CABA.
2. **¿El margen del 7% cargado es el adecuado?** Los índices de operaciones concretadas en CABA muestran hoy una brecha de publicación a cierre en torno al 4,8%. Cargar 7% es cargar por encima del promedio de la ciudad. Eso puede ser correcto —los barrios de menor demanda negocian más que el corredor norte— pero tiene un costo: un aviso por encima de sus comparables recibe menos visitas y acumula más días en mercado. El sistema puede medir ese trade-off con datos reales de la zona en vez de discutirlo por intuición.
3. **¿Cuánto tarda en venderse esta tipología en esta zona?** Días en mercado medianos de 3 ambientes en Monte Castro y barrios linderos. Define si conviene vender antes de comprar.

### Escenarios de venta

El sistema nunca trabaja con un solo número. Tres columnas, siempre:

| Escenario | Precio | USD/m² | Supuesto |
|---|---|---|---|
| Optimista | 134.000 | 1.861 | Cierra con una contraoferta del orden del promedio de CABA |
| **Base** | **130.000** | **1.806** | El máximo que indicó el corredor |
| Conservador | 123.500 | 1.715 | Requiere un recorte del 5% sobre la base para cerrar |

Una propiedad candidata que solo "cierra" en el escenario optimista **no es una candidata**.

Configuración en `config/mi_propiedad.yaml`:

```yaml
mi_propiedad:
  barrio: "Monte Castro"
  tipo: "departamento"
  ambientes: 3
  m2_cubiertos: 72
  m2_total: 72
  antiguedad: null          # completar
  piso: null                # completar
  ascensor: null            # completar
  expensas_ars: null        # completar
  precio_venta_max_usd: 130000    # tasación del corredor — el número real
  precio_publicacion_usd: 140000  # ancla de negociación, NO es valor
  estado_venta: "sin_publicar"
escenarios:
  optimista_usd: 134000
  base_usd: 130000
  conservador_usd: 123500
```

---

## 2. Métrica principal: la brecha neta

La columna que ordena toda la aplicación no es el precio de lista, sino **cuánto tengo que poner**:

```
neto_venta   = precio_venta_mio
             − comisión_venta − impuesto_transferencia − gastos

costo_compra = precio_compra_negociado
             + sellos + escritura + comisión_compra + gastos

brecha_neta  = costo_compra − neto_venta
```

`precio_compra_negociado` = precio de lista × (1 − brecha estimada del barrio). **Nunca el precio de lista pelado.**

Parámetros en `config/costos.yaml`, ninguno hardcodeado:

```yaml
costos:
  comision_venta_pct: 0.03
  comision_compra_pct: 0.03
  iva_sobre_comision: 0.21
  sellos_pct: 0.027               # CABA 2026 — confirmar vigencia
  sellos_a_mi_cargo_pct: 0.5
  escritura_pct: 0.02
  gastos_fijos_usd: 1500
  impuesto_transferencia_pct: 0.0 # DEPENDE DEL CASO — ver abajo
```

**No opcional:** el tratamiento impositivo de la venta depende de cuándo se adquirió la propiedad, de si es vivienda única y de si se reinvierte en otra vivienda. La diferencia entre un caso y otro son miles de dólares. Estos campos existen para cargar lo que confirme un escribano, no para que el sistema lo deduzca. Lo mismo con sellos: hay exenciones para vivienda única de valor acotado y la alícuota cambió recientemente.

---

## 3. Estimación del precio de cierre

### 3.1 Las tres brechas (confundirlas arruina el cálculo)

| Brecha | Qué mide | Magnitud |
|---|---|---|
| **Contraoferta** | Último precio publicado → escritura, de lo **que se vendió** | 4–5% hoy |
| **Recorte acumulado** | Precio original → último precio publicado | 0–20%, variable |
| **Brecha del universo** | Lista de **todo lo publicado** → cierres | Mucho mayor |

La cifra que publican los índices es la primera, y se mide **solo sobre operaciones concretadas**: las propiedades sobrevaluadas que nunca se venden no entran en la estadística. Es sesgo de supervivencia. Un relevamiento de 2023 ubicaba la diferencia contra el valor de lista de lo efectivamente vendido en torno al 6%, y contra el universo de lo publicado en 24%.

**Consecuencia:** aplicar 4,8% a cualquier aviso subestima el margen, porque ese aviso puede ser uno de los que no se venden. Hay que separar el recorte que el aviso **ya hizo** del margen que **le queda**. Un aviso que bajó 12% y lleva 200 días publicado tiene más margen restante, no menos: su precio original estaba mal.

### 3.2 Fuentes, por orden de valor

**A1 — Índice M² Real (RE/MAX + UCEMA + Reporte Inmobiliario).** La más importante. Releva mensualmente valores efectivos de operaciones concretadas de departamentos usados de 1 a 3 ambientes en CABA, con serie desde enero de 2020.

| Mes 2026 | USD/m² cierre | Brecha |
|---|---|---|
| Enero | 2.146 | −5,14% |
| Febrero | — | −4,43% |
| Mayo | — | −4,80% |
| Junio | — | −5,11% |
| Julio | **2.112** | **−4,81%** |

Por tipología en mayo 2026: monoambiente 2.327, 2 ambientes 2.174, 3 ambientes 2.186 USD/m². Históricamente la brecha venía del 9% en 2020 y tocó un mínimo de 4,15% en octubre de 2024.

Se publica en PDF (UCEMA) y Excel (Reporte Inmobiliario): automatizable con un job mensual.

> **Advertencia de uso:** ese nivel de 2.186 USD/m² es promedio de CABA e incluye Palermo, Belgrano y Puerto Madero. Monte Castro está muy por debajo. **Del índice se toma el porcentaje de brecha, nunca el nivel de precio.** Comparar los 1.806 contra los 2.186 lleva a una conclusión falsa.

**A2 — Colegio de Escribanos de CABA.** Ancla macro. En julio de 2026: 6.051 escrituras por $1.068.467 millones, con un monto promedio cercano a US$116.967. Se publica entre el 20 y el 25 del mes siguiente. Sirve para ciclo y sanity check, no para valuar nada puntual.

**A3 — Redes de corredores con datos por barrio.** Al menos una red publica un mapa de precios de cierre construido con los aportes de todos sus corredores, con corte por barrio. Cubre el hueco que deja el A1. Precaución: metodología no auditable y sesgo comercial. Peso bajo, carga semi-manual en `data/manual/cierres_terceros.csv`.

**A4 — Tracking propio de desapariciones.** Snapshots diarios, eventos de precio, y el `status` de la API de Mercado Libre (`active`/`paused`/`closed`). Única fuente **hiperlocal automatizada**. Madura a los 90 días.

**A5 — Datos de campo.** Preguntarle al corredor, después de cerrada la operación, a cuánto terminó. **Veinte cierres reales de 3 ambientes en la zona valen más que cualquier índice nacional.** Máximo peso en el blend. Formulario en el sitio para cargarlo desde el celular al salir de cada visita.

**A6 — Secundarias, verificar antes de invertir tiempo.** Valor Inmobiliario de Referencia de AGIP (piso oficial por partida, si resulta consultable programáticamente); subastas judiciales (precios reales pero de operaciones forzadas: cota inferior); datos abiertos de CABA sobre precios de oferta por barrio (para calibrar sesgo de scraping propio). El Registro de la Propiedad Inmueble tiene los datos pero no de forma abierta ni masiva: no planificar sobre eso.

### 3.3 Cómo se combinan

```sql
CREATE TABLE market_reference (
  id INTEGER PRIMARY KEY,
  fuente TEXT NOT NULL,      -- 'm2real'|'escribanos'|'red'|'propio'|'campo'
  fecha TEXT NOT NULL,
  ambito TEXT NOT NULL,      -- 'caba'|'barrio:Monte Castro'
  tipologia TEXT,
  valor_m2_cierre REAL,
  brecha_pct REAL,
  n_operaciones INTEGER,
  peso REAL NOT NULL,
  url TEXT
);
```

Blend jerárquico, no promedio simple:

1. **Prior:** brecha del Índice M² Real del último mes.
2. **Ajuste por zona:** los barrios de mayor demanda negocian menos; en el corredor norte la brecha se acerca al 4–5%. El oeste no es corredor norte: el ajuste va **hacia arriba**.
3. **Ajuste por aviso:** más margen si acumula muchos días publicado, si su USD/m² supera a sus comparables, si es PH sin ascensor, o si tiene más de 50 años y mala distribución.
4. **Override local:** con ≥ 10 observaciones propias (A4 + A5) para una tipología y barrio, esas mandan y el prior queda residual.

Salida obligatoria, siempre las tres cifras:

```
Publicado:        USD 145.000
Cierre estimado:  USD 137.000  (−5,5%)
Rango:            USD 132.000 – 141.000
Base: M² Real jul-2026 (−4,81%) + ajuste oeste + 3 obs. propias
Confianza: media-baja
```

---

## 4. Arquitectura

GitHub Pages es estático y no puede scrapear. No lo necesita:

```
GitHub Actions (cron diario)
  ├── ingesta de los 3 portales
  ├── normalización + dedupe
  ├── valuación + brecha neta
  └── commit de data/latest.json
              ↓
GitHub Pages sirve JSON + HTML
              ↓
El navegador solo filtra, ordena y grafica
```

| Componente | Elección |
|---|---|
| Hosting | GitHub Pages (repo **privado**: hay datos personales) |
| Backend | GitHub Actions con `schedule` |
| Datos | `data/snapshots/YYYY-MM-DD.parquet` + `data/latest.json` |
| Ingesta | Python 3.11 + httpx + selectolax |
| Análisis | pandas + statsmodels |
| Front | HTML + JS vanilla + Chart.js, sin build step |
| Deps | uv |

El directorio `data/snapshots/` **es** la base histórica, versionada en git. Con ~2.500 avisos diarios en parquet comprimido, el repo crece pocos MB por año.

**Advertencias operativas:** las IPs de Actions son de datacenter y los portales pueden bloquearlas (la API de Mercado Libre no tiene ese problema; si Zonaprop o Argenprop dan pelea, esos scrapers corren en la máquina local o vía Apify). Los cron de Actions se desactivan tras 60 días de inactividad del repo, pero el commit diario lo mantiene vivo. El `schedule` es en UTC y no es puntual.

---

## 5. Alcance geográfico

- **Núcleo (alertas):** Vélez Sarsfield, Floresta
- **Propiedad propia:** Monte Castro
- **Anillo (solo para densificar el modelo):** Flores, Villa Luro, Villa Santa Rita, Villa Real, Versalles, Villa del Parque

Con dos barrios solos la mediana de comparables es ruidosa y el hedónico no converge. El anillo entra al modelo con una variable de barrio que absorbe la diferencia de nivel.

Volumen estimado: 1.500–3.000 avisos activos de venta entre los tres portales.

**Tipologías separadas siempre:** departamento, PH y casa. El PH pesa mucho en esta zona y es el más difícil de valuar por m² (patio, terraza, sin ascensor).

---

## 6. Modelo de datos

Separar **aviso** (lo que publica un portal) de **propiedad** (la unidad física real).

```sql
CREATE TABLE listing (
  id INTEGER PRIMARY KEY,
  portal TEXT NOT NULL,              -- 'zonaprop'|'argenprop'|'meli'
  portal_id TEXT NOT NULL,
  url TEXT NOT NULL,
  property_id INTEGER,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  status TEXT NOT NULL,              -- 'active'|'gone'|'paused'|'closed'
  gone_at TEXT,
  UNIQUE(portal, portal_id)
);

CREATE TABLE listing_snapshot (
  id INTEGER PRIMARY KEY,
  listing_id INTEGER NOT NULL REFERENCES listing(id),
  captured_at TEXT NOT NULL,
  price_amount REAL, price_currency TEXT,
  price_usd REAL, fx_rate_used REAL,
  expensas_ars REAL,
  m2_total REAL, m2_cubiertos REAL,
  ambientes INTEGER, dormitorios INTEGER, banos INTEGER, cocheras INTEGER,
  antiguedad INTEGER, piso INTEGER, ascensor INTEGER,
  tipo TEXT, condicion TEXT,
  barrio TEXT, lat REAL, lon REAL,
  titulo TEXT, descripcion TEXT,
  raw_json TEXT
);

CREATE TABLE price_event (
  id INTEGER PRIMARY KEY,
  listing_id INTEGER NOT NULL REFERENCES listing(id),
  event_at TEXT NOT NULL,
  event_type TEXT NOT NULL,          -- 'listed'|'price_change'|'delisted'|'relisted'
  old_price_usd REAL, new_price_usd REAL, pct_change REAL
);

CREATE TABLE property (
  id INTEGER PRIMARY KEY,
  fingerprint TEXT UNIQUE,
  barrio TEXT, lat REAL, lon REAL,
  m2_total REAL, ambientes INTEGER, tipo TEXT
);

CREATE TABLE cierre_observado (      -- datos de campo: máxima calidad
  id INTEGER PRIMARY KEY,
  fecha TEXT NOT NULL,
  barrio TEXT, direccion_aprox TEXT,
  tipo TEXT, ambientes INTEGER, m2 REAL,
  precio_publicado_usd REAL,
  precio_cierre_usd REAL NOT NULL,
  fuente TEXT,                       -- quién lo reportó
  confianza TEXT                     -- 'alta'|'media'|'baja'
);
```

**No borrar nunca nada.** El `raw_json` permite re-parsear el histórico cuando aparezca un bug en el parser, y va a aparecer.

---

## 7. Ingesta

**Mercado Libre — primero.** API oficial, app registrada en ML Developers, OAuth con refresh persistido en GitHub Secrets. El acceso anónimo a búsqueda está restringido: planificar el token desde el inicio. Expone `status` del ítem, la mejor señal de venta de todo el proyecto.

**Zonaprop y Argenprop.** Extraer primero el JSON embebido (`__NEXT_DATA__` o equivalente) antes de parsear DOM: mucho más estable ante rediseños. Un módulo por portal, misma interfaz. Rate limit de 1 request cada 2–4 s con jitter, User-Agent identificable, sin paralelismo. Si aparece Cloudflare, mover a corrida local o Apify.

Los ToS de ambos portales prohíben el scraping. Para uso personal, a ritmo bajo y sin republicar, el riesgo práctico es bajo. Para un producto comercial habría que apoyarse en la API de ML y en datos abiertos.

**Semilla histórica:** los datasets abiertos de Properati Data para la zona, que permiten entrenar el primer modelo sin esperar tres meses.

---

## 8. Normalización

1. **Moneda:** todo a USD al **dólar MEP** del día, guardando la cotización usada. Nunca el oficial.
2. **Superficie:** `m2_cubiertos` es la variable de valuación. Si falta, **no imputar**: NULL y fuera del modelo. Es el error más frecuente y más caro.
3. **Precio a consultar:** NULL, excluido del modelo, conservado para tracking.
4. **Expensas:** entran al modelo. Deprimen el precio de venta.
5. **Pozo vs usado:** categorías separadas.
6. **Outliers:** descartar fuera de 400–8.000 USD/m².

---

## 9. Deduplicación cross-portal

La misma unidad la publican tres inmobiliarias, a veces a precios distintos. Sin esto la mediana se distorsiona. Fingerprint por capas:

1. Dirección exacta normalizada, cuando el aviso la expone.
2. `geohash(7)` + `round(m2_cubiertos)` + `ambientes` + `tipo`.
3. **pHash de fotos**, Hamming ≤ 6 en ≥ 2 imágenes. La señal más confiable: las inmobiliarias reusan las mismas fotos.
4. Similitud de descripción (TF-IDF > 0,85) como desempate.

Al unificar, conservar el **precio más bajo**.

---

## 10. Motor de valuación

**Capa 1 — Comparables.** Mismo tipo, barrio o adyacente, m² ±15%, ambientes ±1, usado, activos últimos 90 días. Mediana y percentiles 25/75 de USD/m². **Con menos de 30 comparables, no emitir juicio.**

**Capa 2 — Hedónico** (con ≥ 500 observaciones):

```
log(precio_usd) ~ log(m2_cubiertos) + ambientes + banos + cocheras
                + antiguedad + piso + ascensor + log1p(expensas)
                + C(barrio) + C(tipo) + amenities
```

El **residual** es la métrica que importa. Reportar siempre `% vs. predicho`, `percentil`, `n comparables` e intervalo.

**Capa 3 — Ajuste a cierre.** Sección 3.3.

**Regla anti-sesgo:** la propiedad propia se audita con **exactamente el mismo código, los mismos filtros y el mismo umbral de 30 comparables** que las candidatas. Sin excepciones ni parámetros especiales. El riesgo más caro del proyecto es que la app termine justificando los USD 130.000 porque el dueño quiere que valgan eso.

---

## 11. El sitio

1. **Mi propiedad** — los 1.806 USD/m² auditados contra comparables de Monte Castro, percentil, días en mercado estimados, brecha medida del barrio, y los tres escenarios.
2. **Candidatas** — tabla ordenable por **brecha neta**, con precio de lista, precio negociado estimado, USD/m², % vs. modelo, n comparables, días publicado, cantidad de bajas, y la brecha en los tres escenarios.
3. **Mercado** — evolución de USD/m² por barrio, avisos activos, recortes del mes.
4. **Ficha de propiedad** — historial de precios completo, el gráfico que ningún portal muestra.
5. **Carga de cierres** — formulario mobile para registrar lo que informe un corredor.

---

## 12. Fases

| Fase | Entregable | Criterio |
|---|---|---|
| **F0** | Repo + Actions + ingesta ML API + commit de parquet | 3 días de snapshots automáticos sin intervención |
| **F1** | Página estática leyendo `latest.json` | URL pública mostrando los avisos del día |
| **F2** | Parsers Zonaprop y Argenprop | ≥ 95% de avisos con precio y m² |
| **F2.5** | Adaptadores M² Real + Escribanos + `market_reference` | Estimación de cierre disponible desde el mes 1 |
| **F3** | Dedupe | 50 pares revisados a mano, < 5% falsos positivos |
| **F4** | Valuación + auditoría de la propiedad propia | Saber si 1.806 USD/m² es de mercado |
| **F5** | Brecha neta + escenarios + costos | Tabla ordenada por "cuánto tengo que poner" |
| **F6** | Eventos de precio + ficha con historial + carga de cierres | Gráfico de precio por propiedad |
| **F7** | Hedónico + brecha local medida | Requiere ≥ 90 días de datos |

F0 y F1 salen en una sola sesión. **Una fase por sesión**: el error clásico es construir el modelo lindo antes de tener tres meses de datos capturados.

---

## 13. Riesgos

- **Cambio de HTML en los portales.** Guardar `raw_json`, tests con fixtures, y que el workflow **falle ruidosamente** si la tasa de parseo cae del 90%. Un dashboard con datos viejos y sin aviso es peor que uno caído.
- **Bloqueo de IPs de Actions.** Plan B local o Apify.
- **Muestra chica.** Mitigado con el anillo de barrios.
- **Sobreconfianza.** Estado, orientación, luz, humedad y calidad constructiva no están en los datos. El output filtra qué visitar; no tasa.
- **Sesgo del dueño.** Ver regla anti-sesgo, sección 10.

---

## 14. Preguntas para revisar con el corredor

Su experiencia calibra el modelo mejor que cualquier índice. Las respuestas se cargan como parámetros:

**Sobre la propiedad**
1. ¿De dónde salieron los 130.000: comparables de Monte Castro, cierres propios, o valores de publicación de la zona?
2. ¿Cuántas operaciones de 3 ambientes de esa zona vio cerrar en los últimos 12 meses, y en qué rango de USD/m²?
3. ¿Por qué 7% de margen de anclaje y no 5%? ¿Es lo habitual en el oeste, o es específico de esta unidad?
4. ¿Cuántos días estima hasta el cierre publicando a 140.000? ¿Y a 134.000?
5. ¿Publicar por encima de comparables cuesta visitas en esta zona, o el comprador filtra igual por rango de precio?

**Sobre el mercado local**
6. ¿La brecha de negociación en Vélez Sarsfield y Floresta es mayor que el 4,8% promedio de CABA? ¿Cuánto?
7. ¿Qué se vende y qué no? ¿PH vs departamento, con o sin cochera, ascensor?
8. ¿Qué proporción de los avisos publicados son la misma unidad repetida entre inmobiliarias?
9. ¿Qué defectos hunden el precio y no se ven en un aviso? (contrafrente, humedad, expensas altas, deuda, sucesión sin terminar)
10. ¿Cuántos avisos de la zona están, a su criterio, sobrevaluados y no se van a vender a ese precio?

**Sobre la operación**
11. Comisiones reales de compra y venta en la zona, con IVA.
12. ¿Conviene vender primero o comprar primero, en este mercado?
13. ¿Estaría dispuesto a informar precios de cierre de sus operaciones para alimentar el sistema?

La pregunta 13 es la más valiosa de todas. Veinte cierres reales de la zona superan a cualquier índice nacional.

---

## 15. Prompt inicial para Claude Code

> Leé `PLAN-radar-inmobiliario.md` completo. Implementá **F0 + F1**:
>
> 1. Estructura del repo: `ingest/`, `analysis/`, `site/`, `data/`, `config/`, `.github/workflows/`.
> 2. Cliente de la API de Mercado Libre con OAuth y refresh de token desde GitHub Secrets.
> 3. Ingesta de avisos de venta para los barrios de la sección 5, normalización a USD vía dólar MEP, escritura de `data/snapshots/YYYY-MM-DD.parquet` y `data/latest.json`.
> 4. Esquema SQLite completo de la sección 6, aunque F0 use pocas tablas.
> 5. Workflow `daily.yml` con `schedule` diario, idempotente: correrlo dos veces el mismo día no duplica snapshots.
> 6. `site/index.html` estático que hace fetch de `data/latest.json` y muestra una tabla ordenable. Sin build step.
> 7. `config/mi_propiedad.yaml` y `config/costos.yaml` con los valores de las secciones 1 y 2.
> 8. Tests de la capa de normalización.
>
> No implementes todavía: dedupe, valuación, brecha neta ni scrapers de Zonaprop/Argenprop. Al terminar, indicame cómo activar GitHub Pages y qué secrets cargar.
