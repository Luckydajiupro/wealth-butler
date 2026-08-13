import logging
import os
import shutil
import subprocess
from typing import Optional
from functools import partial
from gradio_client import Client, handle_file
import httpx

from Base.Config.setting import settings

logger = logging.getLogger(__name__)


class TtsClient:
    """
    基于 Gradio Client 封装的 TTS 客户端，调用远程语音合成服务。
    支持 HLS 流媒体（.m3u8）自动转为 WAV 文件。
    """

    def __init__(
        self,
        server_url: Optional[str] = None,
    ):
        tts_conf = settings.tts.model_dump()
        self.server_url = server_url or tts_conf["server_url"]
        self._client = Client(self.server_url)
        logger.info(f"TtsClient 已初始化，连接到 {self.server_url}")

    def _intercept_download_file(self, original_method, x):
        """Intercept file download to capture stream URL for HLS files."""
        if isinstance(x, dict) and x.get("is_stream") and "url" in x:
            self._hls_m3u8_url = x["url"]
        return original_method(x)

    def synthesize(
        self,
        text: str,
        mode: str = "预训练音色",
        voice: str = "中文女",
        prompt_text: str = "",
        prompt_wav_path: Optional[str] = None,
        instruct_text: str = "",
        seed: int = 0,
        stream: bool = False,
        speed: float = 1.0,
        output_path: Optional[str] = None,
    ) -> str:
        """
        调用远程 TTS 服务合成语音，返回音频文件路径。
        """
        default_wav = (
            "https://github.com/gradio-app/gradio/raw/main/test/test_files/audio_sample.wav"
        )
        wav_source = handle_file(prompt_wav_path) if prompt_wav_path else handle_file(default_wav)

        # Monkey-patch the Endpoint's _download_file to capture HLS stream URL
        self._hls_m3u8_url = None
        original_methods = []
        for ep in self._client.endpoints.values():
            if hasattr(ep, "_download_file"):
                orig = ep._download_file
                original_methods.append((ep, orig))
                ep._download_file = partial(self._intercept_download_file, orig)

        try:
            result = self._client.predict(
                tts_text=text,
                mode_checkbox_group=mode,
                sft_dropdown=voice,
                prompt_text=prompt_text,
                prompt_wav_upload=wav_source,
                prompt_wav_record=wav_source,
                instruct_text=instruct_text,
                seed=seed,
                stream=stream,
                speed=speed,
                api_name="/generate_audio",
            )
        finally:
            # Restore original methods
            for ep, orig in original_methods:
                ep._download_file = orig

        logger.debug(f"TTS predict 返回结果类型: {type(result)}, 值: {result}")
        if self._hls_m3u8_url:
            logger.debug(f"HLS m3u8 URL: {self._hls_m3u8_url}")

        local_path = self._extract_path(result)
        if not local_path:
            logger.error(f"无法从 TTS 结果中提取文件路径: {result}")
            return None

        # 处理 HLS 流媒体或修正音频文件格式
        local_path = self._normalize_audio_file(local_path)
        if not local_path:
            return None

        if output_path and local_path:
            shutil.move(local_path, output_path)
            local_path = output_path

        logger.info(f"TTS 合成完成，音频路径: {local_path}")
        return local_path

    def _extract_path(self, result) -> Optional[str]:
        """从 Gradio API 返回结果中提取文件路径。"""
        if hasattr(result, "path"):
            return result.path
        if isinstance(result, (list, tuple)):
            for item in result:
                if isinstance(item, str) and os.path.exists(item):
                    return item
                if hasattr(item, "path") and item.path:
                    return item.path
            if result:
                return str(result[0])
        if isinstance(result, dict):
            return result.get("path") or result.get("value") or result.get("url")
        if isinstance(result, str):
            return result
        return None

    def _normalize_audio_file(self, path: str) -> Optional[str]:
        """
        确保音频文件可播放：
        1. 如果是 HLS (.m3u8) 流，先下载分段再转 WAV
        2. 否则检测实际格式并修正扩展名
        """
        if not path or not os.path.exists(path):
            return None

        file_size = os.path.getsize(path)
        if file_size == 0:
            logger.error(f"TTS 生成的文件为空: {path}")
            return None

        ext = os.path.splitext(path)[1].lower()

        # HLS 流 → WAV 转换
        if ext == ".m3u8":
            return self._convert_hls_to_wav(path)

        # 检测实际音频格式（通过文件头 magic bytes）
        with open(path, "rb") as f:
            header = f.read(16)

        format_map = {
            b"RIFF": ".wav",
            b"OggS": ".ogg",
            b"fLaC": ".flac",
            b"\xff\xfb": ".mp3",
            b"\xff\xf3": ".mp3",
            b"\xff\xf2": ".mp3",
            b"ID3": ".mp3",
        }

        actual_ext = None
        for magic, ext_val in format_map.items():
            if header[:len(magic)] == magic:
                actual_ext = ext_val
                break

        current_ext = os.path.splitext(path)[1].lower()
        if actual_ext and current_ext != actual_ext:
            new_path = path.replace(current_ext, actual_ext) if current_ext else path + actual_ext
            shutil.move(path, new_path)
            logger.info(f"修正音频文件扩展名: {current_ext} → {actual_ext}")
            return new_path

        return path

    def _convert_hls_to_wav(self, m3u8_path: str) -> Optional[str]:
        """
        将 HLS (.m3u8) 转为 WAV。
        使用 Gradio Client 内部的 httpx 客户端下载 .aac 分段（携带 session cookie）。
        """
        with open(m3u8_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 提取相对路径的音频分段文件名
        aac_segment = None
        for line in content.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("http"):
                aac_segment = stripped
                break

        if not aac_segment:
            logger.error(f"未找到 HLS 分段文件: {content}")
            return None

        aac_local = m3u8_path.replace(".m3u8", ".aac")
        downloaded = False
        base_url = self.server_url.rstrip("/")

        # 使用 Gradio Client 的 session cookie 来下载分段文件
        cookies = getattr(self._client, "cookies", None)

        # 方式1: 如果捕获到了 HLS m3u8 URL，直接用相同路径替换分段文件名
        if self._hls_m3u8_url:
            m3u8_full_url = self._hls_m3u8_url
            segment_url = m3u8_full_url.replace("playlist.m3u8", aac_segment)
            try:
                resp = httpx.get(segment_url, timeout=60, follow_redirects=True, cookies=cookies)
                if resp.status_code == 200 and len(resp.content) > 100:
                    with open(aac_local, "wb") as f:
                        f.write(resp.content)
                    downloaded = True
                    logger.info(f"下载分段成功 via segment URL: {aac_local} ({len(resp.content)} bytes)")
            except Exception as e:
                logger.debug(f"Segment URL 异常: {e}")

        # 方式2: /file= 端点
        if not downloaded:
            for path_suffix in [f"/file={aac_segment}", f"/gradio_api/file={aac_segment}"]:
                if downloaded:
                    break
                try:
                    url = base_url + path_suffix
                    resp = httpx.get(url, timeout=60, follow_redirects=True, cookies=cookies)
                    if resp.status_code == 200 and len(resp.content) > 100:
                        with open(aac_local, "wb") as f:
                            f.write(resp.content)
                        downloaded = True
                        logger.info(f"下载分段成功 via {url}: {aac_local} ({len(resp.content)} bytes)")
                except Exception as e:
                    logger.debug(f"URL {path_suffix} 异常: {e}")

        if not downloaded:
            logger.error(f"所有方式都无法下载分段文件: {aac_segment}")
            return None

        wav_path = m3u8_path.replace(".m3u8", ".wav")

        # 定位 ffmpeg
        configured_path = settings.ffmpeg.path or ""
        if os.path.isdir(configured_path):
            ffmpeg_path = os.path.join(configured_path, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        else:
            ffmpeg_path = shutil.which("ffmpeg") or "ffmpeg"

        cmd = [
            ffmpeg_path,
            "-y",
            "-i", aac_local,
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            wav_path,
        ]
        logger.info(f"转换 AAC → WAV: {' '.join(cmd)}")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0 and os.path.exists(wav_path):
                logger.info(f"AAC 转 WAV 成功: {wav_path}")
                for p in [m3u8_path, aac_local]:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
                return wav_path
            else:
                logger.error(f"ffmpeg 转换失败 (returncode={result.returncode}): stderr:\n{result.stderr}")
                return None
        except FileNotFoundError:
            logger.error("ffmpeg 未安装或不在 PATH 中")
            return None
        except Exception as e:
            logger.error(f"AAC 转 WAV 异常: {e}")
            return None

    def close(self):
        """Gradio Client 无显式关闭接口，占位保持接口一致性。"""
        logger.info("TtsClient 关闭（无实际连接需要关闭）")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


if __name__ == "__main__":
    with TtsClient() as client:
        path = client.synthesize(
            text="你好，欢迎使用语音合成服务。",
            output_path="tts_test_output.wav",
        )
        print(f"✅ 合成完成: {path}")
