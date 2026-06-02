"""
memory_manager.py - Memory.md 读写与状态管理模块

负责：
1. 从 memory.md 文件中解析当前状态
2. 审核后更新 memory.md 中的状态字段
3. 管理：已优化章节、待优化章节、时间线、人物/单位/物品等状态
"""

import re
import os
from typing import Any, Dict, Optional


class MemoryManager:
    """Memory.md 状态管理器"""

    def __init__(self, memory_file: str = "memory.md"):
        self.memory_file = memory_file

    def read_memory(self) -> Dict[str, Any]:
        """
        读取 memory.md 并解析为结构化字典

        返回:
        {
            "optimized_chapter": str,      # 已优化章节
            "pending_chapter": str,        # 待优化章节
            "total_chapters": str,         # 总章节数
            "current_chapter": str,        # 当前章节
            "story_time": str,             # 故事时间
            "story_location": str,         # 故事地点
            "characters": str,             # 人物状态
            "organizations": str,          # 单位状态
            "items": str,                  # 物品状态
            "body_status": str,            # 身体状态
            "finance": str,                # 主角财物
            "skills": str,                 # 功法状态
            "weapons": str,                # 武器状态
            "other_items": str,            # 其他物品
            "prev_chapter_end": {          # 上一章结尾
                "time": str,
                "location": str,
                "characters": str,
                "plot_progress": str,
                "item_info_status": str
            }
        }
        """
        if not os.path.exists(self.memory_file):
            return self._default_memory()

        with open(self.memory_file, "r", encoding="utf-8") as f:
            content = f.read()

        memory = self._default_memory()

        # 解析处理进度
        optimized = self._extract_field(content, r"- 已优化章节:\s*(.+)")
        if optimized:
            memory["optimized_chapter"] = optimized

        pending = self._extract_field(content, r"- 待优化章节:\s*(.+)")
        if pending:
            memory["pending_chapter"] = pending

        total = self._extract_field(content, r"- 总章节数:\s*(.+)")
        if total:
            memory["total_chapters"] = total

        # 解析时间线
        current_ch = self._extract_field(content, r"- 当前章节:\s*(.+)")
        if current_ch:
            memory["current_chapter"] = current_ch

        story_time = self._extract_field(content, r"- 故事时间:\s*(.+)")
        if story_time:
            memory["story_time"] = story_time

        story_loc = self._extract_field(content, r"- 故事地点:\s*(.+)")
        if story_loc:
            memory["story_location"] = story_loc

        # 解析各状态段（取标题与下一个标题之间的内容）
        sections = {
            "characters": "人物状态",
            "organizations": "单位状态",
            "items": "物品状态",
            "body_status": "人物身体状态",
            "finance": "主角财物状态",
            "skills": "功法状态",
            "weapons": "武器状态",
            "other_items": "其他物品状态",
            "key_settings": "关键设定与事实",  # 跨章一致性记录
        }

        for key, section_title in sections.items():
            section_content = self._extract_section(content, section_title)
            if section_content:
                memory[key] = section_content

        # 解析上一章结尾
        prev_end = memory["prev_chapter_end"]
        prev_end["time"] = self._extract_field(content, r"- 时间:\s*(.+)") or prev_end["time"]
        prev_end["location"] = self._extract_field(
            content, r"- 地点:\s*(.+)"
        ) or prev_end["location"]
        prev_end["characters"] = self._extract_field(
            content, r"- 在场人物:\s*(.+)"
        ) or prev_end["characters"]
        prev_end["plot_progress"] = self._extract_field(
            content, r"- 关键情节进展:\s*(.+)"
        ) or prev_end["plot_progress"]
        prev_end["item_info_status"] = self._extract_field(
            content, r"- 关键物品和信息状态:\s*(.+)"
        ) or prev_end["item_info_status"]

        # 修正：prev_chapter_end 下的字段可能在 "上一章结尾状态" 区域内
        # 上面的正则可能匹配到其他区域的字段，使用区域提取来修正
        prev_section = self._extract_section(content, "上一章结尾状态")
        if prev_section:
            p_time = self._extract_field(prev_section, r"- 时间:\s*(.+)")
            if p_time:
                prev_end["time"] = p_time
            p_loc = self._extract_field(prev_section, r"- 地点:\s*(.+)")
            if p_loc:
                prev_end["location"] = p_loc
            p_chars = self._extract_field(prev_section, r"- 在场人物:\s*(.+)")
            if p_chars:
                prev_end["characters"] = p_chars
            p_plot = self._extract_field(prev_section, r"- 关键情节进展:\s*(.+)")
            if p_plot:
                prev_end["plot_progress"] = p_plot
            p_items = self._extract_field(prev_section, r"- 关键物品和信息状态:\s*(.+)")
            if p_items:
                prev_end["item_info_status"] = p_items

        return memory

    def update_memory(self, updates: Dict[str, Any]) -> None:
        """
        更新 memory.md 文件

        Args:
            updates: 要更新的字段字典，格式同 read_memory() 的返回值
        """
        if not os.path.exists(self.memory_file):
            content = self._default_memory_text()
        else:
            with open(self.memory_file, "r", encoding="utf-8") as f:
                content = f.read()

        # 更新处理进度
        if "optimized_chapter" in updates:
            content = self._update_field(
                content, r"已优化章节:\s*.+", f"已优化章节: {updates['optimized_chapter']}"
            )
        if "pending_chapter" in updates:
            content = self._update_field(
                content, r"待优化章节:\s*.+", f"待优化章节: {updates['pending_chapter']}"
            )
        if "total_chapters" in updates:
            content = self._update_field(
                content, r"总章节数:\s*.+", f"总章节数: {updates['total_chapters']}"
            )

        # 更新时间线
        if "current_chapter" in updates:
            content = self._update_field(
                content, r"当前章节:\s*.+", f"当前章节: {updates['current_chapter']}"
            )
        if "story_time" in updates:
            content = self._update_field(
                content, r"故事时间:\s*.+", f"故事时间: {updates['story_time']}"
            )
        if "story_location" in updates:
            content = self._update_field(
                content, r"故事地点:\s*.+", f"故事地点: {updates['story_location']}"
            )

        # 更新各状态段落
        section_updates = {
            "characters": "人物状态",
            "organizations": "单位状态",
            "items": "物品状态",
            "body_status": "人物身体状态",
            "finance": "主角财物状态",
            "skills": "功法状态",
            "weapons": "武器状态",
            "other_items": "其他物品状态",
            "key_settings": "关键设定与事实",
        }

        for key, section_title in section_updates.items():
            if key in updates and updates[key]:
                content = self._update_section(content, section_title, updates[key])

        # 更新上一章结尾
        if "prev_chapter_end" in updates:
            prev = updates["prev_chapter_end"]
            prev_section = self._extract_section(content, "上一章结尾状态")
            if prev_section:
                for field_name, prefix in [
                    ("time", "时间"),
                    ("location", "地点"),
                    ("characters", "在场人物"),
                    ("plot_progress", "关键情节进展"),
                    ("item_info_status", "关键物品和信息状态"),
                ]:
                    if field_name in prev and prev[field_name]:
                        content = self._update_field(
                            content,
                            rf"{prefix}:\s*.+",
                            f"{prefix}: {prev[field_name]}",
                        )

        with open(self.memory_file, "w", encoding="utf-8") as f:
            f.write(content)

    def _extract_field(self, text: str, pattern: str) -> Optional[str]:
        """从文本中提取单个字段"""
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
        return None

    def _extract_section(self, text: str, title: str) -> Optional[str]:
        """提取某个标题下的段落内容"""
        # 匹配 ## title 到下一个 ## 或文件结尾
        pattern = rf"##\s*{re.escape(title)}\s*\n(.*?)(?=\n##\s|\Z)"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    def _update_field(self, content: str, pattern: str, replacement: str) -> str:
        """更新单个字段"""
        return re.sub(pattern, replacement, content, count=1)

    def _update_section(self, content: str, title: str, new_content: str) -> str:
        """更新某个标题下的段落内容"""
        pattern = rf"(##\s*{re.escape(title)}\s*\n).*?(?=\n##\s|\Z)"
        replacement = r"\1" + new_content + "\n"
        return re.sub(pattern, replacement, content, count=1, flags=re.DOTALL)

    def _default_memory(self) -> Dict[str, Any]:
        """默认 memory 结构"""
        return {
            "optimized_chapter": "无",
            "pending_chapter": "第01章",
            "total_chapters": "待扫描",
            "current_chapter": "第01章",
            "story_time": "未知（初始章节）",
            "story_location": "未知",
            "characters": "（暂无）",
            "organizations": "（暂无）",
            "items": "（暂无）",
            "body_status": "（暂无）",
            "finance": "（暂无）",
            "skills": "（暂无）",
            "weapons": "（暂无）",
            "other_items": "（暂无）",
            "prev_chapter_end": {
                "time": "无（初始章节）",
                "location": "无",
                "characters": "无",
                "plot_progress": "无",
                "item_info_status": "无",
            },
            "key_settings": "（暂无）",
        }

    def _default_memory_text(self) -> str:
        """默认 memory.md 文本内容"""
        return """# 小说状态记忆

## 处理进度
- 已优化章节: 无
- 待优化章节: 第01章
- 总章节数: 待扫描

## 当前时间线
- 当前章节: 第01章
- 故事时间: 未知（初始章节）
- 故事地点: 未知

## 人物状态
（暂无）

## 单位状态
（暂无）

## 物品状态
（暂无）

## 人物身体状态
（暂无）

## 主角财物状态
（暂无）

## 功法状态
（暂无）

## 武器状态
（暂无）

## 其他物品状态
（暂无）

## 上一章结尾状态
- 时间: 无（初始章节）
- 地点: 无
- 在场人物: 无
- 关键情节进展: 无
- 关键物品和信息状态: 无

## 关键设定与事实
（暂无）
"""
