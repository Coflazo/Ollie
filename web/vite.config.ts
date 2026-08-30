import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Dev server talks to the local FastAPI process. In a built bundle the API is
    // same-origin, so this proxy only exists for `npm run dev`.
    proxy: { '/v1': 'http://127.0.0.1:8765' },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
