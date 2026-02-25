import asyncio
import websockets


# WebSocket URLs
URLS = {
    "cam3": "ws://172.20.10.4:85",
    "cam4": "ws://172.20.10.2:86",
    "thermal": "ws://172.20.10.5:81"
}

# Frame sizes
FRAME_WIDTH = 32
FRAME_HEIGHT = 24

# Global dictionary for images
latest_images = {
    "cam3": None,
    "cam4": None,
    "thermal1": None,
    "thermal2": None
}

async def listen_to_camera(name, url):
    async with websockets.connect(url) as websocket:
        print(f"Connected to {name} at {url}")
        while True:
            try:
                message = await websocket.recv()
                if name == "thermal":
                    img1, img2 = json_to_images(message)
                    if img1 is not None and img2 is not None:
                        latest_images["thermal1"] = img1
                        latest_images["thermal2"] = img2
                else:
                    img = csv_to_image(message)
                    if img is not None:
                        latest_images[name] = img
            except Exception as e:
                print(f"Connection to {name} lost: {e}")
                break


async def main():
    await asyncio.gather(
        listen_to_camera("cam3", URLS["cam3"]),
        listen_to_camera("cam4", URLS["cam4"]),
        listen_to_camera("thermal", URLS["thermal"]),
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Exiting...")
