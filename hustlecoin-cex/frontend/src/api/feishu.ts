import client from './client'

export async function getFeishuConfig() {
  const { data } = await client.get('/api/feishu/')
  return data
}

export async function updateFeishuConfig(body: Record<string, unknown>) {
  const { data } = await client.put('/api/feishu/', body)
  return data
}

export async function testFeishuConfig() {
  const { data } = await client.post('/api/feishu/test')
  return data
}
