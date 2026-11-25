export const UPDATE_REMINDER_KEY = 'qbot_update_reminder'
export const LEGACY_DEFERRED_KEY = 'qbot_deferred_update'
export const UPDATE_REMINDER_EVENT = 'qbot-update-reminder-changed'
export const SNOOZE_DURATION_MS = 6 * 60 * 60 * 1000

export type UpdateReminder = { version: string; snooze_until: number }
type ReminderStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

function browserStorage(): ReminderStorage | undefined {
  try { return localStorage } catch { return undefined }
}

export function readUpdateReminder(storage = browserStorage(), now = Date.now()): UpdateReminder | null {
  if (!storage) return null
  try {
    const saved = storage.getItem(UPDATE_REMINDER_KEY)
    let reminder: UpdateReminder | null = saved ? JSON.parse(saved) : null
    if (!saved) {
      const legacy = storage.getItem(LEGACY_DEFERRED_KEY)
      if (legacy) {
        // The old value has no timestamp. Grant one bounded snooze on migration.
        reminder = { version: legacy, snooze_until: now + SNOOZE_DURATION_MS }
        storage.setItem(UPDATE_REMINDER_KEY, JSON.stringify(reminder))
      }
    }
    storage.removeItem(LEGACY_DEFERRED_KEY)
    if (!reminder || typeof reminder.version !== 'string'
      || !Number.isFinite(reminder.snooze_until) || reminder.snooze_until <= now) {
      storage.removeItem(UPDATE_REMINDER_KEY)
      return null
    }
    return reminder
  } catch {
    // Storage disabled or corrupt state must never hide an available update.
    try { storage.removeItem(UPDATE_REMINDER_KEY); storage.removeItem(LEGACY_DEFERRED_KEY) } catch { /* unavailable */ }
    return null
  }
}

export function snoozeUpdate(version: string, storage = browserStorage(), now = Date.now()): UpdateReminder {
  const reminder = { version, snooze_until: now + SNOOZE_DURATION_MS }
  try {
    storage?.setItem(UPDATE_REMINDER_KEY, JSON.stringify(reminder))
    storage?.removeItem(LEGACY_DEFERRED_KEY)
  } catch { /* A failed write leaves the reminder visible. */ }
  window.dispatchEvent(new Event(UPDATE_REMINDER_EVENT))
  return reminder
}

export function shouldRemindUpdate(version: string, available: boolean, intervalMinutes: number,
  reminder: UpdateReminder | null, now = Date.now()) {
  return intervalMinutes > 0 && available && Boolean(version)
    && !(reminder?.version === version && reminder.snooze_until > now)
}

export function subscribeUpdateReminder(listener: (reminder: UpdateReminder | null) => void) {
  let timer: ReturnType<typeof setTimeout> | undefined
  let stopped = false
  const update = () => {
    if (stopped) return
    clearTimeout(timer)
    const reminder = readUpdateReminder()
    listener(reminder)
    if (reminder) timer = setTimeout(update, Math.min(Math.max(1, reminder.snooze_until - Date.now()), 2_147_483_647))
  }
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || [UPDATE_REMINDER_KEY, LEGACY_DEFERRED_KEY].includes(event.key)) update()
  }
  window.addEventListener('storage', onStorage)
  window.addEventListener(UPDATE_REMINDER_EVENT, update)
  document.addEventListener('visibilitychange', update)
  update()
  return () => {
    stopped = true
    clearTimeout(timer)
    window.removeEventListener('storage', onStorage)
    window.removeEventListener(UPDATE_REMINDER_EVENT, update)
    document.removeEventListener('visibilitychange', update)
  }
}
