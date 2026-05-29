# import os
# import io
# import json
# import base64
# from google import genai
# from google.genai import types
# from settings_routes import get_model_for_process, get_api_key

# def call_llm(process_name, prompt, system_instruction=None, image_bytes=None, response_mime_type="application/json"):
#     # Unified caller for different LLM providers
#     model_config = get_model_for_process(process_name)
#     if ":" not in model_config:
#         provider = "google"
#         model_id = model_config
#     else:
#         provider, model_id = model_config.split(":", 1)

#     provider_key_map = {
#             "google": "gemini",
#             "openai": "openai",
#             "anthropic": "anthropic"
#         }
#     api_key = get_api_key(provider_key_map.get(provider, provider))

#     # api_key = get_api_key(provider)
#     if not api_key:
#         raise ValueError(f"No API key configured for provider: {provider}")

#     if provider == "google":
#         return call_gemini(model_id, api_key, prompt, system_instruction, image_bytes, response_mime_type)
#     elif provider == "openai":
#         return call_openai(model_id, api_key, prompt, system_instruction, image_bytes, response_mime_type)
#     elif provider == "anthropic":
#         return call_anthropic(model_id, api_key, prompt, system_instruction, image_bytes, response_mime_type)
#     else:
#         raise ValueError(f"Unsupported provider: {provider}")

# def call_gemini(model_id, api_key, prompt, system_instruction, image_bytes, response_mime_type):
#     client = genai.Client(api_key=api_key)
    
#     contents = []
#     if image_bytes:
#         contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
#     contents.append(types.Part.from_text(text=prompt))

#     config = types.GenerateContentConfig(
#         response_mime_type=response_mime_type,
#         temperature=0.0
#     )
#     if system_instruction:
#         config.system_instruction = system_instruction

#     response = client.models.generate_content(
#         model=model_id,
#         contents=contents,
#         config=config
#     )
#     return response.text.strip()

# def call_openai(model_id, api_key, prompt, system_instruction, image_bytes, response_mime_type):
#     try:
#         from openai import OpenAI
#     except ImportError:
#         raise ImportError("OpenAI library not installed. Run 'pip install openai'")
        
#     client = OpenAI(api_key=api_key)
    
#     messages = []
#     if system_instruction:
#         messages.append({"role": "system", "content": system_instruction})
    
#     content = [{"type": "text", "text": prompt}]
#     if image_bytes:
#         base64_image = base64.b64encode(image_bytes).decode('utf-8')
#         content.append({
#             "type": "image_url",
#             "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
#         })
    
#     messages.append({"role": "user", "content": content})

#     response = client.chat.completions.create(
#         model=model_id,
#         messages=messages,
#         response_format={"type": "json_object"} if response_mime_type == "application/json" else None,
#         temperature=0.0
#     )
#     return response.choices[0].message.content.strip()

# def call_anthropic(model_id, api_key, prompt, system_instruction, image_bytes, response_mime_type):
#     try:
#         import anthropic
#     except ImportError:
#         raise ImportError("Anthropic library not installed. Run 'pip install anthropic'")
        
#     client = anthropic.Anthropic(api_key=api_key)
    
#     messages = []
#     content = []
    
#     if image_bytes:
#         base64_image = base64.b64encode(image_bytes).decode('utf-8')
#         content.append({
#             "type": "image",
#             "source": {
#                 "type": "base64",
#                 "media_type": "image/jpeg",
#                 "data": base64_image
#             }
#         })
    
#     content.append({"type": "text", "text": prompt})
#     messages.append({"role": "user", "content": content})

#     response = client.messages.create(
#         model=model_id,
#         max_tokens=4096,
#         system=system_instruction if system_instruction else "",
#         messages=messages,
#         temperature=0.0
#     )
#     return response.content[0].text.strip()

import os
import io
import re
import json
import base64
from google import genai
from google.genai import types
from settings_routes import get_model_for_process, get_api_key


def detect_media_type(image_bytes):
    """Detect the actual image media type from raw bytes without external libraries."""
    if not image_bytes:
        return 'image/png'
    if image_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if image_bytes.startswith(b'\xff\xd8'):
        return 'image/jpeg'
    if image_bytes.startswith(b'GIF87a') or image_bytes.startswith(b'GIF89a'):
        return 'image/gif'
    if image_bytes.startswith(b'RIFF') and b'WEBP' in image_bytes[8:16]:
        return 'image/webp'
    return 'image/png'  # Default fallback


