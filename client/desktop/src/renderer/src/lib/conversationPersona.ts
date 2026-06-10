export const PERSONA_PRESETS = [
  { id: 'default', label: '默认 Archer', note: '每轮自动选姿态', mode: 'auto' },
  { id: 'sharp', label: '锋利判断', note: '少铺垫，直接指出关键问题', mode: 'critic' },
  { id: 'patient', label: '耐心陪跑', note: '慢一点，帮你理清混乱', mode: 'listener' },
  { id: 'strategist', label: '战略视角', note: '看长期结构和取舍', mode: 'coach' },
  { id: 'craft', label: '创作伙伴', note: '更重表达、气质和文字手感', mode: 'writer' },
] as const

export type PersonaPresetId = (typeof PERSONA_PRESETS)[number]['id']

export const MODE_TO_PERSONA: Record<string, PersonaPresetId> = {
  auto: 'default',
  critic: 'sharp',
  listener: 'patient',
  coach: 'strategist',
  writer: 'craft',
}

export function personaIdFromMode(mode: string | undefined): PersonaPresetId {
  if (!mode) return 'default'
  return MODE_TO_PERSONA[mode] ?? 'default'
}

export function personaPresetFromMode(mode: string | undefined) {
  const id = personaIdFromMode(mode)
  return PERSONA_PRESETS.find((item) => item.id === id) ?? PERSONA_PRESETS[0]
}

export function modeLabelFromId(mode: string, modes: Array<{ id: string; label: string }>): string {
  if (mode === 'auto') return '自动'
  return modes.find((item) => item.id === mode)?.label ?? mode
}

export function connectionStatusLabel(
  apiState: string,
  isLocal: boolean
): string {
  if (isLocal || apiState === 'connected') return '已就绪'
  if (apiState === 'loading') return '连接中'
  if (apiState === 'missing_token') return '缺少口令'
  if (apiState === 'bad_token') return '口令不匹配'
  if (apiState === 'api_offline') return '大脑未运行'
  if (apiState === 'error') return '未连接'
  return '未连接'
}
