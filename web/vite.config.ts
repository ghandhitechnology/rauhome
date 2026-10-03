import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Set by `serve-remote` when the dev server is published over Tailscale; unset
 * for ordinary local work, which keeps the default loopback behaviour exactly
 * as it was.
 *
 * `RAU_PUBLIC_HOST` is the ts.net name the browser actually asks for, so Vite
 * has to allow it, HMR has to dial back to it over wss, and the hub proxy has
 * to be told the original request was TLS -- the hub compares the browser's
 * Origin scheme against its own, and would otherwise reject every socket.
 */
const publicHost = process.env.RAU_PUBLIC_HOST
const publicPort = Number(process.env.RAU_PUBLIC_PORT) || 443

// Host is deliberately NOT rewritten: the hub matches Origin against Host, so
// the pair has to stay the browser's, not the proxy target's.
const forwarded = publicHost ? { 'X-Forwarded-Proto': 'https' } : undefined

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8765', headers: forwarded },
      '/ws': { target: 'ws://127.0.0.1:8765', ws: true, headers: forwarded },
    },
    ...(publicHost
      ? {
          allowedHosts: [publicHost],
          hmr: { protocol: 'wss', host: publicHost, clientPort: publicPort },
        }
      : {}),
  },
})
