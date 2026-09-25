<script setup lang="ts">
import { mdiDeleteOutline, mdiDownload, mdiPlus, mdiRestore } from '@mdi/js'
import { computed, ref } from 'vue'

import type { BandMeasure, JsonSchema } from '../api'
import {
  addBand,
  bandDefinitions,
  exportBands,
  removeBand,
  resetBands,
  state,
  updateBand,
} from '../store'
import ParamForm from './ParamForm.vue'

type View = 'position' | 'shift' | 'truth' | 'depth' | 'width' | 'asymmetry' | 'status' | 'ratios'

const view = ref<View>('position')
const views: { title: string; value: View }[] = [
  { title: 'Position (nm)', value: 'position' },
  { title: 'Shift from nominal centre (nm)', value: 'shift' },
  { title: 'Error vs synthetic truth (nm)', value: 'truth' },
  { title: 'Depth', value: 'depth' },
  { title: 'Width at half depth (nm)', value: 'width' },
  { title: 'Asymmetry', value: 'asymmetry' },
  { title: 'Status', value: 'status' },
  { title: 'Depth ratios', value: 'ratios' },
]

// Method parameters: everything except the band table and the ratios, which have editors.
const methodSchema = computed<JsonSchema>(() => {
  const props = { ...(state.bandSchema?.properties ?? {}) }
  delete props.bands
  delete props.ratios
  return { properties: props, required: [] }
})

const ratios = computed(() => (state.bandParams.ratios as [string, string][] | undefined) ?? [])
const names = computed(() => bandDefinitions.value.map((b) => b.name))

function setRatio(i: number, k: 0 | 1, v: string) {
  state.bandParams.ratios = ratios.value.map((r, j) => (j === i ? (k === 0 ? [v, r[1]] : [r[0], v]) : r))
}
function addRatio() {
  if (names.value.length >= 2) state.bandParams.ratios = [...ratios.value, [names.value[0], names.value[1]]]
}
function removeRatio(i: number) {
  state.bandParams.ratios = ratios.value.filter((_, j) => j !== i)
}

function onNumber(i: number, key: 'center' | 'lo' | 'hi', text: string) {
  const k = `bands.${i}.${key}`
  const v = Number(String(text).replace(',', '.'))
  if (String(text).trim() === '' || Number.isNaN(v)) {
    state.bandLocalErrors[k] = 'number'
    return
  }
  delete state.bandLocalErrors[k]
  updateBand(i, { [key]: v })
}

const ratioColumns = computed(() => Object.keys(state.bandRows[0]?.ratios ?? {}))

const DIGITS: Record<string, number> = { position: 1, shift: 1, truth: 2, depth: 3, width: 1, asymmetry: 2 }

function cell(rowIndex: number, band: string): { text: string; cls: string; title: string } {
  const row = state.bandRows[rowIndex]
  const m: BandMeasure | undefined = row?.bands[band]
  if (!m) return { text: '', cls: '', title: '' }
  const title = `${band}: ${m.status}${m.position != null ? `, ${m.position.toFixed(2)} nm` : ''}`
  if (view.value === 'status') return { text: m.status, cls: m.status === 'minimum' ? '' : 'text-muted', title }
  if (m.status === 'absent' || m.status === 'no_data') return { text: '—', cls: 'text-muted', title }
  const def = bandDefinitions.value.find((b) => b.name === band)
  let v: number | null = null
  if (view.value === 'position') v = m.position
  else if (view.value === 'shift') v = m.position != null && def ? m.position - def.center : null
  else if (view.value === 'truth') {
    const t = row.truth?.[band]
    if (!t) return { text: row.truth ? '' : 'n/a', cls: 'text-muted', title: 'no synthetic truth' }
    v = m.position != null ? m.position - t.center : null
  } else v = (m as unknown as Record<string, number | null>)[view.value]
  const digits = DIGITS[view.value] ?? 3
  const text = v == null ? '—' : (view.value === 'shift' || view.value === 'truth') && v > 0 ? `+${v.toFixed(digits)}` : v.toFixed(digits)
  return { text, cls: m.status === 'shoulder' ? 'font-italic text-muted' : '', title }
}

const fmtRatio = (v: number | null | undefined) => (v == null ? '—' : v.toFixed(3))
</script>

