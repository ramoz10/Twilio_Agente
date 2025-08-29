# Configuración de Funcionalidad del Clima

## Requisitos

Para usar la funcionalidad del clima, necesitas configurar las siguientes API keys:

### 1. OpenAI API Key
- Ve a [https://platform.openai.com/api-keys](https://platform.openai.com/api-keys)
- Crea una nueva API key
- Asegúrate de tener acceso a la API Realtime

### 2. OpenWeatherMap API Key
- Ve a [https://home.openweathermap.org/api_keys](https://home.openweathermap.org/api_keys)
- Regístrate para obtener una cuenta gratuita
- Genera tu API key

## Configuración

Crea un archivo `.env` en la raíz del proyecto con el siguiente contenido:

```bash
# OpenAI API Key (requerido para el LLM)
OPENAI_API_KEY=tu_openai_api_key_aqui

# OpenWeatherMap API Key (requerido para consultas del clima)
OPENWEATHER_API_KEY=tu_openweather_api_key_aqui

# Puerto del servidor
PORT=5050

# Temperatura del LLM
TEMPERATURE=0.8
```

## Uso

### 1. Iniciar el servidor
```bash
python main.py
```

### 2. Probar la funcionalidad del clima
- Endpoint de prueba: `GET /weather/{ciudad}`
- Ejemplo: `http://localhost:5050/weather/Madrid`

### 3. Llamar por teléfono
- Llama al número de Twilio configurado
- Pregunta sobre el clima de cualquier ciudad
- El asistente consultará la API del clima y te responderá

## Funcionalidades

- ✅ Consulta del clima en tiempo real
- ✅ Temperatura en Celsius
- ✅ Descripción del clima en español
- ✅ Velocidad del viento en km/h
- ✅ Humedad y presión atmosférica
- ✅ Manejo de errores para ciudades no encontradas

## Ejemplo de uso

Usuario: "¿Cómo está el clima en Barcelona?"
Asistente: "Te consulto el clima de Barcelona... En Barcelona, España, la temperatura actual es de 22°C, se siente como 24°C. El clima está parcialmente nublado con una humedad del 65%. El viento sopla a 15 km/h desde el noreste."