def call_llm(process_name, prompt, system_instruction=None, image_bytes=None, response_mime_type="application/json"):
    # Unified caller for different LLM providers
    model_config = get_model_for_process(process_name)
    if ":" not in model_config:
        provider = "google"
        model_id = model_config
    else:
        provider, model_id = model_config.split(":", 1)

    provider_key_map = {
        "google": "gemini",
        "openai": "openai",
        "anthropic": "anthropic"
    }
    api_key = get_api_key(provider_key_map.get(provider, provider))

    if not api_key:
        raise ValueError(f"No API key configured for provider: {provider}. Please set it in the Settings -> AI Models tab.")

    # Detect media type once here, pass it to all providers
    media_type = detect_media_type(image_bytes) if image_bytes else "image/png"

    print(f"\n>>> [LLM CALL START] Provider: {provider}, Model: {model_id}, Process: {process_name} <<<", flush=True)
    print(f"    [INFO] Prompt size: {len(prompt)} chars", flush=True)
    if system_instruction: print(f"    [INFO] System instruction size: {len(system_instruction)} chars", flush=True)
    if provider == "google":
        return call_gemini(model_id, api_key, prompt, system_instruction, image_bytes, media_type, response_mime_type)
    elif provider == "openai":
        return call_openai(model_id, api_key, prompt, system_instruction, image_bytes, media_type, response_mime_type)
    elif provider == "anthropic":
        return call_anthropic(model_id, api_key, prompt, system_instruction, image_bytes, media_type, response_mime_type)
    else:
        raise ValueError(f"Unsupported provider: {provider}")


def call_gemini(model_id, api_key, prompt, system_instruction, image_bytes, media_type, response_mime_type):
    client = genai.Client(api_key=api_key)

    contents = []
    if image_bytes:
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type=media_type))  # was hardcoded "image/jpeg"
    contents.append(types.Part.from_text(text=prompt))

    config_args = {"temperature": 0.0}
    if response_mime_type == "application/json":
        config_args["response_mime_type"] = "application/json"

    config = types.GenerateContentConfig(**config_args)
    if system_instruction:
        config.system_instruction = system_instruction

    print(f"   [GEMINI] Sending content to {model_id} (Image: {bool(image_bytes)})", flush=True)
    response = client.models.generate_content(
        model=model_id,
        contents=contents,
        config=config
    )
    result = response.text.strip()
    print(f"    [GEMINI] Response received ({len(result)} chars)", flush=True)
    print(f"    [DEBUG] Response preview: {result[:100]}...", flush=True)
    return result


def call_openai(model_id, api_key, prompt, system_instruction, image_bytes, media_type, response_mime_type):
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
            "image_url": {"url": f"data:{media_type};base64,{base64_image}"}  # was hardcoded "image/jpeg"
        })

    messages.append({"role": "user", "content": content})

    print(f"   [OPENAI] Sending content to {model_id} (Image: {bool(image_bytes)})", flush=True)
    response = client.chat.completions.create(
        model=model_id,
        messages=messages,
        response_format={"type": "json_object"} if response_mime_type == "application/json" else None,
        temperature=0.0
    )
    result = response.choices[0].message.content.strip()
    print(f"    [OPENAI] Response received ({len(result)} chars)", flush=True)
    print(f"    [DEBUG] Response preview: {result[:100]}...", flush=True)
    return result


def call_anthropic(model_id, api_key, prompt, system_instruction, image_bytes, media_type, response_mime_type):
    try:
        import anthropic
    except ImportError:
        raise ImportError("Anthropic library not installed. Run 'pip install anthropic'")

    client = anthropic.Anthropic(api_key=api_key)

    content = []
    if image_bytes:
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,  # was hardcoded "image/jpeg"
                "data": base64_image
            }
        })

    content.append({"type": "text", "text": prompt})

    # Ask Claude explicitly to return JSON when needed
    if response_mime_type == "application/json":
        content.append({"type": "text", "text": "Respond with valid JSON only. No markdown, no code fences, no explanation."})

    print(f"   [ANTHROPIC] Sending content to {model_id} (Image: {bool(image_bytes)})", flush=True)
    response = client.messages.create(
        model=model_id,
        max_tokens=4096,
        system=system_instruction if system_instruction else "",
        messages=[{"role": "user", "content": content}],
        temperature=0.0
    )
    raw = response.content[0].text.strip()
    print(f"    [ANTHROPIC] Response received ({len(raw)} chars)", flush=True)
    print(f"    [DEBUG] Response preview: {raw[:100]}...", flush=True)

    # Strip markdown code fences if Claude wrapped the JSON anyway
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw.strip())

    return raw.strip()