import { listLocalSkills, tryExecuteLocalSkill } from '../agent/skills/localSkillBridge'

async function main(): Promise<void> {
  const [, , skillName, argsJson] = process.argv

  if (skillName === '--list') {
    process.stdout.write(JSON.stringify(listLocalSkills()))
    return
  }

  if (!skillName) {
    process.stderr.write('usage: runLocalSkill.ts <skill> [args-json] | --list\n')
    process.exitCode = 2
    return
  }

  let args: Record<string, unknown> = {}
  if (argsJson) {
    try {
      const parsed = JSON.parse(argsJson)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        args = parsed as Record<string, unknown>
      }
    } catch {
      process.stdout.write(JSON.stringify({ ok: false, output: '', error: 'invalid args json' }))
      process.exitCode = 1
      return
    }
  }

  const result = await tryExecuteLocalSkill(skillName, args)
  if (result === null) {
    process.stdout.write(JSON.stringify({ fallback: true }))
    return
  }

  process.stdout.write(JSON.stringify(result))
  if (!result.ok) process.exitCode = 1
}

main().catch((err) => {
  process.stdout.write(JSON.stringify({
    ok: false,
    output: '',
    error: err instanceof Error ? err.message : String(err),
  }))
  process.exitCode = 1
})
