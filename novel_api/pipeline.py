"""
pipeline.py - 核心生成流水线

实现异步流水线：
1. 大纲优化 (Model A/B) - 优化用户手动输入的大纲
2. 正文生成 (Model C) - 逐章生成正文
3. 正文审核 (Model D) - 逐章审核正文
4. 正文优化 (Model C) - 逐章优化正文
"""

from __future__ import annotations

import re
import json
import asyncio
import time
from typing import Callable, Optional, Dict, Any, List

from novel_api.models import (
    ModelConfig, PipelineConfig, ChapterOutline,
    OutlineResult, ChapterContent, PipelineState
)
from novel_api.llm_client import LLMClient
from novel_api.websocket_manager import WebSocketManager
from memory_manager import MemoryManager

# 单章最大字数限制（设为极大值等同于取消限制）
MAX_CHAPTER_WORDS = 999999


def _make_review_system_prompt(min_words: int) -> str:
    """生成统一的正文章节审核 system prompt"""
    return f"""你是一位拥有15年经验的男频传统武侠小说主编，同时也是一位资深的内容风控专家。你深谙"黄金三章"法则，精通各大男频平台（如起点、番茄）的审核红线与爽点节奏。你的风格犀利、务实，擅长在确保合规的前提下，通过精修文字提升作品的"爽感"和"代入感"。

## 审核维度与标准

### 合规与安全（红线检查）
● 涉政涉黑：严禁影射现实政治、歪曲历史；严禁美化黑社会性质组织（帮派需有正向或中立结局）。
● 暴力血腥：避免过于直白的虐杀、肢解描写（可用侧面描写或氛围渲染代替）。
● 低俗色情：严禁脖子以下的露骨描写，情感戏需留白，重在氛围与暧昧感。
● 价值观导向：主角可以杀伐果断，但不能无底线反社会；反派作恶需有因果，最终需有报应（或伏笔）。

### 男频特有元素检查
● 修炼体系：等级设定是否清晰？力量体系是否崩坏？
● 剧情节奏：是否有明确的"冲突-压抑-爆发-收获"循环？是否存在"送女"、"绿帽"、"主角吃瘪无回击"等男频毒点？
● 爽点设置：装逼打脸是否自然？金手指（外挂）设定是否有趣且逻辑自洽？

### 文笔与叙事
● 代入感：环境描写是否烘托了气氛？战斗描写是否有画面感？
● 人物塑造：主角性格是否鲜明（如：腹黑、热血、稳健）？配角是否智商在线（拒绝无脑反派）？
● 沉浸式叙事：是否遵守"展示而非讲述"原则？是否存在直接用情绪形容词（如"悲伤""愤怒"）给人物心理贴标签的问题？情绪应通过动作、神态、环境来暗示。
● 感官细节：每章是否有至少3处关于气味、温度或声音的描写？场景是否有真实的质感？
● 去AI化：是否存在"总而言之""仿佛""然而""不禁"等AI高频词汇？结尾是否有不必要的议论式价值升华？对话是否符合人物身份和性格？
● 句式节奏：句式是否单一？是否存在工整排比句或对仗句破坏阅读节奏？
● 风格把控：文风是否冷峻克制？是否存在替读者做情感总结的议论性文字？

## 输出格式

严格按照以下三部分格式输出，每部分用 ===== 分隔：

**【重要】尖括号<>中是占位符，必须根据本章实际内容替换为真实分析，禁止照抄占位符文字！**

=====审核报告=====
传统武侠小说审核与优化报告

综合诊断
● 综合评分：<评分数字>/10
● 核心亮点：<实际亮点>
● 致命毒点/风险：<最严重的问题>

问题详情与修改策略
| 问题类型 | 原文片段（引用） | 问题分析 | 修改策略 |
|---|---|---|---|
| <问题类型> | <引用原文> | <问题分析> | <修改策略> |
| <问题类型> | <引用原文> | <问题分析> | <修改策略> |

=====优化文本=====
<优化后的完整章节文本，需遵循展示而非讲述原则、融入感官细节、去AI化、句式长短交错、冷峻克制。字数必须大于{min_words}字，不超过{MAX_CHAPTER_WORDS}字>

=====状态更新=====
请根据本章优化后的内容，提取最新的故事状态信息（所有字段必须根据实际填充）：
故事时间: <实际时间>
故事地点: <实际地点>
人物状态:
- <人名>: <位置/状态/行为描述>
单位状态:
- <单位名>: <状态描述>
物品状态:
- <物品名>: <归属/状态描述>
人物身体状态:
- <人名>: <健康状况/身体状态>
主角财物状态: <灵石/金钱等>
功法状态:
- <功法名>: <修炼阶段/等级>
武器状态:
- <武器名>: <归属/状态>
其他物品状态: <其他值得记录的特殊物品>
关键设定与事实:
- 【人物】<人名>: <身份/修为/状态等>
- 【物品】<物品名>: <归属/外观/功能>
上一章结尾状态:
- 时间: <实际时间>
- 地点: <实际地点>
- 在场人物: <实际在场人物>
- 关键情节进展: <实际情节推进>
- 关键物品和信息状态: <关键物品变化/重要信息获取>"""


def _make_review_force_rewrite_prompt(min_words: int) -> str:
    """强制重写审核 prompt —— 当模型偷懒复制原文时使用"""

    return f"""你是一位拥有15年经验的男频传统武侠小说主编，同时也是一位资深的内容风控专家。你的风格犀利、务实，擅长在确保合规的前提下，通过精修文字提升作品的"爽感"和"代入感"。

## 你的任务
你的任务是**重写**以下小说的章节正文——严格依据你自己给出的审核报告中的问题分析，逐条对原文进行修改。

## 关键规则——不允许复制原文
- 你必须**实际修改**原文：调整措辞、优化句式、增强画面感、修正逻辑、补充细节
- 输出与原文完全相同的文本视为**无效输出**
- 优化后的文本必须在措辞、句式、细节描写上与原文有明显差异
- **【关键】删除本章内部的重复内容**：同一场景描写、同一段对话、同一信息点在全文内出现两次的，只保留一次。
- **【关键】删除开头与上一章重复的情节描写**，只保留一句话过渡。任何对上一章已发生事件的回顾性描述都必须删除或压缩为一句话。
- 如果原文存在"节奏慢"问题——请删减冗余描写、增加对话或冲突
- 如果原文存在"缺乏爽点"问题——请强化主角的高光时刻
- 如果原文存在"合规风险"问题——请用侧面描写替代直白描写
- 如果原文存在"人物塑造单薄"问题——请增加人物细微反应和内心活动
- 如果原文存在"展示而非讲述"问题——删除情绪形容词，改为通过动作、神态、环境暗示
- 如果原文缺乏感官细节——补充至少3处气味、温度或声音描写
- 如果原文存在AI味词汇（"总而言之""仿佛""然而""不禁"等）——删除替换，对话增加口语停顿和潜台词
- 如果原文句式工整排比——打乱长短句节奏
- 如果原文有替读者做情感总结的议论句——删除，保持冷峻克制

## 输出格式

严格按照以下三部分格式输出，每部分用 ===== 分隔：

**【重要】尖括号<>中是占位符，必须根据本章实际内容替换为真实分析，禁止照抄占位符文字！**

=====审核报告=====
[你刚才已给出的审核与优化报告]

=====优化文本=====
[重写后的完整章节文本，需遵循展示而非讲述原则、融入感官细节、去AI化、句式长短交错、冷峻克制。字数必须大于{min_words}字，不超过{MAX_CHAPTER_WORDS}字，且与原文在措辞、句式、细节上显著不同]

=====状态更新=====
故事时间: [...]
故事地点: [...]
人物状态:
- [...]
单位状态:
- [...]
物品状态:
- [...]
人物身体状态:
- [...]
主角财物状态: [...]
功法状态:
- [...]
武器状态:
- [...]
其他物品状态: [...]
关键设定与事实:
- [...]
上一章结尾状态:
- 时间: [...]
- 地点: [...]
- 在场人物: [...]
- 关键情节进展: [...]
- 关键物品和信息状态: [...]"""


def _make_outline_review_prompt() -> str:
    """生成大纲审核 system prompt —— 只审核，不优化"""
    return """你是一位拥有15年经验的男频小说主编，同时也是一位资深的内容风控专家。你深谙"黄金三章"法则，精通各大男频平台（如起点、番茄）的审核红线与爽点节奏。你的风格犀利、务实，擅长在确保合规的前提下，通过精修文字提升作品的"爽感"和"代入感"。

你擅长审核小说大纲。

你的任务是审核大纲的：
1. 故事逻辑是否通顺
2. 章节安排是否合理
3. 情节起伏是否有节奏感
4. 人物塑造是否丰满
5. 每一章简介是否足够详细（超过100字）

请输出详细的审核报告，针对每个问题章节给出具体的修改建议。
不要输出优化后的章节内容，只输出审核报告。

## 输出格式

=====审核报告=====
[详细的大纲审核报告，包含每批章节的整体评价和各章节的具体问题与建议]
"""


def _make_outline_optimize_prompt() -> str:
    """生成大纲优化 system prompt —— 根据审核报告优化"""
    return """你是一位拥有15年经验的男频小说主编，同时也是一位资深的内容风控专家。你深谙"黄金三章"法则，精通各大男频平台（如起点、番茄）的审核红线与爽点节奏。你的风格犀利、务实，擅长在确保合规的前提下，通过精修文字提升作品的"爽感"和"代入感"。

你是一位资深小说大纲策划师，拥有20年网文创作经验。
你的任务是根据审核报告中的建议，优化以下大纲内容。

请保留好的部分，重点优化审核报告中指出的问题。
输出优化后的完整章节大纲。

## 输出格式

## 第XX章 - 章节标题
章节简介：（优化后的详细介绍，必须超过100字）
"""


def _make_review_only_system_prompt() -> str:
    """生成正文章节审核 system prompt —— 只审核，不优化"""
    return """你是一位拥有15年经验的男频小说主编，同时也是一位资深的内容风控专家。你深谙"黄金三章"法则，精通各大男频平台（如起点、番茄）的审核红线与爽点节奏。你的风格犀利、务实，擅长在确保合规的前提下，通过精修文字提升作品的"爽感"和"代入感"。

## 审核维度与标准

### 合规与安全（红线检查）
● 涉政涉黑：严禁影射现实政治、歪曲历史；严禁美化黑社会性质组织（帮派需有正向或中立结局）。
● 暴力血腥：避免过于直白的虐杀、肢解描写（可用侧面描写或氛围渲染代替）。
● 低俗色情：严禁脖子以下的露骨描写，情感戏需留白，重在氛围与暧昧感。
● 价值观导向：主角可以杀伐果断，但不能无底线反社会；反派作恶需有因果，最终需有报应（或伏笔）。

### 男频特有元素检查
● 修炼体系：等级设定是否清晰？力量体系是否崩坏？
● 剧情节奏：是否有明确的"冲突-压抑-爆发-收获"循环？是否存在"送女"、"绿帽"、"主角吃瘪无回击"等男频毒点？
● 爽点设置：装逼打脸是否自然？金手指（外挂）设定是否有趣且逻辑自洽？

### 文笔与叙事
● 代入感：环境描写是否烘托了气氛？战斗描写是否有画面感？
● 人物塑造：主角性格是否鲜明（如：腹黑、热血、稳健）？配角是否智商在线（拒绝无脑反派）？
● 沉浸式叙事：是否遵守"展示而非讲述"原则？是否存在直接用情绪形容词（如"悲伤""愤怒"）给人物心理贴标签的问题？情绪应通过动作、神态、环境来暗示。
● 感官细节：每章是否有至少3处关于气味、温度或声音的描写？场景是否有真实的质感？
● 去AI化：是否存在"总而言之""仿佛""然而""不禁"等AI高频词汇？结尾是否有不必要的议论式价值升华？对话是否符合人物身份和性格？
● 句式节奏：句式是否单一？是否存在工整排比句或对仗句破坏阅读节奏？
● 风格把控：文风是否冷峻克制？是否存在替读者做情感总结的议论性文字？

### 内容重复性检查（重点）
● **【关键】检查本章内部是否存在自身内容重复**：同一场景描写是否出现了两次？同一段对话或相同信息是否反复出现？角色动作/反应是否高度雷同？
● **【关键】检查本章是否存在与前面章节重复的情节**：包括场景描写、人物对话、事件推进的重复
● 开头是否重复描写了上一章已发生的事件？应只做简短衔接，不展开重述
● 是否有不必要的回顾性描述占用篇幅

## 输出格式

严格按照以下两部分格式输出，每部分用 ===== 分隔（不要输出优化文本）：

**【重要】尖括号<>中是占位符，必须根据本章实际内容替换为真实分析，禁止照抄占位符文字！**

=====审核报告=====
传统武侠小说审核与优化报告

综合诊断
● 综合评分：<评分数字>/10
● 核心亮点：<实际亮点>
● 致命毒点/风险：<最严重的问题>

问题详情与修改策略
| 问题类型 | 原文片段（引用） | 问题分析 | 修改策略 |
|---|---|---|---|
| <问题类型> | <引用原文> | <问题分析> | <修改策略> |
| <问题类型> | <引用原文> | <问题分析> | <修改策略> |

=====状态更新=====
请根据本章内容，提取最新的故事状态信息（所有字段必须根据实际填充）：
故事时间: <实际时间>
故事地点: <实际地点>
人物状态:
- <人名>: <位置/状态/行为描述>
单位状态:
- <单位名>: <状态描述>
物品状态:
- <物品名>: <归属/状态描述>
人物身体状态:
- <人名>: <健康状况/身体状态>
主角财物状态: <灵石/金钱等>
功法状态:
- <功法名>: <修炼阶段/等级>
武器状态:
- <武器名>: <归属/状态>
其他物品状态: <其他值得记录的特殊物品>
关键设定与事实:
- 【人物】<人名>: <身份/修为/状态等>
- 【物品】<物品名>: <归属/外观/功能>
上一章结尾状态:
- 时间: <实际时间>
- 地点: <实际地点>
- 在场人物: <实际在场人物>
- 关键情节进展: <实际情节推进>
- 关键物品和信息状态: <关键物品变化/重要信息获取>"""


def _make_content_optimize_prompt(min_words: int) -> str:
    """生成正文优化 system prompt —— 根据审核报告优化"""
    return f"""你是一位拥有15年经验的男频小说主编，同时也是一位资深的内容风控专家。你深谙"黄金三章"法则，精通各大男频平台（如起点、番茄）的审核红线与爽点节奏。你的风格犀利、务实，擅长在确保合规的前提下，通过精修文字提升作品的"爽感"和"代入感"。

你是一位顶级网文作家，擅长根据审核建议优化小说章节。
你的任务是严格按照审核报告中的每一条建议，对原文进行修改优化。

## 关键要求
- 保留原文的故事框架、核心情节和人物设定
- 逐条落实审核报告中的修改建议
- 必须对原文进行实际修改：调整措辞、优化句式、增强画面感、修正逻辑、补充细节
- 优化后的字数必须大于{min_words}字，不超过{MAX_CHAPTER_WORDS}字
- 开头保持与上一章的衔接（但**不得重复描写上一章已发生的事件**）
- 结尾保留悬念或钩子
- 不要复制原文，必须实际修改
- **【关键】检查并删除本章内部的重复内容**：同一场景描写、同一段对话、同一信息在全文内出现多次的，只保留一次。
- **【关键】优化时如发现开头或正文中存在与前面章节重复的情节描述，必须删除**，改为简洁过渡或直接推进新剧情
- 【沉浸式叙事】用动作、神态、环境暗示心理，删除直接的情绪形容词（如"悲伤""愤怒"）
- 【感官细节】补充至少3处气味、温度或声音的细腻描写
- 【去AI化】删除"总而言之""仿佛""然而""不禁"等AI高频词汇，删除结尾价值升华，优化对话使其符合人物身份、包含口语停顿和潜台词
- 【句式节奏】打乱单一句式结构，长短句交错，拆除工整排比句
- 【风格】保持冷峻克制，删除替读者做情感总结的议论句

请直接输出优化后的完整章节正文，不要包含"第X章"标题前缀，不要添加额外的格式说明。"""


