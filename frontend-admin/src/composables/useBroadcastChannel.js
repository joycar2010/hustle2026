import { ref, onUnmounted } from "vue"

const CHANNEL_NAME = "hustle-admin-ws-share"

export function useBroadcastChannel() {
  const lastSharedMessage = ref(null)
  let channel = null

  function init() {
    if (channel) return
    try {
      channel = new BroadcastChannel(CHANNEL_NAME)
      channel.onmessage = (ev) => { lastSharedMessage.value = ev.data }
    } catch {}
  }

  function broadcast(msg) {
    if (!channel) init()
    try { channel?.postMessage(msg) } catch {}
  }

  function close() {
    try { channel?.close() } catch {}
    channel = null
  }

  onUnmounted(close)

  return { lastSharedMessage, init, broadcast, close }
}
