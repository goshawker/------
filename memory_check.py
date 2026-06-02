"""
memory_check.py - 章节实体记忆库（memory_check.md）读写与一致性检查模块

负责：
1. 从 memory_check.md 中读取跨章节实体记录
2. 将新章节提取的实体数据合并/更新到 memory_check.md
3. 提供实体数据供 AI 审核时进行一致性检查

实体类型：
- 人物, 建筑, 宗门, 单位, 物品, 财务, 丹药, 功法
- 人物关系, 人物-宗门关系, 冲突, 事件, 时间线
"""

import re
import os
from typing import Any, Dict, Optional, List


class MemoryCheckManager:
    """章节实体记忆库管理器"""

    def __init__(self, check_file: str = "memory_check.md"):
        self.check_file = check_file

        # 所有实体段标题定义
        self.section_titles = {
            "characters": "人物",
            "buildings": "建筑",
            "sects": "宗门",
            "organizations": "单位",
            "items": "物品",
            "finance": "财务",
            "pills": "丹药",
            "skills": "功法",
            "character_relationships": "人物关系",
            "character_sect_relations": "人物-宗门关系",
            "conflicts": "冲突",
            "events": "事件",
            "timeline": "时间线",
        }

    def read_check_memory(self) -> Dict[str, Any]:
        """
        读取 memory_check.md 并解析为结构化字典

        返回:
        {
            "processed_chapters": str,       # 已处理的章节列表
            "characters": str,               # 人物
            "buildings": str,                # 建筑
            "sects": str,                    # 宗门
            "organizations": str,            # 单位
            "items": str,                    # 物品
            "finance": str,                  # 财务
            "pills": str,                    # 丹药
            "skills": str,                   # 功法
            "character_relationships": str,  # 人物关系
            "character_sect_relations": str, # 人物-宗门关系
            "conflicts": str,                # 冲突
            "events": str,                   # 事件
            "timeline": str,                 # 时间线
        }
        """
        if not os.path.exists(self.check_file):
            return self._default_check_memory()

        with open(self.check_file, "r", encoding="utf-8") as f:
            content = f.read()

        memory = self._default_check_memory()

        # 解析已处理章节
        processed = self._extract_field(content, r"- 已处理章节:\s*(.+)")
        if processed:
            memory["processed_chapters"] = processed

        # 解析各实体段
        for key, section_title in self.section_titles.items():
            section_content = self._extract_section(content, section_title)
            if section_content:
                memory[key] = section_content

        return memory

    def update_check_memory(self, updates: Dict[str, Any]) -> None:
        """
        更新 memory_check.md 文件

        Args:
            updates: 要更新的字段字典
        """
        if not os.path.exists(self.check_file):
            content = self._default_check_memory_text()
        else:
            with open(self.check_file, "r", encoding="utf-8") as f:
                content = f.read()

        # 更新已处理章节列表
        if "processed_chapters" in updates:
            content = self._update_field(
                content,
                r"已处理章节:\s*.+",
                f"已处理章节: {updates['processed_chapters']}",
            )

        # 更新各实体段
        for key, section_title in self.section_titles.items():
            if key in updates and updates[key]:
                # 检查该段是否存在，不存在则追加
                if self._extract_section(content, section_title) is not None:
                    content = self._update_section(content, section_title, updates[key])
                else:
                    content = self._append_section(content, section_title, updates[key])

        with open(self.check_file, "w", encoding="utf-8") as f:
            f.write(content)

    def merge_entity_updates(
        self, chapter_num: str, existing: Dict[str, Any], new_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        将 AI 返回的新实体数据合并到现有记忆库中

        Args:
            chapter_num: 当前章节编号（如 "01"）
            existing: 现有的 memory_check 数据
            new_data: AI 返回的新实体数据（各段文本）

        Returns:
            合并后的更新字典
        """
        merged = {}

        # 更新已处理章节列表
        processed = existing.get("processed_chapters", "")
        chapter_label = f"第{chapter_num}章"
        if chapter_label not in processed:
            if processed and processed != "（暂无）":
                merged["processed_chapters"] = f"{processed}、{chapter_label}"
            else:
                merged["processed_chapters"] = chapter_label

        # 合并各实体段（智能合并：同名实体替换，新实体追加）
        for key in self.section_titles:
            new_text = new_data.get(key, "").strip()
            if not new_text or new_text == "（暂无）" or new_text == "无变化":
                continue

            existing_text = existing.get(key, "").strip()
            if not existing_text or existing_text == "（暂无）":
                # 首次记录
                merged[key] = new_text
            else:
                # 智能合并：解析新旧条目，同名替换
                merged[key] = self._smart_merge_entities(existing_text, new_text)

        return merged

    def _smart_merge_entities(self, existing_text: str, new_text: str) -> str:
        """
        智能合并实体文本：按名称去重，新条目替换旧条目

        Args:
            existing_text: 现有实体段文本
            new_text: 新实体段文本

        Returns:
            合并后的实体段文本
        """
        # 解析现有条目和新条目
        existing_entries = self._parse_entity_entries(existing_text)
        new_entries = self._parse_entity_entries(new_text)

        if not new_entries:
            return existing_text

        # 提取新条目中的实体基础名称（去除括号后缀）
        def get_base_name(entry: str) -> str:
            name = entry.split(":", 1)[0].strip() if ":" in entry else entry.strip()
            if name.startswith("- "):
                name = name[2:].strip()
            # 去除括号内容用于匹配：顾长生（原名顾遇安）→ 顾长生
            base = re.sub(r"[（(][^）)]*[）)]", "", name).strip()
            return base, name  # 返回base和全名

        new_base_names = []
        for entry in new_entries:
            base, _ = get_base_name(entry)
            new_base_names.append(base)

        # 过滤现有条目，去掉被新条目替换的
        filtered = []
        for entry in existing_entries:
            base, full = get_base_name(entry)
            if base in new_base_names or full in new_base_names:
                continue
            filtered.append(entry)

        # 合并：保留未被替换的旧条目 + 新条目
        all_entries = filtered + new_entries
        return "\n".join(all_entries)

    def _parse_entity_entries(self, text: str) -> list:
        """解析实体段文本为条目列表"""
        entries = []
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("- "):
                entries.append(line)
            elif line and entries:
                # 续行（上一行的内容延续）
                entries[-1] = entries[-1] + " " + line
        return entries

    def format_for_prompt(self, check_memory: Dict[str, Any]) -> str:
        """
        将 memory_check 数据格式化为 prompt 上下文文本

        Returns:
            格式化的文本，供注入到 AI prompt 中
        """
        parts = []
        parts.append("### 章节实体记忆库（跨章一致性依据）\n")
        parts.append("以下是截至上一章已记录的所有实体信息。请逐项比对本章内容是否与已有记录矛盾：\n")

        has_content = False
        for key, title in self.section_titles.items():
            value = check_memory.get(key, "").strip()
            if value and value != "（暂无）":
                has_content = True
                parts.append(f"**{title}**\n{value}\n")

        if not has_content:
            parts.append("（暂无实体记录，本章将建立初始记录）\n")

        parts.append(
            "核对要求：\n"
            "● 本章出现的**每个已记录实体**的属性和状态必须与记录完全一致\n"
            "● 如发现本章内容与已有记录矛盾，必须在审核报告中列为\"设定冲突\"问题\n"
            "● 如有新的实体或设定出现，在状态更新的实体记录部分补充\n"
        )

        return "\n".join(parts)

    def _extract_field(self, text: str, pattern: str) -> Optional[str]:
        """从文本中提取单个字段"""
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
        return None

    def _extract_section(self, text: str, title: str) -> Optional[str]:
        """提取某个标题下的段落内容"""
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

    def _append_section(self, content: str, title: str, new_content: str) -> str:
        """在文件末尾追加一个段落"""
        content = content.rstrip("\n")
        content += f"\n\n## {title}\n{new_content}\n"
        return content

    def _default_check_memory(self) -> Dict[str, Any]:
        """默认 memory_check 结构"""
        return {
            "processed_chapters": "（暂无）",
            "characters": "（暂无）",
            "buildings": "（暂无）",
            "sects": "（暂无）",
            "organizations": "（暂无）",
            "items": "（暂无）",
            "finance": "（暂无）",
            "pills": "（暂无）",
            "skills": "（暂无）",
            "character_relationships": "（暂无）",
            "character_sect_relations": "（暂无）",
            "conflicts": "（暂无）",
            "events": "（暂无）",
            "timeline": "（暂无）",
        }

    def _default_check_memory_text(self) -> str:
        """默认 memory_check.md 文本内容"""
        return """# 章节实体记忆库

## 处理记录
- 已处理章节: （暂无）

## 人物
（暂无）

## 建筑
（暂无）

## 宗门
（暂无）

## 单位
（暂无）

## 物品
（暂无）

## 财务
（暂无）

## 丹药
（暂无）

## 功法
（暂无）

## 人物关系
（暂无）

## 人物-宗门关系
（暂无）

## 冲突
（暂无）

## 事件
（暂无）

## 时间线
（暂无）
"""
