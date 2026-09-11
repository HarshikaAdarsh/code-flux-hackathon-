import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The backend's CORS_ORIGINS allowlist names this exact port. If Vite were
    // allowed to fall back to 5174 when 5173 is busy, the app would load fine
    // and then fail every API call on CORS — so fail loudly here instead.
    port: 5173,
    strictPort: true,
  },
})
