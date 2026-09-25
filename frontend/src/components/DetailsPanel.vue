<script setup lang="ts">
import { computed } from 'vue'

import { label } from '../schema'
import { state } from '../store'

const input = computed(() => (state.focused ? state.inputs[state.focused] : undefined))
const output = computed(() => (state.focused ? state.processed[state.focused] : undefined))
const history = computed(() => output.value?.history ?? input.value?.history ?? [])

const metaRows = computed(() =>
  Object.entries(output.value?.meta ?? input.value?.meta ?? {}).map(([k, v]) => [
    k,
    typeof v === 'object' ? JSON.stringify(v) : String(v),
  ]),
)

const params = (p: Record<string, unknown>) =>
  Object.entries(p)
    .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`)
    .join('  ')
</script>

<template>
  <div class="h-100 overflow-y-auto pa-3">
    <div v-if="!state.focused" class="text-muted text-body-2">
      Click a spectrum in the list (or a QC row) to see its metadata and processing history.
    </div>
    <div v-else-if="!input" class="text-muted text-body-2">Tick the spectrum to load it.</div>
    <div v-else class="d-flex ga-6 flex-wrap">
      <div style="min-width: 280px; flex: 1">
        <div class="text-subtitle-2 mb-1">{{ input.name }} — metadata</div>
        <table class="mono w-100">
          <tbody>
            <tr v-for="[k, v] in metaRows" :key="k">
              <td class="text-muted pr-3 align-top" style="white-space: nowrap">{{ k }}</td>
              <td style="word-break: break-all">{{ v }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div style="min-width: 320px; flex: 1.4">
        <div class="text-subtitle-2 mb-1">
          History <span class="text-muted text-caption">({{ output ? 'with the current recipe' : 'as loaded' }})</span>
        </div>
        <ol class="pl-5">
          <li v-for="(h, i) in history" :key="i" class="mb-1">
            <span class="font-weight-medium">{{ label(h.name) }}</span>
            <div class="mono text-muted" style="word-break: break-all">{{ params(h.params) }}</div>
          </li>
        </ol>
      </div>
    </div>
  </div>
</template>
