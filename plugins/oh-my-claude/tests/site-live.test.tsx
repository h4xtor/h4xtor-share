import { expect, mock, test } from 'claude-code/testing'

const PANE = {
  component: 'Pane',
  requestId: 'site-live',
  props: { title: 'Hjemmeside live', isFocused: false, bodyColumns: 40, placement: 'dock' },
} as const

test('edits show in the pane, a vercel deploy sets the live link, /udgiv asks Claude to publish', async ($, on) => {
  const clock = mock.clock(on, { now: Date.UTC(2026, 9, 6, 12, 0, 0) })
  const prompts: string[] = []
  on('ui.open', () => ({ value: { isPlaced: true } }) as never)
  on('ui.toast', () => ({ value: undefined }) as never)
  on('prompt.submit', ($, e) => {
    prompts.push(e.text)
    return { text: e.text }
  })
  on('tool.call', ($, e) =>
    e.tool === 'Bash'
      ? { result: {}, text: 'Production: https://min-side-abc.vercel.app [3s]' }
      : { result: {}, text: 'ok' },
  )

  await $.tool.call({ tool: 'Write', file_path: '/p/site/index.html', content: '<h1>Hej</h1>' })
  await $.tool.call({ tool: 'Write', file_path: '/p/site/notes.txt', content: 'x' })
  await $.tool.call({ tool: 'Bash', command: 'npx vercel deploy --prod --yes' })

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'oh-my-claude', surface, ...PANE } as never)
    expect(await ui.find({ text: 'site/index.html' })).toBeDefined()
    expect(await ui.find({ text: 'notes.txt' })).toBeUndefined()
    expect(await ui.find({ type: 'Link', text: 'https://min-side-abc.vercel.app' })).toBeDefined()
    await ui.unmount()
  }

  const ran = await $.command.run({ command: 'udgiv', args: '' } as never)
  expect(ran.text).toBe('Sender hjemmesiden online …')
  await clock.advance(0)
  expect(prompts[0]).toContain('vercel deploy --prod')
})
