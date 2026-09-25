// Map a pydantic JSON-schema property to an input widget, and convert between the text the
// user types and the JSON value sent to the API. Validation stays server-side; the only
// local errors are "this text is not a number / a list of numbers".

import type { JsonSchema } from './api'

export type Kind =
  | 'enum'
  | 'boolean'
  | 'number'
  | 'integer'
  | 'nullableNumber'
  | 'numberList'
  | 'numberListOrConst'
  | 'range'
  | 'rangeList'
  | 'json'

export interface Widget {
  kind: Kind
  options?: unknown[]
  consts?: string[]
  hint: string
}

const isNumeric = (s?: JsonSchema) => s?.type === 'number' || s?.type === 'integer'
const isPair = (s?: JsonSchema) =>
  s?.type === 'array' && s.prefixItems?.length === 2 && s.prefixItems.every(isNumeric)

export function widgetFor(prop: JsonSchema): Widget {
  if (prop.enum) return { kind: 'enum', options: prop.enum, hint: '' }
  if (prop.type === 'boolean') return { kind: 'boolean', hint: '' }
  if (prop.type === 'integer') return { kind: 'integer', hint: '' }
  if (prop.type === 'number') return { kind: 'number', hint: '' }
  if (isPair(prop)) return { kind: 'range', hint: 'e.g. 2300-2450' }
  if (prop.type === 'array' && isNumeric(prop.items))
    return { kind: 'numberList', hint: 'comma-separated, e.g. 1000, 1800' }
  if (prop.type === 'array' && isPair(prop.items))
    return { kind: 'rangeList', hint: 'ranges separated by ";", e.g. 1350-1450; 1800-1950' }
  if (prop.anyOf) {
    const nonNull = prop.anyOf.filter((s) => s.type !== 'null')
    const hasNull = nonNull.length < prop.anyOf.length
    if (hasNull && nonNull.length === 1 && isNumeric(nonNull[0]))
      return { kind: 'nullableNumber', hint: 'empty = off / automatic' }
    const consts = nonNull.filter((s) => s.const !== undefined).map((s) => String(s.const))
    const list = nonNull.find((s) => s.type === 'array' && isNumeric(s.items))
    if (list && consts.length)
      return {
        kind: 'numberListOrConst',
        consts,
        hint: `comma-separated numbers, or ${consts.map((c) => `"${c}"`).join(' / ')}`,
      }
  }
  return { kind: 'json', hint: 'JSON value' }
}

const num = (s: string): number => {
  const t = s.trim().replace(',', '.')
  if (t === '' || Number.isNaN(Number(t))) throw new Error(`"${s.trim()}" is not a number`)
  return Number(t)
}

const pair = (s: string): [number, number] => {
  const m = s.trim().match(/^([^\s-][^-]*?)\s*-\s*(.+)$/)
  if (!m) throw new Error(`"${s.trim()}" is not a range like 1350-1450`)
  return [num(m[1]), num(m[2])]
}

export function toText(kind: Kind, value: unknown): string {
  if (value === undefined || value === null) return ''
  switch (kind) {
    case 'numberList':
      return (value as number[]).join(', ')
    case 'numberListOrConst':
      return Array.isArray(value) ? value.join(', ') : String(value)
    case 'range':
      return (value as number[]).join('-')
    case 'rangeList':
      return (value as number[][]).map((r) => r.join('-')).join('; ')
    case 'json':
      return JSON.stringify(value)
    default:
      return String(value)
  }
}

/** Parse user text. `undefined` means "leave the parameter out" (server default applies). */
export function fromText(w: Widget, text: string): unknown {
  const t = text.trim()
  switch (w.kind) {
    case 'number':
    case 'integer':
      return t === '' ? undefined : num(t)
    case 'nullableNumber':
      return t === '' ? null : num(t)
    case 'numberList':
      return t === '' ? [] : t.split(/[,;\s]+/).filter(Boolean).map(num)
    case 'numberListOrConst':
      if (w.consts?.includes(t)) return t
      return t === '' ? [] : t.split(/[,;\s]+/).filter(Boolean).map(num)
    case 'range':
      return pair(t)
    case 'rangeList':
      return t === '' ? [] : t.split(';').filter((s) => s.trim()).map(pair)
    case 'json':
      try {
        return JSON.parse(t)
      } catch {
        throw new Error('invalid JSON')
      }
    default:
      return t
  }
}

export function defaults(schema: JsonSchema): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [name, prop] of Object.entries(schema.properties ?? {}))
    // JSON copy: schema objects live in reactive state, which structuredClone cannot copy.
    if (prop.default !== undefined) out[name] = JSON.parse(JSON.stringify(prop.default))
  return out
}

export const label = (name: string) =>
  name.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
