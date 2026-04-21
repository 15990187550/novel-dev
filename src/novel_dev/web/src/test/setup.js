class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

class EventSourceMock {
  static instances = []

  constructor(url) {
    this.url = url
    this.readyState = 0
    this.closed = false
    this.onopen = null
    this.onmessage = null
    this.onerror = null
    EventSourceMock.instances.push(this)
  }

  addEventListener() {}
  removeEventListener() {}
  close() {
    this.closed = true
    this.readyState = 2
  }
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
  globalThis.EventSource.instances = EventSourceMock.instances
}
