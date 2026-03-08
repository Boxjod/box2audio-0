"""BoxAudio-0: 一二布布语音包合成工具

基于 F5-TTS 的 AI 语音合成工具，支持一二 (yier) 和布布 (bubu) 两个角色。
输入文字 → 选择角色 → 生成角色语音。

Usage:
    python app.py
"""

import logging
import os
import shutil
import subprocess
import threading
import uuid
from datetime import datetime

import gradio as gr

# ---------------------------------------------------------------------------
# Patch torchaudio.load — newer torchaudio (2.10+) requires torchcodec for
# audio loading, which needs system ffmpeg shared libraries. We add a
# soundfile fallback so it works everywhere without torchcodec.
# ---------------------------------------------------------------------------
def _patch_torchaudio():
    """Monkey-patch torchaudio.load to fall back to soundfile when torchcodec is unavailable."""
    import torchaudio
    _orig_load = torchaudio.load

    def _patched_load(uri, *args, **kwargs):
        try:
            return _orig_load(uri, *args, **kwargs)
        except (ImportError, RuntimeError):
            import numpy as np
            import soundfile as sf
            import torch
            data, samplerate = sf.read(uri, dtype="float32")
            waveform = torch.from_numpy(data)
            if waveform.ndim == 1:
                waveform = waveform.unsqueeze(0)
            else:
                waveform = waveform.t()
            frame_offset = kwargs.get("frame_offset", 0)
            num_frames = kwargs.get("num_frames", -1)
            channels_first = kwargs.get("channels_first", True)
            if frame_offset > 0:
                waveform = waveform[:, frame_offset:]
            if num_frames > 0:
                waveform = waveform[:, :num_frames]
            if not channels_first:
                waveform = waveform.t()
            return waveform, samplerate

    torchaudio.load = _patched_load

_patch_torchaudio()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("boxaudio")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets", "audio")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Preset voices — (ref_audio_path, ref_text)
# ---------------------------------------------------------------------------
PRESET_VOICES = {
    "bubu": (
        os.path.join(ASSETS_DIR, "bubu_self_introduction.wav"),
        "大家好，我叫布布，上个视频，第二宝做了自我介绍，"
        "我也给大家做个自我介绍吧。",
    ),
    "yier": (
        os.path.join(ASSETS_DIR, "yier_self_introduction.wav"),
        "大家好，我叫一二。听说大家都在问我，为什么叫一二？"
        "下面我来介绍一下我的来历吧。",
    ),
}

# Display name mapping for the Gradio radio
VOICE_LABELS = {"布布 (bubu)": "bubu", "一二 (yier)": "yier", "自定义 (custom)": "custom"}

# ---------------------------------------------------------------------------
# Number-to-Chinese mapping (F5-TTS doesn't handle Arabic digits well)
# ---------------------------------------------------------------------------
_DIGIT_TO_CHINESE = str.maketrans("0123456789", "零一二三四五六七八九")

# ---------------------------------------------------------------------------
# ffmpeg helpers
# ---------------------------------------------------------------------------
FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_BIN = shutil.which("ffprobe") or "ffprobe"


def _run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess:
    """Run ffmpeg command. Raises RuntimeError on failure."""
    cmd = [FFMPEG_BIN] + args
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")[-1000:]
        logger.error("ffmpeg failed (code %d): %s", result.returncode, stderr)
        raise RuntimeError(f"ffmpeg exit code {result.returncode}: {stderr}")
    return result


