import { lezer } from '@lezer/generator/rollup'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import lazyDocusaurus from './scripts/vite-plugin-lazy-docusaurus.mjs'

// https://vite.dev/config/
export default defineConfig({
  plugins: [lezer(), react(), lazyDocusaurus()],
  server: {
    host: true,
  },
})
