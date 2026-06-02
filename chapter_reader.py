"""
chapter_reader.py - 章节读取与整本小说解析模块

双模式：
1. 目录模式 - 从 chapters/ 目录读取单个章节文件
2. 整本小说模式 - 解析一本小说文件，自动分割章节
"""

import os
import re
from typing import List, Tuple, Optional, Dict


class NovelParser:
    """整本小说解析器 - 从单一文件解析并分割章节"""

    # 章节标题正则（按优先级）
    # 注意：支持 Markdown 标题前缀 "# " 和 "## "
    CHAPTER_PATTERNS = [
        # 第X章 - 最标准格式（含标题）
        r"^#{0,3}\s*第([一二三四五六七八九十零百千万\d]+)章\s*(.*?)$",
        # 第X回
        r"^#{0,3}\s*第([一二三四五六七八九十零百千万\d]+)回\s*(.*?)$",
        # 第X节
        r"^#{0,3}\s*第([一二三四五六七八九十零百千万\d]+)节\s*(.*?)$",
        # 第X卷（有时也作为章节分隔）
        r"^#{0,3}\s*第([一二三四五六七八九十零百千万\d]+)卷\s*(.*?)$",
        # 楔子 / 序章 / 尾声
        r"^#{0,3}\s*(楔子|序章|尾声|序言|后记)\s*$",
        # 数字标题：一、 / 1、 / 壹、
        r"^#{0,3}\s*([一二三四五六七八九十零百千万\d]+)[、\.\s]\s*(.*?)$",
    ]

    # 中文数字映射（仅用于简单的一对一映射）
    CN_NUMS = {
        "零": "0", "一": "1", "二": "2", "三": "3", "四": "4",
        "五": "5", "六": "6", "七": "7", "八": "8", "九": "9",
    }

    def __init__(self, filepath: str):
        self.filepath = filepath
        self._chapters: List[Dict[str, str]] = []
        self._parsed = False
        self._pattern_used: Optional[re.Pattern] = None

    def parse(self) -> List[Dict[str, str]]:
        """
        解析整本小说文件，分割为章节列表

        Returns:
            [
                {
                    "index": "00",
                    "label": "第00章",
                    "title": "楔子",
                    "content": "纯内容（不含标题行）",
                    "raw": "楔子\n..."   # 含标题行的原文
                },
                ...
            ]
        """
        if self._parsed:
            return self._chapters

        if not os.path.exists(self.filepath):
            raise FileNotFoundError(f"小说文件不存在: {self.filepath}")

        print(f"   📖 正在解析小说文件: {self.filepath}")

        with open(self.filepath, "r", encoding="utf-8") as f:
            full_text = f.read()

        # 检测章节格式
        pattern, is_match = self._detect_pattern(full_text)
        self._pattern_used = pattern

        if not is_match:
            print("   ⚠️  未检测到标准章节标题，尝试按段落大小分割...")
            # 如果完全检测不到，按每500行作为一个章节
            self._chapters = self._split_by_size(full_text)
        else:
            self._chapters = self._split_by_pattern(full_text, pattern, is_match)
            print(f"   ✅ 检测到 {len(self._chapters)} 个章节，使用格式: {self._describe_pattern(pattern)}")

        self._parsed = True
        return self._chapters

    def get_chapters(self) -> List[Dict[str, str]]:
        """获取已解析的章节列表"""
        if not self._parsed:
            return self.parse()
        return self._chapters

    def read_chapter(self, index: str) -> Optional[str]:
        """按序号读取章节内容"""
        chapters = self.get_chapters()
        for ch in chapters:
            if ch["index"] == index:
                return ch["content"]
        return None

    def get_previous_chapter(self, index: str) -> Optional[str]:
        """获取上一章内容"""
        chapters = self.get_chapters()
        found = False
        for ch in reversed(chapters):
            if ch["index"] == index:
                found = True
            elif found:
                return ch["content"]
        return None

    def get_chapter_count(self) -> int:
        """获取章节总数"""
        return len(self.get_chapters())

    def get_chapter_label(self, index: str) -> str:
        """根据序号生成标签"""
        return f"第{index}章"

    def _detect_pattern(self, text: str) -> Tuple[Optional[re.Pattern], Optional[callable]]:
        """
        自动检测文本中最匹配的章节标题格式
        返回: (编译后的正则, 匹配判断函数)
        """
        lines = text.split("\n")
        # 取前200行和后200行检测
        sample_lines = lines[:200] + (lines[-200:] if len(lines) > 400 else [])

        best_pattern = None
        best_match_fn = None
        best_count = 0

        for pattern_str in self.CHAPTER_PATTERNS:
            pattern = re.compile(pattern_str, re.MULTILINE)
            matches = pattern.findall(text[:50000])  # 前5万字检测
            count = len(matches)
            if count > best_count:
                best_count = count
                best_pattern = pattern
                best_match_fn = lambda m: m  # 标准匹配

        # 如果没有找到标准格式，尝试宽松匹配
        if best_count < 2:
            # 尝试匹配"第X章"任意位置
            loose = re.compile(r"第([\d一二三四五六七八九十百千万零]+)章", re.MULTILINE)
            matches = loose.findall(text[:50000])
            if len(matches) >= best_count and len(matches) > 0:
                best_count = len(matches)
                best_pattern = re.compile(
                    r"^#{0,3}\s*第([\d一二三四五六七八九十百千万零]+)章\s*(.*?)$", re.MULTILINE
                )
                best_match_fn = lambda m: m

        if best_count >= 1:
            return best_pattern, best_match_fn
        return None, None

    def _split_by_pattern(self, text: str, pattern: re.Pattern, match_fn) -> List[Dict[str, str]]:
        """
        按检测到的章节标题格式分割文本

        使用顺序编号（01, 02, 03...）作为输出索引，
        原始章节号存储在 title 字段中供参考。
        楔子/序章使用 "00"。
        """
        chapters = []
        lines = text.split("\n")

        # 状态跟踪
        current_title = ""           # 当前章节的标题文字
        current_title_line = ""      # 当前章节的原始标题行
        current_lines = []           # 当前章节的内容行
        chapter_index = 1            # 顺序编号（从01开始）
        first_is_prologue = False    # 第一章是否为楔子/序章

        for line in lines:
            m = pattern.match(line)
            if m:
                # 遇到新标题 -> 保存上一章
                if current_lines:
                    content = "\n".join(current_lines).strip()
                    if content:
                        # 使用顺序编号
                        if first_is_prologue and chapter_index == 1:
                            idx = "00"
                        else:
                            idx = str(chapter_index).zfill(2)
                        label = f"第{idx}章"
                        chapters.append({
                            "index": idx,
                            "label": label,
                            "title": current_title if current_title else current_title_line.strip(),
                            "content": content,
                            "raw": (current_title_line.strip() + "\n" + content),
                        })
                        chapter_index += 1

                # 开始新章节
                current_title_line = line
                groups = m.groups()

                if len(groups) >= 2:
                    num_part = groups[0]
                    title_part = groups[1].strip() if groups[1] else ""
                    num_str = self._cn_to_arabic(num_part)
                    current_title = f"第{num_str}章 {title_part}" if title_part else f"第{num_str}章"
                elif len(groups) == 1:
                    current_title = groups[0]
                    if groups[0] in ("楔子", "序章", "序言"):
                        first_is_prologue = True
                else:
                    current_title = line.strip()

                current_lines = []
            else:
                current_lines.append(line)

        # 保存最后一章
        if current_lines:
            content = "\n".join(current_lines).strip()
            if content:
                if first_is_prologue and chapter_index == 1:
                    idx = "00"
                else:
                    idx = str(chapter_index).zfill(2)
                label = f"第{idx}章"
                chapters.append({
                    "index": idx,
                    "label": label,
                    "title": current_title if current_title else current_title_line.strip(),
                    "content": content,
                    "raw": (current_title_line.strip() + "\n" + content),
                })

        return chapters

    def _extract_index_from_groups(self, groups) -> Optional[str]:
        """从正则匹配组中提取章节序号"""
        if not groups:
            return None
        if len(groups) >= 2:
            num_part = groups[0]
            if re.match(r"^\d+$", str(num_part)):
                return str(num_part).zfill(2)
            return self._cn_to_arabic(str(num_part))
        if len(groups) == 1:
            if groups[0] in ("楔子", "序章", "序言"):
                return "00"
        return None

    def _split_by_size(self, text: str) -> List[Dict[str, str]]:
        """无法检测章节标题时，按固定行数分割"""
        lines = text.split("\n")
        chapters = []
        chunk_size = 500
        chapter_index = 0

        for i in range(0, len(lines), chunk_size):
            chunk = lines[i:i + chunk_size]
            content = "\n".join(chunk).strip()
            if content:
                idx = str(chapter_index).zfill(2)
                chapters.append({
                    "index": idx,
                    "label": f"第{idx}章",
                    "title": f"第{idx}章",
                    "content": content,
                    "raw": content,
                })
                chapter_index += 1

        print(f"   ⚠️  按每{chunk_size}行分割为 {len(chapters)} 个段落")
        return chapters

    def _cn_to_arabic(self, cn_str: str) -> str:
        """中文数字转阿拉伯数字字符串（支持 一~九百九十九）"""
        try:
            # 如果已经是数字
            int(cn_str)
            return cn_str.zfill(2)
        except ValueError:
            pass

        # 单位映射
        unit_map = {"十": 10, "百": 100, "千": 1000}
        digit_map = {
            "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
        }

        # 如果只是单个数字
        if cn_str in digit_map:
            return str(digit_map[cn_str]).zfill(2)
        if cn_str in unit_map:
            return str(unit_map[cn_str]).zfill(2)

        result = 0
        tmp = 0

        for ch in cn_str:
            if ch in digit_map:
                tmp = digit_map[ch]
            elif ch in unit_map:
                unit = unit_map[ch]
                if tmp == 0:
                    tmp = 1  # "十" 开头 → 10
                result += tmp * unit
                tmp = 0
            else:
                pass  # 忽略无关字符

        result += tmp  # 加上末尾数字（如 "二十一" 中的 "一"）

        return str(result).zfill(2)

    def _describe_pattern(self, pattern: re.Pattern) -> str:
        """描述检测到的模式（仅用于日志）"""
        pattern_str = pattern.pattern
        if "第" in pattern_str and "章" in pattern_str:
            return "第X章"
        elif "第" in pattern_str and "回" in pattern_str:
            return "第X回"
        elif "楔子" in pattern_str:
            return "楔子/序章"
        elif "第" in pattern_str and "卷" in pattern_str:
            return "第X卷"
        return "章节标题"