<template>
  <div class="d-flex h-100">
    <!-- definitions -->
    <div class="border-e overflow-y-auto pa-3" style="width: 420px; flex: none">
      <div class="d-flex align-center mb-1">
        <div class="text-subtitle-2">Bands</div>
        <v-spacer />
        <v-btn :icon="mdiRestore" size="x-small" title="Reset to the default table" @click="resetBands" />
        <v-btn :icon="mdiPlus" size="x-small" title="Add a band" @click="addBand" />
      </div>
      <div class="d-flex text-caption text-muted mb-1 ga-1">
        <span style="width: 112px">name</span><span style="width: 72px">centre</span><span style="width: 72px">from</span><span style="width: 72px">to</span>
      </div>
      <div v-for="(b, i) in bandDefinitions" :key="i" class="d-flex ga-1 mb-1 align-center">
        <v-text-field :model-value="b.name" density="compact" style="width: 112px; flex: none" class="mono" @update:model-value="(v: string) => updateBand(i, { name: v })" />
        <v-text-field v-for="k in (['center', 'lo', 'hi'] as const)" :key="k" :model-value="String(b[k])" density="compact" style="width: 72px; flex: none" class="mono" :error="!!state.bandLocalErrors[`bands.${i}.${k}`]" inputmode="decimal" @update:model-value="(v: string) => onNumber(i, k, v)" />
        <v-btn :icon="mdiDeleteOutline" size="x-small" title="Remove band" @click="removeBand(i)" />
      </div>

      <div class="d-flex align-center mt-4 mb-1">
        <div class="text-subtitle-2">Depth ratios</div>
        <v-spacer />
        <v-btn :icon="mdiPlus" size="x-small" title="Add a ratio" :disabled="names.length < 2" @click="addRatio" />
      </div>
      <div v-for="(r, i) in ratios" :key="i" class="d-flex ga-1 mb-1 align-center">
        <v-select :model-value="r[0]" :items="names" density="compact" class="mono" @update:model-value="(v: string) => setRatio(i, 0, v)" />
        <span class="text-muted">/</span>
        <v-select :model-value="r[1]" :items="names" density="compact" class="mono" @update:model-value="(v: string) => setRatio(i, 1, v)" />
        <v-btn :icon="mdiDeleteOutline" size="x-small" title="Remove ratio" @click="removeRatio(i)" />
      </div>

      <div class="text-subtitle-2 mt-4 mb-1">Method</div>
      <ParamForm
        v-if="state.bandSchema"
        :schema="methodSchema"
        :params="state.bandParams"
        :local-errors="state.bandLocalErrors"
        :server-errors="state.bandServerErrors"
      />
    </div>

    <!-- results -->
    <div class="flex-grow-1 d-flex flex-column" style="min-width: 0">
      <div class="d-flex align-center ga-3 px-3 pt-2">
        <v-select v-model="view" :items="views" density="compact" style="max-width: 300px" />
        <v-switch v-model="state.showBandMarkers" label="Markers" />
        <v-switch v-model="state.showBandWindows" label="Windows" />
        <v-progress-circular v-if="state.bandBusy" indeterminate size="16" width="2" />
        <v-spacer />
        <v-btn :prepend-icon="mdiDownload" size="small" @click="exportBands">CSV</v-btn>
      </div>
      <v-alert v-for="(e, k) in state.bandErrors" :key="k" type="warning" variant="tonal" density="compact" class="mx-3 mt-2 text-caption">
        {{ e }}
      </v-alert>
      <div class="flex-grow-1 overflow-auto px-3 pb-2">
        <div v-if="!state.bandRows.length && !state.bandErrors.length" class="text-muted text-body-2 pt-4">
          Tick spectra to measure their bands. The measure runs on the recipe output (add a
          continuum removal step, or leave continuum = auto for a local hull per window).
        </div>
        <v-table v-else density="compact" fixed-header class="bg-transparent">
          <thead>
            <tr>
              <th>Spectrum</th>
              <template v-if="view === 'ratios'">
                <th v-for="c in ratioColumns" :key="c" class="text-right mono">{{ c }}</th>
              </template>
              <template v-else>
                <th v-for="b in bandDefinitions" :key="b.name" class="text-right mono" :title="`${b.lo}–${b.hi} nm`">{{ b.name }}</th>
              </template>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, ri) in state.bandRows" :key="row.id" :style="{ cursor: 'pointer', background: state.focused === row.id ? 'rgba(var(--v-theme-primary), 0.12)' : undefined }" @click="state.focused = row.id">
              <td class="text-no-wrap" :class="{ 'font-weight-bold': state.focused === row.id }">{{ row.name }}</td>
              <template v-if="view === 'ratios'">
                <td v-for="c in ratioColumns" :key="c" class="text-right mono">{{ fmtRatio(row.ratios[c]) }}</td>
              </template>
              <template v-else>
                <td v-for="b in bandDefinitions" :key="b.name" class="text-right mono" :class="cell(ri, b.name).cls" :title="cell(ri, b.name).title">
                  {{ cell(ri, b.name).text }}
                </td>
              </template>
            </tr>
          </tbody>
        </v-table>
        <div v-if="state.bandRows.length" class="text-caption text-muted mt-2">
          <i>Italic</i> = shoulder (no local minimum in the window, located by the 2nd derivative);
          — = absent or no data. Error vs truth compares with the band the synthetic spectrum was
          generated with (n/a for real spectra).
        </div>
      </div>
    </div>
  </div>
</template>
