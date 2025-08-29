import os
import json
import base64
import asyncio
import websockets
import httpx
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect, Say, Stream
from dotenv import load_dotenv

load_dotenv()

# Configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENWEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY')
PORT = int(os.getenv('PORT', 5050))
TEMPERATURE = float(os.getenv('TEMPERATURE', 0.8))
SYSTEM_MESSAGE = (
    "You are a helpful and bubbly AI assistant who loves to chat about "
    "anything the user is interested in and can also provide weather information. "
    "Tu eres un asistente de mucha ayuda y ama chatear sobre cualquier tema "
    "y también puedes proporcionar información del clima. "
    "Eres alguien que le gusta ayudar, siempre positivo y habla con un poco de chistes. "
    "When users ask about weather, you can use the weather API to get real-time information."
)
VOICE = 'alloy'
LOG_EVENT_TYPES = [
    'error', 'response.content.done', 'rate_limits.updated',
    'response.done', 'input_audio_buffer.committed',
    'input_audio_buffer.speech_stopped', 'input_audio_buffer.speech_started',
    'session.created', 'session.updated'
]
SHOW_TIMING_MATH = False

app = FastAPI()

if not OPENAI_API_KEY:
    raise ValueError('Missing the OpenAI API key. Please set it in the .env file.')

if not OPENWEATHER_API_KEY:
    print('Warning: Missing OpenWeather API key. Weather functionality will be disabled.')

@app.get("/", response_class=JSONResponse)
async def index_page():
    return {"message": "Twilio Media Stream Server is running!"}

@app.get("/weather/{city}", response_class=JSONResponse)
async def get_weather_endpoint(city: str):
    """Test endpoint to get weather for a specific city."""
    weather_info = await get_weather(city)
    return weather_info

@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handle incoming call and return TwiML response to connect to Media Stream."""
    response = VoiceResponse()
    # <Say> punctuation to improve text-to-speech flow
    response.say(
        "Bienvenidos a la gasera ordan, en que le podemos ayudar?",
        voice="Google.es-ES-Chirp3-HD-Aoede"
    )
    response.pause(length=1)
    response.say(   
        "Ahora puedes hablar!",
        voice="Google.es-ES-Chirp3-HD-Aoede"
    )
    host = request.url.hostname
    connect = Connect()
    connect.stream(url=f'wss://{host}/media-stream')
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Handle WebSocket connections between Twilio and OpenAI."""
    print("Client connected")
    await websocket.accept()

    async with websockets.connect(
        f"wss://api.openai.com/v1/realtime?model=gpt-realtime&temperature={TEMPERATURE}&voice={VOICE}",
        additional_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }
    ) as openai_ws:
        await initialize_session(openai_ws)

        # Connection specific state
        stream_sid = None
        latest_media_timestamp = 0
        last_assistant_item = None
        mark_queue = []
        response_start_timestamp_twilio = None
        
        async def receive_from_twilio():
            """Receive audio data from Twilio and send it to the OpenAI Realtime API."""
            nonlocal stream_sid, latest_media_timestamp
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    if data['event'] == 'media' and openai_ws.state.name == 'OPEN':
                        latest_media_timestamp = int(data['media']['timestamp'])
                        audio_append = {
                            "type": "input_audio_buffer.append",
                            "audio": data['media']['payload']
                        }
                        await openai_ws.send(json.dumps(audio_append))
                    elif data['event'] == 'start':
                        stream_sid = data['start']['streamSid']
                        print(f"Incoming stream has started {stream_sid}")
                        response_start_timestamp_twilio = None
                        latest_media_timestamp = 0
                        last_assistant_item = None
                    elif data['event'] == 'mark':
                        if mark_queue:
                            mark_queue.pop(0)
            except WebSocketDisconnect:
                print("Client disconnected.")
                if openai_ws.state.name == 'OPEN':
                    await openai_ws.close()

        async def send_to_twilio():
            """Receive events from the OpenAI Realtime API, send audio back to Twilio."""
            nonlocal stream_sid, last_assistant_item, response_start_timestamp_twilio
            try:
                async for openai_message in openai_ws:
                    response = json.loads(openai_message)
                    if response['type'] in LOG_EVENT_TYPES:
                        print(f"Received event: {response['type']}", response)

                    # Handle tool calls for weather functionality
                    if response.get('type') == 'tool_calls.delta' and response.get('tool_calls'):
                        for tool_call in response['tool_calls']:
                            if tool_call.get('function', {}).get('name') == 'get_weather':
                                city = tool_call['function']['arguments'].get('city', '')
                                if city:
                                    print(f"Weather tool call for city: {city}")
                                    weather_result = await get_weather(city)
                                    
                                    # Send tool result back to OpenAI
                                    tool_result = {
                                        "type": "tool_result",
                                        "tool_result": {
                                            "tool_call_id": tool_call.get('id', ''),
                                            "content": json.dumps(weather_result, ensure_ascii=False)
                                        }
                                    }
                                    await openai_ws.send(json.dumps(tool_result))

                    if response.get('type') == 'response.output_audio.delta' and 'delta' in response:
                        audio_payload = base64.b64encode(base64.b64decode(response['delta'])).decode('utf-8')
                        audio_delta = {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {
                                "payload": audio_payload
                            }
                        }
                        await websocket.send_json(audio_delta)


                        if response.get("item_id") and response["item_id"] != last_assistant_item:
                            response_start_timestamp_twilio = latest_media_timestamp
                            last_assistant_item = response["item_id"]
                            if SHOW_TIMING_MATH:
                                print(f"Setting start timestamp for new response: {response_start_timestamp_twilio}ms")

                        await send_mark(websocket, stream_sid)

                    # Trigger an interruption. Your use case might work better using `input_audio_buffer.speech_stopped`, or combining the two.
                    if response.get('type') == 'input_audio_buffer.speech_started':
                        print("Speech started detected.")
                        if last_assistant_item:
                            print(f"Interrupting response with id: {last_assistant_item}")
                            await handle_speech_started_event()
            except Exception as e:
                print(f"Error in send_to_twilio: {e}")

        async def handle_speech_started_event():
            """Handle interruption when the caller's speech starts."""
            nonlocal response_start_timestamp_twilio, last_assistant_item
            print("Handling speech started event.")
            if mark_queue and response_start_timestamp_twilio is not None:
                elapsed_time = latest_media_timestamp - response_start_timestamp_twilio
                if SHOW_TIMING_MATH:
                    print(f"Calculating elapsed time for truncation: {latest_media_timestamp} - {response_start_timestamp_twilio} = {elapsed_time}ms")

                if last_assistant_item:
                    if SHOW_TIMING_MATH:
                        print(f"Truncating item with ID: {last_assistant_item}, Truncated at: {elapsed_time}ms")

                    truncate_event = {
                        "type": "conversation.item.truncate",
                        "item_id": last_assistant_item,
                        "content_index": 0,
                        "audio_end_ms": elapsed_time
                    }
                    await openai_ws.send(json.dumps(truncate_event))

                await websocket.send_json({
                    "event": "clear",
                    "streamSid": stream_sid
                })

                mark_queue.clear()
                last_assistant_item = None
                response_start_timestamp_twilio = None

        async def send_mark(connection, stream_sid):
            if stream_sid:
                mark_event = {
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": "responsePart"}
                }
                await connection.send_json(mark_event)
                mark_queue.append('responsePart')

        await asyncio.gather(receive_from_twilio(), send_to_twilio())

