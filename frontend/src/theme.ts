import { computed, ref } from 'vue'

export type ThemeSetting = 'dark' | 'light' | 'system'
export type ThemeName = 'dark' | 'light'

const STORAGE_KEY = 'qbot_theme'
const DARK_META = '#070a12'
const LIGHT_META = '#f3f5fa'

function readSetting(): ThemeSetting {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    if (value === 'dark' || value === 'light' || value === 'system') return value
  } catch {
    /* private mode */
  }
  return 'dark'
}

const media = typeof window !== 'undefined'
  ? window.matchMedia('(prefers-color-scheme: light)')
  : null

export const themeSetting = ref<ThemeSetting>(readSetting())
export const systemPrefersLight = ref(media?.matches ?? false)
export const themeName = computed<ThemeName>(() => {
  if (themeSetting.value === 'system') return systemPrefersLight.value ? 'light' : 'dark'
  return themeSetting.value
})

function applyTheme() {
  if (typeof document === 'undefined') return
  const name = themeName.value
  document.documentElement.dataset.theme = name
  document.documentElement.style.colorScheme = name
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', name === 'dark' ? DARK_META : LIGHT_META)
}

export function setThemeSetting(value: ThemeSetting) {
  themeSetting.value = value
  try {
    localStorage.setItem(STORAGE_KEY, value)
  } catch {
    /* private mode */
  }
  applyTheme()
}

export function toggleTheme() {
  setThemeSetting(themeName.value === 'dark' ? 'light' : 'dark')
}

if (media) {
  const onChange = (event: MediaQueryListEvent) => {
    systemPrefersLight.value = event.matches
    if (themeSetting.value === 'system') applyTheme()
  }
  if (typeof media.addEventListener === 'function') media.addEventListener('change', onChange)
  else media.addListener(onChange)
}

applyTheme()

export const chartTheme = computed(() => {
  const dark = themeName.value === 'dark'
  return dark
    ? {
        text: '#e9eefb',
        muted: '#8d9bb2',
        axis: 'rgba(148, 163, 184, 0.16)',
        split: 'rgba(148, 163, 184, 0.10)',
        tooltipBg: 'rgba(14, 20, 32, 0.96)',
        tooltipBorder: 'rgba(148, 163, 184, 0.22)',
        brand: '#7f6dff',
        brandSoft: 'rgba(127, 109, 255, 0.22)',
        cyan: '#38d6e6',
        cyanSoft: 'rgba(56, 214, 230, 0.20)',
        success: '#3ddc97',
        warning: '#f5b849',
        danger: '#fb7185',
      }
    : {
        text: '#1c2637',
        muted: '#6b7a90',
        axis: 'rgba(15, 23, 42, 0.10)',
        split: 'rgba(15, 23, 42, 0.07)',
        tooltipBg: 'rgba(255, 255, 255, 0.98)',
        tooltipBorder: 'rgba(15, 23, 42, 0.12)',
        brand: '#5b5bd6',
        brandSoft: 'rgba(91, 91, 214, 0.14)',
        cyan: '#0891b2',
        cyanSoft: 'rgba(8, 145, 178, 0.12)',
        success: '#059669',
        warning: '#d97706',
        danger: '#e11d48',
      }
})