def _make_optimize_force_rewrite_prompt(min_words: int) -> str:
    """强制重写优化 prompt —— 当优化结果与原文过于相似时使用"""
    return f"""你是一位拥有15年经验的男频小说主编，同时也是一位资深的内容风控专家。你深谙"黄金三章"法则，精通各大男频平台（如起点、番茄）的审核红线与爽点节奏。你的风格犀利、务实，擅长在确保合规的前提下，通过精修文字提升作品的"爽感"和"代入感"。

你是一位顶级网文作家，擅长根据审核建议优化小说章节。

## 你的任务
你的任务是**实际修改**以下小说章节——严格依据审核报告中的问题分析，逐条对原文进行修改。

## 关键规则——不允许复制原文
- 你必须**实际修改**原文：调整措辞、优化句式、增强画面感、修正逻辑、补充细节
- 输出与原文完全相同的文本视为**无效输出**
- 优化后的文本必须在措辞、句式、细节描写上与原文有明显差异
- **【关键】删除本章内部的重复内容**：同一场景描写、同一段对话、同一信息点在全文内出现两次的，只保留一次。
- **【关键】删除开头与上一章重复的情节描写**，只保留一句话过渡。任何对上一章已发生事件的回顾性描述都必须删除或压缩为一句话。
- 如果原文存在"节奏慢"问题——请删减冗余描写、增加对话或冲突
- 如果原文存在"缺乏爽点"问题——请强化主角的高光时刻
- 如果原文存在"合规风险"问题——请用侧面描写替代直白描写
- 如果原文存在"人物塑造单薄"问题——请增加人物细微反应和内心活动
- 如果原文存在"展示而非讲述"问题——删除情绪形容词，改为通过动作、神态、环境暗示
- 如果原文缺乏感官细节——补充至少3处气味、温度或声音描写
- 如果原文存在AI味词汇（"总而言之""仿佛""然而""不禁"等）——删除替换，对话增加口语停顿和潜台词
- 如果原文句式工整排比——打乱长短句节奏
- 如果原文有替读者做情感总结的议论句——删除，保持冷峻克制

请直接输出优化后的完整章节正文，不要包含"第X章"标题前缀，不要添加额外的格式说明。
优化后的字数必须大于{min_words}字，不超过{MAX_CHAPTER_WORDS}字。"""


