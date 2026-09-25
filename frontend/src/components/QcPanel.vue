<script setup lang="ts">
import { mdiAlertOutline, mdiCheck, mdiTuneVariant } from '@mdi/js'
import { computed, ref } from 'vue'

import { state } from '../store'
import ParamForm from './ParamForm.vue'

const showSettings = ref(false)

const FLAG_TEXT: Record<string, string> = {
  above_max: 'above max',
  low_albedo: 'low albedo',
  missing_bands: 'missing bands',
  noisy: 'noisy',
  splice_step: 'splice step',
}

const headers = [
  { title: 'Spectrum', key: 'name' },
  { title: 'Max R', key: 'max_reflectance', align: 'end' },
  { title: 'Mean R', key: 'mean_reflectance', align: 'end' },
  { title: 'NaN %', key: 'nan_fraction', align: 'end' },
  { title: 'Noise RMS', key: 'noise_rms', align: 'end' },
  { title: 'Splice step', key: 'max_splice_step', align: 'end' },
  { title: 'Flags', key: 'flags', sortable: false },
] as const

const rows = computed(() =>
  state.qcResults.map((r) => ({
    id: r.id,
    name: r.name,
    flags: r.flags,
    max_reflectance: r.metrics.max_reflectance,
    mean_reflectance: r.metrics.mean_reflectance,
    nan_fraction: r.metrics.nan_fraction === null ? null : 100 * (r.metrics.nan_fraction ?? 0),
    noise_rms: r.metrics.noise_rms,
    max_splice_step: r.metrics.max_splice_step === null ? null : 100 * (r.metrics.max_splice_step ?? 0),
  })),
)

const fmt = (v: unknown, digits: number) => (typeof v === 'number' ? v.toFixed(digits) : '—')
const flagged = computed(() => state.qcResults.filter((r) => r.flags.length).length)
</script>

<template>
  <div class="d-flex h-100">
    <div class="flex-grow-1 overflow-y-auto">
      <div class="d-flex align-center px-3 pt-2">
        <span class="text-body-2">
          <b>{{ state.qcResults.length }}</b> checked ·
          <b :class="flagged ? 'text-warning' : ''">{{ flagged }}</b> flagged
        </span>
        <v-spacer />
        <v-btn :prepend-icon="mdiTuneVariant" size="small" @click="showSettings = !showSettings">Thresholds</v-btn>
      </div>
      <v-alert v-for="(e, k) in state.qcErrors" :key="k" type="info" variant="tonal" density="compact" class="mx-3 mt-2 text-caption">
        {{ e }}
      </v-alert>
      <v-data-table
        :headers="headers as any"
        :items="rows"
        density="compact"
        items-per-page="-1"
        hide-default-footer
        class="bg-transparent"
        @click:row="(_: unknown, { item }: { item: { id: string } }) => (state.focused = item.id)"
      >
        <template #[`item.max_reflectance`]="{ value }"><span class="mono">{{ fmt(value, 3) }}</span></template>
        <template #[`item.mean_reflectance`]="{ value }"><span class="mono">{{ fmt(value, 3) }}</span></template>
        <template #[`item.nan_fraction`]="{ value }"><span class="mono">{{ fmt(value, 1) }}</span></template>
        <template #[`item.noise_rms`]="{ value }"><span class="mono">{{ fmt(value, 5) }}</span></template>
        <template #[`item.max_splice_step`]="{ value }"><span class="mono">{{ fmt(value, 2) }} %</span></template>
        <template #[`item.flags`]="{ value }">
          <span v-if="!value.length" class="d-inline-flex align-center ga-1 text-success text-caption">
            <v-icon :icon="mdiCheck" size="14" /> ok
          </span>
          <v-chip v-for="f in value" :key="f" size="x-small" color="warning" variant="tonal" class="mr-1" :prepend-icon="mdiAlertOutline">
            {{ FLAG_TEXT[f] ?? f }}
          </v-chip>
        </template>
      </v-data-table>
    </div>
    <div v-if="showSettings && state.qcSchema" class="border-s overflow-y-auto pa-3" style="width: 300px; flex: none">
      <div class="text-subtitle-2 mb-2">QC thresholds</div>
      <ParamForm
        :schema="state.qcSchema"
        :params="state.qcParams"
        :local-errors="state.qcLocalErrors"
        :server-errors="state.qcServerErrors"
      />
    </div>
  </div>
</template>
