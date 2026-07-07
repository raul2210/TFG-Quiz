from app import create_app
import os


import asyncio
import websockets
from flask import Flask, render_template
from threading import Thread
import json
import os
import ssl

receptores = []
wsEmisor = None
app = create_app()

async def handler(ws):
    global wsEmisor, receptores


    async for raw in ws:
            data = json.loads(raw)

            if data.get("type") == "registro" and data.get("role") == "emisor":
                print ("Se registra el emisor")
                wsEmisor = ws
                if len (receptores) > 0:
                    print ("Traslado al emisor los indices de los receptores que estan esperando")
                    for indice, receptor in enumerate(receptores):
                        await wsEmisor.send(json.dumps({
                            "type": "receptor",
                            "id": indice
                        }))

            if data.get("type") == "peticion":
                print ("Recibo petición de receptor")
                receptores.append(ws)
                if wsEmisor:
                    indice = len(receptores)-1
                    print ("Envio al emisor en indice de este nuevo receptor")
                    await wsEmisor.send(json.dumps({
                        "type": "peticion",
                        "id": indice
                    }))
                else:
                    print ("El emisor aun no se ha conectado")

            if data.get("type") == "sdp" and data.get("role") == "emisor":
                id = data.get("id")
                print ("Recibo y traslado la oferta para el receptor: ", id)
                cliente = receptores[id]
                await cliente.send (raw)
            elif data.get("type") == "sdp" and data.get("role") == "receptor":
                id = receptores.index (ws)
                print ("Recibo y traslado al emisor la aceptación del receptor: ", id)
                data["id"] = id
                await wsEmisor.send(json.dumps(data))

            elif data.get("type") == "ice" and data.get("role") == "receptor":
                id = receptores.index(ws)
                data["id"] = id
                print ("Recibo y traslado al emisor un candidato para el receptor: ",id)
                await wsEmisor.send(json.dumps(data))

            elif data.get("type") == "ice" and data.get("role") == "emisor":
                print("Recibo y traslado a todos los receptores un candidato para el emisor")
                for receptor in receptores:
                    await receptor.send(raw)
            elif data.get("type") == "client-disconnect":
                id = receptores.index(ws)
                print ("Se descinecta el cliente: ", id)
                data["id"] = id
                await wsEmisor.send(json.dumps(data))

async def start_websocket_server(ssl_context):
    # Servidor WebSocket escuchando en puerto 8108
    async with websockets.serve(handler, "0.0.0.0", 8110, ssl=ssl_context):
        print("🚀 Servidor WebSocket iniciado en ws://0.0.0.0:8110")
        print("📊 Servidor listo para manejar múltiples streams")
        await asyncio.Future()  # Mantener corriendo

def run_websocket_server(ssl_context):
    """Ejecutar el servidor WebSocket en un event loop separado"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(start_websocket_server(ssl_context))
    except KeyboardInterrupt:
        print("\n🛑 Servidor WebSocket detenido manualmente.")
    finally:
        loop.close()


if __name__ == '__main__':
    base_dir = os.path.abspath(os.path.dirname(__file__))
    cert = os.path.join(base_dir, "localhost.crt")
    key = os.path.join(base_dir, "localhost.key")

    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(cert, key)
    # Crear y empezar el thread del servidor WebSocket
    websocket_thread = Thread(target=lambda:run_websocket_server(ssl_context), daemon=True)
    websocket_thread.start()
    # app.run(debug=True)
    #app.run(host='0.0.0.0', port=5000, debug=True) #para movil
    app.run(host='0.0.0.0', port=8443, debug=True, use_reloader=False, ssl_context=(cert, key))


