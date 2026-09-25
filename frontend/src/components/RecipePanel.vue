<script setup lang="ts">
import {
  mdiArrowDown,
  mdiArrowUp,
  mdiDeleteOutline,
  mdiDownload,
  mdiFolderOpenOutline,
  mdiPlus,
} from '@mdi/js'
import { computed, ref } from 'vue'

import { label } from '../schema'
import {
  addStep,
  download,
  exportCsv,
  loadRecipe,
  moveStep,
  recipeDocument,
  removeStep,
  state,
} from '../store'
import ParamForm from './ParamForm.vue'

const recipeInput = ref<HTMLInputElement | null>(null)

const openPanels = computed({
  get: () => state.steps.filter((s) => s.open).map((s) => s.uid),
  set: (uids: number[]) => {
    for (const s of state.steps) s.open = uids.includes(s.uid)
  },
})

function schemaOf(op: string) {
  return state.operations.find((o) => o.name === op)?.schema ?? {}
}

function saveRecipe() {
  const doc = recipeDocument()
  const name = (state.recipeName || 'recipe').replace(/[^\w-]+/g, '_')
  download(new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' }), `${name}.json`)
}

async function onRecipeFile(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) await loadRecipe(file)
  ;(e.target as HTMLInputElement).value = ''
}

const hasErrors = (i: number) =>
  Object.keys(state.steps[i].localErrors).length + Object.keys(state.steps[i].serverErrors).length > 0
</script>

<template>
  <div class="d-flex flex-column h-100">
    <div class="px-4 pt-3 pb-2">
      <div class="d-flex align-center">
        <div class="text-subtitle-1 font-weight-medium">Recipe</div>
        <v-spacer />
        <v-progress-circular v-if="state.processing" indeterminate size="16" width="2" class="mr-2" />
        <v-btn :icon="mdiFolderOpenOutline" size="small" title="Load a recipe (TOML or JSON)" @click="recipeInput?.click()" />
        <v-btn :icon="mdiDownload" size="small" title="Save the recipe (JSON)" :disabled="!state.steps.length" @click="saveRecipe" />
        <input ref="recipeInput" type="file" accept=".toml,.json" hidden @change="onRecipeFile" />
      </div>
      <v-text-field v-model="state.recipeName" label="Recipe name" class="mt-2" />
    </div>

    <div class="flex-grow-1 overflow-y-auto px-2">
      <div v-if="!state.steps.length" class="text-body-2 text-muted pa-3">
        No step yet. Add operations below; the plot updates as you change parameters.
      </div>
      <v-expansion-panels v-model="openPanels" variant="accordion" multiple flat>
        <v-expansion-panel
          v-for="(step, i) in state.steps"
          :key="step.uid"
          :value="step.uid"
          :class="{ 'opacity-60': !step.enabled }"
          class="border-b"
        >
          <v-expansion-panel-title class="py-1 px-3" style="min-height: 44px">
            <div class="d-flex align-center ga-2 w-100">
              <span class="mono text-muted">{{ i + 1 }}</span>
              <span class="font-weight-medium" :class="{ 'text-error': hasErrors(i) }">{{ label(step.op) }}</span>
              <v-spacer />
              <v-switch v-model="step.enabled" class="flex-grow-0 mr-1" title="Enable / disable this step" @click.stop />
              <v-btn :icon="mdiArrowUp" size="x-small" :disabled="i === 0" title="Move up" @click.stop="moveStep(i, -1)" />
              <v-btn :icon="mdiArrowDown" size="x-small" :disabled="i === state.steps.length - 1" title="Move down" @click.stop="moveStep(i, 1)" />
              <v-btn :icon="mdiDeleteOutline" size="x-small" title="Remove" @click.stop="removeStep(i)" />
            </div>
          </v-expansion-panel-title>
          <v-expansion-panel-text>
            <div class="text-caption text-muted mb-2">
              {{ state.operations.find((o) => o.name === step.op)?.summary }}
            </div>
            <ParamForm
              :schema="schemaOf(step.op)"
              :params="step.params"
              :local-errors="step.localErrors"
              :server-errors="step.serverErrors"
            />
          </v-expansion-panel-text>
        </v-expansion-panel>
      </v-expansion-panels>
    </div>

    <div class="pa-3 d-flex flex-column ga-2 border-t">
      <v-alert v-for="(e, k) in state.processErrors" :key="k" type="warning" variant="tonal" density="compact" class="text-caption">
        {{ e }}
      </v-alert>
      <v-menu location="top">
        <template #activator="{ props: menu }">
          <v-btn v-bind="menu" :prepend-icon="mdiPlus" variant="tonal" color="primary" block>Add step</v-btn>
        </template>
        <v-list density="compact" max-width="380">
          <v-list-item v-for="op in state.operations" :key="op.name" @click="addStep(op.name)">
            <v-list-item-title>{{ label(op.name) }}</v-list-item-title>
            <v-list-item-subtitle class="text-wrap">{{ op.summary }}</v-list-item-subtitle>
          </v-list-item>
        </v-list>
      </v-menu>
      <v-btn :prepend-icon="mdiDownload" variant="outlined" block @click="exportCsv">Export shown spectra (CSV)</v-btn>
    </div>
  </div>
</template>
