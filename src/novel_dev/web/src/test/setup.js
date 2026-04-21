class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

class EventSourceMock {
  constructor() {
    this.readyState = 0
    this.onopen = null
    this.onmessage = null
    this.onerror = null
  }

  addEventListener() {}
  removeEventListener() {}
  close() {}
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = ResizeObserverMock
}

if (!globalThis.matchMedia) {
  globalThis.matchMedia = () => ({
    matches: false,
    media: '',
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {
      return false
    },
  })
}

if (!globalThis.EventSource) {
  globalThis.EventSource = EventSourceMock
}
