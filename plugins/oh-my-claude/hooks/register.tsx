import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { SiteChange } from '../types'

const PANE = 'site-live'
const TITLE = 'Hjemmeside live'
const WEB_FILE = /\.(html?|css|s[ac]ss|m?[jt]sx?|vue|svelte|astro|md|json|svg|png|jpe?g|webp|gif|ico)$/i
const SITE_MARKERS = ['index.html', 'public/index.html', 'src/index.html', 'vercel.json', '.vercel']
const VERCEL_URL = /https:\/\/[\w.-]+\.vercel\.app\S*/g

const changes = atom({ plugin: 'oh-my-claude', key: 'changes' } as const, [] as SiteChange[])
const url = atom({ plugin: 'oh-my-claude', key: 'url' } as const, null as string | null)
const isPublishing = atom({ plugin: 'oh-my-claude', key: 'isPublishing' } as const, false)

// The pane is a nice-to-have: never let a surface that places no panes break a command or a tool call.
const openPane = ($: EngineInterface) => $.ui.open({ id: PANE, title: TITLE }).catch(() => undefined)

const clockTime = (ms: number) => new Date(ms).toTimeString().slice(0, 8)

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'udgiv',
      description: 'Læg hjemmesiden online på Vercel og tjek den i Chrome',
    })
    const ran = await next(e)
    const isSite = (await Promise.all(SITE_MARKERS.map(p => $.fs.exists(p)))).some(Boolean)
    if (isSite) void openPane($)

    return ran
  })

  on('command.run', { command: 'udgiv' }, async $ => {
    await update($, isPublishing, () => true)
    await openPane($)
    // A command.run hook may not submit while it holds the turn: submit once it has answered.
    void $.clock.after(0, () =>
      $.prompt.submit({
        text:
          'Udgiv hjemmesiden i denne mappe til Vercel med skill publish-homepage: ' +
          'deploy med `npx vercel deploy --prod --yes`, tjek den offentlige adresse i Chrome DevTools, ' +
          'ret fejl, og giv mig til sidst linket på dansk.',
      }),
    )

    return { text: 'Sender hjemmesiden online …' }
  })

  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    // Any finished vercel run ends the "publishing" state, a failed one too.
    if (e.tool === 'Bash' && /vercel/.test(e.command)) await update($, isPublishing, () => false)
    if (ran.deny !== undefined || ran.isError) return ran

    if ((e.tool === 'Write' || e.tool === 'Edit') && WEB_FILE.test(e.file_path)) {
      const change = { file: e.file_path.split(/[\\/]/).slice(-2).join('/'), at: await $.clock.now() }
      await update($, changes, list => [change, ...list.filter(c => c.file !== change.file)].slice(0, 8))
      void openPane($)
    }

    if (e.tool === 'Bash' && /vercel/.test(e.command)) {
      const found = (ran.text ?? '').match(VERCEL_URL)
      if (found) {
        const live = found[found.length - 1]
        await update($, url, () => live ?? null)
        $.ui.toast(`Online: ${live}`)
      }
    }

    return ran
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Link } = $.ui.resolve(e)
    const list = await read($, changes)
    const live = await read($, url)
    const busy = await read($, isPublishing)

    return (
      <Box flexDirection="column">
        <Text bold>Online</Text>
        {busy && <Text color="yellow">Sendes online …</Text>}
        {live ? <Link href={live} label={live} /> : <Text dimColor>Ikke udgivet endnu. Skriv /udgiv</Text>}
        <Text> </Text>
        <Text bold>Seneste ændringer</Text>
        {list.length === 0 && <Text dimColor>Ingen ændringer endnu.</Text>}
        {list.map(c => (
          <Text>
            <Text dimColor>{clockTime(c.at)}</Text> {c.file}
          </Text>
        ))}
      </Box>
    )
  })
}
