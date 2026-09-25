// Categorical series colours: fixed order, never cycled (validated reference palette).
// A spectrum keeps its slot while it stays visible; past eight visible spectra the extra
// ones are drawn in a neutral grey instead of inventing new hues.

export const SERIES = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
}

export const OVERFLOW = { light: '#9a9993', dark: '#6f6e69' }

export const STATUS = {
  good: '#0ca30c',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#d03b3b',
}

export function seriesColor(slot: number | undefined, dark: boolean): string {
  const mode = dark ? 'dark' : 'light'
  return slot === undefined || slot < 0 ? OVERFLOW[mode] : SERIES[mode][slot]
}
