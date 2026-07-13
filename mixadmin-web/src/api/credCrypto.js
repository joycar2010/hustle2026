// 浏览器端 API 凭证加密（用户拍板方案一）——明文永不离开本机。
// 用 B 机 sealed box 公钥加密 key\nsecret\npassphrase，只把密文提交给 mix-backend。
import nacl from 'tweetnacl'
import sealedbox from 'tweetnacl-sealedbox-js'

const b64ToBytes = (b64) => Uint8Array.from(atob(b64), c => c.charCodeAt(0))
const bytesToB64 = (bytes) => btoa(String.fromCharCode(...bytes))

// 明文三行组包 → sealed box 密文（base64）。pubkeyB64 来自 /credentials/pubkey
export function sealCredential(pubkeyB64, apiKey, apiSecret, passphrase = '') {
  const plain = `${apiKey}\n${apiSecret}\n${passphrase}`
  const msg = new TextEncoder().encode(plain)
  const ct = sealedbox.seal(msg, b64ToBytes(pubkeyB64))
  return bytesToB64(ct)
}

// 前 4 后 4 掩码（网页展示/落库用，非敏感）
export function maskKey(k) {
  if (!k || k.length <= 8) return '****'
  return `${k.slice(0, 4)}…${k.slice(-4)}`
}

export { nacl }
