"""
config_manager.py - 配置管理

管理4个大模型的独立配置，支持从 .env 读取默认值，
通过 config.json 持久化保存，前端可动态修改。
"""

from __future__ import annotations

import json
import os
from typing import Dict, Optional

from dotenv import load_dotenv
from novel_api.models import ModelConfig, PipelineConfig


# 默认配置
DEFAULT_MODEL_CONFIG = {
    "api_key": "",
    "base_url": "",
    "model_name": "",
    "temperature": 0.8,
    "max_tokens": 16384,
}

DEFAULT_PIPELINE_CONFIG = {
    "model_a": {"description": "大纲优化", **DEFAULT_MODEL_CONFIG},
    "model_b": {"description": "大纲优化辅助", **DEFAULT_MODEL_CONFIG},
    "model_c": {"description": "正文生成", **DEFAULT_MODEL_CONFIG},
    "model_d": {"description": "正文审核", **DEFAULT_MODEL_CONFIG},
    "model_e": {"description": "章节生成", **DEFAULT_MODEL_CONFIG},
    "model_f": {"description": "审核&优化", **DEFAULT_MODEL_CONFIG},
    "plot": "",
    "total_chapters": 10,
}


class ConfigManager:
    """配置管理器"""

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
        self.config_path = config_path

        # 加载 .env
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        load_dotenv(env_path)

        # 从 .env 读取默认值
        self._env_defaults = {
            "api_key": os.getenv("OPENAI_API_KEY", ""),
            "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "model_name": os.getenv("OPENAI_MODEL", "gpt-4o"),
        }

    def load(self) -> PipelineConfig:
        """加载配置"""
        config_dict = self._load_raw()

        # 构造 ModelConfig 对象
        def make_model_config(data: Dict) -> ModelConfig:
            # 优先级: config.json > .env  > 硬编码默认值
            hc_defaults = {"api_key": "", "base_url": "https://api.openai.com/v1",
                           "model_name": "gpt-4o", "temperature": 0.8, "max_tokens": 16384}

            fields = {}
            for key in ["api_key", "base_url", "model_name", "temperature", "max_tokens"]:
                # 检查 config.json 中是否明确设置了该字段
                if key in data and data[key]:
                    fields[key] = data[key]
                elif self._env_defaults.get(key):
                    fields[key] = self._env_defaults[key]
                else:
                    fields[key] = hc_defaults[key]

            return ModelConfig(
                api_key=fields["api_key"],
                base_url=fields["base_url"],
                model_name=fields["model_name"],
                temperature=float(fields["temperature"]),
                max_tokens=int(fields["max_tokens"]),
            )

        cfg = PipelineConfig(
            model_a=make_model_config(config_dict.get("model_a", {})),
            model_b=make_model_config(config_dict.get("model_b", {})),
            model_c=make_model_config(config_dict.get("model_c", {})),
            model_d=make_model_config(config_dict.get("model_d", {})),
            model_e=make_model_config(config_dict.get("model_e", {})),
            model_f=make_model_config(config_dict.get("model_f", {})),
            plot=config_dict.get("plot", ""),
            total_chapters=int(config_dict.get("total_chapters", 10)),
            min_words=int(config_dict.get("min_words", 3000)),
            chapter_gen_prompt=config_dict.get("chapter_gen_prompt", ""),
            chapter_review_prompt=config_dict.get("chapter_review_prompt", ""),
            content_gen_prompt=config_dict.get("content_gen_prompt", ""),
            review_optimize_prompt=config_dict.get("review_optimize_prompt", ""),
        )

        return cfg

    def save(self, config: PipelineConfig):
        """保存配置到 config.json"""
        config_dict = self._to_dict(config)
        self._write_raw(config_dict)

    def update_from_frontend(self, data: Dict) -> PipelineConfig:
        """从前端请求数据更新配置"""
        config_dict = self._load_raw()

        for key in ["plot", "total_chapters", "min_words", "chapter_gen_prompt", "chapter_review_prompt", "content_gen_prompt", "review_optimize_prompt"]:
            if key in data:
                config_dict[key] = data[key]

        for model_key in ["model_a", "model_b", "model_c", "model_d", "model_e", "model_f"]:
            if model_key in data:
                model_data = data[model_key]
                if model_key not in config_dict:
                    config_dict[model_key] = {}
                for k, v in model_data.items():
                    # 跳过掩码的 API key (包含 ****)
                    if k == "api_key" and v and "****" in v:
                        continue
                    # 空值表示重置为 .env 默认值 → 从 config_dict 中移除该键
                    if v is None or v == "":
                        config_dict[model_key].pop(k, None)
                    else:
                        config_dict[model_key][k] = v

        self._write_raw(config_dict)
        return self.load()

    def to_api_response(self, config: PipelineConfig) -> Dict:
        """转换为前端可用的配置（隐藏完整 api_key，只显示后4位）"""
        def mask_key(key: str) -> str:
            if not key or len(key) < 8:
                return ""
            return key[:4] + "****" + key[-4:]

        return {
            "model_a": {
                "api_key": mask_key(config.model_a.api_key),
                "base_url": config.model_a.base_url,
                "model_name": config.model_a.model_name,
                "temperature": config.model_a.temperature,
                "max_tokens": config.model_a.max_tokens,
            },
            "model_b": {
                "api_key": mask_key(config.model_b.api_key),
                "base_url": config.model_b.base_url,
                "model_name": config.model_b.model_name,
                "temperature": config.model_b.temperature,
                "max_tokens": config.model_b.max_tokens,
            },
            "model_c": {
                "api_key": mask_key(config.model_c.api_key),
                "base_url": config.model_c.base_url,
                "model_name": config.model_c.model_name,
                "temperature": config.model_c.temperature,
                "max_tokens": config.model_c.max_tokens,
            },
            "model_d": {
                "api_key": mask_key(config.model_d.api_key),
                "base_url": config.model_d.base_url,
                "model_name": config.model_d.model_name,
                "temperature": config.model_d.temperature,
                "max_tokens": config.model_d.max_tokens,
            },
            "model_e": {
                "api_key": mask_key(config.model_e.api_key),
                "base_url": config.model_e.base_url,
                "model_name": config.model_e.model_name,
                "temperature": config.model_e.temperature,
                "max_tokens": config.model_e.max_tokens,
            },
            "model_f": {
                "api_key": mask_key(config.model_f.api_key),
                "base_url": config.model_f.base_url,
                "model_name": config.model_f.model_name,
                "temperature": config.model_f.temperature,
                "max_tokens": config.model_f.max_tokens,
            },
            "plot": config.plot,
            "total_chapters": config.total_chapters,
            "min_words": config.min_words,
            "chapter_gen_prompt": config.chapter_gen_prompt,
            "chapter_review_prompt": config.chapter_review_prompt,
            "content_gen_prompt": config.content_gen_prompt,
            "review_optimize_prompt": config.review_optimize_prompt,
        }

    def _load_raw(self) -> Dict:
        """从 config.json 加载原始数据"""
        if not os.path.exists(self.config_path):
            return dict(DEFAULT_PIPELINE_CONFIG)

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return dict(DEFAULT_PIPELINE_CONFIG)

        # 合并默认值
        result = dict(DEFAULT_PIPELINE_CONFIG)
        result.update(data)
        return result

    def _write_raw(self, data: Dict):
        """写入 config.json"""
        # 移除较大的字段只保留配置
        config_only = {}
        for k, v in data.items():
            if k in ("model_a", "model_b", "model_c", "model_d", "model_e", "model_f",
                     "plot", "total_chapters", "temperature", "max_tokens", "min_words",
                     "chapter_gen_prompt", "chapter_review_prompt", "content_gen_prompt", "review_optimize_prompt"):
                config_only[k] = v

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config_only, f, ensure_ascii=False, indent=2)

    def _to_dict(self, config: PipelineConfig) -> Dict:
        """将 PipelineConfig 转为字典"""
        def mc_to_dict(mc: ModelConfig) -> Dict:
            return {
                "api_key": mc.api_key,
                "base_url": mc.base_url,
                "model_name": mc.model_name,
                "temperature": mc.temperature,
                "max_tokens": mc.max_tokens,
            }

        return {
            "model_a": mc_to_dict(config.model_a),
            "model_b": mc_to_dict(config.model_b),
            "model_c": mc_to_dict(config.model_c),
            "model_d": mc_to_dict(config.model_d),
            "model_e": mc_to_dict(config.model_e),
            "model_f": mc_to_dict(config.model_f),
            "plot": config.plot,
            "total_chapters": config.total_chapters,
            "min_words": config.min_words,
            "chapter_gen_prompt": config.chapter_gen_prompt,
            "chapter_review_prompt": config.chapter_review_prompt,
            "content_gen_prompt": config.content_gen_prompt,
            "review_optimize_prompt": config.review_optimize_prompt,
        }
