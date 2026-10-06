export type SiteChange = { file: string; at: number }

declare module 'claude-code' {
  interface PluginState {
    'oh-my-claude': { changes: SiteChange[]; url: string | null; isPublishing: boolean }
  }
}
