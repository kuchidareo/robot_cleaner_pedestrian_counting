import asyncio
import websockets
import binascii
import time

URL = "ws://192.168.121.161:81"

def hex_preview(b: bytes, n: int = 64) -> str:
    head = b[:n]
    return binascii.hexlify(head).decode()

async def main():
    while True:
        try:
            async with websockets.connect(URL, ping_interval=20, ping_timeout=20) as ws:
                print(f"[{time.strftime('%H:%M:%S')}] connected -> {URL}")

                i = 0
                while True:
                    msg = await ws.recv()
                    i += 1

                    if isinstance(msg, str):
                        print(f"[{i}] TEXT len={len(msg)}: {msg[:200]!r}")
                    else:
                        print(f"[{i}] BIN  len={len(msg)}  head(hex)={hex_preview(msg)}")

        except Exception as e:
            print(f"connect/error: {e} (retry in 1s)")
            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())