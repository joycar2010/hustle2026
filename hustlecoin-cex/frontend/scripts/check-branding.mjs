import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// COIN-REG-20260914-LOGO: fail a release if the old favicon is reintroduced.
// Optionally pass a Vite output directory to check the artifact before deployment.
const frontend = fileURLToPath(new URL('../', import.meta.url))
const artifact = process.argv[2] && path.resolve(process.argv[2])
const root = artifact || frontend
const publicDir = artifact || path.join(frontend, 'public')
const logoPath = '/assets/logo.png'
const logo = readFileSync(path.join(publicDir, logoPath))
const version = createHash('sha256').update(logo).digest('hex').slice(0, 12)
const iconUrl = `${logoPath}?v=${version}`
const html = readFileSync(path.join(root, 'index.html'), 'utf8')
const links = [...html.matchAll(/<link\b[^>]*>/gi)].map(([tag]) =>
  Object.fromEntries([...tag.matchAll(/([\w-]+)=["']([^"']*)["']/g)].map(([, key, value]) => [key, value])),
)

for (const rel of ['icon', 'apple-touch-icon', 'manifest']) {
  const matches = links.filter(link => (link.rel || '').split(/\s+/).includes(rel))
  assert.equal(matches.length, 1, `Expected exactly one ${rel} link`)
  assert.equal(matches[0].href, rel === 'manifest' ? `/manifest.json?v=${version}` : iconUrl,
    `${rel} must use the Dashboard logo and its current cache version`)
  if (rel === 'icon') assert.equal(matches[0].type, 'image/png')
}
const manifest = JSON.parse(readFileSync(path.join(publicDir, 'manifest.json'), 'utf8'))
assert.ok(manifest.icons?.length, 'PWA icons are required')
for (const icon of manifest.icons) {
  assert.equal(icon.src, iconUrl, 'PWA must use the Dashboard logo')
  assert.equal(icon.type, 'image/png')
}
const topbar = readFileSync(path.join(frontend, 'src/components/layout/OwlTopBar.tsx'), 'utf8')
assert.ok(topbar.includes(`src="${logoPath}"`), 'Review icon references when the Dashboard logo changes')
console.log(`Branding verified (${artifact ? 'artifact' : 'source'}): ${iconUrl}`)
