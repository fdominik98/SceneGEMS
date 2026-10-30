import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Setup for the `*.dom.test.tsx` files only (see the `dom` project in vite.config.ts). Testing Library
// cleans up on its own only when vitest globals are on, which they are not here.

// jsdom has no ResizeObserver, which React Flow (the campaign wizard's map) needs to mount. This one never
// reports a size; a test that needs size changes stubs its own with vi.stubGlobal.
if (typeof window.ResizeObserver === 'undefined') {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}

afterEach(() => {
  cleanup()
  window.localStorage.clear()
})
