import type { SettingsDraft } from '../types'

/** Preview fixture only; never published as a local server snapshot. */
export const mockSettings: SettingsDraft = {
    activeProfile: 'lite',
    activeExpert: 'default',
    experts: [
      { id: 'default', label: '基础 Archer', note: '灵魂陪伴，不担任特定工作角色', modelProfile: 'lite', skillCount: 0, configured: true },
      { id: 'developer', label: '开发工程师', note: '查代码、排错、看结构、委派实现', modelProfile: 'pro', skillCount: 6, configured: false },
      { id: 'video-coach', label: '短视频教练', note: '脚本、口播、选题与表达节奏', modelProfile: 'pro', skillCount: 3, configured: false },
      { id: 'content-creator', label: '内容创作者', note: '文章、博客、长文与发布链路', modelProfile: 'lite', skillCount: 4, configured: true },
      { id: 'counselor', label: '心理咨询师', note: '情绪、关系与自我理解', modelProfile: 'pro', skillCount: 3, configured: false },
      { id: 'parent-educator', label: '亲子教育家', note: '育儿沟通与教育理念', modelProfile: 'lite', skillCount: 3, configured: true },
    ],
    modelProfiles: [
      { id: 'lite', label: 'DSK', provider: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1', model: 'deepseek-chat', apiKeyPreview: '••••', configured: true },
      { id: 'pro', label: 'KIM', provider: 'Kimi', baseUrl: '', model: '', apiKeyPreview: '', configured: false },
      { id: 'max', label: 'GLM', provider: 'GLM', baseUrl: '', model: '', apiKeyPreview: '', configured: false },
    ],
    provider: 'OpenAI-compatible',
    baseUrl: 'https://api.deepseek.com/v1',
    model: 'deepseek-chat',
    apiKeyPreview: '••••',
    configPath: '~/.archer/archer.toml',
    memoryDbPath: '~/.archer/archer.db',
    sessionsPath: '~/.archer/sessions'
  }
