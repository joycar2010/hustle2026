// Passkey/WebAuthn 前端接线(V6.1 §8.2 P0):调后端已存在的注册/认证接口,
// 认证成功换 10 分钟 reauth ticket——高危动作用 ticket 代替手输 TOTP。
import { mixApi } from './mix'

const b64uToBuf = (s) => Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - s.length % 4) % 4)), c => c.charCodeAt(0))
const bufToB64u = (b) => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')

export function passkeySupported() {
  return typeof window !== 'undefined' && !!window.PublicKeyCredential
}

/** 注册本设备 Passkey(平台认证器:指纹/面容/PIN) */
export async function passkeyRegister(deviceLabel = '') {
  const opts = await mixApi.webauthnRegOptions()
  const pk = { ...opts,
    challenge: b64uToBuf(opts.challenge),
    user: { ...opts.user, id: b64uToBuf(opts.user.id) },
    excludeCredentials: (opts.excludeCredentials || []).map(c => ({ ...c, id: b64uToBuf(c.id) })) }
  const cred = await navigator.credentials.create({ publicKey: pk })
  const payload = {
    id: cred.id, rawId: bufToB64u(cred.rawId), type: cred.type,
    response: {
      clientDataJSON: bufToB64u(cred.response.clientDataJSON),
      attestationObject: bufToB64u(cred.response.attestationObject),
    },
    clientExtensionResults: cred.getClientExtensionResults?.() || {},
  }
  return mixApi.webauthnRegVerify({ credential: payload, device_label: deviceLabel })
}

/** 认证并返回 reauth_ticket(一次性,600s) */
export async function passkeyTicket() {
  const opts = await mixApi.webauthnAuthOptions()
  const pk = { ...opts,
    challenge: b64uToBuf(opts.challenge),
    allowCredentials: (opts.allowCredentials || []).map(c => ({ ...c, id: b64uToBuf(c.id) })) }
  const cred = await navigator.credentials.get({ publicKey: pk })
  const payload = {
    id: cred.id, rawId: bufToB64u(cred.rawId), type: cred.type,
    response: {
      clientDataJSON: bufToB64u(cred.response.clientDataJSON),
      authenticatorData: bufToB64u(cred.response.authenticatorData),
      signature: bufToB64u(cred.response.signature),
      userHandle: cred.response.userHandle ? bufToB64u(cred.response.userHandle) : null,
    },
    clientExtensionResults: cred.getClientExtensionResults?.() || {},
  }
  const r = await mixApi.webauthnAuthVerify({ credential: payload })
  return r.reauth_ticket
}
