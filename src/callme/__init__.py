import asyncio
import time
from fractions import Fraction

from dataclasses import dataclass
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack, MediaStreamError
from aiortc.contrib.media import MediaRelay

app = FastAPI()
relay = MediaRelay()

class Puente(MediaStreamTrack):
    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self.pista: MediaStreamTrack | None = None
        self.hay_pista = asyncio.Event()
        self.inicio = time.time()
        self.muestras  = 0

    def conectar(self, pista: MediaStreamTrack):
        self.pista = pista
        self.hay_pista.set()

    def desconectar(self):
        self.pista = None
        self.hay_pista.clear()

    async def recv(self):
        while True:
            await self.hay_pista.wait()
            try:
                frame = await self.pista.recv()
                break
            except MediaStreamError:
                self.desconectar()
        if self.kind == "video":
            frame.pts = int((time.time() - self.inicio) * 90_000)
            frame.time_base = Fraction(1, 90_000)
        else:
            frame.pts = self.muestras
            frame.time_base = Fraction(1, frame.sample_rate)
            self.muestras += frame.samples
        return frame


class Participante:
    def __init__(self, ws: WebSocket, nombre: str):
        self.ws = ws
        self.nombre = nombre
        self.pc = RTCPeerConnection()
        self.entrantes: dict[str, MediaStreamTrack] = {}
        self.salientes = {"audio": Puente("audio"), "video": Puente("video")}
    
    async def avisar(self, mensaje: dict):
        try:
            await self.ws.send_json(mensaje)
        except Exception:
            print("Se desconecto")

sala: list[Participante] = []

@app.websocket("/ws")
async def senalizacion(ws: WebSocket):
    await ws.accept()
    yo: Participante | None = None

    try:
        while True:
            msg = await ws.receive_json()

            if msg["tipo"] != "oferta" or yo is not None:
                continue

            yo = Participante(ws=ws, nombre=msg["nombre"])
            otro = sala[0] if sala else None

            sala.append(yo)

            @yo.pc.on("track")
            def al_recibir_pista(pista):
                yo.entrantes[pista.kind] = pista
                for participante in sala:
                    if participante is not yo:
                        participante.salientes[pista.kind].conectar(
                            relay.subscribe(pista)
                        )

            oferta = msg["sdp"]
            await yo.pc.setRemoteDescription(
                RTCSessionDescription(
                    sdp=oferta, type="offer"
                )
            )
            for pista in yo.salientes.values():
                yo.pc.addTrack(pista)

            if otro:
                for kind, pista in otro.entrantes.items():
                    yo.salientes[kind].conectar(
                        relay.subscribe(pista)
                    )

            await yo.pc.setLocalDescription(
                await yo.pc.createAnswer()
            )
            await ws.send_json({
                "tipo": "respuesta",
                "sdp": yo.pc.localDescription.sdp
            })

            if otro:
                await otro.avisar({
                    "tipo": "entro", "nombre": yo.nombre
                })
                await yo.avisar({
                    "tipo": "entro", "nombre": otro.nombre
                })



    except WebSocketDisconnect:
        pass
    finally:
        if yo:
            await salir(yo)


async def salir(yo: Participante):
    sala.remove(yo)
    for p in sala:
        for pista in p.salientes.values():
            pista.desconectar()
        await p.avisar({"tipo": "salio", "nombre": yo.nombre})
    await yo.pc.close()
    print(f"{yo.nombre} salio de la sala")



app.mount("/", StaticFiles(directory="public", html=True))