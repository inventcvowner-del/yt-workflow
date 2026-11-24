import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The page's server is scripts\server.py ("run ui"); its port is UI_PORT in scripts\config.py.
// "pnpm dev" passes the page's requests on to it, so start "run ui" first.
const server = 'http://127.0.0.1:9335'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { '/api': { target: server, changeOrigin: true, headers: { origin: server } } },
  },
})
