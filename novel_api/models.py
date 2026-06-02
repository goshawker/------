"""
models.py - Pydantic 数据模型定义
"""

from __future__ import annotations
from typing import Optional, List, Dict
from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    """单个模型配置"""
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model_name: str = "gpt-4o"
    temperature: float = 0.8
    max_tokens: int = 16384


class PipelineConfig(BaseModel):
    """流水线整体配置"""
    model_a: ModelConfig = Field(default_factory=lambda: ModelConfig(
        model_name="gpt-4o", description="大纲优化模型"
    ))
    model_b: ModelConfig = Field(default_factory=lambda: ModelConfig(
        model_name="gpt-4o", description="大纲优化辅助模型"
    ))
    model_c: ModelConfig = Field(default_factory=lambda: ModelConfig(
        model_name="gpt-4o", description="正文生成模型"
    ))
    model_d: ModelConfig = Field(default_factory=lambda: ModelConfig(
        model_name="gpt-4o", description="正文审核模型"
    ))
    model_e: ModelConfig = Field(default_factory=lambda: ModelConfig(
        model_name="gpt-4o", description="章节生成模型"
    ))
    model_f: ModelConfig = Field(default_factory=lambda: ModelConfig(
        model_name="gpt-4o", description="审核&优化模型"
    ))
    plot: str = ""
    total_chapters: int = 10
    min_words: int = 3000
    chapter_gen_prompt: str = ""
    chapter_review_prompt: str = ""
    content_gen_prompt: str = ""
    review_optimize_prompt: str = ""


class ChapterOutline(BaseModel):
    """大纲中的单个章节"""
    index: int
    title: str
    summary: str  # ≥100字简介


class OutlineResult(BaseModel):
    """大纲/审核结果"""
    title: str = ""  # 小说标题
    chapters: List[ChapterOutline] = []
    raw_text: str = ""


class ChapterContent(BaseModel):
    """生成的章节正文"""
    index: int
    title: str
    summary: str = ""
    content: str = ""
    review_report: str = ""
    optimized_content: str = ""


class PipelineState(BaseModel):
    """流水线当前状态"""
    status: str = "idle"  # idle | running | paused | completed | error
    current_step: int = 0  # 0=大纲优化, 1=正文生成, 2=正文审核, 3=正文优化
    step_names: List[str] = [
        "章节/大纲", "正文生成", "正文审核", "正文优化"
    ]
    progress: float = 0.0  # 0-100
    outline: Optional[OutlineResult] = None
    outline_review_report: str = ""  # 模型B对大纲的审核报告（含优化建议），供模型A优化时使用
    optimized_outline: Optional[OutlineResult] = None
    chapters: List[ChapterContent] = []
    error_message: str = ""
    start_time: Optional[str] = None
    plot: str = ""
    total_chapters: int = 10
    min_words: int = 3000


class WSMessage(BaseModel):
    """WebSocket 消息"""
    type: str  # progress | chapter_outline | chapter_content | review_result | complete | error | log
    data: Dict = Field(default_factory=dict)


class StartRequest(BaseModel):
    """启动流水线请求"""
    plot: str
    total_chapters: int = 10
    min_words: int = 3000


class SubmitOutlineRequest(BaseModel):
    """提交手动大纲请求"""
    outline_text: str
    plot: str = ""
    total_chapters: int = 10
    min_words: int = 3000


class ExportRequest(BaseModel):
    """导出请求"""
    format: str = "markdown"  # markdown | txt


class RegenerateRequest(BaseModel):
    """重生成指定章节请求"""
    chapter_indices: List[int] = Field(..., description="需要重新生成的章节索引列表")


class UpdateOutlineRequest(BaseModel):
    """更新章节大纲请求"""
    index: int = Field(..., description="章节索引")
    title: str = Field(..., description="章节标题")
    summary: str = Field(..., description="章节简介/内容")
