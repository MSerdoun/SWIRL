<script setup lang="ts">
// A form generated from a pydantic JSON schema. The schema is the only definition of what
// can be set; nothing here knows what a parameter means.
import { mdiInformationOutline } from '@mdi/js'
import { computed, reactive } from 'vue'

import type { JsonSchema } from '../api'
import { fromText, label, toText, widgetFor } from '../schema'

const props = defineProps<{
  schema: JsonSchema
  params: Record<string, unknown>
  localErrors: Record<string, string>
  serverErrors?: Record<string, string>
}>()

const fields = computed(() =>
  Object.entries(props.schema.properties ?? {}).map(([name, prop]) => ({
    name,
    prop,
    widget: widgetFor(prop),
    required: props.schema.required?.includes(name) ?? false,
  })),
)

const texts = reactive<Record<string, string>>({})
for (const f of fields.value) texts[f.name] = toText(f.widget.kind, props.params[f.name])

function onText(name: string, text: string) {
  const f = fields.value.find((x) => x.name === name)!
  texts[name] = text
  try {
    const value = fromText(f.widget, text)
    if (value === undefined) {
      delete props.params[name]
      if (f.required) props.localErrors[name] = 'required'
      else delete props.localErrors[name]
    } else {
      props.params[name] = value
      delete props.localErrors[name]
    }
  } catch (err) {
    props.localErrors[name] = (err as Error).message
  }
}

function errorFor(name: string): string[] {
  const e = props.localErrors[name] ?? props.serverErrors?.[name]
  return e ? [e] : []
}
</script>

<template>
  <div class="d-flex flex-column ga-3 pt-1">
    <div v-for="f in fields" :key="f.name">
      <v-select
        v-if="f.widget.kind === 'enum'"
        :model-value="params[f.name] as string"
        :items="f.widget.options as string[]"
        :label="label(f.name)"
        :error-messages="errorFor(f.name)"
        @update:model-value="(v: string) => (params[f.name] = v)"
      >
        <template #append-inner>
          <v-tooltip v-if="f.prop.description" location="start" max-width="320">
            <template #activator="{ props: tip }">
              <v-icon v-bind="tip" :icon="mdiInformationOutline" size="16" class="text-muted" />
            </template>
            {{ f.prop.description }}
          </v-tooltip>
        </template>
      </v-select>

      <v-switch
        v-else-if="f.widget.kind === 'boolean'"
        v-model="params[f.name]"
        :label="label(f.name)"
      />

      <v-text-field
        v-else
        :model-value="texts[f.name]"
        :label="label(f.name) + (f.required ? ' *' : '')"
        :placeholder="f.widget.kind === 'nullableNumber' ? 'off / auto' : ''"
        :hint="f.widget.hint"
        :error-messages="errorFor(f.name)"
        :inputmode="['number', 'integer', 'nullableNumber'].includes(f.widget.kind) ? 'decimal' : 'text'"
        :class="{ mono: f.widget.kind !== 'number' }"
        persistent-placeholder
        @update:model-value="(v: string) => onText(f.name, v ?? '')"
      >
        <template #append-inner>
          <v-tooltip v-if="f.prop.description" location="start" max-width="320">
            <template #activator="{ props: tip }">
              <v-icon v-bind="tip" :icon="mdiInformationOutline" size="16" class="text-muted" />
            </template>
            {{ f.prop.description }}
          </v-tooltip>
        </template>
      </v-text-field>
    </div>
    <div v-if="serverErrors?._" class="text-error text-caption">{{ serverErrors._ }}</div>
  </div>
</template>