async def send_initial_conversation_item(openai_ws):
    """Send initial conversation item if AI talks first."""
    initial_conversation_item = {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "Buenas Quisiera saber en que pudiera ayudarle'"
                }
            ]
        }
    }
    await openai_ws.send(json.dumps(initial_conversation_item))
    await openai_ws.send(json.dumps({"type": "response.create"}))


async def get_weather(city: str) -> dict:
    """Get weather information for a specific city using OpenWeatherMap API."""
    if not OPENWEATHER_API_KEY:
        return {"error": "Weather API key not configured"}
    
    try:
        async with httpx.AsyncClient() as client:
            # OpenWeatherMap API endpoint
            url = f"http://api.openweathermap.org/data/2.5/weather"
            params = {
                "q": city,
                "appid": OPENWEATHER_API_KEY,
                "units": "metric",  # Use Celsius
                "lang": "es"  # Spanish language
            }
            
            response = await client.get(url, params=params)
            response.raise_for_status()
            
            weather_data = response.json()
            
            # Extract relevant information
            weather_info = {
                "city": weather_data["name"],
                "country": weather_data["sys"]["country"],
                "temperature": round(weather_data["main"]["temp"]),
                "feels_like": round(weather_data["main"]["feels_like"]),
                "humidity": weather_data["main"]["humidity"],
                "description": weather_data["weather"][0]["description"],
                "wind_speed": round(weather_data["wind"]["speed"] * 3.6),  # Convert m/s to km/h
                "pressure": weather_data["main"]["pressure"]
            }
            
            return weather_info
            
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"Ciudad '{city}' no encontrada"}
        elif e.response.status_code == 401:
            return {"error": "API key inválida para OpenWeatherMap"}
        else:
            return {"error": f"Error HTTP: {e.response.status_code}"}
    except Exception as e:
        return {"error": f"Error al consultar el clima: {str(e)}"}

async def initialize_session(openai_ws):
    """Control initial session with OpenAI."""
    session_update = {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": "gpt-realtime",
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcmu"},
                    "turn_detection": {"type": "server_vad"}
                },
                "output": {
                    "format": {"type": "audio/pcmu"}
                }
            },
            "instructions": SYSTEM_MESSAGE,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get current weather information for a specific city",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "city": {
                                    "type": "string",
                                    "description": "The name of the city to get weather for"
                                }
                            },
                            "required": ["city"]
                        }
                    }
                }
            ]
        }
    }
    print('Sending session update:', json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))

    # Uncomment the next line to have the AI speak first
    # await send_initial_conversation_item(openai_ws)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
