import os
import io
import json
import base64
from google import genai
from google.genai import types
from settings_routes import get_model_for_process, get_api_key

def call_llm(process_name, prompt, system_instruction=None, image_bytes=None, response_mime_type="application/json"):
    # Unified caller for different LLM providers
    model_config = get_model_for_process(process_name)
    if ":" not in model_config:
        provider = "google"
        model_id = model_config
    else:
        provider, model_id = model_config.split(":", 1)

    api_key = get_api_key(provider)
    if not api_key:
        raise ValueError(f"No API key configured for provider: {provider}")

    if provider == "google":
        return call_gemini(model_id, api_key, prompt, system_instruction, image_bytes, response_mime_type)
    elif provider == "openai":
        return call_openai(model_id, api_key, prompt, system_instruction, image_bytes, response_mime_type)
    elif provider == "anthropic":
        return call_anthropic(model_id, api_key, prompt, system_instruction, image_bytes, response_mime_type)
    else:
        raise ValueError(f"Unsupported provider: {provider}")

def call_gemini(model_id, api_key, prompt, system_instruction, image_bytes, response_mime_type):
    client = genai.Client(api_key=api_key)
    
    contents = []
    if image_bytes:
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
    contents.append(types.Part.from_text(text=prompt))

    config = types.GenerateContentConfig(
        response_mime_type=response_mime_type,
        temperature=0.0
    )
    if system_instruction:
        config.system_instruction = system_instruction

    response = client.models.generate_content(
        model=model_id,
        contents=contents,
        config=config
    )
    return response.text.strip()

def call_openai(model_id, api_key, prompt, system_instruction, image_bytes, response_mime_type):
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("OpenAI library not installed. Run 'pip install openai'")
        
    client = OpenAI(api_key=api_key)
    
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    
    content = [{"type": "text", "text": prompt}]
    if image_bytes:
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
        })
    
    messages.append({"role": "user", "content": content})

    response = client.chat.completions.create(
        model=model_id,
        messages=messages,
        response_format={"type": "json_object"} if response_mime_type == "application/json" else None,
        temperature=0.0
    )
    return response.choices[0].message.content.strip()

def call_anthropic(model_id, api_key, prompt, system_instruction, image_bytes, response_mime_type):
    try:
        import anthropic
    except ImportError:
        raise ImportError("Anthropic library not installed. Run 'pip install anthropic'")
        
    client = anthropic.Anthropic(api_key=api_key)
    
    messages = []
    content = []
    
    if image_bytes:
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64_image
            }
        })
    
    content.append({"type": "text", "text": prompt})
    messages.append({"role": "user", "content": content})

    response = client.messages.create(
        model=model_id,
        max_tokens=4096,
        system=system_instruction if system_instruction else "",
        messages=messages,
        temperature=0.0
    )
    return response.content[0].text.strip()
