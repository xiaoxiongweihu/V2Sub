"""OpenAI 兼容大模型翻译。

通过 openai SDK 的 base_url + api_key，兼容 OpenAI 官方及任意兼容服务
（DeepSeek / Moonshot / 智谱 / 本地 Ollama 等）。术语表注入到系统提示。
"""
from __future__ import annotations

from typing import Callable

try:
    from openai import OpenAI
    _OPENAI_OK = True
except Exception:
    OpenAI = None  # type: ignore
    _OPENAI_OK = False


class Translator:
    def __init__(self,
                 base_url: str = "https://api.openai.com/v1",
                 api_key: str = "",
                 model: str = "gpt-4o-mini",
                 target_language: str = "中文",
                 temperature: float = 0.3,
                 timeout: float = 30.0) -> None:
        if not _OPENAI_OK:
            raise RuntimeError(
                "openai 未安装，请 `pip install openai`。"
            )
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.target_language = target_language
        self.temperature = temperature
        self.timeout = timeout

    def update(self, **kwargs) -> None:
        """更新配置（base_url/api_key/model/target_language/temperature）。"""
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def _build_client(self):
        return OpenAI(base_url=self.base_url, api_key=self.api_key,
                      timeout=self.timeout)

    def _build_system_prompt(self, glossary_hint: str) -> str:
        prompt = (
            f"You are a professional real-time subtitle translator. "
            f"Translate the user's text into {self.target_language}. "
            f"Rules:\n"
            f"1. Output ONLY the translation, no explanations, no quotes.\n"
            f"2. Keep it natural and concise, suitable for live subtitles.\n"
            f"3. Preserve numbers, names, and code identifiers.\n"
        )
        if glossary_hint:
            prompt += (
                f"4. Use this glossary consistently (term=translation):\n"
                f"{glossary_hint}\n"
            )
        return prompt

    def translate(self, text: str,
                  glossary_hint: str = "",
                  on_error: Callable[[str], None] | None = None) -> str:
        """翻译文本。失败时返回原文并调用 on_error。"""
        text = (text or "").strip()
        if not text:
            return ""
        if not self.api_key:
            if on_error:
                on_error("未配置 API Key")
            return text
        try:
            client = self._build_client()
            resp = client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=[
                    {"role": "system",
                     "content": self._build_system_prompt(glossary_hint)},
                    {"role": "user", "content": text},
                ],
            )
            out = resp.choices[0].message.content
            return (out or "").strip()
        except Exception as e:
            if on_error:
                on_error(f"翻译失败: {e}")
            return text  # 失败时降级显示原文

    def test_connection(self) -> tuple[bool, str]:
        """测试 API 连通性，返回 (ok, message)。"""
        if not self.api_key:
            return False, "未配置 API Key"
        try:
            client = self._build_client()
            resp = client.chat.completions.create(
                model=self.model,
                max_tokens=8,
                messages=[{"role": "user", "content": "Hi"}],
            )
            return True, f"连接成功，模型: {self.model}"
        except Exception as e:
            return False, f"连接失败: {e}"
