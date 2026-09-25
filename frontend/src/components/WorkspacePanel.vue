<script setup lang="ts">
import { mdiDeleteOutline, mdiDeleteSweepOutline, mdiFlaskOutline, mdiUpload } from '@mdi/js'
import { computed, ref } from 'vue'
import { useTheme } from 'vuetify'

import { seriesColor } from '../palette'
import { clearWorkspace, loadExamples, removeSpectrum, setAllVisible, setVisible, state, uploadFiles, visibleIds } from '../store'

const theme = useTheme()
const dark = computed(() => theme.current.value.dark)
const fileInput = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
const filter = ref('')

const shown = computed(() => {
  const q = filter.value.trim().toLowerCase()
  return q ? state.spectra.filter((s) => `${s.name} ${s.source}`.toLowerCase().includes(q)) : state.spectra
})

function onFiles(e: Event) {
  const input = e.target as HTMLInputElement
  void uploadFiles(Array.from(input.files ?? []))
  input.value = ''
}

function onDrop(e: DragEvent) {
  dragging.value = false
  void uploadFiles(Array.from(e.dataTransfer?.files ?? []))
}

const allOn = computed(() => state.spectra.length > 0 && visibleIds.value.length === state.spectra.length)
</script>

<template>
  <div
    class="d-flex flex-column h-100"
    :class="{ 'drop-active': dragging }"
    @dragover.prevent="dragging = true"
    @dragleave.prevent="dragging = false"
    @drop.prevent="onDrop"
  >
    <div class="px-4 pt-3 pb-2">
      <div class="text-subtitle-1 font-weight-medium mb-2">Spectra</div>
      <div class="d-flex ga-2">
        <v-btn :prepend-icon="mdiUpload" variant="tonal" color="primary" class="flex-grow-1" :loading="state.busy" @click="fileInput?.click()">
          Open files
        </v-btn>
        <v-btn :icon="mdiFlaskOutline" variant="tonal" title="Load the synthetic examples" @click="loadExamples" />
      </div>
      <input ref="fileInput" type="file" multiple accept=".asd,.txt,.csv,.tsv,.dat,.sco" hidden @change="onFiles" />
      <div class="text-caption text-muted mt-1">.asd .txt .csv .tsv .dat .sco — or drop files here</div>
    </div>

    <div v-if="state.spectra.length" class="px-4 pb-1 d-flex align-center ga-1">
      <v-checkbox-btn :model-value="allOn" :indeterminate="!allOn && visibleIds.length > 0" title="Show / hide all" @update:model-value="setAllVisible(!allOn)" />
      <v-text-field v-model="filter" placeholder="Filter" clearable class="flex-grow-1" />
      <v-btn :icon="mdiDeleteSweepOutline" size="small" title="Remove all spectra" @click="clearWorkspace" />
    </div>

    <div class="flex-grow-1 overflow-y-auto">
      <div v-if="!state.spectra.length" class="text-body-2 text-muted px-4 py-6">
        No spectra yet. Open ASD or text files, drop them here, or load the synthetic examples
        (flask button).
      </div>
      <v-list density="compact" class="py-0" bg-color="transparent">
        <v-list-item
          v-for="s in shown"
          :key="s.id"
          :active="state.focused === s.id"
          color="primary"
          class="px-3"
          @click="state.focused = s.id"
        >
          <template #prepend>
            <v-checkbox-btn :model-value="!!state.visible[s.id]" @click.stop @update:model-value="(v: boolean | null) => setVisible(s.id, !!v)" />
          </template>
          <v-list-item-title class="d-flex align-center ga-2">
            <span v-if="state.visible[s.id]" class="swatch" :style="{ background: seriesColor(state.slots[s.id], dark) }" />
            <span class="text-truncate">{{ s.name }}</span>
          </v-list-item-title>
          <v-list-item-subtitle class="mono">
            {{ s.quantity }} · {{ s.wl_min }}–{{ s.wl_max }} nm · {{ s.n_bands }} b
          </v-list-item-subtitle>
          <template #append>
            <v-btn :icon="mdiDeleteOutline" size="x-small" title="Remove" @click.stop="removeSpectrum(s.id)" />
          </template>
        </v-list-item>
      </v-list>
    </div>
    <div v-if="state.spectra.length" class="px-4 py-2 text-caption text-muted border-t">
      {{ visibleIds.length }} shown / {{ state.spectra.length }} loaded
      <span v-if="visibleIds.length > 8"> — spectra past the 8th are drawn in grey</span>
    </div>
  </div>
</template>