def _generate_output_path(ext: str = ".wav") -> str:
    """Generate a unique output file path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:8]
    return os.path.join(OUTPUTS_DIR, f"{timestamp}_{uid}{ext}")


def trim_silence(file_path: str, threshold_db: int = -40) -> str:
    """Remove leading and trailing silence from an audio file in-place.

    Uses ffmpeg silenceremove filter. Returns the same file path.
    """
    tmp_path = os.path.splitext(file_path)[0] + "_notrim.wav"
    try:
        os.rename(file_path, tmp_path)
        af = (
            f"silenceremove=start_periods=1:start_duration=0:start_threshold={threshold_db}dB,"
            f"areverse,"
            f"silenceremove=start_periods=1:start_duration=0:start_threshold={threshold_db}dB,"
            f"areverse"
        )
        _run_ffmpeg([
            "-i", tmp_path,
            "-af", af,
            "-ar", "24000", "-ac", "1",
            "-y", file_path,
        ])
        logger.info("Trimmed silence from %s", file_path)
    except Exception:
        if os.path.isfile(tmp_path) and not os.path.isfile(file_path):
            os.rename(tmp_path, file_path)
        logger.warning("Silence trimming failed for %s, keeping original", file_path, exc_info=True)
    finally:
        try:
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
    return file_path


def _get_audio_duration(path: str) -> float:
    """Get audio duration in seconds using ffprobe. Returns 0.0 on failure."""
    try:
        cmd = [
            FFPROBE_BIN,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        logger.warning("Failed to get duration for %s", path, exc_info=True)
    return 0.0


def _prepare_custom_audio(path: str) -> str:
    """Validate, convert, and optionally trim custom reference audio.

    Steps:
        1. Check file exists
        2. Convert to 24kHz mono WAV
        3. Verify duration >= 0.5s
        4. If duration > 10s, trim to first 10s

    Returns:
        Path to the processed WAV file.

    Raises:
        ValueError: If the file is missing or too short.
    """
    if not path or not os.path.isfile(path):
        raise ValueError("参考音频文件不存在")

    # Convert to standard WAV (24kHz mono)
    converted_path = _generate_output_path("_ref.wav")
    _run_ffmpeg([
        "-i", path,
        "-ar", "24000", "-ac", "1",
        "-y", converted_path,
    ])

    # Check duration
    duration = _get_audio_duration(converted_path)
    if duration < 0.5:
        try:
            os.remove(converted_path)
        except OSError:
            pass
        raise ValueError(f"参考音频太短（{duration:.1f}秒），至少需要 0.5 秒")

    # Trim to 10s if too long
    if duration > 10.0:
        trimmed_path = _generate_output_path("_ref_trimmed.wav")
        _run_ffmpeg([
            "-i", converted_path,
            "-t", "10",
            "-ar", "24000", "-ac", "1",
            "-y", trimmed_path,
        ])
        try:
            os.remove(converted_path)
        except OSError:
            pass
        logger.info("Trimmed custom audio from %.1fs to 10s: %s", duration, trimmed_path)
        return trimmed_path

    return converted_path


# ---------------------------------------------------------------------------
# F5-TTS Engine (singleton)
# ---------------------------------------------------------------------------
_engine_instance = None
_engine_lock = threading.Lock()


class F5TTSEngine:
    """Wrapper around F5-TTS for speech synthesis."""

    def __init__(self):
        from f5_tts.api import F5TTS

        vocoder_path = self._find_cached_vocos()
        logger.info("[F5Engine] Initializing model (vocoder_local_path=%s)", vocoder_path)
        self.model = F5TTS(vocoder_local_path=vocoder_path)
        logger.info("[F5Engine] Model loaded successfully")

    @staticmethod
    def _find_cached_vocos():
        """Find locally cached Vocos model to skip redundant download log."""
        try:
            from huggingface_hub import snapshot_download
            return snapshot_download("charactr/vocos-mel-24khz", local_files_only=True)
        except Exception:
            return None

    def synthesize(
        self,
        text: str,
        ref_audio: str,
        ref_text: str = "",
        speed: float = 1.0,
    ) -> str:
        """Synthesize speech and return the output WAV file path."""
        # Pre-process: convert digits to Chinese
        text = text.translate(_DIGIT_TO_CHINESE)

        output_path = _generate_output_path(".wav")
        logger.info(
            "[F5Engine] synthesize: text=%r, ref_audio=%s, speed=%.1f",
            text[:50], ref_audio, speed,
        )

        wav, sr, _ = self.model.infer(
            ref_file=ref_audio,
            ref_text=ref_text,
            gen_text=text,
            speed=speed,
            file_wave=output_path,
        )

        logger.info(
            "[F5Engine] Output: %s (size=%d bytes)",
            output_path,
            os.path.getsize(output_path) if os.path.exists(output_path) else 0,
        )

        # Remove leading/trailing silence
        trim_silence(output_path)

        return output_path


def get_engine() -> F5TTSEngine:
    """Get or create the singleton TTS engine (thread-safe)."""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = F5TTSEngine()
    return _engine_instance


# ---------------------------------------------------------------------------
# Gradio Web UI
# ---------------------------------------------------------------------------

def synthesize_voice(text: str, voice_label: str, speed: float, custom_audio=None, custom_ref_text: str = ""):
    """Gradio callback: synthesize speech from text."""
    if not text or not text.strip():
        gr.Warning("请输入要合成的文字")
        return None, None

    if len(text) > 500:
        gr.Warning("文本长度不能超过 500 字")
        return None, None

    voice_key = VOICE_LABELS.get(voice_label, "bubu")

    if voice_key == "custom":
        # Custom voice branch
        if not custom_audio:
            gr.Warning("请上传参考音频")
            return None, None
        if not custom_ref_text or not custom_ref_text.strip():
            gr.Warning("请输入参考音频中说的话")
            return None, None
        try:
            ref_audio = _prepare_custom_audio(custom_audio)
        except ValueError as e:
            gr.Warning(str(e))
            return None, None
        ref_text = custom_ref_text.strip()
    else:
        # Preset voice branch
        ref_audio, ref_text = PRESET_VOICES[voice_key]
        if not os.path.isfile(ref_audio):
            gr.Warning(f"参考音频文件不存在: {ref_audio}")
            return None, None

    try:
        engine = get_engine()
        output_path = engine.synthesize(text, ref_audio, ref_text, speed)
        return output_path, output_path
    except Exception as e:
        logger.error("Synthesis failed: %s", e, exc_info=True)
        gr.Warning(f"合成出错: {e}")
        return None, None


def build_ui() -> gr.Blocks:
    """Build the Gradio Blocks UI."""
    with gr.Blocks(
        title="BoxAudio-0: 一二布布语音包合成工具",
    ) as demo:
        gr.Markdown(
            "# BoxAudio-0: 一二布布语音包合成工具\n"
            "输入文字，选择角色，一键生成 AI 语音。\n"
            "基于 [F5-TTS](https://github.com/SWivid/F5-TTS) 开源模型。"
        )

        with gr.Row():
            with gr.Column(scale=1):
                text_input = gr.Textbox(
                    label="输入文字",
                    placeholder="请输入要合成的文字（最多 500 字）...",
                    lines=5,
                    max_lines=10,
                )
                voice_radio = gr.Radio(
                    choices=list(VOICE_LABELS.keys()),
                    value="布布 (bubu)",
                    label="选择角色",
                )
                custom_audio = gr.Audio(
                    label="上传参考音频（5-15秒）",
                    sources=["upload", "microphone"],
                    visible=False,
                )
                custom_ref_text = gr.Textbox(
                    label="参考音频文字",
                    placeholder="请输入参考音频中说的话...",
                    visible=False,
                )
                speed_slider = gr.Slider(
                    minimum=0.3,
                    maximum=2.0,
                    value=1.0,
                    step=0.1,
                    label="语速",
                )
                gen_btn = gr.Button("生成语音", variant="primary", size="lg")

            with gr.Column(scale=1):
                audio_output = gr.Audio(label="合成结果", type="filepath")
                download_output = gr.File(label="下载音频")

        def _toggle_custom(voice_label):
            is_custom = VOICE_LABELS.get(voice_label) == "custom"
            return gr.update(visible=is_custom), gr.update(visible=is_custom)

        voice_radio.change(
            fn=_toggle_custom,
            inputs=[voice_radio],
            outputs=[custom_audio, custom_ref_text],
        )

        gen_btn.click(
            fn=synthesize_voice,
            inputs=[text_input, voice_radio, speed_slider, custom_audio, custom_ref_text],
            outputs=[audio_output, download_output],
        )

    return demo


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting BoxAudio-0 ...")
    logger.info("Output directory: %s", OUTPUTS_DIR)
    for name, (path, _) in PRESET_VOICES.items():
        logger.info("Voice [%s]: %s (exists=%s)", name, path, os.path.exists(path))

    demo = build_ui()
    demo.launch(server_name="0.0.0.0", server_port=7860, theme=gr.themes.Soft())