class NovelPipeline:
    """小说生成流水线"""

    def __init__(self, ws_manager: WebSocketManager):
        self.ws_manager = ws_manager
        self.state = PipelineState()
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # 默认不暂停
        self._cancelled = False
        self._generation = 0  # 递增计数器，旧任务的残留操作通过比对 generation 来放弃
        self._llm_clients: Dict[str, LLMClient] = {}
        self.memory_manager = MemoryManager("memory_web.md")

    def _init_clients(self, config: PipelineConfig):
        """初始化 LLM 客户端"""
        self._llm_clients = {
            "model_a": LLMClient(config.model_a, "大纲优化"),
            "model_b": LLMClient(config.model_b, "大纲优化辅助"),
            "model_c": LLMClient(config.model_c, "正文生成"),
            "model_d": LLMClient(config.model_d, "正文审核"),
            "model_e": LLMClient(config.model_e, "章节生成"),
            "model_f": LLMClient(config.model_f, "审核&优化"),
        }

    def _init_memory(self, config: PipelineConfig, force: bool = False):
        """根据故事情节初始化记忆系统

        Args:
            config: 流水线配置
            force: 是否强制重新初始化（清除旧记忆）
        """
        import os
        memory_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory_web.md")
        # 如果强制重新初始化或文件不存在，创建新记忆
        if force or not os.path.exists(memory_path):
            self._write_memory_file(memory_path, config)
            return

        # 文件存在时检查是否是有效记忆（包含必要标记）
        with open(memory_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "## 处理进度" in content and "## 人物状态" in content:
            return

        # 文件存在但内容不完整，重新初始化
        self._write_memory_file(memory_path, config)

    def _write_memory_file(self, memory_path: str, config: PipelineConfig):
        """写入初始记忆文件"""
        # 从已有大纲中提取小说标题
        novel_title = "未命名"
        if hasattr(self, 'state') and self.state and self.state.outline and self.state.outline.title:
            novel_title = self.state.outline.title

        text = f"""# 小说状态记忆

## 处理进度
- 已优化章节: 无
- 待优化章节: 第01章
- 总章节数: {config.total_chapters}

## 当前时间线
- 当前章节: 第01章
- 故事时间: 未知（初始章节）
- 故事地点: 未知

## 人物状态
（待首次审核后更新）

## 单位状态
（待首次审核后更新）

## 物品状态
（待首次审核后更新）

## 人物身体状态
（待首次审核后更新）

## 主角财物状态
（待首次审核后更新）

## 功法状态
（待首次审核后更新）

## 武器状态
（待首次审核后更新）

## 其他物品状态
（待首次审核后更新）

## 关键设定与事实
- 【设定】小说标题: {novel_title}
- 【设定】总章节数: {config.total_chapters}
- 【设定】每章字数: {config.min_words}~{MAX_CHAPTER_WORDS}字

## 上一章结尾状态
- 时间: 无（初始章节）
- 地点: 无
- 在场人物: 无
- 关键情节进展: 无
- 关键物品和信息状态: 无
"""
        with open(memory_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[记忆系统] 记忆文件已初始化: memory_web.md")

    async def _check_pause(self):
        """检查是否需要暂停"""
        while not self._pause_event.is_set():
            if self._cancelled:
                raise asyncio.CancelledError()
            await asyncio.sleep(0.5)
        if self._cancelled:
            raise asyncio.CancelledError()

    async def _broadcast(self, type_: str, data: Dict[str, Any]):
        """广播消息"""
        await self.ws_manager.broadcast({
            "type": type_,
            "data": data,
            "timestamp": time.time(),
        })

    async def _update_progress(self, step: int, progress: float,
                                step_name: str = None, message: str = ""):
        """更新并广播进度"""
        self.state.current_step = step
        self.state.progress = progress
        step_name_text = step_name or (self.state.step_names[step] if step < len(self.state.step_names) else "")
        await self._broadcast("progress", {
            "current_step": step,
            "step_name": step_name_text,
            "progress": progress,
            "message": message,
            "state": self.state.model_dump(),
        })

    def _check_generation(self, gen: int = -1):
        """检查当前 generation 是否仍然有效，防止旧任务污染新状态
        Args:
            gen: 任务启动时的 _generation 值，若与当前不一致说明是旧任务
        """
        if gen >= 0 and gen != self._generation:
            raise asyncio.CancelledError(f"[Stale] generation {gen} != {self._generation}")
        if self._cancelled:
            raise asyncio.CancelledError()

    async def _call_llm_safe(
        self,
        client: LLMClient,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        retry_label: str = "",
    ) -> Optional[str]:
        """安全调用 LLM，超时/失败时自动重试并广播进度

        Returns:
            成功返回文本，重试耗尽后返回 None
        """
        max_retries = 3  # 额外重试次数（LLM Client内部已有5次）
        for attempt in range(max_retries):
            try:
                # 带心跳的 API 调用：每15秒广播一次进度，避免用户以为卡死
                api_task = asyncio.create_task(
                    client.call(prompt, system_prompt=system_prompt,
                                temperature=temperature, max_tokens=max_tokens)
                )
                heartbeat_task = asyncio.create_task(
                    self._llm_heartbeat(api_task, retry_label, attempt)
                )
                done, _ = await asyncio.wait(
                    [api_task, heartbeat_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # 心跳任务自动结束
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
                # 获取 API 结果
                if api_task in done and not api_task.cancelled():
                    result = api_task.result()
                    return result
                # API 任务异常
                exc = api_task.exception()
                if exc:
                    raise exc
                raise Exception("API 调用未知错误")
            except asyncio.CancelledError:
                # asyncio.CancelledError 是 BaseException，不是 Exception
                # 用户主动取消时 _cancelled 为 True，正常传播
                # 其他情况（如服务器reload）转为重试
                if self._cancelled:
                    raise
                await self._broadcast("log", {
                    "message": f"{retry_label}请求被中断（可能服务器热重载），5秒后第{attempt + 2}次重试..."
                })
                await asyncio.sleep(5)
            except Exception as e:
                is_timeout = any(kw in str(e).lower() for kw in ["timeout", "timed out", "deadline", "read timed out"])
                is_connection = any(kw in str(e).lower() for kw in ["connection", "econnrefused", "econnreset", "cannot connect"])
                if attempt < max_retries - 1:
                    wait = 30 if is_timeout else 15 if is_connection else 10
                    reason = "连接失败" if is_connection else "超时" if is_timeout else "失败"
                    await self._broadcast("log", {
                        "message": f"{retry_label}API {reason}，{wait}秒后第{attempt + 2}次重试..."
                    })
                    await asyncio.sleep(wait)
                else:
                    await self._broadcast("log", {
                        "message": f"{retry_label}API 调用多次重试后仍失败，跳过该批次: {str(e)[:150]}"
                    })
                    return None

    async def _llm_heartbeat(self, api_task: asyncio.Task, label: str, attempt: int):
        """API 调用期间定期广播心跳进度，避免用户以为卡死"""
        waited = 0
        interval = 15
        while not api_task.done():
            await asyncio.sleep(interval)
            waited += interval
            if not api_task.done():
                retry_info = f"（第{attempt+1}次尝试）" if attempt > 0 else ""
                time_str = f"{waited//60}分{waited%60}秒" if waited >= 60 else f"{waited}秒"
                tip = "（本地模型生成5000~10000字章节预计需要5~15分钟，请耐心等待）" if waited > 120 else ""
                await self._broadcast("log_replace", {
                    "message": f"{label}正在生成，已等待{time_str}{retry_info}{tip}..."
                })

    @staticmethod
    def _strip_planning_text(text: str) -> str:
        """剥离模型输出的规划/分析文字，只保留小说正文

        GLM 模型经常在正文前先输出创作规划，格式如：
        "用户想要...\n**关键要求：**\n...\n好的，计划已定。我现在将生成文本。\\n\\n\"正文...\""
        此方法检测并删除正文前的所有规划文字。
        """
        if not text:
            return text

        # 尝试多种分割标记，取最后一段正文
        markers = [
            "我现在将生成文本",
            "我将生成文本",
            "开始生成文本",
            "直接写故事",
            "正文如下",
            "生成文本",
        ]
        best_pos = -1
        for marker in markers:
            pos = text.rfind(marker)
            if pos > best_pos:
                best_pos = pos

        if best_pos > 0:
            # 从标记后提取正文（跳过引号、换行等）
            rest = text[best_pos:]
            # 找到第一个 " 或「或『或实际内容
            for ch in ['"', '「', '『', '\n']:
                idx = rest.find(ch)
                if idx >= 0:
                    rest = rest[idx + 1:]
                    break
            rest = rest.strip().strip('"').strip('「').strip('『').strip('」').strip('』')
            if len(rest) > 100:  # 确保提取到的是有效内容
                return rest

        # 如果按照标记分割效果不好，尝试检测开头是否是分析性文字
        lines = text.strip().split('\n')
        # 检查第一行是否是"用户想要" "角色" "格式" 等分析性开头
        first_line = lines[0].strip() if lines else ""
        analysis_markers = ["用户想要", "用户要求", "**关键要求", "*   **角色", "*   **格式", "*   **长度"]
        if any(first_line.startswith(m) for m in analysis_markers):
            # 找到第一个看起来像正文的段落（没有分析性标记的段落）
            story_lines = []
            in_story = False
            for line in lines:
                stripped = line.strip()
                if not in_story:
                    # 跳过分析段落
                    if stripped.startswith("*") or stripped.startswith("-") or \
                       stripped.startswith("**") or stripped.startswith("好的") or \
                       stripped.startswith("我将") or stripped.startswith("计划"):
                        continue
                    # 找到正文的迹象：长度>30的普通叙述句
                    if len(stripped) > 30 and not stripped.startswith("*") and not stripped.startswith("```"):
                        in_story = True
                        story_lines.append(stripped)
                else:
                    story_lines.append(stripped)
            if story_lines:
                result = '\n'.join(story_lines).strip()
                if len(result) > 200:
                    return result

        return text

    async def _extract_memory_from_content(
        self, client, content: str, idx: int, co
    ) -> Dict[str, Any]:
        """从刚生成的正文中提取完整的故事状态信息，用于更新记忆系统

        提取字段：故事时间、地点、人物状态、单位状态、物品状态、人物身体状态、
        主角财物状态、功法状态、武器状态、其他物品状态、关键设定、上一章结尾状态。
        """
        # 截取正文首尾各800字供分析
        head = content[:800]
        tail = content[-800:] if len(content) > 1600 else content[-400:]
        summary_text = co.summary[:200] if co and co.summary else ""

        prompt = f"""从以下小说章节中提取完整的故事状态信息，用于更新存档。

章节：第{idx}章 - {co.title if co else ''}
章节简介：{summary_text}

--- 正文开头800字 ---
{head}

--- 正文末尾800字 ---
{tail}

请按以下格式提取信息（没有明确信息时写"无变化"）：

故事时间: <具体时间点，如"翌日清晨""三日后正午"等>
故事地点: <本章主要发生地点>

人物状态:
- <人名>: <位置/状态/行为>

单位状态:
- <单位名>: <状态描述>

物品状态:
- <物品名>: <归属/状态>

人物身体状态:
- <人名>: <健康状况>

主角财物状态: <灵石/金钱等变化>

功法状态:
- <功法名>: <修炼阶段/等级>

武器状态:
- <武器名>: <归属/状态>

其他物品状态: <特殊物品变化>

关键设定与事实:
- 列出本章新出现的重要设定或事实

上一章结尾状态:
- 时间: <本章结束时的时间点>
- 地点: <本章结束时的地点>
- 在场人物: <本章结束时尚在场的人物>
- 关键情节进展: <本章的核心推进>
- 关键物品和信息状态: <本章重要的物品/信息变化>
"""
        system_prompt = '你是一个小说状态信息提取器。只输出结构化数据，不输出任何解释和分析。不存在的字段写「无变化」。'
        try:
            _gen = self._generation
            result = await self._call_llm_safe(
                client, prompt, system_prompt=system_prompt,
                temperature=0.3, max_tokens=1000,
                retry_label=f"[记忆提取] 第{idx}章 "
            )
            self._check_generation(_gen)
            if result:
                return self._parse_state_update_text(result)
        except Exception as e:
            print(f"[记忆提取] 第{idx}章提取失败: {e}")
        return {}

    async def start_generate_chapters_v2(self, config: PipelineConfig):
        """章节生成：使用 model_e 和章节生成提示词，根据小说剧情/大纲生成章节大纲（标题+简介）"""
        if not self.state.plot and not config.plot:
            plot = config.plot or self.state.plot
        else:
            plot = self.state.plot or config.plot

        if not plot:
            raise ValueError("请先填写小说剧情/大纲")

        self._generation += 1
        self._init_clients(config)
        self._last_config = config
        self._cancelled = False
        self._pause_event.set()
        self.state.status = "running"
        self.state.current_step = 0
        self.state.min_words = config.min_words
        self.state.plot = plot
        self.state.progress = 0.0
        self.state.error_message = ""

        try:
            client_e = self._llm_clients["model_e"]
            total = config.total_chapters
            chapter_gen_prompt = config.chapter_gen_prompt or "请根据以下小说剧情/大纲，生成{total}章的章节大纲，包括每章的标题和简介。标题要吸睛，简介要包含具体的情节推进。格式：\n\n## 第XX章 - 标题\n章节简介：（不少于100字的具体内容）"

            combined_prompt = f"""{chapter_gen_prompt}

小说剧情/大纲：
{plot}

请生成 {total} 章的章节大纲，包括每章的标题和简介。

要求：
1. 标题要吸睛、有悬念感
2. 每章简介不少于100字，包含具体的情节推进、人物互动和冲突设计
3. 章节间逻辑连贯，情节有起承转合
4. 严格按照以下格式输出：

## 第01章 - 标题
章节简介：（不少于100字的具体介绍）

## 第02章 - 标题
章节简介：（不少于100字的具体介绍）

...以此类推，共{total}章"""

            await self._broadcast("log", {
                "message": f"[章节生成] 开始使用模型生成 {total} 章大纲..."
            })

            _gen = self._generation
            result = await self._call_llm_safe(
                client_e, combined_prompt, system_prompt=None,
                temperature=0.8, max_tokens=65535,
                retry_label="[章节生成] "
            )
            self._check_generation(_gen)

            if not result:
                raise ValueError("章节生成失败，模型返回空内容")

            # 解析结果
            parsed_chapters = self._parse_outline_chapters(result)
            if not parsed_chapters:
                raise ValueError("章节生成失败，无法解析模型输出，请检查提示词")

            # 提取小说标题（从第一行或默认）
            title = parsed_chapters[0].title if parsed_chapters else "未命名"
            # 用"第XX章 -" 前的内容作为标题，或者用大纲第一段的标题
            first_line = result.strip().split('\n')[0] if result.strip() else ""
            if first_line and not first_line.startswith("##"):
                title = first_line.strip().strip('#').strip()

            # 创建 OutlineResult
            from novel_api.models import OutlineResult
            outline = OutlineResult(
                title=title,
                chapters=parsed_chapters,
                raw_text=result,
            )

            # 如果生成的章节数少于请求数，补齐缺失章节（防止 token 截断导致章节丢失）
            max_index = max(ch.index for ch in parsed_chapters) if parsed_chapters else 0
            expected = max(config.total_chapters, max_index)
            missing_indices = sorted(set(range(1, expected + 1)) - {ch.index for ch in parsed_chapters})
            if missing_indices:
                for missing_idx in missing_indices:
                    parsed_chapters.append(ChapterOutline(
                        index=missing_idx,
                        title=f"第{missing_idx}章",
                        summary=f"第{missing_idx}章：剧情继续推进，主角面对新的挑战与机遇，逐步揭开更大的阴谋，故事走向高潮。",
                    ))
                parsed_chapters.sort(key=lambda c: c.index)
                outline.chapters = parsed_chapters

            self.state.outline = outline
            self.state.optimized_outline = None
            self.state.chapters = []
            self.state.total_chapters = len(parsed_chapters)

            # 广播生成的章节
            for ch in parsed_chapters:
                await self._broadcast("chapter_outline", {
                    "index": ch.index,
                    "title": ch.title,
                    "summary": ch.summary,
                    "step": "outline_optimized",
                    "outline_optimized": True,
                })

            self.state.status = "idle"
            self.state.current_step = 0
            self.state.progress = 100.0
            self._save_state_to_disk()

            await self._broadcast("complete", {
                "message": f"章节生成完成！共生成 {len(parsed_chapters)} 章大纲。现在可以进行章节审核。",
                "state": self.state.model_dump(),
            })

        except asyncio.CancelledError:
            if self.state.status != "cancelled":
                self.state.status = "cancelled"
                await self._broadcast("error", {
                    "message": "章节生成已取消",
                    "state": self.state.model_dump(),
                })
        except Exception as e:
            self.state.status = "error"
            self.state.error_message = str(e)
            await self._broadcast("error", {
                "message": str(e),
                "state": self.state.model_dump(),
            })
            import traceback
            traceback.print_exc()

    async def start_review_and_optimize(self, config: PipelineConfig):
        """审核&优化：使用 model_f 对已生成的章节进行审核和优化（合并步骤）"""
        if not self.state.chapters or not any(ch.content and ch.content.strip() for ch in self.state.chapters):
            raise ValueError("没有已生成的正文内容，请先执行正文生成")

        self._generation += 1
        self._init_clients(config)
        self._last_config = config
        self._cancelled = False
        self._pause_event.set()
        self.state.status = "running"
        self.state.current_step = 3
        self.state.min_words = config.min_words
        self.state.progress = 0.0
        self.state.error_message = ""

        client_f = self._llm_clients["model_f"]
        outline = self.state.optimized_outline or self.state.outline
        total = len(outline.chapters) if outline else len(self.state.chapters)

        chapters = sorted(self.state.chapters, key=lambda c: c.index)
        review_optimize_prompt = config.review_optimize_prompt or ""

        try:
            await self._broadcast("log", {
                "message": "[审核&优化] 开始逐章审核与优化..."
            })

            for i, chapter in enumerate(chapters):
                await self._check_pause()
                if self._cancelled:
                    return

                idx = chapter.index
                await self._update_progress(3, (i / total) * 100,
                                            message=f"正在审核&优化第{idx}章: {chapter.title}（{i+1}/{total}）")

                # 构建审核+优化 prompt
                memory = self.memory_manager.read_memory()
                prev_end = memory.get("prev_chapter_end", {})

                system_prompt = review_optimize_prompt if review_optimize_prompt else f"""你是一位资深男频小说主编，请对以下章节进行审核和优化。

审核维度：
1. 合规安全、剧情节奏、爽点设置
2. 文笔叙事、人物塑造、沉浸式叙事
3. 感官细节、去AI化、句式节奏

优化要求：
- 根据审核发现的问题逐条修改
- 保留故事框架和核心情节
- 优化后用词更精准、句式更丰富
- 字数不低于{config.min_words}字"""

                user_prompt = f"""请对以下小说章节进行审核和优化。

小说标题：{outline.title if outline else ""}
章节：第{idx}章 - {chapter.title}
章节简介：{chapter.summary}

当前故事状态：
- 故事时间: {memory.get('story_time', '未知')}
- 故事地点: {memory.get('story_location', '未知')}

上一章结尾状态（仅参考，切勿重复描写）：
- 时间: {prev_end.get('time', '无')}
- 地点: {prev_end.get('location', '无')}
- 关键情节进展: {prev_end.get('plot_progress', '无')}

待处理章节正文：
{chapter.content[:8000] if len(chapter.content) > 8000 else chapter.content}

请先输出审核报告（包含综合评分、问题详情与修改策略），然后在审核报告后输出优化后的完整章节正文。用 ===== 分隔审核报告和优化文本。"""

                await self._broadcast("log", {
                    "message": f"[审核&优化] 第{idx}章 正在处理..."
                })

                _gen = self._generation
                result = await self._call_llm_safe(
                    client_f, user_prompt, system_prompt=system_prompt,
                    temperature=0.7, max_tokens=32768,
                    retry_label=f"[审核&优化] 第{idx}章 "
                )
                self._check_generation(_gen)

                if result is None:
                    await self._broadcast("log", {
                        "message": f"[错误] 第{idx}章审核&优化失败，跳过"
                    })
                    continue

                # 解析结果：按照 ===== 分隔符拆分审核报告和优化文本
                parts = result.split("=====")
                review_report = ""
                optimized_content = ""

                if len(parts) >= 3:
                    # 有审核报告和优化文本
                    review_report = parts[1].strip()
                    optimized_content = "=====".join(parts[2:]).strip()
                elif len(parts) == 2:
                    # 可能只有审核报告或只有优化文本
                    review_report = parts[1].strip()
                else:
                    # 没有分隔符，整段作为审核报告
                    review_report = result.strip()

                # 清理优化文本中的 "优化文本" 标题
                if optimized_content:
                    for prefix in ["优化文本", "优化后的文本", "=====优化文本====="]:
                        if optimized_content.startswith(prefix):
                            optimized_content = optimized_content[len(prefix):].strip()

                # 更新章节数据
                if review_report:
                    chapter.review_report = review_report
                if optimized_content and len(optimized_content) > 100:
                    chapter.optimized_content = optimized_content

                # 更新记忆
                try:
                    chapter_label = f"第{str(idx).zfill(2)}章"
                    next_label = f"第{str(idx + 1).zfill(2)}章" if idx < total else "全部完成"
                    updates = {
                        "optimized_chapter": chapter_label,
                        "pending_chapter": next_label,
                        "current_chapter": chapter_label,
                    }
                    self.memory_manager.update_memory(updates)
                except Exception as e:
                    print(f"[记忆系统] 第{idx}章状态更新失败: {e}")

                await self._broadcast("optimize_result", {
                    "index": idx,
                    "title": chapter.title,
                    "has_optimized": bool(optimized_content),
                    "progress": ((i + 1) / total) * 100,
                })

                self._save_state_to_disk()

            self.state.status = "completed"
            self.state.progress = 100.0
            await self._broadcast("complete", {
                "message": "审核&优化全部完成！",
                "state": self.state.model_dump(),
            })

        except asyncio.CancelledError:
            if self.state.status != "cancelled":
                self.state.status = "cancelled"
                await self._broadcast("error", {
                    "message": "审核&优化已取消",
                    "state": self.state.model_dump(),
                })
        except Exception as e:
            self.state.status = "error"
            self.state.error_message = str(e)
            await self._broadcast("error", {
                "message": str(e),
                "state": self.state.model_dump(),
            })
            import traceback
            traceback.print_exc()

    async def start_review_chapters_v2(self, config: PipelineConfig):
        """章节审核：使用 model_f 对大纲所有章节名称和简介进行一次性审核"""
        outline = self.state.optimized_outline or self.state.outline
        if not outline or not outline.chapters:
            raise ValueError("没有已生成的章节大纲，请先执行章节生成")

        self._generation += 1
        self._init_clients(config)
        self._last_config = config
        self._cancelled = False
        self._pause_event.set()
        self.state.status = "running"
        self.state.current_step = 0
        self.state.min_words = config.min_words
        self.state.progress = 0.0
        self.state.error_message = ""

        try:
            client_f = self._llm_clients["model_f"]
            await self._update_progress(0, 0, message="开始章节审核...")

            # 构建所有章节的名称和简介文本
            chapters_text = ""
            for ch in outline.chapters:
                chapters_text += f"""## 第{str(ch.index).zfill(2)}章 - {ch.title}
章节简介：{ch.summary}

"""

            review_prompt = config.chapter_review_prompt or "请审核以下小说章节大纲，对每章的标题和简介给出优化建议。"

            combined_prompt = f"""{review_prompt}

以下是需要审核的小说章节大纲：

{chapters_text}

请对以上所有章节的标题和简介逐一审核，给出具体的优化建议。
标题要吸睛、有悬念感；简介要超过100字且包含具体情节推进。
对于不符合要求的章节，请明确标出需要修改的内容。"""

            await self._broadcast("log", {
                "message": f"[章节审核] 开始一次性审核 {len(outline.chapters)} 章大纲..."
            })

            _gen = self._generation
            result = await self._call_llm_safe(
                client_f, combined_prompt, system_prompt=None,
                temperature=0.7, max_tokens=8192,
                retry_label="[章节审核] "
            )
            self._check_generation(_gen)

            if result:
                self.state.outline_review_report = result
                await self._broadcast("log", {
                    "message": f"[章节审核] 审核完成，共审核 {len(outline.chapters)} 章"
                })
            else:
                await self._broadcast("log", {
                    "message": "[章节审核] 审核返回为空，请检查提示词"
                })

            self.state.status = "idle"
            self.state.current_step = 0
            await self._broadcast("complete", {
                "message": "章节审核完成！",
                "state": self.state.model_dump(),
            })

        except asyncio.CancelledError:
            if self.state.status != "cancelled":
                self.state.status = "cancelled"
                await self._broadcast("error", {"message": "章节审核已取消", "state": self.state.model_dump()})
        except Exception as e:
            self.state.status = "error"
            self.state.error_message = str(e)
            await self._broadcast("error", {"message": str(e), "state": self.state.model_dump()})
            import traceback
            traceback.print_exc()

    async def start_optimize_chapters_v2(self, config: PipelineConfig):
        """章节优化：将所有章节名称、简介、审核结果一次性提交给大模型，根据结果更新章节名称和简介"""
        outline = self.state.optimized_outline or self.state.outline
        if not outline or not outline.chapters:
            raise ValueError("没有已生成的章节大纲，请先执行章节生成")
        if not self.state.outline_review_report:
            raise ValueError("没有章节审核结果，请先执行章节审核")

        self._generation += 1
        self._init_clients(config)
        self._last_config = config
        self._cancelled = False
        self._pause_event.set()
        self.state.status = "running"
        self.state.current_step = 0
        self.state.min_words = config.min_words
        self.state.progress = 0.0
        self.state.error_message = ""

        try:
            client_f = self._llm_clients["model_f"]
            await self._update_progress(0, 0, message="开始章节优化...")

            # 构建所有章节的名称、简介文本
            chapters_text = ""
            for ch in outline.chapters:
                chapters_text += f"""## 第{str(ch.index).zfill(2)}章 - {ch.title}
章节简介：{ch.summary}

"""

            review_report = self.state.outline_review_report or "（无审核报告）"
            optimize_prompt = config.review_optimize_prompt or "请根据审核结果优化以下章节大纲，更新章节标题和简介。"

            combined_prompt = f"""{optimize_prompt}

待优化的章节大纲：
{chapters_text}

审核结果：
{review_report}

请根据审核结果中的建议，优化以上所有章节的标题和简介。
要求：
1. 标题要更吸睛、有悬念感
2. 每章简介必须超过100字，包含具体的情节推进、人物互动和冲突设计
3. 严格按照以下格式输出优化后的所有章节：

## 第01章 - 优化后标题
章节简介：（优化后超过100字的详细介绍）

## 第02章 - 优化后标题
章节简介：（优化后超过100字的详细介绍）

...以此类推，输出全部章节"""

            await self._broadcast("log", {
                "message": f"[章节优化] 开始一次性优化 {len(outline.chapters)} 章大纲..."
            })

            _gen = self._generation
            result = await self._call_llm_safe(
                client_f, combined_prompt, system_prompt=None,
                temperature=0.8, max_tokens=16384,
                retry_label="[章节优化] "
            )
            self._check_generation(_gen)

            if result:
                parsed = self._parse_outline_chapters(result)
                if parsed:
                    # 只保留当前范围内的章节
                    existing_indices = {ch.index for ch in outline.chapters}
                    valid = [ch for ch in parsed if ch.index in existing_indices]
                    if valid:
                        # 补充遗漏的章节
                        valid_indices = {ch.index for ch in valid}
                        for ch in outline.chapters:
                            if ch.index not in valid_indices:
                                valid.append(ch)
                        valid.sort(key=lambda c: c.index)
                        valid = self._deduplicate_outline_chapters(valid)

                        new_outline = OutlineResult(
                            title=outline.title,
                            chapters=valid,
                        )
                        self.state.optimized_outline = new_outline
                        self.state.outline_review_report = ""

                        # 同步更新 state.chapters 中的 title 和 summary
                        ch_map = {ch.index: ch for ch in self.state.chapters}
                        for oc in valid:
                            if oc.index in ch_map:
                                ch_map[oc.index].title = oc.title
                                ch_map[oc.index].summary = oc.summary

                        # 广播更新
                        for ch in valid:
                            await self._broadcast("chapter_outline", {
                                "index": ch.index,
                                "title": ch.title,
                                "summary": ch.summary,
                                "step": "outline_optimized",
                                "outline_optimized": True,
                            })

                        await self._broadcast("log", {
                            "message": f"[章节优化] 优化完成，共更新 {len(valid)} 章的标题和简介"
                        })
                    else:
                        await self._broadcast("log", {
                            "message": "[章节优化] 解析结果未包含有效章节，保留原大纲"
                        })
                else:
                    await self._broadcast("log", {
                        "message": "[章节优化] 无法解析优化结果，保留原大纲"
                    })
            else:
                await self._broadcast("log", {
                    "message": "[章节优化] 优化返回为空，保留原大纲"
                })

            self.state.status = "idle"
            self.state.current_step = 0
            self.state.progress = 100.0
            await self._broadcast("complete", {
                "message": "章节优化完成！",
                "state": self.state.model_dump(),
            })

        except asyncio.CancelledError:
            if self.state.status != "cancelled":
                self.state.status = "cancelled"
                await self._broadcast("error", {"message": "章节优化已取消", "state": self.state.model_dump()})
        except Exception as e:
            self.state.status = "error"
            self.state.error_message = str(e)
            await self._broadcast("error", {"message": str(e), "state": self.state.model_dump()})
            import traceback
            traceback.print_exc()

    async def start_generate_chapters(self, config: PipelineConfig):
        """仅运行正文生成（需先完成大纲）"""
        outline = self.state.optimized_outline or self.state.outline
        if not outline or not outline.chapters:
            raise ValueError("大纲尚未提交，请先提交大纲")

        self._generation += 1
        self._init_clients(config)
        self._last_config = config
        self._cancelled = False
        self._pause_event.set()
        self.state.status = "running"
        self.state.current_step = 1  # 正文生成
        self.state.outline_review_report = ""
        self.state.min_words = config.min_words
        self.state.plot = config.plot

        # 初始化记忆系统（安全，已有文件会跳过）
        self._init_memory(config)
        self.state.progress = 0.0
        self.state.error_message = ""
        self._custom_content_prompt = config.content_gen_prompt or None

        try:
            await self._broadcast("progress", {"message": "开始逐章正文生成..."})

            await self._step_generate_chapters()
            if self._cancelled:
                return

            # 正文生成完成
            self.state.status = "idle"
            self.state.current_step = 1
            await self._broadcast("complete", {
                "message": "正文生成完成！请点击「正文审核」进行审核。",
                "state": self.state.model_dump(),
            })

        except asyncio.CancelledError:
            if self.state.status != "cancelled":
                self.state.status = "cancelled"
                await self._broadcast("error", {
                    "message": "正文生成已取消",
                    "state": self.state.model_dump(),
                })
        except Exception as e:
            self.state.status = "error"
            self.state.error_message = str(e)
            await self._broadcast("error", {
                "message": str(e),
                "state": self.state.model_dump(),
            })
            import traceback
            traceback.print_exc()

    async def start_review_chapters(self, config: PipelineConfig):
        """仅运行正文审核（需先有已生成的正文）"""
        if not self.state.chapters:
            raise ValueError("没有已生成的章节，请先执行正文生成")
        if not any(ch.content and ch.content.strip() for ch in self.state.chapters):
            raise ValueError("没有包含有效正文的章节，请先执行正文生成")

        self._generation += 1
        self._init_clients(config)
        self._last_config = config
        self._cancelled = False
        self._pause_event.set()
        self.state.status = "running"
        self.state.current_step = 2  # 正文审核
        self.state.min_words = config.min_words
        self.state.progress = 0.0
        self.state.error_message = ""

        try:
            # 使用正文审核提示词（如果有）
            self._custom_review_prompt = config.review_optimize_prompt or None
            await self._broadcast("progress", {"message": "开始逐章正文审核..."})

            await self._step_review_chapters()
            if self._cancelled:
                return

            # 正文审核完成
            self.state.status = "idle"
            self.state.current_step = 2
            await self._broadcast("complete", {
                "message": "正文审核完成！请点击「正文优化」进行优化。",
                "state": self.state.model_dump(),
            })

        except asyncio.CancelledError:
            if self.state.status != "cancelled":
                self.state.status = "cancelled"
                await self._broadcast("error", {
                    "message": "正文审核已取消",
                    "state": self.state.model_dump(),
                })
        except Exception as e:
            self.state.status = "error"
            self.state.error_message = str(e)
            await self._broadcast("error", {
                "message": str(e),
                "state": self.state.model_dump(),
            })
            import traceback
            traceback.print_exc()
        finally:
            self._custom_review_prompt = None

    async def start_optimize_chapters(self, config: PipelineConfig):
        """正文优化：逐章优化，每个章节附带历史所有章节的正文作为上下文"""
        if not self.state.chapters:
            raise ValueError("没有已生成的章节，请先执行正文生成")
        if not any(ch.review_report and ch.review_report.strip() for ch in self.state.chapters):
            raise ValueError("没有已审核的章节，请先执行正文审核")

        self._generation += 1
        self._init_clients(config)
        self._last_config = config
        self._cancelled = False
        self._pause_event.set()
        self.state.status = "running"
        self.state.current_step = 3  # 正文优化
        self.state.min_words = config.min_words
        self.state.progress = 0.0
        self.state.error_message = ""

        try:
            client_c = self._llm_clients["model_c"]
            chapters = sorted(self.state.chapters, key=lambda c: c.index)
            outline = self.state.optimized_outline or self.state.outline
            total = len(chapters)

            # 正文生成提示词作为基础
            optimize_base_prompt = config.content_gen_prompt or config.review_optimize_prompt or ""
            system_prompt = optimize_base_prompt if optimize_base_prompt else f"""你是一位资深网文优化编辑，请根据审核报告逐条修改问题，输出优化后的章节正文。

优化要求：
- 保留故事框架和核心情节
- 逐条落实审核报告中的修改建议
- 优化后用词更精准、句式更丰富
- 字数不低于{config.min_words}字
- 不要重复上一章已发生的情节"""

            await self._broadcast("log", {
                "message": f"[正文优化] 开始逐章优化共 {total} 章..."
            })

            for i, chapter in enumerate(chapters):
                await self._check_pause()
                if self._cancelled:
                    return

                idx = chapter.index
                await self._update_progress(3, (i / total) * 100,
                                            message=f"正在优化第{idx}章: {chapter.title}（{i+1}/{total}）")

                # 构建历史所有已优化章节的正文作为上下文
                history_text = ""
                for prev_ch in chapters:
                    if prev_ch.index >= idx:
                        break
                    prev_body = prev_ch.optimized_content or prev_ch.content
                    if prev_body and not prev_body.startswith("["):
                        history_text += f"""
##### 第{prev_ch.index}章 - {prev_ch.title} 正文
{prev_body[:3000] if len(prev_body) > 3000 else prev_body}

"""

                user_prompt = f"""当前待优化章节：
第{idx}章 - {chapter.title}
章节简介：{chapter.summary}

历史已优化章节正文：
{history_text if history_text else "（尚无已优化章节）"}

待优化章节原始正文：
{chapter.content[:8000] if len(chapter.content) > 8000 else chapter.content}

该章节审核报告：
{chapter.review_report[:2000] if chapter.review_report and len(chapter.review_report) > 2000 else (chapter.review_report or '（无审核报告）')}

请根据审核报告逐条优化当前章节的正文。保留故事框架和核心情节，优化后用词更精准、句式更丰富、画面感更强。
字数不低于{config.min_words}字。不要重复历史章节已发生的情节，直接从当前章节剧情推进。
直接输出优化后的完整章节正文。"""

                _gen = self._generation
                result = await self._call_llm_safe(
                    client_c, user_prompt, system_prompt=system_prompt,
                    temperature=0.8, max_tokens=32768,
                    retry_label=f"[正文优化] 第{idx}章 "
                )
                self._check_generation(_gen)

                if result and len(result) > 100:
                    chapter.optimized_content = result.strip()
                    await self._broadcast("log", {
                        "message": f"[正文优化] 第{idx}章优化完成（{len(result)}字）"
                    })
                else:
                    await self._broadcast("log", {
                        "message": f"[警告] 第{idx}章优化结果为空或太短，保留原始内容"
                    })

                await self._broadcast("optimize_result", {
                    "index": idx,
                    "title": chapter.title,
                    "has_optimized": bool(chapter.optimized_content),
                    "progress": ((i + 1) / total) * 100,
                })

                self._save_state_to_disk()

            self.state.status = "completed"
            self.state.progress = 100.0
            self.state.current_step = 3
            await self._broadcast("complete", {
                "message": "正文优化全部完成！",
                "state": self.state.model_dump(),
            })

        except asyncio.CancelledError:
            if self.state.status != "cancelled":
                self.state.status = "cancelled"
                await self._broadcast("error", {
                    "message": "正文优化已取消",
                    "state": self.state.model_dump(),
                })
        except Exception as e:
            self.state.status = "error"
            self.state.error_message = str(e)
            await self._broadcast("error", {
                "message": str(e),
                "state": self.state.model_dump(),
            })
            import traceback
            traceback.print_exc()

    def submit_manual_outline(self, outline_text: str, total_chapters: int, min_words: int, plot: str = ""):
        """提交用户手动输入的大纲，解析并存入 state"""
        import json
        import os

        # 解析大纲文本
        outline = self._parse_outline(outline_text, total_chapters)
        outline.raw_text = outline_text
        self.state.outline = outline
        self.state.optimized_outline = None   # 清除可能残留的旧优化大纲
        self.state.chapters = []              # 清除可能残留的旧章节数据
        self.state.outline_review_report = ""  # 清除旧审核报告
        self.state.total_chapters = total_chapters
        self.state.min_words = min_words
        self.state.plot = plot
        self.state.current_step = 1  # 直接跳到正文生成步骤
        # 大纲审核不是必须的，提交后可直接进行正文生成

        # 自动保存状态到磁盘，防止刷新或服务器重启丢失
        self._save_state_to_disk()

    async def start_manual_outline_review(self, config: PipelineConfig):
        """仅运行步骤0-1：大纲审核 (Model B) + 大纲优化 (Model A)
        用户手动输入大纲后，调用此方法进行审核和优化
        """
        if not self.state.outline or not self.state.outline.chapters:
            raise ValueError("大纲尚未提交，请先输入并提交大纲")

        self._generation += 1
        self._init_clients(config)
        self._last_config = config
        self._cancelled = False
        self._pause_event.set()
        self.state.status = "running"
        self.state.current_step = 0
        self.state.progress = 0.0
        self.state.error_message = ""

        await self._broadcast("log", {"message": "开始大纲审核流程..."})

        try:
            # Step 0+1: 按批交错进行大纲审核和优化（审核一批→优化一批→下一批）
            await self._step_review_and_optimize_interleaved()
            if self._cancelled:
                return

            # 完成后回到 idle 状态，步骤指示器停在 current_step=2（正文生成）
            self.state.status = "idle"
            self.state.current_step = 3  # 正文生成
            self.state.progress = 0.0
            # 保存状态到磁盘，防止刷新丢失
            self._save_state_to_disk()
            await self._broadcast("complete", {
                "message": "大纲审核与优化完成！可以开始正文生成。",
                "state": self.state.model_dump(),
            })

        except asyncio.CancelledError:
            if self.state.status != "cancelled":
                self.state.status = "cancelled"
                await self._broadcast("error", {
                    "message": "大纲审核已取消",
                    "state": self.state.model_dump(),
                })
        except Exception as e:
            self.state.status = "error"
            self.state.error_message = str(e)
            await self._broadcast("error", {
                "message": str(e),
                "state": self.state.model_dump(),
            })
            import traceback
            traceback.print_exc()

    def pause(self):
        """暂停流水线"""
        self._pause_event.clear()
        self.state.status = "paused"
        asyncio.create_task(self._broadcast("progress", {
            "state": self.state.model_dump(),
            "message": "流水线已暂停",
        }))

    def resume(self):
        """恢复流水线"""
        self._pause_event.set()
        self.state.status = "running"
        asyncio.create_task(self._broadcast("progress", {
            "state": self.state.model_dump(),
            "message": "流水线已恢复",
        }))

    def cancel(self):
        """取消流水线"""
        self._cancelled = True
        self.state.status = "cancelled"
        asyncio.create_task(self._broadcast("error", {
            "state": self.state.model_dump(),
            "message": "流程已取消",
        }))

    def _save_state_to_disk(self):
        """保存当前流水线状态到磁盘，防止刷新/重启丢失"""
        import json
        import os

        output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
        os.makedirs(output_dir, exist_ok=True)
        state_path = os.path.join(output_dir, "pipeline_state.json")
        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(self.state.model_dump(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[save_state] 保存失败: {e}")

    @staticmethod
    def _try_restore_state_from_disk(state_obj) -> bool:
        """尝试从磁盘恢复流水线状态（用于服务器重启后自动恢复）"""
        import json
        import os

        output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
        state_path = os.path.join(output_dir, "pipeline_state.json")
        if not os.path.exists(state_path):
            return False

        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 使用 Pydantic 模型反序列化（确保嵌套模型正确实例化）
            restored = state_obj.__class__(**data)
            restored.status = "idle"

            # 状态迁移：各种旧版格式 → 新版4步states
            NEW_STEPS = ["大纲优化", "正文生成", "正文审核", "正文优化"]
            if len(restored.step_names) == 4:
                # 旧4步states: ["大纲生成", "大纲审核", "正文生成", "正文审核"]
                old_step = restored.current_step
                restored.step_names = list(NEW_STEPS)
                mapping = {0: 0, 1: 0, 2: 1, 3: 2}  # 旧→新
                restored.current_step = mapping.get(old_step, old_step)
                restored.outline_review_report = ""
                print(f"[恢复] 已迁移旧版4步状态: step {old_step} → {restored.current_step}")
            elif len(restored.step_names) == 5:
                # 旧5步states: ["大纲审核", "大纲优化", "正文生成", "正文审核", "正文优化"]
                old_step = restored.current_step
                restored.step_names = list(NEW_STEPS)
                mapping = {0: 0, 1: 0, 2: 1, 3: 2, 4: 3}
                restored.current_step = mapping.get(old_step, old_step)
                print(f"[恢复] 已迁移旧版5步状态: step {old_step} → {restored.current_step}")
            elif len(restored.step_names) == 6:
                # 旧6步states: ["大纲生成", "大纲审核", "大纲优化", "正文生成", "正文审核", "正文优化"]
                old_step = restored.current_step
                restored.step_names = list(NEW_STEPS)
                mapping = {0: 0, 1: 0, 2: 0, 3: 1, 4: 2, 5: 3}
                restored.current_step = mapping.get(old_step, old_step)
                print(f"[恢复] 已迁移旧版6步状态: step {old_step} → {restored.current_step}")

            # 逐个属性赋值到目标对象
            for key in restored.model_dump():
                if hasattr(state_obj, key):
                    setattr(state_obj, key, getattr(restored, key))
            print(f"[恢复] 已从磁盘恢复流水线状态: {len(data.get('chapters', []))} 章")
            return True
        except Exception as e:
            print(f"[恢复] 自动恢复失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _format_outline_batch(self, chapters: List[ChapterOutline], title: str) -> str:
        """格式化一批大纲章节为文本"""
        lines = [f"小说标题：《{title}》", ""]
        for ch in chapters:
            lines.append(f"## 第{str(ch.index).zfill(2)}章 - {ch.title}")
            lines.append(f"章节简介：{ch.summary}")
            lines.append("")
        return "\n".join(lines)

    async def _step_review_and_optimize_interleaved(self):
        """按批交错执行大纲审核和优化：审核一批 → 优化一批 → 下一批
        不同于原先全部审核完再全部优化的方案，此方法逐批进行，
        减少等待时间，且优化时能更聚焦于对应批次的审核建议。
        """
        if not self.state.outline or not self.state.outline.chapters:
            raise ValueError("大纲尚未生成，无法审核")

        client_review = self._llm_clients["model_b"]
        client_optimize = self._llm_clients["model_a"]

        chapters_in = self.state.outline.chapters
        total = len(chapters_in)
        BATCH_SIZE = 10
        num_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

        review_system_prompt = _make_outline_review_prompt()
        optimize_system_prompt = _make_outline_optimize_prompt()

        all_optimized: List[ChapterOutline] = []

        for batch in range(num_batches):
            await self._check_pause()
            if self._cancelled:
                return

            start_idx = batch * BATCH_SIZE
            end_idx = min(start_idx + BATCH_SIZE, total)
            batch_chapters = chapters_in[start_idx:end_idx]

            ch_start = batch_chapters[0].index
            ch_end = batch_chapters[-1].index

            # ---- 审核当前批次 (Model B) ----
            await self._update_progress(1, (batch / num_batches) * 100.0,
                                        message=f"正在审核大纲 第{batch+1}/{num_batches}批（第{ch_start}-{ch_end}章）...")

            prev_ctx = ""
            if start_idx > 0:
                prev = chapters_in[start_idx - 1]
                prev_ctx = f"上一章（仅参考，不要修改）：\n## 第{str(prev.index).zfill(2)}章 - {prev.title}\n章节简介：{prev.summary}\n\n"

            review_prompt = f"""请审核以下大纲（第{ch_start}章至第{ch_end}章）：

{prev_ctx}{self._format_outline_batch(batch_chapters, self.state.outline.title)}

要求：
1. 仔细检查每一章的简介是否足够详细（必须超过100字），不足的需明确指出
2. 检查章节间的逻辑衔接是否合理
3. 检查情节节奏是否有问题
4. 针对每个问题给出具体的修改建议
5. 只输出审核报告，不要输出优化后的章节内容"""

            await self._broadcast("log", {
                "message": f"正在调用API审核大纲（第{ch_start}-{ch_end}章，等待模型响应）..."
            })

            _gen = self._generation
            review_result = await self._call_llm_safe(
                client_review, review_prompt, system_prompt=review_system_prompt,
                temperature=0.7, max_tokens=8192,
                retry_label=f"[大纲审核] 第{ch_start}-{ch_end}章 "
            )
            self._check_generation(_gen)

            # 存储当前批次的审核报告（供优化用），覆盖前一批次
            if review_result:
                self.state.outline_review_report = f"## 第{ch_start}-{ch_end}章审核报告\n\n{review_result}"

            # 广播：当前批次大纲已审核（标记状态）
            for ch in batch_chapters:
                await self._broadcast("chapter_outline", {
                    "index": ch.index,
                    "title": ch.title,
                    "summary": ch.summary,
                    "step": "outline_reviewed",
                })

            if self._cancelled:
                return

            # ---- 优化当前批次 (Model A)，使用刚生成的审核报告 ----
            await self._update_progress(2, (batch / num_batches) * 100.0,
                                        message=f"正在优化大纲 第{batch+1}/{num_batches}批（第{ch_start}-{ch_end}章）...")

            prompt = f"""请根据审核报告中的建议，优化以下大纲（第{ch_start}章至第{ch_end}章）：

{prev_ctx}{self._format_outline_batch(batch_chapters, self.state.outline.title)}

审核报告中的建议（请逐条参考）：
{self.state.outline_review_report}

要求：
1. 优化章节标题，使其更吸引人
2. [必须]扩充章节简介，每章严格超过100字（目标150-200字），包含具体情节推进、人物互动和冲突设计
3. 调整情节节奏，确保有起承转合
4. **必须实际修改标题和简介**，不要复制原文
5. 只输出当前批次的章节，严格按照以下格式输出：

## 第XX章 - 章节标题
章节简介：（优化后超过100字的详细介绍）

（以此类推）"""

            await self._broadcast("log", {
                "message": f"正在调用API优化大纲（第{ch_start}-{ch_end}章，等待模型响应）..."
            })

            _gen = self._generation
            optimize_result = await self._call_llm_safe(
                client_optimize, prompt, system_prompt=optimize_system_prompt,
                temperature=0.8, max_tokens=8192,
                retry_label=f"[大纲优化] 第{ch_start}-{ch_end}章 "
            )
            self._check_generation(_gen)

            parsed = []
            if optimize_result:
                parsed = self._parse_outline_chapters(optimize_result)
            # 过滤：只保留本批次范围
            parsed = [ch for ch in parsed if ch_start <= ch.index <= ch_end]

            if not parsed:
                # 解析失败，保留原章节
                all_optimized.extend(batch_chapters)
            else:
                # 补充遗漏的章节
                parsed_indices = {ch.index for ch in parsed}
                for ch in batch_chapters:
                    if ch.index not in parsed_indices:
                        parsed.append(ch)
                parsed.sort(key=lambda c: c.index)
                all_optimized.extend(parsed)

            # 广播优化后的大纲
            for ch in (parsed if parsed else batch_chapters):
                await self._broadcast("chapter_outline", {
                    "index": ch.index,
                    "title": ch.title,
                    "summary": ch.summary,
                    "step": "outline_optimized",
                    "outline_optimized": True,
                })

            # 每批完成后保存状态到磁盘（防止热重载/崩溃导致进度丢失）
            self._save_state_to_disk()

        # 所有批次完成后，设置优化后的大纲
        all_optimized = self._deduplicate_outline_chapters(all_optimized)
        outline = OutlineResult(
            title=self.state.outline.title,
            chapters=all_optimized,
        )
        self.state.optimized_outline = outline
        self.state.outline_review_report = ""  # 清理审核报告

        await self._update_progress(2, 100.0, message=f"大纲优化完成，共{len(all_optimized)}章")

    # ---- 步骤4: 正文审核 ----

    async def _review_single_chapter(
        self, client, chapter, idx, total, outline,
        memory, prev_end,
    ):
        """审核单个章节（只审核，不优化），返回 (review_report, state_update_text)"""
        system_prompt = getattr(self, '_custom_review_prompt', None) or _make_review_only_system_prompt()

        prompt = self._build_review_only_prompt(
            chapter, idx, outline, memory, prev_end
        )

        _gen = self._generation
        result = await self._call_llm_safe(
            client, prompt, system_prompt=system_prompt,
            temperature=0.7, max_tokens=4096,
            retry_label=f"[正文审核] 第{idx}章 "
        )

        self._check_generation(_gen)

        if result is None:
            return None, ""

        review_report, state_update_text = self._parse_review_only_result(result)

        return review_report, state_update_text

    async def _optimize_single_chapter(
        self, client, chapter, idx, total, outline,
        memory, prev_end, is_retry=False,
    ):
        """根据审核报告优化单个章节"""
        if is_retry:
            system_prompt = _make_optimize_force_rewrite_prompt(self.state.min_words)
        else:
            system_prompt = _make_content_optimize_prompt(self.state.min_words)

        prompt = self._build_optimize_prompt(
            chapter, idx, outline, memory, prev_end
        )

        _gen = self._generation
        result = await self._call_llm_safe(
            client, prompt, system_prompt=system_prompt,
            temperature=0.8, max_tokens=32768,
            retry_label=f"[正文优化] 第{idx}章{'（强制重写）' if is_retry else ''} "
        )

        self._check_generation(_gen)

        if result is None:
            return None

        optimized_content = result.strip()

        # 校验优化内容是否真的被修改了
        if not is_retry and chapter.content:
            similarity = self._calc_text_similarity(optimized_content, chapter.content)
            if similarity > 0.85:
                await self._broadcast("log", {
                    "message": f"[警告] 第{idx}章优化内容与原文相似度{similarity:.0%}，正在强制要求重写..."
                })
                retry_result = await self._optimize_single_chapter(
                    client, chapter, idx, total, outline,
                    memory, prev_end, is_retry=True,
                )
                if retry_result:
                    retry_similarity = self._calc_text_similarity(retry_result, chapter.content)
                    if retry_similarity < 0.85:
                        optimized_content = retry_result
                        await self._broadcast("log", {
                            "message": f"[完成] 第{idx}章重写成功，相似度降至{retry_similarity:.0%}"
                        })
                    else:
                        await self._broadcast("log", {
                            "message": f"[警告] 第{idx}章强制重写后相似度仍为{retry_similarity:.0%}，使用第一次结果"
                        })

        return optimized_content

    def _calc_text_similarity(self, text1: str, text2: str) -> float:
        """计算两段文本的相似度（基于字符级别的简单比较）"""
        if not text1 or not text2:
            return 0.0
        # 取较短的文本长度
        min_len = min(len(text1), len(text2))
        if min_len == 0:
            return 0.0
        # 比较开头的字符重合度
        same = sum(1 for a, b in zip(text1[:min_len], text2[:min_len]) if a == b)
        return same / min_len

    def _build_review_only_prompt(self, chapter, idx, outline, memory, prev_end):
        """构建审核 prompt（只审核，不优化）"""
        # 只保留非空的记忆段
        mem_parts = []
        for label, key in [
            ("人物状态", "characters"),
            ("单位状态", "organizations"),
            ("物品状态", "items"),
            ("人物身体状态", "body_status"),
            ("主角财物状态", "finance"),
            ("功法状态", "skills"),
            ("武器状态", "weapons"),
            ("其他物品状态", "other_items"),
            ("关键设定与事实", "key_settings"),
        ]:
            val = memory.get(key, "").strip()
            if val and val not in ("（暂无）", "（待首次审核后更新）", ""):
                mem_parts.append(f"### {label}\n{val}")

        prompt = f"""请对以下小说章节进行审核（只审核，不输出优化文本）。

## 章节信息

小说标题：{outline.title if outline else ""}
章节：第{idx}章 - {chapter.title}
章节简介：{chapter.summary}

## 当前系统状态（来自记忆系统）

### 处理进度
- 已优化章节: {memory.get('optimized_chapter', '无')}
- 待优化章节: {memory.get('pending_chapter', '未知')}

### 当前时间线
- 当前章节: {memory.get('current_chapter', '未知')}
- 故事时间: {memory.get('story_time', '未知')}
- 故事地点: {memory.get('story_location', '未知')}

{chr(10).join(mem_parts)}

### 上一章结尾状态（仅作参考）
- 时间: {prev_end.get('time', '无')}
- 地点: {prev_end.get('location', '无')}
- 在场人物: {prev_end.get('characters', '无')}
- 关键情节进展: {prev_end.get('plot_progress', '无')}
- 关键物品和信息状态: {prev_end.get('item_info_status', '无')}

## 跨章一致性检查要求

● 本章内容不得与前面任何章节的情节重复。
● **【关键】检查本章内部是否存在自身重复**：同一场景描写是否出现了两次？同一段对话或相同含义的信息是否反复出现？
● 时间线必须连贯。
● 人物对已知信息的认知必须保持连贯。
● 设定统一性：宗门名称、功法名称、人物关系、等级体系等核心设定在全书中必须统一。
● 实体一致性：检查本章中出现的每一个已知实体（人物、宗门、物品）是否与记忆系统中的记录完全一致。

## 待处理章节正文

{chapter.content[:8000] if len(chapter.content) > 8000 else chapter.content}

请严格按照输出格式要求，先输出审核报告，再输出状态更新。不要输出优化文本。"""
        return prompt

    def _build_optimize_prompt(self, chapter, idx, outline, memory, prev_end):
        """构建优化 prompt（根据审核报告优化章节）"""
        review_report = chapter.review_report or "（无审核报告）"
        # 截断审核报告到1500字，避免输入过长影响输出质量
        if len(review_report) > 1500:
            review_report = review_report[:1500] + "\n\n...（审核报告已截断，请重点解决以上列出的关键问题）"

        # 只取非空的关键设定，缩减prompt
        key_settings = memory.get('key_settings', '（暂无）')
        if key_settings and key_settings.strip() == '（暂无）':
            key_settings = ''

        prompt = f"""请根据以下审核报告中的建议，优化修改小说章节正文。

## 章节信息

小说标题：{outline.title if outline else ""}
章节：第{idx}章 - {chapter.title}
章节简介：{chapter.summary}

## 审核报告（需根据以下建议逐条优化）

{review_report}

## 当前系统状态

- 故事时间: {memory.get('story_time', '未知')}
- 故事地点: {memory.get('story_location', '未知')}

### 人物状态
{memory.get('characters', '（暂无）')}

### 关键设定与事实
{key_settings}

### 上一章结尾状态（仅参考，切勿重复描写）
- 时间: {prev_end.get('time', '无')}
- 地点: {prev_end.get('location', '无')}
- 在场人物: {prev_end.get('characters', '无')}
- 关键情节进展: {prev_end.get('plot_progress', '无')}

## 原始章节正文

{chapter.content[:8000] if len(chapter.content) > 8000 else chapter.content}

## 要求
1. 【必须】保留原文的故事框架和核心情节
2. 根据审核报告逐条修改问题（不要忽略任何一条建议）
3. **【关键】检查并删除本章内部重复的内容**：同一场景描写、同一段对话、同一信息点在全文内出现两次的，只保留第一次，其余删除。
4. **【关键】优化时不要重复描写上一章已发生的情节**，直接从新剧情切入。不要在开头重新描述前因后果，一句话过渡即可。
5. 优化后的字数不低于{self.state.min_words}字，不超过{MAX_CHAPTER_WORDS}字
6. 结尾保留原有的悬念或钩子
7. 【沉浸式叙事】用动作、神态、环境暗示心理，删除直接的情绪形容词
8. 【感官细节】补充至少3处气味、温度或声音的细腻描写（每处角度不同，不得重复）
9. 【去AI化】删除"总而言之""仿佛"等AI高频词汇，删除结尾价值升华，优化对话使其符合人物身份
10. 【句式节奏】长短句交错，拆除工整排比句，让阅读节奏有起伏
11. 【风格】冷峻克制，像镜头一样客观记录，不替读者做情感总结

请直接输出优化后的完整章节正文，不要包含"第X章"标题前缀。"""
        return prompt

    def _build_generation_prompt(self, ch_outline, idx, outline, memory, prev_end,
                                  prev_content="", plot_text="",
                                  prev_chapters_content=""):
        """构建带记忆上下文和剧情大纲的正文章节生成 prompt"""
        context_prompt = ""
        if prev_content:
            # 只取前200字给模型参考衔接，避免重复上一章内容
            prev_short = prev_content[:200]
            context_prompt = f"\n上一章末尾200字衔接参考：\n{prev_short}\n"

        # 小说总体剧情/大纲区块
        plot_section = ""
        if plot_text and plot_text.strip():
            plot_section = f"""
## 小说总体剧情/大纲（全局参考，必须保持一致）
{plot_text.strip()}

"""

        # 前文参考区块（上一章正文）
        prev_chapters_section = ""
        if prev_chapters_content and prev_chapters_content.strip():
            prev_chapters_section = f"""
## 前文参考（最近3章正文，供情节连续性参考）
{prev_chapters_content.strip()}

"""

        # 前面所有已生成章节的标题列表
        prev_titles_section = ""
        if outline and outline.chapters:
            prev_titles = []
            for prev_ch in outline.chapters:
                if prev_ch.index < idx:
                    prev_titles.append(f"第{str(prev_ch.index).zfill(2)}章 - {prev_ch.title}")
            if prev_titles:
                prev_titles_section = f"""
## 前面已生成章节列表
{'、'.join(prev_titles)}

"""

        memory_context = ""
        if memory:
            story_time = memory.get("story_time", "未知")
            story_location = memory.get("story_location", "未知")

            prev_time = prev_end.get("time", "无")
            prev_location = prev_end.get("location", "无")
            prev_chars = prev_end.get("characters", "无")
            prev_plot = prev_end.get("plot_progress", "无")
            prev_items = prev_end.get("item_info_status", "无")

            # 只包含非空的记忆段落，缩减prompt长度
            mem_parts = []
            for label, key in [
                ("人物状态", "characters"),
                ("单位状态", "organizations"),
                ("人物身体状态", "body_status"),
                ("主角财物状态", "finance"),
                ("功法状态", "skills"),
                ("武器状态", "weapons"),
                ("物品状态", "items"),
                ("其他物品状态", "other_items"),
                ("关键设定与事实", "key_settings"),
            ]:
                val = memory.get(key, "").strip()
                if val and val not in ("（暂无）", "（待首次审核后更新）", ""):
                    mem_parts.append(f"### {label}\n{val}")

            memory_context = f"""
## 当前故事状态（已审核章节记录，必须保持一致）
- 故事时间: {story_time}
- 故事地点: {story_location}

{chr(10).join(mem_parts)}

### 上一章结尾状态（仅参考衔接，切勿重复描写）
- 时间: {prev_time}
- 地点: {prev_location}
- 在场人物: {prev_chars}
- 关键情节进展: {prev_plot}
- 关键物品和信息状态: {prev_items}
"""

        prompt = f"""请根据以下大纲信息，撰写小说的第{idx}章。

小说标题：{outline.title}
本章标题：{ch_outline.title}
本章简介：{ch_outline.summary}
{plot_section}
{prev_chapters_section}
{prev_titles_section}
{context_prompt}
{memory_context}
## 创作前的记忆检查（必须执行）
1. **阅读小说总体剧情**：仔细阅读上方"小说总体剧情/大纲"部分，确保本章情节与全书走向保持一致。
2. **阅读前文正文**：仔细阅读上方"前文参考"中上一章的正文，确保本章的情节、人物状态、时间线和前文无缝衔接，没有逻辑矛盾。
3. **阅读当前故事状态**：仔细阅读上方"当前故事状态"中的所有信息——时间线、人物状态、单位状态、物品状态、功法等。你的正文必须与这些已记录的状态保持完全一致，不得冲突。
4. **阅读上一章结尾状态**：仔细检查上一章结束时的时间、地点、在场人物、关键情节进展。你的本章开头必须从这些状态自然衔接，不能跳跃或忽略。
5. **检查人物状态一致性**：出场人物的状态（位置、健康、修为）必须与上方记录一致。如果某人物在上章结尾受了重伤，本章开头不能突然活蹦乱跳。

## 与上一章的衔接要求（重点）
- 开头用**一句话**自然过渡（如"翌日清晨，..."或"三日后，..."），不要重复描写上一章已发生的情节
- 时间线必须连贯：检查上一章结束的时间点，然后合理推进
- 人物状态必须延续：上一章结尾的人物位置、状态就是本章的起点
- 不得出现逻辑破绽：如上一章人物在甲地，本章开头不能无理由地在乙地

## 写作要求
- 字数{self.state.min_words}~{MAX_CHAPTER_WORDS}字
- 严格按照章节简介展开情节
- 严禁本章内部内容重复
- 结尾留有悬念
- 展示而非讲述
- 至少3处感官描写（气味/温度/声音）

直接输出小说正文，不要输出任何创作说明或分析。
"""
        return prompt

    async def _step_generate_chapters(self):
        """步骤：流水线式逐章生成正文（仅生成，不审核不优化）

        支持断点续传：加载已保存进度后，从已生成的最后一章之后继续生成。
        """
        outline = self.state.optimized_outline or self.state.outline
        if not outline or not outline.chapters:
            raise ValueError("无可用大纲，无法生成正文")

        client_c = self._llm_clients["model_c"]
        total = len(outline.chapters)

        # 使用自定义正文生成提示词（如果有），否则使用默认提示词
        system_prompt_c = getattr(self, '_custom_content_prompt', None) or """你是一位顶级网文作家，擅长创作精彩的传统武侠小说。
只用小说正文回答问题，不要在正文前输出任何创作说明、场景规划、节奏分析或写作思路。

## 创作前的检查
- 仔细阅读"当前故事状态"中的时间线、人物、单位、物品等记录，确保正文与已有设定完全一致
- 检查"上一章结尾状态"，确保本章开头从正确的时间、地点、人物状态自然衔接
- 不能重复上一章已展开的情节，开头一句话过渡即可
- 出场人物的状态（位置、健康、修为）必须与记录一致

## 写作要求
- 字数5000~8000字
- 严禁本章内部内容重复：同一场景、同一对话、同一信息点不得出现两次
- 结尾要有悬念或钩子
- 展示而非讲述：用动作、神态、环境暗示心理
- 感官细节：每章至少融入3处气味、温度或声音的描写
- 去AI化：禁止"总而言之""仿佛""然而""不禁"等词汇；禁止结尾议论式升华
- 句式长短交错，避免工整排比"""

        # 断点续传：找出已存在的章节索引，跳过它们
        existing_indices = {ch.index for ch in self.state.chapters
                           if ch.content and ch.content.strip() and not ch.content.startswith("[")}
        to_generate = [co for co in outline.chapters if (co.index) not in existing_indices]
        if not to_generate:
            await self._broadcast("log", {"message": "[续传] 所有章节均已生成，跳过正文生成步骤"})
            return

        if existing_indices:
            await self._broadcast("log", {
                "message": f"[续传] 检测到已有 {len(existing_indices)} 章已生成（{sorted(existing_indices)}），跳过续传"
            })

        # 初始化前文内容列表（断点续传时从已有章节中加载最后3章全文）
        initial_prev_chapters = []
        if self.state.chapters:
            sorted_chs = sorted(self.state.chapters, key=lambda c: c.index)
            for ch in sorted_chs[-3:]:
                ch_content = ch.optimized_content or ch.content
                if ch_content and not ch_content.startswith("["):
                    initial_prev_chapters.append((ch.index, ch_content))

        prev_chapters_future: asyncio.Future = asyncio.Future()
        prev_chapters_future.set_result(initial_prev_chapters)

        gen_tasks: Dict[int, asyncio.Task] = {}

        for co in to_generate:
            idx = co.index
            next_chapters_future: asyncio.Future = asyncio.Future()

            async def _pipelined_gen(co=co, idx=idx,
                                     pcf=prev_chapters_future,
                                     ncf=next_chapters_future):
                """流水线生成：等待上一章内容 → 生成本章 → 传递内容给下一章"""
                prev_chapters_list = await pcf  # list of (index, full_content)

                # 构建前3章全文上下文
                prev_chapters_text = ""
                for prev_idx, prev_content in prev_chapters_list:
                    prev_chapters_text += f"\n--- 第{prev_idx}章 正文 ---\n{prev_content}\n"

                # 兼容旧参数：上一章末尾200字
                prev_chapter_last_200 = ""
                if prev_chapters_list:
                    prev_chapter_last_200 = prev_chapters_list[-1][1][-200:]

                mem = self.memory_manager.read_memory()
                pe = mem.get("prev_chapter_end", {})

                prompt = self._build_generation_prompt(
                    co, idx, outline, mem, pe,
                    prev_content=prev_chapter_last_200,
                    plot_text=self.state.plot,
                    prev_chapters_content=prev_chapters_text,
                )

                await self._broadcast("log", {
                    "message": f"[正文] 第{idx}章 正在生成中..."
                })

                _gen = self._generation
                content = await self._call_llm_safe(
                    client_c, prompt, system_prompt=system_prompt_c,
                    temperature=0.85, max_tokens=None,
                    retry_label=f"[正文] 第{idx}章 "
                )
                self._check_generation(_gen)

                if content is None:
                    content = f"[第{idx}章生成失败，请稍后重试]"

                # 剥离GLM模型的规划/分析文字
                if content and not content.startswith("["):
                    cleaned = self._strip_planning_text(content)
                    if cleaned != content:
                        await self._broadcast("log", {
                            "message": f"[正文] 第{idx}章已剥离规划文字（{len(content)-len(cleaned)}字）"
                        })
                        content = cleaned

                # 字数检查：超长则重新生成（最多重试2次）
                if content and not content.startswith("["):
                    actual_len = len(content)
                    if actual_len > MAX_CHAPTER_WORDS:
                        for retry in range(2):
                            await self._broadcast("log", {
                                "message": f"[正文] 第{idx}章内容{actual_len}字，超过{MAX_CHAPTER_WORDS}字上限，正在重新生成（第{retry+1}次）..."
                            })
                            retry_prompt = prompt + f"\n\n【重要】你上一版生成了{actual_len}字，超过{MAX_CHAPTER_WORDS}字限制。请重新生成，确保字数不超过{MAX_CHAPTER_WORDS}字。精简冗余描写，但不要截断结尾，必须完成本章的完整情节。"
                            content = await self._call_llm_safe(
                                client_c, retry_prompt, system_prompt=system_prompt_c,
                                temperature=0.85, max_tokens=16384,
                                retry_label=f"[正文-长度重试] 第{idx}章 "
                            )
                            if content is None:
                                content = f"[第{idx}章生成失败，请稍后重试]"
                                break
                            actual_len = len(content)
                            if actual_len <= MAX_CHAPTER_WORDS:
                                await self._broadcast("log", {
                                    "message": f"[正文] 第{idx}章重新生成成功（{actual_len}字）"
                                })
                                break
                        else:
                            await self._broadcast("log", {
                                "message": f"[警告] 第{idx}章重试后仍超过{MAX_CHAPTER_WORDS}字（当前{actual_len}字），保留最终版本"
                            })

                # 更新记忆系统：从正文快速提取状态信息，为下一章提供故事连续性
                if content and not content.startswith("["):
                    try:
                        chapter_label = f"第{str(idx).zfill(2)}章"
                        next_label = f"第{str(idx + 1).zfill(2)}章"
                        total_ch = len(outline.chapters) if outline else total

                        mem_updates = await self._extract_memory_from_content(
                            client_c, content, idx, co
                        )
                        if not mem_updates:
                            mem_updates = {
                                "story_time": "（续前章）",
                                "story_location": "（续前章）",
                                "prev_chapter_end": {
                                    "time": "（续前章）",
                                    "location": "（续前章）",
                                    "characters": "（续前章出场人物）",
                                    "plot_progress": co.summary[:200] if co and co.summary else "（续前章）",
                                    "item_info_status": "（续前章）",
                                },
                            }

                        mem_updates["current_chapter"] = chapter_label
                        mem_updates["optimized_chapter"] = chapter_label
                        mem_updates["pending_chapter"] = next_label if idx < total_ch else "全部完成"
                        self.memory_manager.update_memory(mem_updates)

                        if "prev_chapter_end" in mem_updates:
                            await self._broadcast("log", {
                                "message": f"[记忆] 第{idx}章提取完成：时间={mem_updates.get('story_time','?')}，地点={mem_updates.get('story_location','?')}"
                            })
                    except Exception as e:
                        print(f"[记忆系统] 第{idx}章生成后更新记忆失败: {e}")

                # 将本章全文传递给下一章（维护最近3章的滚动列表）
                new_prev_list = list(prev_chapters_list)
                new_prev_list.append((idx, content if content else ""))
                if len(new_prev_list) > 3:
                    new_prev_list = new_prev_list[-3:]
                ncf.set_result(new_prev_list)
                return content

            gen_tasks[idx] = asyncio.create_task(_pipelined_gen())
            prev_chapters_future = next_chapters_future

        await self._broadcast("log", {
            "message": f"[流水线] 已创建 {len(to_generate)} 章生成任务，正在生成全部正文（共{total}章）..."
        })

        # 收集所有生成结果，创建章节对象
        completed_count = 0
        for co in to_generate:
            await self._check_pause()
            if self._cancelled:
                return

            idx = co.index
            content = await gen_tasks[idx]

            if content.startswith("[") and "失败" in content:
                await self._broadcast("log", {
                    "message": f"[错误] 第{idx}章正文生成失败，已跳过，稍后可手动重生成"
                })
                chapter = ChapterContent(index=idx, title=co.title, summary=co.summary, content=content)
                self.state.chapters.append(chapter)
                continue

            actual_len = len(content)
            if actual_len < self.state.min_words:
                await self._broadcast("log", {
                    "message": f"[警告] 第{idx}章正文仅{actual_len}字，低于设定值{self.state.min_words}字"
                })

            chapter = ChapterContent(
                index=idx,
                title=co.title,
                summary=co.summary,
                content=content,
            )
            self.state.chapters.append(chapter)

            await self._broadcast("chapter_content", {
                "index": idx,
                "title": co.title,
                "content_preview": content[:200] + "...",
                "progress": (idx / total) * 100,
            })
            await self._update_progress(1, (idx / total) * 100,
                                        message=f"第{idx}章正文生成完成（共{total}章）")
            completed_count += 1

        # 清理生成任务
        for task in gen_tasks.values():
            if not task.done():
                task.cancel()
        if gen_tasks:
            await asyncio.gather(*gen_tasks.values(), return_exceptions=True)

        await self._broadcast("log", {
            "message": f"[完成] 全部 {completed_count} 章正文生成完成"
        })
        # 保存状态到磁盘
        self._save_state_to_disk()

    async def _step_review_chapters(self):
        """步骤：逐章审核正文（仅审核，不生成不优化）"""
        outline = self.state.optimized_outline or self.state.outline
        if not outline or not outline.chapters:
            raise ValueError("无可用大纲")

        client_d = self._llm_clients["model_d"]
        total = len(outline.chapters)

        chapters = sorted(self.state.chapters, key=lambda c: c.index)
        if not chapters:
            await self._broadcast("log", {"message": "没有已生成的章节，跳过审核"})
            return

        for i, chapter in enumerate(chapters):
            await self._check_pause()
            if self._cancelled:
                return

            idx = chapter.index
            await self._update_progress(2, (i / total) * 100,
                                        message=f"正在审核第{idx}章: {chapter.title}（{i+1}/{total}）")

            memory = self.memory_manager.read_memory()
            prev_end = memory.get("prev_chapter_end", {})

            review_report, state_update_text = await self._review_single_chapter(
                client_d, chapter, idx, total, outline,
                memory, prev_end,
            )

            if review_report is None:
                await self._broadcast("log", {
                    "message": f"[错误] 第{idx}章审核失败，保留原始内容"
                })
                continue

            chapter.review_report = review_report

            # 更新记忆系统
            if state_update_text:
                try:
                    updates = self._parse_state_update_text(state_update_text)
                    if updates:
                        chapter_label = f"第{str(idx).zfill(2)}章"
                        next_label = f"第{str(idx + 1).zfill(2)}章" if idx < total else "全部完成"
                        updates["optimized_chapter"] = chapter_label
                        updates["pending_chapter"] = next_label
                        updates["current_chapter"] = chapter_label
                        updates["total_chapters"] = str(total)
                        self.memory_manager.update_memory(updates)
                except Exception as e:
                    print(f"[记忆系统] 第{idx}章审核状态更新失败: {e}")

            await self._broadcast("review_result", {
                "index": idx,
                "title": chapter.title,
                "review_report_preview": review_report[:300] + "..." if len(review_report) > 300 else review_report,
                "has_optimized": False,
                "progress": ((i + 1) / total) * 100,
            })

            # 每章审核后保存状态
            self._save_state_to_disk()

        await self._broadcast("log", {
            "message": f"[完成] 全部 {total} 章审核完成"
        })

    async def _step_optimize_chapters(self):
        """步骤：逐章优化正文（仅优化，假设已审核）"""
        outline = self.state.optimized_outline or self.state.outline
        if not outline or not outline.chapters:
            raise ValueError("无可用大纲")

        client_c = self._llm_clients["model_c"]
        total = len(outline.chapters)

        chapters = sorted(self.state.chapters, key=lambda c: c.index)
        if not chapters:
            await self._broadcast("log", {"message": "没有已生成的章节，跳过优化"})
            return

        for i, chapter in enumerate(chapters):
            await self._check_pause()
            if self._cancelled:
                return

            idx = chapter.index
            await self._update_progress(3, (i / total) * 100,
                                        message=f"正在优化第{idx}章: {chapter.title}（{i+1}/{total}）")

            memory = self.memory_manager.read_memory()
            prev_end = memory.get("prev_chapter_end", {})

            optimized_content = await self._optimize_single_chapter(
                client_c, chapter, idx, total, outline,
                memory, prev_end,
            )

            if optimized_content is None:
                await self._broadcast("log", {
                    "message": f"[错误] 第{idx}章优化失败，保留原始内容"
                })
                continue

            # 字数检查：超长则重新优化（最多重试1次）
            if len(optimized_content) > MAX_CHAPTER_WORDS:
                await self._broadcast("log", {
                    "message": f"[优化] 第{idx}章优化后内容{len(optimized_content)}字，超过{MAX_CHAPTER_WORDS}字上限，正在重新优化..."
                })
                retry_result = await self._optimize_single_chapter(
                    client_c, chapter, idx, total, outline,
                    memory, prev_end, is_retry=False,
                )
                if retry_result and len(retry_result) <= MAX_CHAPTER_WORDS:
                    optimized_content = retry_result
                    await self._broadcast("log", {
                        "message": f"[优化] 第{idx}章重新优化成功（{len(optimized_content)}字）"
                    })
                else:
                    await self._broadcast("log", {
                        "message": f"[警告] 第{idx}章重新优化后仍超过{MAX_CHAPTER_WORDS}字，保留当前版本"
                    })

            chapter.optimized_content = optimized_content

            # 重新读取 review 中的状态更新并写入记忆
            try:
                _, state_update_text = self._parse_review_result_v2(chapter.review_report or "")
                if state_update_text:
                    updates = self._parse_state_update_text(state_update_text)
                    if updates:
                        chapter_label = f"第{str(idx).zfill(2)}章"
                        next_label = f"第{str(idx + 1).zfill(2)}章" if idx < total else "无"
                        updates["optimized_chapter"] = chapter_label
                        updates["pending_chapter"] = next_label if next_label != "无" else "全部完成"
                        updates["current_chapter"] = chapter_label
                        updates["total_chapters"] = str(total)
                        self.memory_manager.update_memory(updates)
            except Exception as e:
                print(f"[记忆系统] 第{idx}章优化状态更新失败: {e}")

            await self._broadcast("optimize_result", {
                "index": idx,
                "title": chapter.title,
                "has_optimized": True,
                "progress": ((i + 1) / total) * 100,
            })

            # 每章完成后保存状态到磁盘
            self._save_state_to_disk()

        await self._broadcast("log", {
            "message": f"[完成] 正文优化全部完成，共处理 {len(chapters)} 章"
        })

    async def regenerate_chapters(self, chapter_indices: List[int], config: PipelineConfig):
        """重新生成指定章节的内容和审核结果"""
        # 去重、排序
        chapter_indices = sorted(set(chapter_indices))
        if not chapter_indices:
            raise ValueError("未指定章节")

        # 验证所有索引都存在
        existing = {ch.index for ch in self.state.chapters}
        for idx in chapter_indices:
            if idx not in existing:
                raise ValueError(f"章节 第{idx}章 不存在")

        # 初始化客户端
        if "model_c" not in self._llm_clients:
            self._init_clients(config)
        else:
            self._llm_clients["model_c"] = LLMClient(config.model_c, "正文生成")
            self._llm_clients["model_d"] = LLMClient(config.model_d, "正文审核")

        self._cancelled = False
        self._pause_event.set()
        self.state.status = "running"
        self.state.error_message = ""
        self._generation += 1  # 隔离新旧任务，防止旧任务残留污染
        # 保存原始 step_names，后面恢复
        _saved_step_names = list(self.state.step_names)
        self.state.step_names = ["", "正文重生成", "正文重新审核", "正文重新优化"]

        total = len(chapter_indices)

        # 保存当前 memory 文件到临时备份
        import os
        import tempfile
        memory_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory_web.md")
        memory_backup_path = ""
        if os.path.exists(memory_path):
            memory_backup_path = memory_path + ".bak"
            import shutil
            shutil.copy2(memory_path, memory_backup_path)

        client_c = self._llm_clients["model_c"]
        client_d = self._llm_clients["model_d"]
        outline = self.state.optimized_outline or self.state.outline

        try:
            for i, idx in enumerate(chapter_indices):
                await self._check_pause()

                # 找到章节对象
                chapter = next((ch for ch in self.state.chapters if ch.index == idx), None)
                if not chapter:
                    continue

                progress_base = (i / total) * 95.0

                # 先清空旧数据并广播，让前端显示"重生成中"状态
                chapter.content = ""
                chapter.optimized_content = ""
                chapter.review_report = ""
                await self._broadcast("chapter_content", {
                    "index": idx,
                    "title": chapter.title,
                    "content_preview": "",
                    "progress": (i / total) * 30,
                })

                # --- 步骤2: 重生成正文内容 ---
                await self._update_progress(1, progress_base / 3,
                                            message=f"正在重生成第{idx}章: {chapter.title}")

                # 构建最近3章全文上下文
                prev_chapters_text = ""
                prev_content_short = ""
                for offset in range(1, 4):
                    prev_idx = idx - offset
                    if prev_idx >= 1:
                        prev_ch = next((ch for ch in self.state.chapters if ch.index == prev_idx), None)
                        if prev_ch:
                            ch_content = prev_ch.optimized_content or prev_ch.content
                            if ch_content and not ch_content.startswith("["):
                                prev_chapters_text = f"\n--- 第{prev_idx}章 正文 ---\n{ch_content}\n" + prev_chapters_text
                                if offset == 1:
                                    prev_content_short = ch_content[-200:]

                # 从大纲中找本章 outline
                ch_outline = next((co for co in outline.chapters if co.index == idx), None)

                context_prompt = ""
                if prev_content_short:
                    context_prompt = f"\n上一章末尾200字衔接参考：\n{prev_content_short}\n"

                # 小说总体剧情/大纲区块
                plot_section = ""
                if self.state.plot and self.state.plot.strip():
                    plot_section = f"""
## 小说总体剧情/大纲（全局参考，必须保持一致）
{self.state.plot.strip()}

"""

                # 前文参考区块（上一章正文）
                prev_chapters_section = ""
                if prev_chapters_text:
                    prev_chapters_section = f"""
## 前文参考（最近3章正文，供情节连续性参考）
{prev_chapters_text.strip()}

"""

                # 读取记忆上下文用于生成
                mem = self.memory_manager.read_memory()
                prev_end = mem.get("prev_chapter_end", {})
                story_time = mem.get("story_time", "未知")
                story_location = mem.get("story_location", "未知")

                prev_time = prev_end.get("time", "无")
                prev_location = prev_end.get("location", "无")
                prev_chars = prev_end.get("characters", "无")
                prev_plot = prev_end.get("plot_progress", "无")
                prev_items = prev_end.get("item_info_status", "无")

                mem_parts = []
                for label, key in [
                    ("人物状态", "characters"),
                    ("单位状态", "organizations"),
                    ("人物身体状态", "body_status"),
                    ("主角财物状态", "finance"),
                    ("功法状态", "skills"),
                    ("武器状态", "weapons"),
                    ("物品状态", "items"),
                    ("其他物品状态", "other_items"),
                    ("关键设定与事实", "key_settings"),
                ]:
                    val = mem.get(key, "").strip()
                    if val and val not in ("（暂无）", "（待首次审核后更新）", ""):
                        mem_parts.append(f"### {label}\n{val}")

                memory_context = ""
                if mem_parts or story_time != "未知":
                    memory_context = f"""
## 当前故事状态（已审核章节记录，必须保持一致）
- 故事时间: {story_time}
- 故事地点: {story_location}

{chr(10).join(mem_parts)}

### 上一章结尾状态（仅参考衔接，切勿重复描写）
- 时间: {prev_time}
- 地点: {prev_location}
- 在场人物: {prev_chars}
- 关键情节进展: {prev_plot}
- 关键物品和信息状态: {prev_items}
"""

                prompt_c = f"""请根据以下大纲信息，撰写小说的第{idx}章。

小说标题：{outline.title}
本章标题：{ch_outline.title if ch_outline else chapter.title}
本章简介：{ch_outline.summary if ch_outline else chapter.summary}
{plot_section}
{prev_chapters_section}
{prev_titles_section}
{context_prompt}
{memory_context}
## 创作前的记忆检查（必须执行）
1. **阅读小说总体剧情**：仔细阅读上方"小说总体剧情/大纲"部分，确保本章情节与全书走向保持一致。
2. **阅读前文正文**：仔细阅读上方"前文参考"中上一章的正文，确保本章的情节、人物状态、时间线和前文无缝衔接，没有逻辑矛盾。
3. **阅读当前故事状态**：仔细阅读上方"当前故事状态"中的所有信息——时间线、人物状态、单位状态、物品状态、功法等。你的正文必须与这些已记录的状态保持完全一致，不得冲突。
4. **阅读上一章结尾状态**：仔细检查上一章结束时的时间、地点、在场人物、关键情节进展。你的本章开头必须从这些状态自然衔接，不能跳跃或忽略。
5. **检查人物状态一致性**：出场人物的状态（位置、健康、修为）必须与上方记录一致。

## 与上一章的衔接要求（重点）
- 开头用**一句话**自然过渡，不要重复描写上一章已发生的情节
- 时间线必须连贯：检查上一章结束的时间点，合理推进
- 人物状态必须延续：上一章结尾的人物位置、状态就是本章的起点
- 不得出现逻辑破绽

## 写作要求
- 字数{self.state.min_words}~{MAX_CHAPTER_WORDS}字
- 严格按照章节简介展开情节
- 严禁本章内部内容重复
- 结尾留有悬念
- 展示而非讲述
- 至少3处感官描写

直接输出小说正文，不要输出任何创作说明或分析。
"""

                system_prompt_c = """你是一位顶级网文作家，擅长创作精彩的传统武侠小说。
只用小说正文回答问题，不要在正文前输出任何创作说明、场景规划或写作思路。

## 创作前的检查
- 仔细阅读当前故事状态中的时间线、人物、单位、物品等记录，确保正文与已有设定完全一致
- 检查上一章结尾状态，确保本章开头从正确的时间、地点、人物状态自然衔接
- 不能重复上一章已展开的情节，开头一句话过渡即可
- 出场人物的状态（位置、健康、修为）必须与记录一致

## 写作要求
- 字数5000~8000字
- 严禁本章内部内容重复
- 结尾要有悬念或钩子
- 展示而非讲述，融入感官细节
- 去AI化，句式长短交错"""

                _gen = self._generation
                content = await self._call_llm_safe(
                    client_c, prompt_c, system_prompt=system_prompt_c,
                    temperature=0.85, max_tokens=None,
                    retry_label=f"[重生成正文] 第{idx}章 "
                )

                self._check_generation(_gen)

                if content is None:
                    await self._broadcast("log", {
                        "message": f"[错误] 重生成第{idx}章正文失败，已跳过"
                    })
                    continue

                # 剥离GLM模型的规划/分析文字
                if content and not content.startswith("["):
                    cleaned = self._strip_planning_text(content)
                    if cleaned != content:
                        await self._broadcast("log", {
                            "message": f"[重生成] 第{idx}章已剥离规划文字（{len(content)-len(cleaned)}字）"
                        })
                        content = cleaned

                # 字数检查
                actual_len = len(content)
                if actual_len < self.state.min_words:
                    await self._broadcast("log", {
                        "message": f"[警告] 重生成第{idx}章正文仅{actual_len}字，低于设定值{self.state.min_words}字"
                    })

                # 字数检查：超长则重新生成（最多重试2次）
                if content:
                    actual_len = len(content)
                    if actual_len > MAX_CHAPTER_WORDS:
                        for retry in range(2):
                            await self._broadcast("log", {
                                "message": f"[重生成] 第{idx}章内容{actual_len}字，超过{MAX_CHAPTER_WORDS}字上限，正在重新生成（第{retry+1}次）..."
                            })
                            retry_prompt = prompt_c + f"\n\n【重要】你上一版生成了{actual_len}字，超过{MAX_CHAPTER_WORDS}字限制。请重新生成，确保字数不超过{MAX_CHAPTER_WORDS}字。精简冗余描写，但不要截断结尾，必须完成本章的完整情节。"
                            content = await self._call_llm_safe(
                                client_c, retry_prompt, system_prompt=system_prompt_c,
                                temperature=0.85, max_tokens=16384,
                                retry_label=f"[重生成-长度重试] 第{idx}章 "
                            )
                            if content is None:
                                content = f"[第{idx}章生成失败，请稍后重试]"
                                break
                            actual_len = len(content)
                            if actual_len <= MAX_CHAPTER_WORDS:
                                await self._broadcast("log", {
                                    "message": f"[重生成] 第{idx}章重新生成成功（{actual_len}字）"
                                })
                                break
                        else:
                            await self._broadcast("log", {
                                "message": f"[警告] 第{idx}章重试后仍超过{MAX_CHAPTER_WORDS}字（当前{actual_len}字），保留最终版本"
                            })

                chapter.content = content

                # 更新记忆系统：从重生成的正文提取状态信息
                if content and not content.startswith("["):
                    try:
                        mem_updates = await self._extract_memory_from_content(
                            client_c, content, idx, ch_outline or chapter
                        )
                        if mem_updates:
                            chapter_label = f"第{str(idx).zfill(2)}章"
                            next_label = f"第{str(idx + 1).zfill(2)}章"
                            mem_updates["current_chapter"] = chapter_label
                            mem_updates["optimized_chapter"] = chapter_label
                            mem_updates["pending_chapter"] = next_label if idx < len(self.state.chapters) else "全部完成"
                            self.memory_manager.update_memory(mem_updates)
                            await self._broadcast("log", {
                                "message": f"[记忆] 第{idx}章重生成后记忆已更新"
                            })
                    except Exception as e:
                        print(f"[记忆系统] 第{idx}章重生成后更新记忆失败: {e}")

                # 广播
                await self._broadcast("chapter_content", {
                    "index": idx,
                    "title": chapter.title,
                    "content_preview": content[:200] + "...",
                    "progress": ((i + 1) / total) * 50,
                })

                # --- 步骤3: 重新审核（只审核，不优化） ---
                await self._update_progress(2, 50.0 + progress_base / 3,
                                            message=f"正在审核重生成后的第{idx}章: {chapter.title}")

                # 构建正确的 memory context
                memory = self.memory_manager.read_memory()
                prev_end = memory.get("prev_chapter_end", {})

                chapter_label = f"第{str(idx).zfill(2)}章"
                if idx > 1:
                    prev_label = f"第{str(idx-1).zfill(2)}章"
                    memory["optimized_chapter"] = prev_label
                    memory["current_chapter"] = chapter_label
                    memory["pending_chapter"] = chapter_label

                    # 从上一章的审核结果中提取上一章结尾状态
                    prev_ch = next((ch for ch in self.state.chapters if ch.index == idx - 1), None)
                    if prev_ch and prev_ch.review_report:
                        _, _, state_update_text = self._parse_review_result_v2(prev_ch.review_report)
                        if state_update_text:
                            prev_updates = self._parse_state_update_text(state_update_text)
                            if "prev_chapter_end" in prev_updates:
                                prev_end = prev_updates["prev_chapter_end"]
                else:
                    memory["optimized_chapter"] = "无"
                    memory["current_chapter"] = "第01章"
                    memory["pending_chapter"] = "第01章"

                review_report, state_update_text = await self._review_single_chapter(
                    client_d, chapter, idx, total, outline,
                    memory, prev_end,
                )

                if review_report is None:
                    await self._broadcast("log", {
                        "message": f"[错误] 第{idx}章重审失败，保留原始内容"
                    })
                    continue

                chapter.review_report = review_report

                # 广播审核结果（标记尚未优化）
                await self._broadcast("review_result", {
                    "index": idx,
                    "title": chapter.title,
                    "review_report_preview": review_report[:300] + "..." if len(review_report) > 300 else review_report,
                    "has_optimized": False,
                    "progress": 50.0 + ((i + 0.5) / total) * 100,
                })

                # --- 步骤4: 根据审核报告重新优化 ---
                await self._update_progress(3, 50.0 + progress_base / 3,
                                            message=f"正在优化重生成后的第{idx}章: {chapter.title}")

                optimized_content = await self._optimize_single_chapter(
                    client_c, chapter, idx, total, outline,
                    memory, prev_end,
                )

                if optimized_content is None:
                    await self._broadcast("log", {
                        "message": f"[错误] 第{idx}章重优化失败，保留原始内容"
                    })
                    continue

                # 字数检查：超长则重新优化（最多重试1次）
                if optimized_content and len(optimized_content) > MAX_CHAPTER_WORDS:
                    await self._broadcast("log", {
                        "message": f"[重优化] 第{idx}章优化后内容{len(optimized_content)}字，超过{MAX_CHAPTER_WORDS}字上限，正在重新优化..."
                    })
                    retry_result = await self._optimize_single_chapter(
                        client_c, chapter, idx, total, outline,
                        memory, prev_end, is_retry=False,
                    )
                    if retry_result and len(retry_result) <= MAX_CHAPTER_WORDS:
                        optimized_content = retry_result
                        await self._broadcast("log", {
                            "message": f"[重优化] 第{idx}章重新优化成功（{len(optimized_content)}字）"
                        })
                    else:
                        await self._broadcast("log", {
                            "message": f"[警告] 第{idx}章重新优化后仍超过{MAX_CHAPTER_WORDS}字，保留当前版本"
                        })
                chapter.optimized_content = optimized_content

                # 更新 memory（优化完成后更新）
                try:
                    updates = self._parse_state_update_text(state_update_text)
                    if updates:
                        next_label = f"第{str(idx + 1).zfill(2)}章" if idx < len(self.state.chapters) else "无"
                        updates["optimized_chapter"] = chapter_label
                        updates["pending_chapter"] = next_label if next_label != "无" else "全部完成"
                        updates["current_chapter"] = chapter_label
                        updates["total_chapters"] = str(len(self.state.chapters))
                        self.memory_manager.update_memory(updates)
                except Exception as e:
                    print(f"[记忆系统] 第{idx}章状态更新失败: {e}")

                # 广播优化结果
                await self._broadcast("optimize_result", {
                    "index": idx,
                    "title": chapter.title,
                    "has_optimized": True,
                    "progress": ((i + 1) / total) * 100,
                })

                # 每章完成后保存状态到磁盘
                self._save_state_to_disk()

            # 恢复 memory 文件到原始状态（从磁盘备份）
            if memory_backup_path and os.path.exists(memory_backup_path):
                import shutil
                shutil.copy2(memory_backup_path, memory_path)
                os.remove(memory_backup_path)

            self.state.status = "completed"
            self.state.progress = 100.0
            self.state.step_names = _saved_step_names  # 恢复原始 step_names
            await self._broadcast("complete", {
                "message": "指定章节重生成完成！",
                "state": self.state.model_dump(),
            })

        except asyncio.CancelledError:
            # 清理备份文件
            if memory_backup_path and os.path.exists(memory_backup_path):
                os.remove(memory_backup_path)
            if self.state.status != "cancelled":
                self.state.status = "cancelled"
                await self._broadcast("error", {
                    "message": "重生成已取消",
                    "state": self.state.model_dump(),
                })
        except Exception as e:
            # 清理备份文件
            if memory_backup_path and os.path.exists(memory_backup_path):
                os.remove(memory_backup_path)
            self.state.status = "error"
            self.state.error_message = str(e)
            await self._broadcast("error", {
                "message": str(e),
                "state": self.state.model_dump(),
            })
            import traceback
            traceback.print_exc()

    # ---- 辅助方法 ----

    def _parse_outline(self, text: str, expected_count: int) -> OutlineResult:
        """解析大纲文本为结构化数据"""
        result = OutlineResult()

        # 提取小说标题
        title_match = re.search(r'小说标题[：:]\s*[《（]?(.+?)[》）]?\s*$', text, re.MULTILINE)
        if title_match:
            result.title = title_match.group(1).strip()

        # 提取章节
        # 匹配格式: ## 第X章 - 标题 或 ## 第X章 标题
        chapter_pattern = r'(?:^|\n)#{1,3}\s*第(\d+)章[.、\s-]*([^\n]*?)(?:\n|$)'
        chapters_raw = re.findall(chapter_pattern, text)

        # 提取章节简介
        chapters = []
        # 按 ## 分割（先加换行确保 sections[0] 始终为空，避免首章无前导换行出错）
        sections = re.split(r'\n#+\s*第\d+章', '\n' + text)

        for i, (num_str, title) in enumerate(chapters_raw):
            idx = int(num_str)

            # 查找对应分段的简介
            section_idx = i + 1 if i + 1 < len(sections) else len(sections) - 1
            section = sections[section_idx] if section_idx < len(sections) else ""

            # 提取简介
            summary_match = re.search(r'章节简介[：:]\s*([\s\S]+?)(?=\n#+\s*第\d+章|\Z)', section)
            summary = summary_match.group(1).strip() if summary_match else section.strip()

            # 清理简介
            summary = re.sub(r'^\s*[-—]?\s*', '', summary)
            summary = summary[:500]  # 限制长度

            chapters.append(ChapterOutline(
                index=idx,
                title=title.strip() or f"第{idx}章",
                summary=summary,
            ))

        # 如果解析失败，使用宽松匹配
        if not chapters:
            # 尝试匹配所有章节标题行
            all_chapters = re.findall(r'(?:第(\d+)章)[.、\s-]*([^\n]{1,50})', text)
            for num_str, title in all_chapters:
                idx = int(num_str) if num_str.isdigit() else len(chapters) + 1
                chapters.append(ChapterOutline(
                    index=idx,
                    title=title.strip(),
                    summary="（章节简介已内嵌到正文中）",
                ))

        # 如果还是没有章节，创建默认
        if not chapters:
            for i in range(1, expected_count + 1):
                chapters.append(ChapterOutline(
                    index=i,
                    title=f"第{i}章",
                    summary=f"第{i}章的情节展开...",
                ))

        result.chapters = chapters
        return result

    @staticmethod
    def _parse_outline_chapters(text: str) -> List[ChapterOutline]:
        """从文本中解析章节列表（不包含标题，用于分批解析）"""
        chapters = []

        # 匹配格式: ## 第X章 - 标题
        chapter_pattern = r'(?:^|\n)#{1,3}\s*第(\d+)章[.、\s-]*([^\n]*?)(?:\n|$)'
        chapters_raw = re.findall(chapter_pattern, text)

        if not chapters_raw:
            return chapters

        # 按 ## 分割（先加换行确保 sections[0] 始终为空）
        sections = re.split(r'\n#+\s*第\d+章', '\n' + text)

        for i, (num_str, title) in enumerate(chapters_raw):
            idx = int(num_str)

            section_idx = i + 1 if i + 1 < len(sections) else len(sections) - 1
            section = sections[section_idx] if section_idx < len(sections) else ""

            # 提取简介
            summary_match = re.search(r'章节简介[：:]\s*([\s\S]+?)(?=\n#+\s*第\d+章|\Z)', section)
            summary = summary_match.group(1).strip() if summary_match else section.strip()

            summary = re.sub(r'^\s*[-—]?\s*', '', summary)
            summary = summary[:500]

            # 不低于100字（取自 prompt 要求，做兜底处理）
            if len(summary) < 100:
                summary = summary + "\n（本章围绕主角展开新的冒险，在经历前期铺垫与成长后，主角将面对更强大的敌人和复杂的局势，通过智慧与勇气逐步揭开真相，做出影响故事走向的重要抉择。）"

            chapters.append(ChapterOutline(
                index=idx,
                title=title.strip() or f"第{idx}章",
                summary=summary,
            ))

        return chapters

    @staticmethod
    def _calc_summary_similarity(summary1: str, summary2: str) -> float:
        """计算两段章节简介的字符级相似度"""
        if not summary1 or not summary2:
            return 0.0
        min_len = min(len(summary1), len(summary2))
        if min_len == 0:
            return 0.0
        same = sum(1 for a, b in zip(summary1[:min_len], summary2[:min_len]) if a == b)
        return same / min_len

    @staticmethod
    def _deduplicate_outline_chapters(chapters: List[ChapterOutline]) -> List[ChapterOutline]:
        """去重：检测并修复连续章节间标题和内容完全重复或高度相似的问题"""
        if len(chapters) <= 1:
            return chapters

        result = list(chapters)
        result.sort(key=lambda c: c.index)
        i = 0
        while i < len(result) - 1:
            curr = result[i]
            next_ch = result[i + 1]

            # 检测重复的条件：
            # 1. 标题和简介完全相同
            # 2. 或简介字符相似度 > 85%（说明剧情雷同，标题不同但内容实质一样）
            title_identical = curr.title == next_ch.title
            summary_identical = curr.summary == next_ch.summary
            summary_similarity = NovelPipeline._calc_summary_similarity(curr.summary, next_ch.summary)

            is_duplicate = (title_identical and summary_identical) or summary_similarity > 0.85

            if is_duplicate:
                # 为后一个章节生成替代内容
                fallback_template = (
                    f"第{next_ch.index}章：在前一章的基础上，局势进一步升级，各方势力纷纷登场。"
                    f"主角尚未完全恢复便迎来了新的挑战，隐藏的真相逐渐浮出水面。"
                    f"面对更加复杂的局面，主角必须在困境中做出关键抉择，"
                    f"为后续的最终决战积蓄力量，同时化解眼前的危机。"
                )

                # 尝试基于前一章生成一个稍有推进的标题
                new_title = f"余波未平"
                # 如果当前标题已经是"结局"类标题，下一个用不同措辞
                if any(kw in curr.title for kw in ["时代", "终局", "结局", "尾声", "大结局"]):
                    new_title = f"最终决战"

                if summary_similarity > 0.85 and not (title_identical and summary_identical):
                    print(f"[去重] 检测到第{curr.index}章与第{next_ch.index}章简介相似度{summary_similarity:.0%}（剧情雷同），已自动替换第{next_ch.index}章标题为「{new_title}」")
                else:
                    print(f"[去重] 检测到第{curr.index}章与第{next_ch.index}章内容完全重复，已自动替换第{next_ch.index}章标题为「{new_title}」")

                next_ch.title = new_title
                next_ch.summary = fallback_template

            i += 1

        return result

    def _format_outline_for_prompt(self, outline: OutlineResult) -> str:
        """将大纲格式化为 prompt 文本"""
        lines = [f"小说标题：《{outline.title}》" if outline.title else "小说标题：（待定）", ""]
        for ch in outline.chapters:
            lines.append(f"## 第{str(ch.index).zfill(2)}章 - {ch.title}")
            lines.append(f"章节简介：{ch.summary}")
            lines.append("")
        return "\n".join(lines)

    def _parse_review_result(self, text: str) -> tuple:
        """解析审核结果，返回 (review_report, optimized_content)"""
        review_report = ""
        optimized_content = ""

        # 尝试按分隔符解析
        report_match = re.search(
            r'={3,5}\s*审核报告\s*={3,5}([\s\S]*?)(?=\n={3,5}\s*优化文本\s*={3,5})', text
        )
        text_match = re.search(
            r'={3,5}\s*优化文本\s*={3,5}([\s\S]*)', text
        )

        if report_match:
            review_report = report_match.group(1).strip()
        if text_match:
            optimized_content = text_match.group(1).strip()

        # 如果没找到分隔符，全文作为优化文本
        if not review_report and not optimized_content:
            optimized_content = text

        return review_report, optimized_content

    @staticmethod
    def _parse_review_only_result(text: str) -> tuple:
        """解析审核结果（2段格式：审核报告 + 状态更新），返回 (review_report, state_update_text)"""
        review_report = ""
        state_update_text = ""

        # 提取状态更新部分
        state_patterns = [
            r'={3,5}\s*状态更新\s*={3,5}([\s\S]*)',           # ===状态更新===
            r'\*{2}\s*状态更新\s*\*{2}([\s\S]*)',              # **状态更新**
            r'(?:^|\n)#{1,3}\s+状态更新\s*\n([\s\S]*)',         # # 状态更新
        ]
        for pattern in state_patterns:
            m = re.search(pattern, text)
            if m:
                state_update_text = m.group(1).strip()
                text = text[:m.start()].strip()
                break

        # 从剩余文本中提取审核报告
        report_pattern = r'={3,5}\s*审核报告\s*={3,5}([\s\S]*)'
        report_match = re.search(report_pattern, text)
        if report_match:
            review_report = report_match.group(1).strip()
        else:
            review_report = text

        return review_report, state_update_text

    @staticmethod
    def _parse_review_result_v2(text: str) -> tuple:
        """解析审核结果（3段格式），返回 (review_report, optimized_content, state_update_text)"""
        review_report = ""
        optimized_content = ""
        state_update_text = ""

        # 提取状态更新部分
        state_patterns = [
            r'={3,5}\s*状态更新\s*={3,5}([\s\S]*)',           # ===状态更新===
            r'\*{2}\s*状态更新\s*\*{2}([\s\S]*)',              # **状态更新**
            r'(?:^|\n)#{1,3}\s+状态更新\s*\n([\s\S]*)',         # # 状态更新
        ]
        for pattern in state_patterns:
            m = re.search(pattern, text)
            if m:
                state_update_text = m.group(1).strip()
                text = text[:m.start()].strip()
                break

        # 从剩余文本中分离审核报告和优化文本
        report_pattern = r'={3,5}\s*审核报告\s*={3,5}([\s\S]*?)(?=\n={3,5}\s*优化文本\s*={3,5})'
        text_pattern = r'={3,5}\s*优化文本\s*={3,5}([\s\S]*)'

        report_match = re.search(report_pattern, text)
        text_match = re.search(text_pattern, text)

        if report_match and text_match:
            review_report = report_match.group(1).strip()
            optimized_content = text_match.group(1).strip()
        elif text_match:
            optimized_content = text_match.group(1).strip()
            before_text = text[:text_match.start()].strip()
            review_report = re.sub(r'={3,5}\s*审核报告\s*={3,5}', '', before_text).strip()
        elif report_match:
            # 只有审核报告，没有优化文本（review-only场景容错）
            review_report = report_match.group(1).strip()
            optimized_content = ""
        else:
            optimized_content = text

        # 清理优化文本中的代码块标记
        optimized_content = re.sub(
            r"^```(?:markdown|text|md)?\s*", "", optimized_content, flags=re.MULTILINE
        )
        optimized_content = re.sub(r"\s*```$", "", optimized_content, flags=re.MULTILINE)

        return review_report, optimized_content, state_update_text

    @staticmethod
    def _parse_state_update_text(text: str) -> Dict[str, str]:
        """解析状态更新文本为结构化字典"""
        if not text or not text.strip():
            return {}

        result = {}
        # 去除加粗标记
        cleaned = re.sub(r"\*\*", "", text)

        # 提取简单字段
        fields = {
            "story_time": r"故事时间\s*[:：]\s*(.+)",
            "story_location": r"故事地点\s*[:：]\s*(.+)",
            "finance": r"主角财物状态\s*[:：]\s*(.+)",
            "other_items": r"其他物品状态\s*[:：]\s*(.+)",
        }
        for key, pattern in fields.items():
            m = re.search(pattern, cleaned)
            if m:
                result[key] = m.group(1).strip()

        # 提取多行段落
        sections = {
            "characters": "人物状态",
            "organizations": "单位状态",
            "items": "物品状态",
            "body_status": "人物身体状态",
            "skills": "功法状态",
            "weapons": "武器状态",
            "key_settings": "关键设定与事实",
        }
        for key, title in sections.items():
            section_text = NovelPipeline._extract_memory_section(cleaned, title)
            if section_text:
                result[key] = section_text

        # 提取上一章结尾
        prev_end = {}
        prev_section = NovelPipeline._extract_memory_section(cleaned, "上一章结尾状态")
        if prev_section:
            prev_fields = {
                "time": r"时间\s*[:：]\s*(.+)",
                "location": r"地点\s*[:：]\s*(.+)",
                "characters": r"在场人物\s*[:：]\s*(.+)",
                "plot_progress": r"关键情节进展\s*[:：]\s*(.+)",
                "item_info_status": r"关键物品和信息状态\s*[:：]\s*(.+)",
            }
            for key, pattern in prev_fields.items():
                m = re.search(pattern, prev_section)
                if m:
                    prev_end[key] = m.group(1).strip()

        if prev_end:
            result["prev_chapter_end"] = prev_end

        return result

    @staticmethod
    def _upsert_chapter(chapter_list: List, new_chapter) -> None:
        """更新或追加章节：同 index 覆盖，不同 index 追加"""
        for i, ch in enumerate(chapter_list):
            if ch.index == new_chapter.index:
                chapter_list[i] = new_chapter
                return
        chapter_list.append(new_chapter)
        chapter_list.sort(key=lambda c: c.index)

    @staticmethod
    def _extract_memory_section(text: str, title: str) -> Optional[str]:
        """提取 memory 文本中某个标题下的段落内容"""
        pattern = rf"(?:^|\n)\s*{re.escape(title)}\s*[:：]?\s*\n(.*?)(?=\n(?:\s*(?:人物状态|单位状态|物品状态|人物身体状态|主角财物状态|功法状态|武器状态|其他物品状态|故事时间|故事地点|关键设定与事实|上一章结尾状态)|\Z))"
        m = re.search(pattern, text, re.DOTALL)
        if m:
            return m.group(1).strip()
        return None

    def update_chapter_outline(self, index: int, title: str, summary: str) -> bool:
        """更新指定章节的大纲（标题+简介），同步更新原始大纲和优化后大纲"""
        updated = False

        # 更新原始大纲
        if self.state.outline:
            for ch in self.state.outline.chapters:
                if ch.index == index:
                    ch.title = title
                    ch.summary = summary
                    updated = True
                    break

        # 更新优化后大纲
        if self.state.optimized_outline:
            for ch in self.state.optimized_outline.chapters:
                if ch.index == index:
                    ch.title = title
                    ch.summary = summary
                    updated = True
                    break

        # 更新章节内容中的摘要
        if self.state.chapters:
            for ch in self.state.chapters:
                if ch.index == index:
                    ch.title = title
                    ch.summary = summary
                    updated = True
                    break

        return updated

    def get_novel_content(self) -> str:
        """获取完整小说内容（用于导出）"""
        outline = self.state.optimized_outline or self.state.outline
        if not outline:
            return ""

        lines = [f"# {outline.title}", ""]

        for ch in self.state.chapters:
            content = ch.optimized_content or ch.content
            lines.append(f"## 第{str(ch.index).zfill(2)}章 {ch.title}")
            lines.append("")
            lines.append(content)
            lines.append("")

        return "\n".join(lines)

    def get_review_report(self) -> str:
        """获取完整审核报告"""
        outline = self.state.optimized_outline or self.state.outline
        if not outline:
            return ""

        lines = [f"# {outline.title} - 审核报告", ""]

        for ch in self.state.chapters:
            if ch.review_report:
                lines.append(f"## 第{str(ch.index).zfill(2)}章 {ch.title}")
                lines.append("")
                lines.append(ch.review_report)
                lines.append("")

        return "\n".join(lines)
