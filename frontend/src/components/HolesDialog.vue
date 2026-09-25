<script setup lang="ts">
// Assign holes and depths to spectra: by example on their names, or from a sample table.
// The rule inference runs server-side; this component only collects examples and shows the
// preview. Nothing is applied before "Apply".
import { mdiAutoFix, mdiClose, mdiDeleteSweepOutline, mdiPlus, mdiRestore, mdiTableArrowRight } from '@mdi/js'
import { computed, ref, watch } from 'vue'

import { api, type AssignRow, type AssignSummary, type NamingExample, type TableMappingIn } from '../api'
import { notify, spectraUpdated, state } from '../store'

type Role = 'hole' | 'depth'
interface Tok {
  text: string
  start: number
  end: number
  kind: 'alpha' | 'digit' | 'sep'
}

const tab = ref<'names' | 'table'>('names')
const source = ref<'name' | 'file'>('name')
const role = ref<Role>('hole')
const current = ref('')
const spans = ref<Record<Role, [number, number] | null>>({ hole: null, depth: null })
const examples = ref<NamingExample[]>([])
const rules = ref<string[]>([])
const rows = ref<AssignRow[]>([])
const summary = ref<AssignSummary | null>(null)
const error = ref('')
const busy = ref(false)
const problemsOnly = ref(false)

const keyOf = (s: { name: string; file: string | null }) => (source.value === 'file' ? (s.file ?? s.name) : s.name)
const keys = computed(() => state.spectra.map(keyOf))

function tokenize(name: string): Tok[] {
  return [...name.matchAll(/[A-Za-z]+|\d+|[^A-Za-z\d]+/g)].map((m) => ({
    text: m[0],
    start: m.index!,
    end: m.index! + m[0].length,
    kind: /[A-Za-z]/.test(m[0][0]) ? 'alpha' : /\d/.test(m[0][0]) ? 'digit' : 'sep',
  }))
}
const tokens = computed(() => tokenize(current.value))

function pickDefaultExample() {
  const unassigned = state.spectra.find((s) => !s.hole_id && /\d/.test(keyOf(s)))
  current.value = unassigned ? keyOf(unassigned) : (keys.value[0] ?? '')
}

watch(
  () => state.holesDialog,
  (open) => {
    if (!open) return
    error.value = ''
    if (!current.value) pickDefaultExample()
  },
  { immediate: true },
)
watch(current, () => (spans.value = { hole: null, depth: null }))
watch(source, () => {
  examples.value = []
  pickDefaultExample()
})

function tokenRole(t: Tok): Role | null {
  for (const r of ['hole', 'depth'] as Role[]) {
    const s = spans.value[r]
    if (s && t.start >= s[0] && t.end <= s[1]) return r
  }
  return null
}

function clickToken(i: number) {
  const t = tokens.value[i]
  const s = spans.value[role.value]
  let next: [number, number]
  if (!s || (t.start >= s[0] && t.end <= s[1])) next = [t.start, t.end]
  else if (t.start < s[0]) next = [t.start, s[1]]
  else next = [s[0], t.end]
  const other = spans.value[role.value === 'hole' ? 'depth' : 'hole']
  if (other && next[0] < other[1] && other[0] < next[1]) spans.value[role.value === 'hole' ? 'depth' : 'hole'] = null
  spans.value[role.value] = next
}

/** Propose the most common layout: depth = the last number, hole = what comes before the
 * separator preceding it. The user checks it and corrects if needed. */
function suggest() {
  const name = current.value
  const m = name.match(/(\d+(?:[.,]\d+)?)(?!.*\d)/)
  if (!m || m.index === undefined) return
  const d0 = m.index
  const d1 = d0 + m[1].length
  let h1 = d0
  while (h1 > 0 && /[^A-Za-z\d]/.test(name[h1 - 1])) h1--
  if (h1 === 0) {
    spans.value = { hole: null, depth: [d0, d1] }
    role.value = 'hole'
    return
  }
  spans.value = { hole: [0, h1], depth: [d0, d1] }
}

const holeText = computed(() => (spans.value.hole ? current.value.slice(...spans.value.hole) : ''))
const depthText = computed(() => (spans.value.depth ? current.value.slice(...spans.value.depth) : ''))
const depthOk = computed(() => /^\d+(?:[.,]\d+)?$/.test(depthText.value))
const currentExample = computed<NamingExample | null>(() =>
  spans.value.hole && spans.value.depth && depthOk.value
    ? { name: current.value, hole: spans.value.hole, depth: spans.value.depth }
    : null,
)
const allExamples = computed(() => [...examples.value, ...(currentExample.value ? [currentExample.value] : [])])

