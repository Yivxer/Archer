import { describe, expect, it } from 'vitest'
import { buildThinkingMutter } from '../thinkingMutter'

describe('buildThinkingMutter', () => {
  it('returns contextual mutter for questions', () => {
    const mutter = buildThinkingMutter('我换了一个你知道是什么模型么？')
    expect(mutter.length).toBeGreaterThan(0)
    expect(mutter).not.toContain('先判断方向')
    expect(mutter).not.toContain('具体处理继续往下跑')
  })

  it('varies mutter by question content', () => {
    const a = buildThinkingMutter('为什么天空是蓝的？')
    const b = buildThinkingMutter('你觉得这件事怎么办？')
    expect(a).not.toBe(b)
  })

  it('returns stable mutter for the same prompt', () => {
    const prompt = '你不知道什么模型怎么判断你能否了解我呢？'
    expect(buildThinkingMutter(prompt)).toBe(buildThinkingMutter(prompt))
  })
})
