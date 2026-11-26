import { existsSync, readdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

export const inject = ['agents']

export async function apply(ctx, config) {
  const { createUserMessage } = await import(pathToFileURL(config.llmPath).href)
  if (config.completionEndpoint) {
    ctx.on('agent/turn-stopping', async ({ signal }) => {
      const response = await fetch(config.completionEndpoint, {
        method: 'POST', signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]),
      })
      if (!response.ok) throw new Error(`DynaRev completion check returned ${response.status}`)
    })
  }
  ctx.on('agent/created', ({ agent }) => {
    const timer = setInterval(() => {
      for (const file of readdirSync(config.mailbox).filter(name => name.endsWith('.request')).sort()) {
        const receipt = join(config.mailbox, file.replace(/\.request$/, '.receipt'))
        if (existsSync(receipt)) continue
        const { text } = JSON.parse(readFileSync(join(config.mailbox, file), 'utf8'))
        const running = agent.status === 'running'
        if (running) {
          agent.steer(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text }] }))
        }
        writeFileSync(receipt + '.pending', JSON.stringify({
          accepted: running, status: agent.status, session_id: agent.id,
        }))
        renameSync(receipt + '.pending', receipt)
      }
    }, 50)
    timer.unref()
    ctx.on('dispose', () => clearInterval(timer))
  })
}
