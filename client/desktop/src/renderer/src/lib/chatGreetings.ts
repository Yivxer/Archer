/** 首页问候：偏陪伴感，避免客服腔。每次新建对话随机一条。 */
export const CHAT_GREETINGS = [
  '想说点什么？',
  '我在，慢慢说。',
  '先开口，别的交给我。',
  '今天想聊点什么？',
  '有什么在脑子里转？',
  '从哪一句开始都行。',
  '不用想清楚再说。',
  '今天怎么样？',
  '想聊聊，还是先坐一会儿？',
  '先把话搁这儿。',
] as const

export function pickChatGreeting(seed?: number): string {
  const index =
    seed === undefined
      ? Math.floor(Math.random() * CHAT_GREETINGS.length)
      : Math.abs(seed) % CHAT_GREETINGS.length
  return CHAT_GREETINGS[index]
}
