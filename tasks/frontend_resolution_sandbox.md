# Tarea: Sandbox de Resolución de Verbatims (Frontend)

## 📌 Contexto
Tras estabilizar y optimizar el pipeline de backend (Marcas y Razones), el motor semántico y fuzzy logran una asertividad del ~93% aislando las marcas emergentes y la "basura" (~7%) en la base de datos como "anomalías".
La siguiente fase crítica es construir la UI para que el analista de mercado resuelva estas anomalías, aplicando la directriz de diseño del proyecto: **"Una interacción tipo Notion o Excel: rápida, apoyada en el teclado y sin fricciones."**

## 🎯 Objetivos de la Interfaz
1. Mostrar claramente los verbatims agrupados que el modelo catalogó como `anomaly`.
2. Permitir asignaciones ultra-rápidas mediante atajos de teclado (`CommandPalette`).
3. Permitir la creación al vuelo de nuevos códigos (para marcas/razones descubiertas) y agregarlos al diccionario global de esa ronda.
4. Sentirse como una extensión fluida del estudio (Sandbox lateral o modal expandido).

## 🧩 Arquitectura de Componentes (React + Tailwind + Zustand)

### 1. `ResolutionSidebar.tsx` o `ResolutionDrawer.tsx`
- **Ubicación:** `frontend/src/components/studio/`
- **Comportamiento:** 
  - Slide-in panel desde la derecha (o expandible estilo Notion split-view) que se abre automáticamente (o a petición) cuando el estado del pipeline pasa a "Completado".
  - Debe contener la tabla interactiva de anomalías y los comandos de resolución rápida.

### 2. `AnomaliesTable.tsx` (Lista interactiva estilo Excel)
- **Columnas clave:** 
  - Mención original normalizada (ej. `pampacolca`).
  - Frecuencia (ej. `9`). Este dato es vital para que el usuario sepa si vale la pena crear un código nuevo (frecuencia alta) o desecharlo (frecuencia baja).
- **Interacción:** 
  - Las flechas del teclado (Arriba/Abajo) deben permitir navegar entre filas.
  - Al presionar `Enter`, se debe abrir el `CommandPalette` enfocado en esa fila.
  - Permitir selección múltiple (`Shift + Click` o `Ctrl + Click`) para agrupar basura similar ("a", "b", "c") y resolverla de un golpe.

### 3. Interacción de Asignación y Descarte (Game-like Menu)
- **Cero Command Palettes intrusivos.** Toda la acción ocurre fluidamente dentro del propio sidebar.
- **Flujo de "Descartar":** Al presionar "Descartar" en una fila (o seleccionando varias), se despliega un **menú contextual rápido (estilo menú de videojuego)** anclado al botón, que ofrece visualmente a qué "papelera" enviarlo:
  - 🗑️ *95 - Confusas / Basura*
  - 🤷 *96 - No Sabe / No Contesta*
  - 🚫 *98 - Ninguna*
  - 🤫 *99 - No Recuerda / No Responde*
- Al seleccionar una opción de ese menú, el Frontend enviará al backend la orden de `approve` al respectivo `code_id` del código de sistema y `add_alias: true` para que el motor aprenda.
- **Flujo de Asignación Positiva:** Un pequeño input in-line en el sidebar para buscar códigos existentes (con auto-completado) o un botón "+ Crear" que muta el catálogo al vuelo.

### 4. `useResolutionStore.ts` (Zustand)
- Globalizar el estado de la resolución para no saturar de props los componentes.
- Mantener la lista local optimista de las anomalías resueltas para que la tabla se vacíe instantáneamente al dar Enter (optimistic UI), despachando las mutaciones al backend de forma asíncrona (SWR o Mutation).

## 🛠️ Conexión con el Backend (API)
Se requerirán las siguientes interacciones (mutaciones):
- `GET /api/v1/studios/{id}/mention-groups?status=anomaly` (Listar)
- `POST /api/v1/studios/{id}/resolve-group` (Mutación para asignar un grupo a un code_id existente).
- `POST /api/v1/codebooks/{id}/codes` (Crear nuevo código al vuelo y luego resolver el grupo).

## 🎨 Consideraciones de UX/UI (Directrices del proyecto)
- **Cero Loaders Innecesarios:** Al resolver una fila, debe desaparecer de inmediato con una animación de salida (Framer Motion). No bloquear la UI esperando al servidor.
- **Micro-interacciones:** Animación de *pop-in* del Command Palette, hover states vibrantes (brand colors).
- **Dark/Light mode ready:** Respetando las variables CSS de Tailwind de la arquitectura base.

## 🚀 Plan de Ejecución
1. Crear el layout estructural (`ResolutionSidebar` + `AnomaliesTable`).
2. Integrar navegación por teclado y selección de filas (Excel-like).
3. Construir e integrar el `ResolutionCommandPalette` con auto-completado sobre el catálogo (cargado en memoria).
4. Integrar las llamadas asíncronas a la API del backend para materializar la resolución.
5. Efectos de pulido (Framer Motion, feedback toasts).
