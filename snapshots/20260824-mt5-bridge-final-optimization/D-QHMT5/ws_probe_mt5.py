import asyncio,json,websockets
async def one(port,key):
 try:
  async with websockets.connect(f'ws://127.0.0.1:{port}/ws/terminal?api_key={key}',open_timeout=5,close_timeout=2) as ws:
   m=await asyncio.wait_for(ws.recv(),timeout=5); d=json.loads(m); print(port,'OK',d.get('type'),d.get('instance'),d.get('snapshot_seq'),d.get('execution'))
 except Exception as e: print(port,'ERR',type(e).__name__,str(e)[:160])
async def main():
 key='7af2221c27241dd524273d2752772aa43e6b18c0187dffbf'; await asyncio.gather(one(8061,key),one(8063,key))
asyncio.run(main())
