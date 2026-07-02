import { describe, expect, it } from 'vitest'
import { modelSwitchNotice } from '../conversationPersona'

describe('modelSwitchNotice', () => {
  it('builds a visible model switch notice and performance warning', () => {
    expect(modelSwitchNotice('lite', 'max')).toEqual({
      text: '⇄ 模型已从 DSK 更改为 GLM',
      detail: '在对话中途切换模型会降低性能表现。背景信息可能会自动压缩。',
    })
  })
})