class ChapterReader:
    """目录模式章节读取器 - 从 chapters/ 目录读取文件"""

    def __init__(self, chapters_dir: str = "chapters"):
        self.chapters_dir = chapters_dir

    def scan_chapters(self) -> List[Tuple[str, str]]:
        """
        扫描章节目录，返回排序后的 (文件名, 章节序号) 列表

        Returns:
            [(filename, chapter_number_str), ...]
            按章节顺序排序
        """
        if not os.path.exists(self.chapters_dir):
            return []

        files = os.listdir(self.chapters_dir)
        chapter_files = []

        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in (".md", ".txt"):
                continue

            num = self._extract_chapter_number(f)
            if num is not None:
                chapter_files.append((f, num))

        chapter_files.sort(key=lambda x: int(x[1]))
        return chapter_files

    def get_chapter_count(self) -> int:
        """获取章节总数"""
        return len(self.scan_chapters())

    def read_chapter(self, chapter_num: str) -> Optional[str]:
        """
        读取指定章节的内容

        Args:
            chapter_num: 章节序号，如 "01", "1"

        Returns:
            章节文本内容，如果文件不存在则返回 None
        """
        filename = self._find_chapter_file(chapter_num)
        if not filename:
            return None

        filepath = os.path.join(self.chapters_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()

    def find_chapter_info(self, chapter_label: str) -> Optional[str]:
        """根据章节标签查找对应的章节序号"""
        chapters = self.scan_chapters()
        for filename, num in chapters:
            label = f"第{num}章"
            if label == chapter_label:
                return num
            if f"第{num}章" in filename or chapter_label in filename:
                return num
        return None

    def read_previous_chapter(self, current_chapter_label: str) -> Optional[str]:
        """读取当前章节的上一章内容"""
        chapters = self.scan_chapters()
        current_num = None
        m = re.search(r"(\d+)", current_chapter_label)
        if m:
            current_num = int(m.group(1))

        if current_num is None or current_num <= 1:
            return None

        prev_num = str(current_num - 1).zfill(2)
        return self.read_chapter(prev_num)

    def get_chapter_label(self, chapter_num: str) -> str:
        """根据序号生成章节标签"""
        return f"第{chapter_num}章"

    def _extract_chapter_number(self, filename: str) -> Optional[str]:
        """从文件名中提取章节序号"""
        name = os.path.splitext(filename)[0]

        m = re.search(r"第(\d+)章", name)
        if m:
            return m.group(1).zfill(2)

        chinese_nums = {
            "一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
            "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
            "零": "0",
        }
        m = re.search(r"第([一二三四五六七八九十零]+)章", name)
        if m:
            ch_num = m.group(1)
            if ch_num in chinese_nums:
                return chinese_nums[ch_num].zfill(2)

        m = re.match(r"(\d+)$", name)
        if m:
            return m.group(1).zfill(2)

        return None

    def _find_chapter_file(self, chapter_num: str) -> Optional[str]:
        """根据章节序号查找对应的文件名"""
        chapters = self.scan_chapters()
        for filename, num in chapters:
            if num == chapter_num:
                return filename
        return None
