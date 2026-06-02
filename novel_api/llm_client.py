"""
llm_client.py - 统一 LLM 调用客户端

支持异步调用 OpenAI-compatible API，带重试机制。
"""

from __future__ import annotations

import json
import time
import asyncio
import re
from typing import Optional, Dict, Any

from openai import AsyncOpenAI

from novel_api.models import ModelConfig


class LLMClient:
    """异步 LLM 调用客户端"""

    def __init__(self, config: ModelConfig, label: str = "模型"):
        self.label = label
        self.api_key = config.api_key
        self.base_url = config.base_url.rstrip("/")
        self.model_name = config.model_name
        self.temperature = config.temperature
        self.max_tokens = config.max_tokens
        self.retry_times = 1  # 仅调用一次，重试由外部 _call_llm_safe 处理

        # 创建异步客户端（600秒超时，本地模型生成万字章节可能需要10分钟以上）
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=600.0,
            max_retries=0,  # 由外部 retry 机制控制，不再叠加 SDK 内重试
        )

    async def call(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        调用 LLM 并返回文本结果

        Args:
            prompt: 用户提示
            system_prompt: 系统提示（可选）
            temperature: 温度（默认使用配置值）
            max_tokens: 最大 token 数（默认使用配置值）

        Returns:
            模型返回的文本
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        temp = temperature if temperature is not None else self.temperature
        # 如果 max_tokens 为 None 或 0，则不传递限制（让模型自由生成至自然结束）
        tokens = max_tokens if max_tokens is not None else self.max_tokens
        kwargs = dict(model=self.model_name, messages=messages, temperature=temp)
        if tokens and tokens > 0:
            kwargs["max_tokens"] = tokens

        try:
            response = await self.client.chat.completions.create(**kwargs)
            result = response.choices[0].message.content
            if not result:
                raise ValueError("API 返回空内容")
            return result

        except Exception as e:
            raise RuntimeError(f"[{self.label}] API 调用失败: {e}")

    @staticmethod
    def extract_json(text: str) -> Optional[Dict[str, Any]]:
        """从文本中提取 JSON 对象"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试从 ```json ``` 块中提取
        json_match = re.search(r'```(?:json)?\s*({[\s\S]*?})\s*```', text)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试从文本中提取第一个 { 到最后一个 }
        brace_match = re.search(r'({[\s\S]*})', text)
        if brace_match:
            try:
                return json.loads(brace_match.group(1))
            except json.JSONDecodeError:
                pass

        return None

    @staticmethod
    def extract_between_markers(text: str, marker: str) -> str:
        """提取两个 marker 之间的内容"""
        pattern = rf'={3,5}\s*{re.escape(marker)}\s*={3,5}([\s\S]*?)(?=\n={3,5}|$)'
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
        return text
