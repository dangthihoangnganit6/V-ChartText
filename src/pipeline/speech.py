"""Bước 4: chuẩn bị văn bản để đọc và tổng hợp giọng nói tiếng Việt.

  văn bản -> to_speech (số, đơn vị thành chữ) -> tách câu ngắn -> TTS
Engine:
  edge  : pip install edge-tts   (giọng Microsoft vi-VN-HoaiMyNeural / vi-VN-NamMinhNeural, cần Internet)
  gtts  : pip install gTTS       (Google Translate TTS, cần Internet, giọng kém tự nhiên hơn)
Không có Internet: demo web vẫn đọc được bằng Web Speech API của trình duyệt (giọng tiếng Việt tuỳ máy).
"""
import asyncio

from vn import sentences, to_speech

VOICES = {"nu": "vi-VN-HoaiMyNeural", "nam": "vi-VN-NamMinhNeural"}


def speech_text(text):
    """-> chuỗi đã đổi số thành chữ, mỗi câu ngắn một dòng (dễ ngắt nghỉ khi đọc)."""
    return "\n".join(to_speech(s) for s in sentences(text))


def synthesize(text, out_path, engine="edge", voice="nu", rate="-5%"):
    """Ghi file mp3. Trả về out_path. Lỗi mạng/thiếu thư viện -> RuntimeError (demo sẽ chuyển sang Web Speech)."""
    spoken = speech_text(text)
    try:
        if engine == "edge":
            import edge_tts

            async def _run():
                await edge_tts.Communicate(spoken, VOICES.get(voice, voice), rate=rate).save(str(out_path))
            asyncio.run(_run())
        elif engine == "gtts":
            from gtts import gTTS
            gTTS(spoken, lang="vi").save(str(out_path))
        else:
            raise ValueError(engine)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"TTS ({engine}) lỗi: {e}") from e
    return out_path
