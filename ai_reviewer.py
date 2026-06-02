"""
ai_reviewer.py - AI 审核与优化调用模块

负责：
1. 构建三种独立的 Prompt（正文生成、正文审核、正文优化）
2. 调用 OpenAI API 进行生成/审核/优化
3. 解析返回的审核报告、优化文本和状态更新
4. 支持重试机制
"""

import json
import time
import re
from typing import Any, Dict, Optional, Tuple, List
from openai import OpenAI


class AIReviewer:
    """AI 审核与优化器"""

    def __init__(self, config: Dict[str, Any]):
        self.client = OpenAI(
            api_key=config.get("api_key"),
            base_url=config.get("base_url", "https://api.openai.com/v1"),
        )
        self.model = config.get("model", "gpt-4o")
        self.temperature = config.get("temperature", 0.8)
        self.max_tokens = config.get("max_tokens", 32768)
        self.retry_times = config.get("retry_times", 3)
        self.plot = config.get("plot", "")  # 小说大纲
        self.min_words = config.get("min_words", 5000)

    def _call_api(self, prompt: str, constraint: str = "") -> str:
        """调用 API 并支持重试"""
        last_error = None
        content = prompt + constraint if constraint else prompt
        for attempt in range(self.retry_times):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "user", "content": content},
                    ],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                result = response.choices[0].message.content
                if not result:
                    raise ValueError("API 返回空内容")
                return result
            except Exception as e:
                last_error = e
                if attempt < self.retry_times - 1:
                    wait = 2 ** attempt
                    print(f"\n⚠️ API 调用失败（第{attempt + 1}次），{wait}秒后重试...")
                    print(f"   错误: {e}")
                    time.sleep(wait)
                else:
                    raise RuntimeError(
                        f"API 调用失败，已重试{self.retry_times}次: {last_error}"
                    )
        raise RuntimeError(f"API 调用失败: {last_error}")

    # ========== 正文生成 ==========

    def generate_chapter(
        self,
        chapter_num: int,
        chapter_title: str,
        chapter_outline: str,
        previous_chapters: List[Dict[str, str]],
        memory_context: Dict[str, Any],
        check_memory_context: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        根据大纲和前面章节生成新章节正文

        Args:
            chapter_num: 章节编号
            chapter_title: 章节标题
            chapter_outline: 本章大纲/剧情要求
            previous_chapters: 前面章节列表 [{"num": "01", "title": "...", "content": "..."}]
            memory_context: memory.md 解析后的结构化状态
            check_memory_context: memory_check.md 格式化的实体记忆库文本

        Returns:
            (generated_text, state_update)
        """
        prompt = self._build_generate_prompt(
            chapter_num, chapter_title, chapter_outline,
            previous_chapters, memory_context, check_memory_context
        )

        print(f"\n📝 正在生成第{chapter_num}章正文...")
        result = self._call_api(prompt)

        # 解析结果
        generated_text, state_update = self._parse_generate_response(result)

        # 字数检查
        if generated_text and len(generated_text) < self.min_words:
            print(f"\n⚠️ 生成文本{len(generated_text)}字，不足{self.min_words}字，正在重新生成...")
            constraint = f"\n\n【重要】你上一版生成了{len(generated_text)}字，不足{self.min_words}字要求。请重新生成，确保字数大于{self.min_words}字。扩展场景描写和对话，但不要添加无关情节。"
            result2 = self._call_api(prompt, constraint)
            generated_text2, state_update2 = self._parse_generate_response(result2)
            if generated_text2 and len(generated_text2) >= self.min_words:
                generated_text, state_update = generated_text2, state_update2
                print(f"✅ 重新生成成功（{len(generated_text)}字）")
            else:
                print(f"⚠️ 重新生成后仍不足{self.min_words}字，保留原始版本")

        return generated_text, state_update

    def _build_generate_prompt(
        self,
        chapter_num: int,
        chapter_title: str,
        chapter_outline: str,
        previous_chapters: List[Dict[str, str]],
        memory: Dict[str, Any],
        check_memory_context: Optional[str] = None,
    ) -> str:
        """构建正文生成 Prompt"""

        # 构建前面章节内容（可能需要截断）
        previous_content = self._build_previous_chapters_content(previous_chapters)

        # 构建记忆部分
        mem_parts = self._build_memory_parts(memory)
        key_settings = memory.get('key_settings', '')
        if key_settings.strip() in ("（暂无）", "（待首次审核后更新）", ""):
            key_settings = ""

        prev_end = memory.get("prev_chapter_end", {})

        prompt = f"""## 角色设定

你是一位拥有15年经验的男频武侠小说主编，同时也是一位资深的内容风控专家。你深谙"黄金三章"法则，精通各大男频平台（如起点、番茄）的审核红线与爽点节奏。你的风格犀利、务实，擅长在确保合规的前提下，通过精修文字提升作品的"爽感"和"代入感"。

## 小说大纲

{self.plot}

## 前面章节内容

{previous_content}

## 当前系统状态

### 处理进度
- 当前生成章节: 第{chapter_num}章 {chapter_title}

### 当前时间线
- 故事时间: {memory.get('story_time', '未知')}
- 故事地点: {memory.get('story_location', '未知')}

{chr(10).join(mem_parts)}

### 关键设定与事实（跨章一致性依据）

{key_settings or '（暂无）'}

{check_memory_context or ''}

### 上一章结尾状态（仅作衔接参考，切勿重复描写）
- 时间: {prev_end.get('time', '无')}
- 地点: {prev_end.get('location', '无')}
- 在场人物: {prev_end.get('characters', '无')}
- 关键情节进展: {prev_end.get('plot_progress', '无')}
- 关键物品和信息状态: {prev_end.get('item_info_status', '无')}

## 本章大纲

{chapter_outline}

## 任务目标

请根据小说大纲和前面章节内容，创作第{chapter_num}章的完整正文。

### 文笔与叙事

● 代入感：环境描写是否烘托了气氛？战斗描写是否有画面感？
● 人物塑造：主角性格是否鲜明（如：腹黑、热血、稳健）？配角是否智商在线（拒绝无脑反派）？
● 沉浸式叙事：严格遵循"展示而非讲述"原则，通过动作、神态和环境细节来暗示人物心理，严禁直接出现情绪形容词（如"悲伤"、"愤怒"）。
● 感官细节：加入至少3处关于气味、温度或声音的细腻描写，增强场景的真实质感。
● 去AI化：禁止使用"总而言之"、"仿佛"等AI常用词汇；禁止在结尾进行价值升华；对话要符合人物身份，包含口语化的停顿和潜台词。
● 句式节奏：长短句交错，营造紧张/舒缓的氛围，避免工整的排比句。
● 风格参考：保持冷峻、克制的文风，像电影镜头一样客观记录。

### 写作约束

● 章节内容不得与前面任何章节的情节重复，尤其是物品发现、人物初遇、信息获取等关键场景。
● 时间线必须连贯，不能出现上一章已结束在夜晚、本章又从清晨重新开始的情况，除非有明确的"次日""三日后"等过渡提示。
● 人物对已知信息的认知必须保持连贯，不能把"已经知道"写成"刚刚发现"。
● 生成内容严谨，逻辑自洽，文风与前面章节保持一致。
● 章节正文内容的字数必须大于{self.min_words}字。

### 输出格式

请严格按照以下两部分格式输出，每部分用 ===== 分隔：

=====正文内容=====
[完整的第{chapter_num}章正文，字数必须大于{self.min_words}字]

=====状态更新=====
请根据本章内容，提取最新的故事状态信息。格式如下：
故事时间: [当前故事发生的时间点]
故事地点: [当前故事发生的核心地点]
人物状态:
- [人名]: [位置/状态/行为描述]
单位状态:
- [单位名]: [状态描述]
物品状态:
- [物品名]: [归属/状态描述]
人物身体状态:
- [人名]: [健康状况/身体状态]
主角财物状态: [财物情况]
功法状态:
- [功法名]: [修炼阶段/等级]
武器状态:
- [武器名]: [归属/状态]
其他物品状态: [其他值得记录的特殊物品]
关键设定与事实: [关键实体与设定]
上一章结尾状态:
- 时间: [本章结尾的时间点]
- 地点: [本章结尾的地点]
- 在场人物: [本章结尾时在场的人物]
- 关键情节进展: [本章最重要的情节推进]
- 关键物品和信息状态: [关键物品变化/重要信息获取]"""

        return prompt

    def _build_previous_chapters_content(self, previous_chapters: List[Dict[str, str]]) -> str:
        """构建前面章节内容，如果超过上下文限制则截断"""
        if not previous_chapters:
            return "（无前面章节，这是第一章）"

        # 估算可用空间（留出空间给大纲和其他内容）
        MAX_PREVIOUS_CHARS = 20000  # 前面章节最大字符数

        # 按章节顺序排列
        sorted_chapters = sorted(previous_chapters, key=lambda x: int(x.get("num", "0")))

        # 计算总长度
        total_length = sum(len(ch.get("content", "")) for ch in sorted_chapters)

        if total_length <= MAX_PREVIOUS_CHARS:
            # 不需要截断
            parts = []
            for ch in sorted_chapters:
                num = ch.get("num", "?")
                title = ch.get("title", "")
                content = ch.get("content", "")
                parts.append(f"### 第{num}章 {title}\n\n{content}")
            return "\n\n---\n\n".join(parts)
        else:
            # 需要截断：保留大纲级别的摘要 + 最近几章的完整内容
            print(f"\n⚠️ 前面章节内容过长（{total_length}字），将进行截断...")

            # 保留最近3章的完整内容
            recent_chapters = sorted_chapters[-3:]
            older_chapters = sorted_chapters[:-3]

            parts = []

            # 对较早的章节生成摘要
            if older_chapters:
                parts.append("### 前面章节摘要\n")
                for ch in older_chapters:
                    num = ch.get("num", "?")
                    title = ch.get("title", "")
                    content = ch.get("content", "")
                    # 提取前200字作为摘要
                    summary = content[:200] + "..." if len(content) > 200 else content
                    parts.append(f"**第{num}章 {title}**: {summary}")

            # 最近几章完整内容
            parts.append("\n### 最近章节完整内容\n")
            for ch in recent_chapters:
                num = ch.get("num", "?")
                title = ch.get("title", "")
                content = ch.get("content", "")
                parts.append(f"#### 第{num}章 {title}\n\n{content}")

            result = "\n\n".join(parts)

            # 如果仍然超过限制，进一步截断
            if len(result) > MAX_PREVIOUS_CHARS:
                result = result[:MAX_PREVIOUS_CHARS] + "\n\n...（内容过长，已截断）"

            return result

    # ========== 正文审核 ==========

    def review_chapter(
        self,
        chapter_content: str,
        memory_context: Dict[str, Any],
        check_memory_context: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        对章节进行审核，返回审核报告

        Args:
            chapter_content: 章节文本内容
            memory_context: memory.md 解析后的结构化状态
            check_memory_context: memory_check.md 格式化的实体记忆库文本

        Returns:
            (review_report, state_update)
        """
        prompt = self._build_review_prompt(chapter_content, memory_context, check_memory_context)

        print(f"\n🔍 正在审核章节内容...")
        result = self._call_api(prompt)

        # 解析结果
        review_report, state_update = self._parse_review_response(result)

        return review_report, state_update

    def _build_review_prompt(
        self,
        chapter_content: str,
        memory: Dict[str, Any],
        check_memory_context: Optional[str] = None,
    ) -> str:
        """构建正文审核 Prompt"""

        mem_parts = self._build_memory_parts(memory)
        key_settings = memory.get('key_settings', '')
        if key_settings.strip() in ("（暂无）", "（待首次审核后更新）", ""):
            key_settings = ""

        prev_end = memory.get("prev_chapter_end", {})

        prompt = f"""## 角色设定

你是一位拥有15年经验的男频武侠小说主编，同时也是一位资深的内容风控专家。你深谙"黄金三章"法则，精通各大男频平台（如起点、番茄）的审核红线与爽点节奏。你的风格犀利、务实，擅长在确保合规的前提下，通过精修文字提升作品的"爽感"和"代入感"。

## 当前系统状态

### 处理进度
- 已优化章节: {memory.get('optimized_chapter', '无')}
- 待优化章节: {memory.get('pending_chapter', '未知')}

### 当前时间线
- 当前章节: {memory.get('current_chapter', '未知')}
- 故事时间: {memory.get('story_time', '未知')}
- 故事地点: {memory.get('story_location', '未知')}

{chr(10).join(mem_parts)}

### 关键设定与事实（跨章一致性依据）

本章审核前，请仔细核对以下记录中的**实体属性**，逐项比对本章内容是否与之矛盾。

{key_settings or '（暂无）'}

核对要求：
● 本章出现的**每个已记录实体**的属性和状态必须与记录完全一致
● 如发现本章内容与已有记录矛盾，必须在审核报告中列为"设定冲突"问题

{check_memory_context or ''}

### 上一章结尾状态（仅作衔接参考）
- 时间: {prev_end.get('time', '无')}
- 地点: {prev_end.get('location', '无')}
- 在场人物: {prev_end.get('characters', '无')}
- 关键情节进展: {prev_end.get('plot_progress', '无')}
- 关键物品和信息状态: {prev_end.get('item_info_status', '无')}

## 待审核章节内容

```
{chapter_content[:12000] if len(chapter_content) > 12000 else chapter_content}
```

## 任务目标

请对上述传统武侠小说章节进行**审核分析**，输出详细的审核报告。

### 审核维度与标准

**合规与安全（红线检查）**
● 涉政涉黑：严禁影射现实政治、歪曲历史；严禁美化黑社会性质组织（帮派需有正向或中立结局）。
● 暴力血腥：避免过于直白的虐杀、肢解描写（可用侧面描写或氛围渲染代替）。
● 低俗色情：严禁脖子以下的露骨描写，情感戏需留白，重在氛围与暧昧感。
● 价值观导向：主角可以杀伐果断，但不能无底线反社会；反派作恶需有因果，最终需有报应（或伏笔）。

**男频特有元素检查**
● 修炼体系：等级设定是否清晰？力量体系是否崩坏？
● 剧情节奏：是否有明确的"冲突-压抑-爆发-收获"循环？是否存在"送女"、"绿帽"、"主角吃瘪无回击"等男频毒点？
● 爽点设置：装逼打脸是否自然？金手指（外挂）设定是否有趣且逻辑自洽？

**文笔与叙事**
● 代入感：环境描写是否烘托了气氛？战斗描写是否有画面感？
● 人物塑造：主角性格是否鲜明？配角是否智商在线（拒绝无脑反派）？
● 沉浸式叙事：是否遵循"展示而非讲述"原则？是否存在直接使用情绪形容词的问题？
● 感官细节：是否有足够的气味、温度或声音描写？
● 去AI化：是否存在"总而言之"、"仿佛"等AI常用词汇？对话是否口语化？
● 句式节奏：是否长短句交错？是否存在工整的排比句？

**写作约束检查**
● 本章内部内容是否有重复？
● 与前面章节情节是否有重复（物品发现、人物初遇、信息获取等）？
● 时间线是否连贯？
● 人物认知是否连贯？
● 字数是否满足要求（>{self.min_words}字）？

**跨章节一致性检查**
● 时序一致性：本章开头与上一结尾是否无缝衔接？
● 地理距离一致性：同一段距离在不同章节中是否一致？
● 人物行为合理性：人物行动是否符合身份设定？
● 设定统一性：宗门名称、功法名称、人物关系等是否统一？

### 输出格式

请严格按照以下两部分格式输出，每部分用 ===== 分隔：

=====审核报告=====
传统武侠小说审核报告

综合诊断
● 综合评分：[X]/10
● 核心亮点：[简述1-2个吸引人的点]
● 致命毒点/风险：[简述最严重的问题]

问题详情与修改策略
| 问题类型 | 原文片段（引用） | 问题分析 | 修改策略 |
|---|---|---|---|
| ... | ... | ... | ... |

=====状态更新=====
请根据本章内容，提取最新的故事状态信息。格式如下：
故事时间: [当前故事发生的时间点]
故事地点: [当前故事发生的核心地点]
人物状态:
- [人名]: [位置/状态/行为描述]
单位状态:
- [单位名]: [状态描述]
物品状态:
- [物品名]: [归属/状态描述]
人物身体状态:
- [人名]: [健康状况/身体状态]
主角财物状态: [财物情况]
功法状态:
- [功法名]: [修炼阶段/等级]
武器状态:
- [武器名]: [归属/状态]
其他物品状态: [其他值得记录的特殊物品]
关键设定与事实: [关键实体与设定]
上一章结尾状态:
- 时间: [本章结尾的时间点]
- 地点: [本章结尾的地点]
- 在场人物: [本章结尾时在场的人物]
- 关键情节进展: [本章最重要的情节推进]
- 关键物品和信息状态: [关键物品变化/重要信息获取]"""

        return prompt

    # ========== 正文优化 ==========

    def optimize_chapter(
        self,
        review_report: str,
        chapter_content: str,
        chapter_num: int,
        chapter_title: str,
        chapter_outline: str,
        previous_chapters: List[Dict[str, str]],
        memory_context: Dict[str, Any],
        check_memory_context: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        根据审核报告和生成提示词优化章节

        Args:
            review_report: 审核报告内容
            chapter_content: 原始章节内容
            chapter_num: 章节编号
            chapter_title: 章节标题
            chapter_outline: 本章大纲
            previous_chapters: 前面章节列表
            memory_context: memory.md 解析后的结构化状态
            check_memory_context: memory_check.md 格式化的实体记忆库文本

        Returns:
            (optimized_text, state_update)
        """
        prompt = self._build_optimize_prompt(
            review_report, chapter_content,
            chapter_num, chapter_title, chapter_outline,
            previous_chapters, memory_context, check_memory_context
        )

        print(f"\n✨ 正在优化章节内容...")
        result = self._call_api(prompt)

        # 解析结果
        optimized_text, state_update = self._parse_optimize_response(result)

        # 字数检查
        MAX_WORDS = 8000
        if optimized_text and len(optimized_text) > MAX_WORDS:
            actual_len = len(optimized_text)
            print(f"\n⚠️ 优化文本{actual_len}字，超过{MAX_WORDS}字上限，正在重新生成...")
            constraint = f"\n\n【重要】你上一版生成了{actual_len}字，超过{MAX_WORDS}字限制。请重新生成，确保字数不超过{MAX_WORDS}字。精简冗余描写，但不要截断结尾，必须完成本章的完整情节。"
            result2 = self._call_api(prompt, constraint)
            optimized_text2, state_update2 = self._parse_optimize_response(result2)
            if optimized_text2 and len(optimized_text2) <= MAX_WORDS:
                optimized_text, state_update = optimized_text2, state_update2
                print(f"✅ 重新生成成功（{len(optimized_text)}字）")
            else:
                print(f"⚠️ 重新生成后仍超过{MAX_WORDS}字，保留原始版本")

        return optimized_text, state_update

    def _build_optimize_prompt(
        self,
        review_report: str,
        chapter_content: str,
        chapter_num: int,
        chapter_title: str,
        chapter_outline: str,
        previous_chapters: List[Dict[str, str]],
        memory: Dict[str, Any],
        check_memory_context: Optional[str] = None,
    ) -> str:
        """构建正文优化 Prompt（审核报告 + 正文生成提示词）"""

        # 构建前面章节内容
        previous_content = self._build_previous_chapters_content(previous_chapters)

        # 构建记忆部分
        mem_parts = self._build_memory_parts(memory)
        key_settings = memory.get('key_settings', '')
        if key_settings.strip() in ("（暂无）", "（待首次审核后更新）", ""):
            key_settings = ""

        prev_end = memory.get("prev_chapter_end", {})

        prompt = f"""## 角色设定

你是一位拥有15年经验的男频武侠小说主编，同时也是一位资深的内容风控专家。你深谙"黄金三章"法则，精通各大男频平台（如起点、番茄）的审核红线与爽点节奏。你的风格犀利、务实，擅长在确保合规的前提下，通过精修文字提升作品的"爽感"和"代入感"。

## 小说大纲

{self.plot}

## 前面章节内容

{previous_content}

## 当前系统状态

### 处理进度
- 当前优化章节: 第{chapter_num}章 {chapter_title}

### 当前时间线
- 故事时间: {memory.get('story_time', '未知')}
- 故事地点: {memory.get('story_location', '未知')}

{chr(10).join(mem_parts)}

### 关键设定与事实（跨章一致性依据）

{key_settings or '（暂无）'}

{check_memory_context or ''}

### 上一章结尾状态（仅作衔接参考）
- 时间: {prev_end.get('time', '无')}
- 地点: {prev_end.get('location', '无')}
- 在场人物: {prev_end.get('characters', '无')}
- 关键情节进展: {prev_end.get('plot_progress', '无')}
- 关键物品和信息状态: {prev_end.get('item_info_status', '无')}

## 本章大纲

{chapter_outline}

## 审核报告

{review_report}

## 待优化章节原文

```
{chapter_content}
```

## 任务目标

请根据**审核报告**中指出的问题，对上述章节进行**优化重写**。

### 优化要求

1. **必须修复审核报告中指出的所有问题**，特别是：
   - 设定冲突和逻辑硬伤
   - 违规风险内容
   - 男频毒点
   - 时间线和认知连贯性问题

2. **文笔与叙事优化**：
   ● 代入感：环境描写是否烘托了气氛？战斗描写是否有画面感？
   ● 人物塑造：主角性格是否鲜明（如：腹黑、热血、稳健）？配角是否智商在线（拒绝无脑反派）？
   ● 沉浸式叙事：严格遵循"展示而非讲述"原则，通过动作、神态和环境细节来暗示人物心理，严禁直接出现情绪形容词（如"悲伤"、"愤怒"）。
   ● 感官细节：加入至少3处关于气味、温度或声音的细腻描写，增强场景的真实质感。
   ● 去AI化：禁止使用"总而言之"、"仿佛"等AI常用词汇；禁止在结尾进行价值升华；对话要符合人物身份，包含口语化的停顿和潜台词。
   ● 句式节奏：长短句交错，营造紧张/舒缓的氛围，避免工整的排比句。
   ● 风格参考：保持冷峻、克制的文风，像电影镜头一样客观记录。

3. **写作约束**：
   ● 章节内容不得与前面任何章节的情节重复，尤其是物品发现、人物初遇、信息获取等关键场景。
   ● 时间线必须连贯，不能出现上一章已结束在夜晚、本章又从清晨重新开始的情况，除非有明确的"次日""三日后"等过渡提示。
   ● 人物对已知信息的认知必须保持连贯，不能把"已经知道"写成"刚刚发现"。
   ● 生成内容严谨，逻辑自洽，文风与前面章节保持一致。
   ● 章节正文内容的字数必须大于{self.min_words}字。

### 输出格式

请严格按照以下两部分格式输出，每部分用 ===== 分隔：

=====优化文本=====
[优化后的完整章节文本，字数必须大于{self.min_words}字]

=====状态更新=====
请根据本章优化后的内容，提取最新的故事状态信息。格式如下：
故事时间: [当前故事发生的时间点]
故事地点: [当前故事发生的核心地点]
人物状态:
- [人名]: [位置/状态/行为描述]
单位状态:
- [单位名]: [状态描述]
物品状态:
- [物品名]: [归属/状态描述]
人物身体状态:
- [人名]: [健康状况/身体状态]
主角财物状态: [财物情况]
功法状态:
- [功法名]: [修炼阶段/等级]
武器状态:
- [武器名]: [归属/状态]
其他物品状态: [其他值得记录的特殊物品]
关键设定与事实: [关键实体与设定]
上一章结尾状态:
- 时间: [本章结尾的时间点]
- 地点: [本章结尾的地点]
- 在场人物: [本章结尾时在场的人物]
- 关键情节进展: [本章最重要的情节推进]
- 关键物品和信息状态: [关键物品变化/重要信息获取]"""

        return prompt

    # ========== 通用辅助方法 ==========

    def _build_memory_parts(self, memory: Dict[str, Any]) -> List[str]:
        """构建记忆部分"""
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
        ]:
            val = memory.get(key, "").strip()
            if val and val not in ("（暂无）", "（待首次审核后更新）", ""):
                mem_parts.append(f"### {label}\n{val}")
        return mem_parts

    # ========== 响应解析方法 ==========

    def _parse_generate_response(self, response: str) -> Tuple[str, Dict[str, Any]]:
        """解析正文生成的响应"""
        return self._parse_two_part_response(response, "正文内容")

    def _parse_review_response(self, response: str) -> Tuple[str, Dict[str, Any]]:
        """解析正文审核的响应"""
        return self._parse_two_part_response(response, "审核报告")

    def _parse_optimize_response(self, response: str) -> Tuple[str, Dict[str, Any]]:
        """解析正文优化的响应"""
        return self._parse_two_part_response(response, "优化文本")

    def _parse_two_part_response(self, response: str, main_label: str) -> Tuple[str, Dict[str, Any]]:
        """
        解析两部分格式的响应（主内容 + 状态更新）

        Args:
            response: API 返回的完整文本
            main_label: 主内容的标签（如"正文内容"、"审核报告"、"优化文本"）

        Returns:
            (main_content, state_update)
        """
        main_content = ""
        state_update = {}

        # 第一步：提取状态更新部分
        state_marker_patterns = [
            r"={3,5}\s*状态更新\s*={3,5}",
            r"\*{2}\s*状态更新\s*\*{2}",
            r"={3,5}\s*状态更新\s*",
            r"\*{1,3}\s*状态更新\s*\*{0,3}",
            r"(?:^|\n)#{1,3}\s+状态更新",
            r"(?:^|\n)\s*状态更新\s*[:：]?\s*(?:\n|$)",
        ]
        cleaned_response = response
        for pattern in state_marker_patterns:
            m = re.search(pattern, cleaned_response)
            if m:
                state_start = m.start()
                state_text = cleaned_response[state_start:]
                cleaned_response = cleaned_response[:state_start].strip()
                # 清理状态更新标记
                state_text = re.sub(r"[=*]{2,5}\s*状态更新\s*[=*]{2,5}\n?", "", state_text)
                state_text = re.sub(r"(?:^|\n)#{1,3}\s*状态更新\s*\n?", "", state_text)
                state_text = re.sub(r"(?:^|\n)\s*状态更新\s*[:：]?\s*(?:\n|$)", "", state_text).strip()
                state_update = self._parse_state_update(state_text)
                break

        # 第二步：提取主内容
        # 尝试匹配各种可能的标签
        label_patterns = [
            rf"={3,5}\s*{re.escape(main_label)}\s*={3,5}",
            rf"\*{{2}}\s*{re.escape(main_label)}\s*\*{{2}}",
            rf"#{1,3}\s+{re.escape(main_label)}",
        ]

        for pattern in label_patterns:
            m = re.search(pattern, cleaned_response)
            if m:
                main_content = cleaned_response[m.end():].strip()
                break

        if not main_content:
            # 如果没有找到标签，检查是否有"优化文本"标签（兼容）
            alt_patterns = [
                r"={3,5}\s*优化文本\s*={3,5}",
                r"={3,5}\s*正文内容\s*={3,5}",
                r"={3,5}\s*审核报告\s*={3,5}",
            ]
            for pattern in alt_patterns:
                m = re.search(pattern, cleaned_response)
                if m:
                    main_content = cleaned_response[m.end():].strip()
                    break

        if not main_content:
            # 仍然没有找到，使用清理后的整个响应
            main_content = cleaned_response

        # 清理代码块标记
        main_content = re.sub(r"^```(?:markdown|text|md)?\s*", "", main_content, flags=re.MULTILINE)
        main_content = re.sub(r"\s*```$", "", main_content, flags=re.MULTILINE)

        # 清理可能残留的状态内容
        residual_patterns = [
            r"\n={3,5}\s*状态更新\s*={3,5}.*",
            r"\n\*{2}\s*状态更新\s*\*{2}[\s\S]*",
            r"\n\*{1,2}\s*状态更新\s*\*{0,2}[\s\S]*",
            r"\n状态更新\s*[:：][\s\S]*",
            r"\n#{1,3}\s*状态更新[\s\S]*",
            r"\n\*{2}故事时间[\s\S]*",
            r"\n\*{2}人物状态[\s\S]*",
        ]
        for rp in residual_patterns:
            main_content = re.sub(rp, "", main_content, flags=re.DOTALL).strip()

        return main_content, state_update

    def _parse_state_update(self, text: str) -> Dict[str, Any]:
        """解析状态更新文本为结构化字典"""
        result = {}

        # 先去除文本中所有加粗标记
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
            else:
                bold_pattern = rf"\*{{0,2}}{pattern}\*{{0,2}}"
                m = re.search(bold_pattern, text)
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
        }
        for key, title in sections.items():
            section_text = self._extract_section(cleaned, title)
            if section_text:
                result[key] = section_text

        # 提取关键设定与事实
        ks_match = re.search(r"关键设定与事实\s*[:：]\s*(.*?)(?=\n(?:实体分类记录|上一章结尾状态)|\Z)", cleaned, re.DOTALL)
        if ks_match:
            ks_value = ks_match.group(1).strip()
            if ks_value:
                result["key_settings"] = ks_value

        # 提取实体分类记录
        check_section = self._extract_section(cleaned, "实体分类记录")
        if not check_section:
            check_section = self._extract_section_in_text(cleaned, "实体分类记录")
        if not check_section:
            check_section = self._extract_section_in_text(cleaned, "实体分类记录（章节实体记忆库更新）")
        if check_section:
            entity_sections = {
                "characters_check": "人物",
                "buildings": "建筑",
                "sects": "宗门",
                "organizations_check": "单位",
                "items_check": "物品",
                "finance_check": "财务",
                "pills": "丹药",
                "skills_check": "功法",
                "character_relationships": "人物关系",
                "character_sect_relations": "人物-宗门关系",
                "conflicts": "冲突",
                "events": "事件",
                "timeline": "时间线",
            }
            for key, title in entity_sections.items():
                section_text = self._extract_simple_field(check_section, title)
                if section_text and section_text != "（无变化）":
                    result[key] = section_text

        # 提取上一章结尾状态
        prev_end = {}
        prev_section = self._extract_section(cleaned, "上一章结尾状态")
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

    def _extract_section(self, text: str, title: str) -> Optional[str]:
        """提取某个标题下的段落内容"""
        pattern = rf"(?:^|\n)\*{{0,2}}{re.escape(title)}\*{{0,2}}[\s:：]*\n(.*?)(?=\n(?:\*{{0,2}}(?:人物状态|单位状态|物品状态|人物身体状态|主角财物状态|功法状态|武器状态|其他物品状态|上一章结尾状态|故事时间|故事地点|关键设定与事实|实体分类记录)\*{{0,2}})|\Z)"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    def _extract_section_in_text(self, text: str, title: str) -> Optional[str]:
        """提取文本中某个标题下的内容"""
        escaped = re.escape(title)
        pattern = rf"(?:^|\n){escaped}(?:（[^）]*）)?[\s:：]*\n(.*)"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    def _extract_simple_field(self, text: str, title: str) -> Optional[str]:
        """提取简单字段内容"""
        pattern = rf"(?:^|\n){re.escape(title)}\s*[:：]\s*\n(.*?)(?=\n(?:人物|建筑|宗门|单位|物品|财务|丹药|功法|人物关系|人物-宗门关系|冲突|事件|时间线|上一章结尾状态)\s*[:：]|\Z)"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None
