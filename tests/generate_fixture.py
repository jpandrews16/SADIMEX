#!/usr/bin/env python3
"""
tests/generate_fixture.py — Generador de Audio de Prueba
=========================================================
Crea un archivo de audio sintético WAV con texto hablado simulado
para probar la pipeline sin necesidad de un audio de campo real.

Usa gTTS (Google Text-to-Speech) si está disponible, o genera
un WAV silencioso de relleno como último recurso.

Uso:
    python3 tests/generate_fixture.py
    # Genera: tests/fixtures/sample_visit.wav
"""

import struct
import wave
import math
import os
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH = FIXTURES_DIR / "sample_visit.wav"

# Transcripción simulada de una visita de campo boliviana
SIMULATED_TRANSCRIPT = """
Vendedor: Buenos días caserita, soy Juan de Sadimex, ¿cómo le va hoy?
Cliente: Bien nomás, ¿qué me trae?
Vendedor: Le traigo las novedades de Noel y Wild Protein. ¿Cómo está su stock de galletas Festival?
Cliente: Ya se me acabó, no hay caso, se venden rápido.
Vendedor: Perfecto, ¿le dejo dos cajas de Festival y una de Saltín? También tengo Wild Protein a precio especial esta semana.
Cliente: ¿Cuánto me sale todo?
Vendedor: Festival dos cajas a 45 bolivianos cada una, Saltín 40, y Wild Protein 35. En total 165 bolivianos.
Cliente: Ya pues, déjeme eso nomás.
Vendedor: ¡Excelente! Le anoto el pedido. ¿Le puedo visitar el próximo miércoles también?
Cliente: Sí, venga nomás.
Vendedor: Muchas gracias caserita, hasta el miércoles entonces.
"""


def generate_sine_wave_wav(output_path: Path, duration_sec: int = 5, sample_rate: int = 16000):
    """
    Genera un archivo WAV con una onda sinusoidal pura.
    Es un placeholder de audio — suficiente para probar la ingesta.
    Para prueba real de Gemini, usa un archivo .mp3/.wav de terreno.
    """
    num_samples = duration_sec * sample_rate
    frequency = 440.0  # Hz - tono La

    with wave.open(str(output_path), 'w') as wav_file:
        wav_file.setnchannels(1)    # mono
        wav_file.setsampwidth(2)    # 16-bit
        wav_file.setframerate(sample_rate)

        for i in range(num_samples):
            sample = int(32767 * 0.3 * math.sin(2 * math.pi * frequency * i / sample_rate))
            wav_file.writeframes(struct.pack('<h', sample))

    return output_path


def try_gtts(output_path: Path) -> bool:
    """
    Intenta generar audio real usando gTTS.
    Retorna True si exitoso, False si gTTS no está instalado.
    """
    try:
        from gtts import gTTS
        import tempfile

        print("📢 Usando gTTS para generar audio con texto hablado...")
        tts = gTTS(text=SIMULATED_TRANSCRIPT, lang='es', slow=False)

        # gTTS genera MP3, lo guardamos como fixture mp3
        mp3_path = output_path.with_suffix('.mp3')
        tts.save(str(mp3_path))
        print(f"✅ Audio MP3 con texto hablado generado: {mp3_path}")
        return True, mp3_path
    except ImportError:
        return False, None
    except Exception as e:
        print(f"⚠️  gTTS falló ({e}), usando WAV sintético como fallback")
        return False, None


def main():
    print("\n🎙️  Generando fixture de audio para pruebas SADIMEX...")
    print(f"   Destino: {OUTPUT_PATH}\n")

    # Intentar gTTS primero (audio con voz real en español)
    success, mp3_path = try_gtts(OUTPUT_PATH)

    if success and mp3_path:
        # Guardar también metadata de la transcripción
        transcript_path = FIXTURES_DIR / "sample_visit_transcript.txt"
        transcript_path.write_text(SIMULATED_TRANSCRIPT.strip())
        print(f"📝 Transcripción guardada en: {transcript_path}")
        print(f"\n✅ Usa este archivo para la prueba:")
        print(f"   python3 tools/ingest_audio.py --file {mp3_path} --vendedor_id test-vendedor-001 --ciudad LPZ --cliente_nombre 'Tienda Prueba'")
        return mp3_path
    else:
        # Fallback: WAV sintético (funciona para probar ingesta, no transcripción)
        wav_path = generate_sine_wave_wav(OUTPUT_PATH)
        print(f"✅ WAV sintético generado: {wav_path}")
        print(f"\n⚠️  NOTA: Este WAV es solo ruido sintético.")
        print(f"   Sirve para probar ingest_audio.py y transcribe_diarize.py (Gemini intentará transcribirlo).")
        print(f"   Para una prueba completa real, copia un .mp3 de campo a: {FIXTURES_DIR}/")
        print(f"\n   Usa este archivo:")
        print(f"   python3 tools/ingest_audio.py --file {wav_path} --vendedor_id test-vendedor-001 --ciudad LPZ --cliente_nombre 'Tienda Prueba'")
        return wav_path


if __name__ == "__main__":
    main()