function addExample() {
  if (!currentExample.value) return
  examples.value.push(currentExample.value)
  const next = rows.value.find((r) => r.status === 'unmatched' && /\d/.test(r.key))
  current.value = next ? next.key : ''
  role.value = 'hole'
}

function describe(e: NamingExample) {
  return `${e.name} → ${e.name.slice(...e.hole)} · ${e.name.slice(...e.depth)} m`
}

// --- sample table ---------------------------------------------------------------------
const tableInput = ref<HTMLInputElement | null>(null)
const table = ref<{ table_id: string; filename: string; columns: string[]; n_rows: number; head: string[][] } | null>(null)
const mapping = ref<TableMappingIn>({
  key: null,
  hole: null,
  depth_from: null,
  depth_to: null,
  match_on: 'name',
  ignore_case: true,
  ignore_extension: true,
})

async function onTableFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  try {
    const t = await api.tableUpload(file)
    table.value = t
    mapping.value = {
      ...mapping.value,
      key: t.mapping.key ?? null,
      hole: t.mapping.hole ?? null,
      depth_from: t.mapping.depth_from ?? null,
      depth_to: t.mapping.depth_to ?? null,
    }
  } catch (err) {
    notify((err as Error).message)
  }
}
const mappingReady = computed(() => !!(table.value && mapping.value.key && mapping.value.hole && mapping.value.depth_from))

// --- live preview ---------------------------------------------------------------------
let timer: number | undefined
let seq = 0
async function preview() {
  const n = ++seq
  error.value = ''
  try {
    if (tab.value === 'names') {
      if (!allExamples.value.length) {
        rows.value = []
        summary.value = null
        rules.value = []
        return
      }
      const r = await api.namingPreview(allExamples.value, source.value)
      if (n !== seq) return
      rows.value = r.rows
      summary.value = r.summary
      rules.value = r.rules
    } else {
      if (!mappingReady.value) {
        rows.value = []
        summary.value = null
        return
      }
      const r = await api.tablePreview(table.value!.table_id, mapping.value)
      if (n !== seq) return
      rows.value = r.rows
      summary.value = r.summary
      rules.value = []
    }
  } catch (err) {
    if (n === seq) error.value = (err as Error).message
  }
}
watch(
  () => [tab.value, JSON.stringify(allExamples.value), source.value, JSON.stringify(mapping.value), table.value?.table_id, state.holesDialog],
  () => {
    window.clearTimeout(timer)
    if (state.holesDialog) timer = window.setTimeout(preview, 200)
  },
)

async function apply() {
  busy.value = true
  try {
    const r =
      tab.value === 'names'
        ? await api.namingApply(allExamples.value, source.value)
        : await api.tableApply(table.value!.table_id, mapping.value)
    await spectraUpdated(r.spectra, `Hole and depth assigned to ${r.applied} spectra`)
    state.holesDialog = false
    if (state.holes.length) state.mainView = 'drillhole'
  } catch (err) {
    notify((err as Error).message)
  } finally {
    busy.value = false
  }
}

async function clearAll() {
  if (!window.confirm('Remove the hole and depth of every spectrum?')) return
  try {
    const r = await api.clearHoles(null)
    await spectraUpdated(r.spectra, 'Holes and depths removed')
    void preview()
  } catch (err) {
    notify((err as Error).message)
  }
}

const shownRows = computed(() => (problemsOnly.value ? rows.value.filter((r) => r.status !== 'ok') : rows.value))
const headers = [
  { title: 'Name', key: 'key' },
  { title: 'Hole', key: 'hole_id' },
  { title: 'Depth (m)', key: 'depth_from', align: 'end' },
  { title: 'To (m)', key: 'depth_to', align: 'end' },
  { title: '', key: 'status', sortable: false },
] as const
const canApply = computed(() => !!summary.value?.matched && !busy.value)
</script>

