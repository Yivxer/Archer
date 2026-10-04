/** Settings HTTP operations; transport and authorization stay shared. */
import { getJson, postJson } from './localArcher'
import type { SettingsDraft, SettingsValidationResult, SettingsSaveResult, ModelProfileTestResult, ScheduleListResult, ScheduleMutationResult } from '../types'

export async function readLocalSettings(): Promise<SettingsDraft> {
  return getJson<SettingsDraft>('/settings')
}

export async function validateLocalSettings(settings: SettingsDraft): Promise<SettingsValidationResult> {
  return postJson<SettingsValidationResult>('/settings/validate', { settings })
}

export async function saveLocalSettings(settings: SettingsDraft): Promise<SettingsSaveResult> {
  return postJson<SettingsSaveResult>('/settings/save', { settings })
}

export async function saveLocalProfileSettings(payload: {
  profileId: 'lite' | 'pro' | 'max'
  provider?: string
  baseUrl?: string
  model?: string
  apiKey?: string
}): Promise<{ ok: boolean; profileId?: string; error?: string; message?: string }> {
  return postJson('/settings/profile/save', payload)
}

export async function switchLocalActiveProfile(profileId: 'lite' | 'pro' | 'max'): Promise<{ ok: boolean; profileId?: string; activeProfile?: string; error?: string; message?: string }> {
  const result = await postJson<{ ok: boolean; profileId?: string; activeProfile?: string; error?: string; message?: string }>('/settings/profile/switch', { profileId })
  return result
}

export async function testLocalModelProfile(settings: SettingsDraft): Promise<ModelProfileTestResult> {
  return postJson<ModelProfileTestResult>('/settings/test-model', { settings })
}

export async function listSchedules(): Promise<ScheduleListResult> {
  return getJson<ScheduleListResult>('/schedules')
}

export async function addSchedule(payload: {
  skillName: string
  interval: string
  label?: string
  catchup?: 'latest' | 'skip'
}): Promise<ScheduleMutationResult> {
  return postJson<ScheduleMutationResult>('/schedules', payload)
}

export async function removeSchedule(taskId: number): Promise<ScheduleMutationResult> {
  return postJson<ScheduleMutationResult>(`/schedules/${taskId}/remove`, {})
}

export async function setScheduleEnabled(taskId: number, enabled: boolean): Promise<ScheduleMutationResult> {
  return postJson<ScheduleMutationResult>(`/schedules/${taskId}/${enabled ? 'enable' : 'disable'}`, {})
}

export async function runSchedule(taskId: number): Promise<ScheduleMutationResult> {
  return postJson<ScheduleMutationResult>(`/schedules/${taskId}/run`, {})
}
