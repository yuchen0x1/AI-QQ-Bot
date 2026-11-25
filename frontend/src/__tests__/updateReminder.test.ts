import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  LEGACY_DEFERRED_KEY, readUpdateReminder, shouldRemindUpdate, snoozeUpdate,
  SNOOZE_DURATION_MS, subscribeUpdateReminder, UPDATE_REMINDER_KEY,
} from '../updateReminder'

describe('update reminders', () => {
  beforeEach(() => { localStorage.clear(); vi.useFakeTimers(); vi.setSystemTime(1_800_000_000_000) })
  afterEach(() => { vi.useRealTimers(); localStorage.clear() })

  it('migrates a legacy permanent deferral once and restores it after six hours', () => {
    localStorage.setItem(LEGACY_DEFERRED_KEY, '1.6.0')
    const reminder = readUpdateReminder()
    expect(localStorage.getItem(LEGACY_DEFERRED_KEY)).toBeNull()
    expect(shouldRemindUpdate('1.6.0', true, 360, reminder)).toBe(false)
    vi.advanceTimersByTime(SNOOZE_DURATION_MS)
    expect(readUpdateReminder()).toBeNull()
    expect(shouldRemindUpdate('1.6.0', true, 360, readUpdateReminder())).toBe(true)
  })

  it('reappears on an open page when the snooze expires and keeps a newer version visible', () => {
    const values: unknown[] = []
    const stop = subscribeUpdateReminder((value) => values.push(value))
    snoozeUpdate('1.6.0')
    expect(shouldRemindUpdate('1.6.1', true, 360, readUpdateReminder())).toBe(true)
    vi.advanceTimersByTime(SNOOZE_DURATION_MS)
    expect(values.at(-1)).toBeNull()
    stop()
  })

  it('updates other tabs through storage events and preserves a snooze after relogin', () => {
    snoozeUpdate('1.6.0')
    const persisted = readUpdateReminder()
    expect(shouldRemindUpdate('1.6.0', true, 360, persisted)).toBe(false)
    const seen: unknown[] = []
    const stop = subscribeUpdateReminder((value) => seen.push(value))
    const otherTab = { version: '1.6.1', snooze_until: Date.now() + 60_000 }
    localStorage.setItem(UPDATE_REMINDER_KEY, JSON.stringify(otherTab))
    window.dispatchEvent(new StorageEvent('storage', { key: UPDATE_REMINDER_KEY }))
    expect(seen.at(-1)).toEqual(otherTab)
    stop()
  })

  it('honors disabled checks and fails visible for invalid or inaccessible storage', () => {
    expect(shouldRemindUpdate('1.6.0', true, 0, null)).toBe(false)
    expect(shouldRemindUpdate('1.6.0', false, 360, null)).toBe(false)
    localStorage.setItem(UPDATE_REMINDER_KEY, '{broken')
    expect(readUpdateReminder()).toBeNull()
    const blocked = { getItem: () => { throw new Error('blocked') }, setItem: () => {}, removeItem: () => {} }
    expect(readUpdateReminder(blocked)).toBeNull()
    expect(shouldRemindUpdate('1.6.0', true, 360, readUpdateReminder(blocked))).toBe(true)
  })
})