<template>
  <v-dialog v-model="state.holesDialog" max-width="1280" scrollable>
    <v-card style="height: 86vh">
      <v-toolbar density="compact" color="transparent" class="border-b">
        <v-toolbar-title class="text-subtitle-1 font-weight-medium">Holes &amp; depths</v-toolbar-title>
        <v-tabs v-model="tab" density="compact" color="primary">
          <v-tab value="names">From the names</v-tab>
          <v-tab value="table">From a sample table</v-tab>
        </v-tabs>
        <v-spacer />
        <v-btn :icon="mdiClose" @click="state.holesDialog = false" />
      </v-toolbar>

      <div class="d-flex flex-grow-1" style="min-height: 0">
        <!-- left: how to read -->
        <div class="border-e overflow-y-auto pa-4" style="width: 470px; flex: none">
          <template v-if="tab === 'names'">
            <div class="text-body-2 mb-3">
              Show once where the hole and the depth are in a name; SWIRL finds the rule and applies
              it to every name.
            </div>
            <v-btn-toggle v-model="source" mandatory density="compact" variant="outlined" divided class="mb-3">
              <v-btn value="name" size="small">Spectrum name</v-btn>
              <v-btn value="file" size="small">File name</v-btn>
            </v-btn-toggle>
            <v-autocomplete v-model="current" :items="keys" label="Example name" class="mono mb-3" />

            <div class="text-caption text-muted mb-1">
              Choose a role, then click the parts of the name (click the first and the last part of
              a span) — or let SWIRL suggest.
            </div>
            <v-btn-toggle v-model="role" mandatory density="compact" divided class="mb-3">
              <v-btn value="hole" size="small" :color="role === 'hole' ? 'primary' : undefined">Hole ID</v-btn>
              <v-btn value="depth" size="small" :color="role === 'depth' ? 'deep-orange' : undefined">Depth</v-btn>
            </v-btn-toggle>
            <v-btn :prepend-icon="mdiAutoFix" size="small" variant="text" class="ml-2 mb-3" title="Depth = last number, hole = what precedes it" @click="suggest">
              Suggest
            </v-btn>
            <v-btn :prepend-icon="mdiRestore" size="small" variant="text" class="mb-3" @click="spans = { hole: null, depth: null }">
              Reset
            </v-btn>

            <div class="d-flex flex-wrap ga-1 pa-3 rounded border mb-3" style="min-height: 52px">
              <v-chip
                v-for="(t, i) in tokens"
                :key="i"
                label
                :size="t.kind === 'sep' ? 'small' : 'default'"
                :variant="tokenRole(t) ? 'flat' : 'outlined'"
                :color="tokenRole(t) === 'hole' ? 'primary' : tokenRole(t) === 'depth' ? 'deep-orange' : undefined"
                class="mono"
                @click="clickToken(i)"
              >
                {{ t.text }}
              </v-chip>
              <span v-if="!tokens.length" class="text-muted text-body-2">Pick an example name above.</span>
            </div>

            <div class="text-body-2 mb-1">
              Hole: <b class="mono">{{ holeText || '—' }}</b> · Depth:
              <b class="mono" :class="{ 'text-error': depthText && !depthOk }">{{ depthText || '—' }}</b>
              <span v-if="depthText && !depthOk" class="text-error text-caption"> (not a number)</span>
            </div>

            <div v-if="examples.length" class="mt-3">
              <div class="text-caption text-muted mb-1">Other examples</div>
              <v-chip v-for="(e, i) in examples" :key="i" size="small" class="mr-1 mb-1 mono" closable @click:close="examples.splice(i, 1)">
                {{ describe(e) }}
              </v-chip>
            </div>
            <v-btn
              :prepend-icon="mdiPlus"
              size="small"
              variant="tonal"
              class="mt-3"
              :disabled="!currentExample || !summary?.unmatched"
              @click="addExample"
            >
              Add another example (for the names not read)
            </v-btn>

            <v-alert v-if="rules.length" type="info" variant="tonal" density="compact" class="mt-4 text-caption">
              <div v-for="(r, i) in rules" :key="i">Rule{{ rules.length > 1 ? ` ${i + 1}` : '' }}: {{ r }}</div>
            </v-alert>
          </template>

          <template v-else>
            <div class="text-body-2 mb-3">
              A CSV or TSV exported from your sample sheet, one row per sample: sample name, hole,
              depth (and interval bottom).
            </div>
            <v-btn :prepend-icon="mdiTableArrowRight" variant="tonal" color="primary" @click="tableInput?.click()">
              Choose a table…
            </v-btn>
            <input ref="tableInput" type="file" accept=".csv,.tsv,.txt" hidden @change="onTableFile" />
            <template v-if="table">
              <div class="text-caption text-muted mt-2">{{ table.filename }} · {{ table.n_rows }} rows</div>
              <div class="d-flex flex-column ga-2 mt-3">
                <v-select v-model="mapping.key" :items="table.columns" label="Sample name column *" />
                <v-select v-model="mapping.hole" :items="table.columns" label="Hole column *" />
                <v-select v-model="mapping.depth_from" :items="table.columns" label="Depth (or From) column *" />
                <v-select v-model="mapping.depth_to" :items="table.columns" label="To column (optional)" clearable />
                <v-btn-toggle v-model="mapping.match_on" mandatory density="compact" variant="outlined" divided>
                  <v-btn value="name" size="small">Match spectrum names</v-btn>
                  <v-btn value="file" size="small">Match file names</v-btn>
                </v-btn-toggle>
                <v-switch v-model="mapping.ignore_case" label="Ignore upper / lower case" />
                <v-switch v-model="mapping.ignore_extension" label="Ignore file extensions (.asd, .txt…)" />
              </div>
              <v-table density="compact" class="mt-3 mono text-caption">
                <thead>
                  <tr><th v-for="c in table.columns" :key="c">{{ c }}</th></tr>
                </thead>
                <tbody>
                  <tr v-for="(r, i) in table.head.slice(0, 5)" :key="i"><td v-for="(v, j) in r" :key="j">{{ v }}</td></tr>
                </tbody>
              </v-table>
            </template>
          </template>
        </div>

        <!-- right: preview -->
        <div class="flex-grow-1 d-flex flex-column pa-4" style="min-width: 0">
          <div class="text-subtitle-2 mb-2">Preview <span class="text-caption text-muted">(nothing is changed until you apply)</span></div>
          <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-2 text-caption">{{ error }}</v-alert>
          <template v-if="summary">
            <div class="d-flex flex-wrap ga-2 mb-2 align-center">
              <v-chip color="success" variant="tonal" size="small">{{ summary.matched }} read</v-chip>
              <v-chip :color="summary.unmatched ? 'warning' : undefined" variant="tonal" size="small">{{ summary.unmatched }} not read</v-chip>
              <v-chip v-for="h in summary.holes" :key="h.hole_id" size="small" variant="outlined" class="mono">
                {{ h.hole_id }} · {{ h.n }} · {{ h.top }}–{{ h.bottom }} m
              </v-chip>
            </div>
            <v-alert v-for="(w, i) in summary.warnings" :key="i" type="warning" variant="tonal" density="compact" class="mb-2 text-caption">
              {{ w }}
            </v-alert>
            <v-switch v-model="problemsOnly" label="Show only the names not read or duplicated" class="mb-1" />
            <v-data-table
              :headers="headers as any"
              :items="shownRows"
              density="compact"
              items-per-page="50"
              fixed-header
              class="flex-grow-1 bg-transparent"
              style="min-height: 0"
            >
              <template #[`item.key`]="{ value }"><span class="mono">{{ value }}</span></template>
              <template #[`item.hole_id`]="{ value }"><span class="mono">{{ value ?? '—' }}</span></template>
              <template #[`item.depth_from`]="{ value }"><span class="mono">{{ value ?? '—' }}</span></template>
              <template #[`item.depth_to`]="{ value }"><span class="mono">{{ value ?? '—' }}</span></template>
              <template #[`item.status`]="{ value }">
                <v-chip v-if="value === 'unmatched'" size="x-small" variant="tonal">not read</v-chip>
                <v-chip v-else-if="value === 'duplicate'" size="x-small" color="warning" variant="tonal">same depth</v-chip>
              </template>
            </v-data-table>
          </template>
          <div v-else class="text-muted text-body-2 mt-4">
            {{ tab === 'names' ? 'Mark the hole and the depth in the example name to see the result on every name.' : 'Choose a table and its columns to see the result.' }}
          </div>
        </div>
      </div>

      <v-card-actions class="border-t px-4">
        <v-btn :prepend-icon="mdiDeleteSweepOutline" variant="text" @click="clearAll">Remove all holes &amp; depths</v-btn>
        <v-spacer />
        <v-btn variant="text" @click="state.holesDialog = false">Cancel</v-btn>
        <v-btn color="primary" variant="flat" :disabled="!canApply" :loading="busy" @click="apply">
          Apply to {{ summary?.matched ?? 0 }} spectra
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
