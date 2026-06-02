"""
system.py - 核心系统逻辑

双模式：
1. 整本小说模式 - 从单一小说文件解析章节
2. 目录模式 - 从 chapters/ 目录读取章节文件

负责：
1. 审核循环控制
2. 从 memory 确定当前待优化章节
3. 调用各组件完成"读取→审核→优化→保存→更新"循环
4. 检查是否所有章节已完成
"""

import os
import re
from typing import Any, Dict, Optional, Tuple, List

from memory_manager import MemoryManager
from memory_check import MemoryCheckManager
from chapter_reader import ChapterReader, NovelParser
from ai_reviewer import AIReviewer


class NovelReviewSystem:
    """小说审核优化系统"""

    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: 配置字典
        """
        self.config = config
        self.memory_manager = MemoryManager(config.get("memory_file", "memory.md"))
        self.check_manager = MemoryCheckManager(config.get("check_file", "memory_check.md"))
        self.output_dir = config.get("output_dir", "output")
        self.ai_reviewer = AIReviewer(config)

        # 存储已处理的章节内容（用于生成提示词）
        self._processed_chapters: List[Dict[str, str]] = []

        # 检测模式：整本小说模式 vs 目录模式
        self.novel_file = config.get("novel_file", "") or os.getenv("NOVEL_FILE", "")
        self.novel_parser = None
        self.chapter_reader = None
        self._mode = None  # "novel" or "directory"

        if self.novel_file:
            self._mode = "novel"
            self.novel_parser = NovelParser(self.novel_file)
        else:
            self._mode = "directory"
            self.chapter_reader = ChapterReader(config.get("chapters_dir", "chapters"))

        # 确保输出目录存在
        os.makedirs(self.output_dir, exist_ok=True)

        # 累计器：用于生成综合输出文件
        self._all_optimized: List[str] = []
        self._all_reports: List[str] = []

    def run(self) -> None:
        """运行完整的审核优化流程"""
        print("=" * 60)
        print("   传统武侠小说审核与优化系统")
        print("=" * 60)

        if self._mode == "novel":
            self._run_novel_mode()
        else:
            self._run_directory_mode()

    def run_single(self, chapter_label_or_num: str, mode: str = "review_optimize") -> None:
        """
        处理单个指定章节

        Args:
            chapter_label_or_num: "第01章" 或 "01" 格式
            mode: 处理模式
                - "generate": 正文生成（从大纲生成新章节）
                - "review": 正文审核（仅审核，不优化）
                - "optimize": 正文优化（审核+优化）
                - "review_optimize": 审核+优化（默认，兼容旧流程）
        """
        num = self._extract_number(chapter_label_or_num)
        if not num:
            print(f"❌ 无法识别章节: {chapter_label_or_num}")
            return

        memory = self.memory_manager.read_memory()

        # 读取 memory_check 实体记忆库
        check_memory = self.check_manager.read_check_memory()
        check_context = self.check_manager.format_for_prompt(check_memory)

        chapter_label = f"第{num}章"

        print(f"\n{'=' * 60}")
        print(f"   正在处理: {chapter_label} (模式: {mode})")
        print(f"{'=' * 60}")

        try:
            if mode == "generate":
                # 正文生成模式
                self._handle_generate_mode(num, chapter_label, memory, check_context)
            elif mode == "review":
                # 正文审核模式
                self._handle_review_mode(num, chapter_label, memory, check_context)
            elif mode in ("optimize", "review_optimize"):
                # 正文优化模式（审核+优化）
                self._handle_optimize_mode(num, chapter_label, memory, check_context)
            else:
                print(f"❌ 未知模式: {mode}")

        except Exception as e:
            print(f"\n❌ 处理 {chapter_label} 时出错: {e}")

    def _handle_generate_mode(self, num: str, chapter_label: str, memory: dict, check_context: str) -> None:
        """处理正文生成模式"""
        # 获取本章大纲
        chapter_outline = self._get_chapter_outline(num)
        if not chapter_outline:
            print(f"❌ 找不到第{num}章的大纲信息")
            return

        # 获取前面章节内容
        previous_chapters = self._get_previous_chapters(num)

        # 生成正文
        generated_text, state_update = self.ai_reviewer.generate_chapter(
            chapter_num=int(num),
            chapter_title=chapter_outline.get("title", f"第{num}章"),
            chapter_outline=chapter_outline.get("outline", ""),
            previous_chapters=previous_chapters,
            memory_context=memory,
            check_memory_context=check_context
        )

        if not generated_text or len(generated_text.strip()) < 100:
            print(f"\n⚠️ 生成文本为空或过短({len(generated_text or '')}字符)")
            raise ValueError(f"生成文本内容无效（{len(generated_text or '')}字符）")

        print(f"\n{'─' * 60}")
        print(f"   生成完成")
        print(f"{'─' * 60}")
        print(f"   字数: {len(generated_text)} 字符")

        # 构建带标题的文本
        optimized_heading = f"# {chapter_label}\n\n"
        optimized_with_heading = optimized_heading + generated_text

        # 累计到综合输出列表
        self._all_optimized.append(optimized_with_heading)

        # 写入综合输出文件
        self._write_combined_files()

        total = self._get_total_chapters()
        self._update_memory_after_chapter(num, total, "", generated_text, state_update=state_update)

        # 更新 memory_check 实体记忆库
        check_memory = self.check_manager.read_check_memory()
        self._update_check_memory_after_chapter(num, check_memory, state_update)

        # 记录已处理章节
        self._processed_chapters.append({
            "num": num,
            "title": chapter_outline.get("title", ""),
            "content": generated_text
        })

        print(f"\n✅ {chapter_label} 正文生成完成！")

    def _handle_review_mode(self, num: str, chapter_label: str, memory: dict, check_context: str) -> None:
        """处理正文审核模式"""
        # 读取章节内容
        if self._mode == "novel":
            chapter_content = self.novel_parser.read_chapter(num)
        else:
            chapter_content = self.chapter_reader.read_chapter(num)

        if not chapter_content:
            print(f"❌ 找不到章节: {chapter_label}")
            return

        # 打印章节预览
        preview_len = min(len(chapter_content), 500)
        print(f"\n{'─' * 60}")
        print(f"   章节内容预览")
        print(f"{'─' * 60}")
        print(f"   总字数: {len(chapter_content)} 字符")
        print(chapter_content[:preview_len])
        if len(chapter_content) > preview_len:
            print(f"\n   ...(共 {len(chapter_content)} 字符)")
        print(f"{'─' * 60}")

        # 审核
        review_report, state_update = self.ai_reviewer.review_chapter(
            chapter_content, memory, check_memory_context=check_context
        )

        print(f"\n{'─' * 60}")
        print(f"   审核报告")
        print(f"{'─' * 60}")
        print(review_report)

        # 构建带标题的审核报告
        report_heading = f"# {chapter_label} 审核报告\n\n"
        report_with_heading = report_heading + review_report

        # 累计到综合输出列表
        self._all_reports.append(report_with_heading)

        # 写入综合输出文件
        self._write_combined_files()

        print(f"\n✅ {chapter_label} 审核完成！")

    def _handle_optimize_mode(self, num: str, chapter_label: str, memory: dict, check_context: str) -> None:
        """处理正文优化模式（审核+优化）"""
        # 读取章节内容
        if self._mode == "novel":
            chapter_content = self.novel_parser.read_chapter(num)
        else:
            chapter_content = self.chapter_reader.read_chapter(num)

        if not chapter_content:
            print(f"❌ 找不到章节: {chapter_label}")
            return

        # 打印章节预览
        preview_len = min(len(chapter_content), 500)
        print(f"\n{'─' * 60}")
        print(f"   章节内容预览")
        print(f"{'─' * 60}")
        print(f"   总字数: {len(chapter_content)} 字符")
        print(chapter_content[:preview_len])
        if len(chapter_content) > preview_len:
            print(f"\n   ...(共 {len(chapter_content)} 字符)")
        print(f"{'─' * 60}")

        # 第一步：审核
        print(f"\n🔍 第一步：审核章节内容...")
        review_report, review_state = self.ai_reviewer.review_chapter(
            chapter_content, memory, check_memory_context=check_context
        )

        print(f"\n{'─' * 60}")
        print(f"   审核报告")
        print(f"{'─' * 60}")
        print(review_report)

        # 第二步：优化
        print(f"\n✨ 第二步：优化章节内容...")

        # 获取本章大纲
        chapter_outline = self._get_chapter_outline(num)
        outline_text = chapter_outline.get("outline", "") if chapter_outline else ""

        # 获取前面章节内容
        previous_chapters = self._get_previous_chapters(num)

        optimized_text, optimize_state = self.ai_reviewer.optimize_chapter(
            review_report=review_report,
            chapter_content=chapter_content,
            chapter_num=int(num),
            chapter_title=chapter_outline.get("title", f"第{num}章") if chapter_outline else f"第{num}章",
            chapter_outline=outline_text,
            previous_chapters=previous_chapters,
            memory_context=memory,
            check_memory_context=check_context
        )

        # 合并状态更新
        state_update = {**review_state, **optimize_state}

        if not optimized_text or len(optimized_text.strip()) < 100:
            print(f"\n⚠️ 优化后文本为空或过短({len(optimized_text or '')}字符)")
            raise ValueError(f"优化文本内容无效（{len(optimized_text or '')}字符）")

        print(f"\n{'─' * 60}")
        print(f"   优化完成")
        print(f"{'─' * 60}")
        print(f"   字数: {len(optimized_text)} 字符")

        # 构建带标题的优化文本
        raw_title = chapter_content.split("\n")[0].strip() if chapter_content else ""
        ch_title = chapter_label
        if re.search(r"第[\d一二三四五六七八九十百千万零]+章\s+\S", raw_title):
            ch_title = raw_title

        optimized_heading = f"# {ch_title}\n\n"
        optimized_with_heading = optimized_heading + optimized_text

        # 构建带标题的审核报告
        report_heading = f"# {chapter_label} 审核报告\n\n"
        report_with_heading = report_heading + review_report

        # 累计到综合输出列表
        self._all_optimized.append(optimized_with_heading)
        self._all_reports.append(report_with_heading)

        # 写入综合输出文件
        self._write_combined_files()

        print(f"\n💾 优化结果已累计（字数: {len(optimized_text)} 字符）")

        total = self._get_total_chapters()
        self._update_memory_after_chapter(num, total, chapter_content, optimized_text, state_update=state_update)

        # 更新 memory_check 实体记忆库
        check_memory = self.check_manager.read_check_memory()
        self._update_check_memory_after_chapter(num, check_memory, state_update)

        # 记录已处理章节
        self._processed_chapters.append({
            "num": num,
            "title": ch_title,
            "content": optimized_text
        })

        print(f"\n✅ {chapter_label} 审核优化完成！")

    def _run_novel_mode(self) -> None:
        """整本小说模式的主处理循环"""
        try:
            self.novel_parser.parse()
        except FileNotFoundError as e:
            print(f"\n❌ {e}")
            return

        chapters = self.novel_parser.get_chapters()
        print(f"\n📚 检测到 {len(chapters)} 个章节:")
        for ch in chapters[:10]:
            print(f"   - {ch['label']} {ch['title']}")
        if len(chapters) > 10:
            print(f"   ... 共 {len(chapters)} 章")

        # 更新总章节数
        self.memory_manager.update_memory({"total_chapters": str(len(chapters))})

        print(f"\n{'=' * 60}")
        print(f"   开始审核流程")
        print(f"{'=' * 60}")

        while True:
            memory = self.memory_manager.read_memory()
            pending = memory.get("pending_chapter", "无")

            if pending == "无" or pending == "全部完成":
                print("\n🎉 所有章节已审核优化完成！")
                break

            chapter_num = self._extract_number(pending)
            if not chapter_num:
                optimized = memory.get("optimized_chapter", "无")
                opt_num = self._extract_number(optimized)
                if opt_num is not None:
                    chapter_num = str(int(opt_num) + 1).zfill(2)
                else:
                    chapter_num = chapters[0]["index"]

            # 查找章节
            chapter_data = None
            for ch in chapters:
                if ch["index"] == chapter_num:
                    chapter_data = ch
                    break

            if not chapter_data:
                # 按顺序找下一个未处理的
                opt_num = self._extract_number(memory.get("optimized_chapter", "0")) or 0
                available = [ch for ch in chapters if int(ch["index"]) >= int(opt_num) + 1]
                if available:
                    chapter_data = available[0]
                    chapter_num = chapter_data["index"]
                else:
                    print("❌ 没有可处理的章节，终止。")
                    break

            chapter_label = f"第{chapter_num}章"

            # 跳过已处理的
            optimized = memory.get("optimized_chapter", "无")
            if chapter_label in optimized:
                print(f"\n⏭️  {chapter_label} 已优化完成，跳过。")
                self._advance_to_next(chapter_num, len(chapters), chapters_list=chapters)
                continue

            print(f"\n{'=' * 60}")
            print(f"   正在处理: {chapter_label} - {chapter_data.get('title', '')}")
            print(f"{'=' * 60}")

            chapter_content = chapter_data["content"]

            # 读取 memory_check 实体记忆库
            check_memory = self.check_manager.read_check_memory()
            check_context = self.check_manager.format_for_prompt(check_memory)

            # 打印当前章节的审核信息（内容预览）
            preview_len = min(len(chapter_content), 500)
            print(f"\n{'─' * 60}")
            print(f"   当前章节审核预览")
            print(f"{'─' * 60}")
            print(f"   章节: {chapter_label} - {chapter_data.get('title', '')}")
            print(f"   总字数: {len(chapter_content)} 字符")
            print(f"   内容预览 ({preview_len}字符):")
            print(f"{'─' * 60}")
            print(chapter_content[:preview_len])
            if len(chapter_content) > preview_len:
                print(f"\n   ...(共 {len(chapter_content)} 字符，此处仅显示前 {preview_len} 字符)")
            print(f"{'─' * 60}")

            print(f"\n🔍 正在调用 AI 进行审核与优化...")
            print(f"   模型: {self.config.get('model', 'gpt-4o')}")

            try:
                # 第一步：审核
                print(f"\n🔍 第一步：审核章节内容...")
                review_report, review_state = self.ai_reviewer.review_chapter(
                    chapter_content, memory, check_memory_context=check_context
                )

                print(f"\n{'─' * 60}")
                print(f"   审核报告")
                print(f"{'─' * 60}")
                print(review_report)

                # 第二步：优化
                print(f"\n✨ 第二步：优化章节内容...")
                chapter_outline = self._get_chapter_outline(chapter_num)
                outline_text = chapter_outline.get("outline", "") if chapter_outline else ""
                previous_chapters = self._get_previous_chapters(chapter_num)

                optimized_text, optimize_state = self.ai_reviewer.optimize_chapter(
                    review_report=review_report,
                    chapter_content=chapter_content,
                    chapter_num=int(chapter_num),
                    chapter_title=chapter_data.get('title', f"第{chapter_num}章"),
                    chapter_outline=outline_text,
                    previous_chapters=previous_chapters,
                    memory_context=memory,
                    check_memory_context=check_context
                )

                state_update = {**review_state, **optimize_state}

                # 验证优化文本不为空
                if not optimized_text or len(optimized_text.strip()) < 100:
                    raise ValueError(f"优化文本内容无效（{len(optimized_text or '')}字符）")

                # 检查章节标题是否存在
                raw_title = chapter_data.get("title", "").strip()
                ch_title = raw_title if raw_title and raw_title != chapter_label else chapter_label

                # 构建带标题的优化文本
                optimized_heading = f"# {ch_title}\n\n"
                optimized_with_heading = optimized_heading + optimized_text

                # 构建带标题的审核报告
                report_heading = f"# {chapter_label} 审核报告\n\n"
                report_with_heading = report_heading + review_report

                # 累计到综合输出列表
                self._all_optimized.append(optimized_with_heading)
                self._all_reports.append(report_with_heading)

                print(f"\n💾 优化结果已累计（字数: {len(optimized_text)} 字符）")

                self._update_memory_after_chapter(
                    chapter_num, len(chapters), chapter_content, optimized_text,
                    state_update=state_update
                )

                # 更新 memory_check 实体记忆库
                self._update_check_memory_after_chapter(chapter_num, check_memory, state_update)

                # 记录已处理章节
                self._processed_chapters.append({
                    "num": chapter_num,
                    "title": ch_title,
                    "content": optimized_text
                })

                print(f"\n✅ {chapter_label} 审核优化完成！")

                # 每章处理完后增量写入综合文件，防止后续崩溃导致数据丢失
                self._write_combined_files()

            except Exception as e:
                print(f"\n❌ 处理 {chapter_label} 时出错: {e}")
                print(f"   请检查 API 配置和网络连接后重试。")
                break

        print(f"\n{'=' * 60}")
        print(f"   审核流程结束")
        print(f"{'=' * 60}")

        # 写综合输出文件（最终写入，确保完整性）
        self._write_combined_files()

    def _run_directory_mode(self) -> None:
        """目录模式的主处理循环"""
        chapters = self.chapter_reader.scan_chapters()
        if not chapters:
            print("\n❌ 错误: chapters/ 目录下没有找到任何章节文件。")
            print("   请将章节文件（第01章.md、第02章.md...）放入 chapters/ 目录。")
            print("   或使用 --novel-file 参数指定整本小说文件。")
            return

        print(f"\n📚 检测到 {len(chapters)} 个章节:")
        for filename, num in chapters:
            print(f"   - {filename}")

        self.memory_manager.update_memory({"total_chapters": str(len(chapters))})

        print(f"\n{'=' * 60}")
        print(f"   开始审核流程")
        print(f"{'=' * 60}")

        while True:
            memory = self.memory_manager.read_memory()
            pending = memory.get("pending_chapter", "无")

            if pending == "无" or pending == "全部完成":
                print("\n🎉 所有章节已审核优化完成！")
                break

            chapter_num = self._extract_number(pending)
            if not chapter_num:
                optimized = memory.get("optimized_chapter", "无")
                opt_num = self._extract_number(optimized)
                if opt_num is not None:
                    chapter_num = str(int(opt_num) + 1).zfill(2)
                else:
                    chapter_num = chapters[0][1]

            chapter_content = self.chapter_reader.read_chapter(chapter_num)
            chapter_label = f"第{chapter_num}章"

            if not chapter_content:
                found_num = self.chapter_reader.find_chapter_info(pending)
                if found_num:
                    chapter_content = self.chapter_reader.read_chapter(found_num)
                    chapter_num = found_num
                    chapter_label = f"第{found_num}章"

            if not chapter_content:
                available = [
                    (fn, num)
                    for fn, num in chapters
                    if int(num) >= (
                        int(self._extract_number(memory.get("optimized_chapter", "0")) or 0) + 1
                    )
                ]
                if available:
                    chapter_num = available[0][1]
                    chapter_label = f"第{chapter_num}章"
                    chapter_content = self.chapter_reader.read_chapter(chapter_num)
                    print(f"\n   自动切换到下一章: {chapter_label}")
                else:
                    print("❌ 没有可处理的章节，终止。")
                    break

            optimized = memory.get("optimized_chapter", "无")
            if chapter_label in optimized or f"第{chapter_num}章" in optimized:
                print(f"\n⏭️  {chapter_label} 已优化完成，跳过。")
                self._advance_to_next(chapter_num, len(chapters))
                continue

            print(f"\n{'=' * 60}")
            print(f"   正在处理: {chapter_label}")
            print(f"{'=' * 60}")

            # 读取 memory_check 实体记忆库
            check_memory = self.check_manager.read_check_memory()
            check_context = self.check_manager.format_for_prompt(check_memory)

            # 打印当前章节的审核信息（内容预览）
            preview_len = min(len(chapter_content), 500)
            print(f"\n{'─' * 60}")
            print(f"   当前章节审核预览")
            print(f"{'─' * 60}")
            print(f"   章节: {chapter_label}")
            print(f"   总字数: {len(chapter_content)} 字符")
            print(f"   内容预览 ({preview_len}字符):")
            print(f"{'─' * 60}")
            print(chapter_content[:preview_len])
            if len(chapter_content) > preview_len:
                print(f"\n   ...(共 {len(chapter_content)} 字符，此处仅显示前 {preview_len} 字符)")
            print(f"{'─' * 60}")

            print(f"\n🔍 正在调用 AI 进行审核与优化...")
            print(f"   模型: {self.config.get('model', 'gpt-4o')}")

            try:
                # 第一步：审核
                print(f"\n🔍 第一步：审核章节内容...")
                review_report, review_state = self.ai_reviewer.review_chapter(
                    chapter_content, memory, check_memory_context=check_context
                )

                print(f"\n{'─' * 60}")
                print(f"   审核报告")
                print(f"{'─' * 60}")
                print(review_report)

                # 第二步：优化
                print(f"\n✨ 第二步：优化章节内容...")
                chapter_outline = self._get_chapter_outline(chapter_num)
                outline_text = chapter_outline.get("outline", "") if chapter_outline else ""
                previous_chapters = self._get_previous_chapters(chapter_num)

                optimized_text, optimize_state = self.ai_reviewer.optimize_chapter(
                    review_report=review_report,
                    chapter_content=chapter_content,
                    chapter_num=int(chapter_num),
                    chapter_title=f"第{chapter_num}章",
                    chapter_outline=outline_text,
                    previous_chapters=previous_chapters,
                    memory_context=memory,
                    check_memory_context=check_context
                )

                state_update = {**review_state, **optimize_state}

                # 验证优化文本不为空
                if not optimized_text or len(optimized_text.strip()) < 100:
                    raise ValueError(f"优化文本内容无效（{len(optimized_text or '')}字符）")

                print(f"\n{'─' * 60}")
                print(f"   优化完成")
                print(f"{'─' * 60}")
                print(f"   字数: {len(optimized_text)} 字符")

                # 从内容中提取章节标题（检查是否存在）
                first_line = chapter_content.split("\n")[0].strip()
                ch_title = chapter_label
                if re.search(r"第[\d一二三四五六七八九十百千万零]+章\s+\S", first_line):
                    ch_title = first_line

                # 构建带标题的优化文本
                optimized_heading = f"# {ch_title}\n\n"
                optimized_with_heading = optimized_heading + optimized_text

                # 构建带标题的审核报告
                report_heading = f"# {chapter_label} 审核报告\n\n"
                report_with_heading = report_heading + review_report

                # 累计到综合输出列表
                self._all_optimized.append(optimized_with_heading)
                self._all_reports.append(report_with_heading)

                print(f"\n💾 优化结果已累计（字数: {len(optimized_text)} 字符）")

                self._update_memory_after_chapter(
                    chapter_num, len(chapters), chapter_content, optimized_text,
                    state_update=state_update
                )

                # 更新 memory_check 实体记忆库
                self._update_check_memory_after_chapter(chapter_num, check_memory, state_update)

                # 记录已处理章节
                self._processed_chapters.append({
                    "num": chapter_num,
                    "title": ch_title,
                    "content": optimized_text
                })

                print(f"\n✅ {chapter_label} 审核优化完成！")

                # 每章处理完后增量写入综合文件，防止后续崩溃导致数据丢失
                self._write_combined_files()

            except Exception as e:
                print(f"\n❌ 处理 {chapter_label} 时出错: {e}")
                print(f"   请检查 API 配置和网络连接后重试。")
                break

        print(f"\n{'=' * 60}")
        print(f"   审核流程结束")
        print(f"{'=' * 60}")

        # 写综合输出文件（最终写入，确保完整性）
        self._write_combined_files()

    # ---- 以下为通用辅助方法 ----

    def _get_chapter_outline(self, chapter_num: str) -> Optional[Dict[str, str]]:
        """
        从 config.json 的 plot 大纲中提取指定章节的大纲信息

        Args:
            chapter_num: 章节编号（如 "01", "02"）

        Returns:
            {"title": "章节标题", "outline": "章节大纲内容"} 或 None
        """
        plot = self.config.get("plot", "")
        if not plot:
            return None

        # 查找章节标题和大纲
        # 匹配格式如：1. **中秋惊变**（第1章）：...
        # 或：1. **中秋惊变**（第1章）：内容
        chapter_int = int(chapter_num)

        # 尝试多种匹配模式
        patterns = [
            # 模式1: 数字. **标题**（第X章）：内容
            rf"{chapter_int}\.\s*\*\*([^*]+)\*\*（第{chapter_int}章）[：:]\s*(.+?)(?=\n\d+\.|\n---|\n###|\Z)",
            # 模式2: **标题**（第X章）：内容
            rf"\*\*([^*]+)\*\*（第{chapter_int}章）[：:]\s*(.+?)(?=\n\d+\.|\n---|\n###|\Z)",
            # 模式3: 第X章 标题
            rf"第{chapter_int}章\s*[：:]\s*(.+?)(?=\n第|\n---|\n###|\Z)",
        ]

        for pattern in patterns:
            m = re.search(pattern, plot, re.DOTALL)
            if m:
                if len(m.groups()) == 2:
                    title = m.group(1).strip()
                    outline = m.group(2).strip()
                else:
                    title = f"第{chapter_num}章"
                    outline = m.group(1).strip()
                return {"title": title, "outline": outline}

        # 如果没有找到具体章节，尝试提取卷级大纲
        # 查找当前章节属于哪一卷
        volume_patterns = [
            (r"第一卷：血海深仇（第1-18章）", 1, 18),
            (r"第二卷：逐鹿武林（第19-44章）", 19, 44),
            (r"第三卷：笑傲江湖（第45-70章）", 45, 70),
            (r"第四卷：后日谈·番外（第71-90章）", 71, 90),
        ]

        for vol_pattern, start, end in volume_patterns:
            if start <= chapter_int <= end:
                vol_match = re.search(vol_pattern + r"(.*?)(?=---|\n##|\Z)", plot, re.DOTALL)
                if vol_match:
                    return {
                        "title": f"第{chapter_num}章",
                        "outline": vol_match.group(0).strip()
                    }

        return None

    def _get_previous_chapters(self, current_num: str) -> List[Dict[str, str]]:
        """
        获取前面所有已处理章节的内容

        Args:
            current_num: 当前章节编号

        Returns:
            [{"num": "01", "title": "...", "content": "..."}, ...]
        """
        previous = []
        current_int = int(current_num)

        # 从已处理章节列表中获取
        for ch in self._processed_chapters:
            ch_num = int(ch.get("num", "0"))
            if ch_num < current_int:
                previous.append(ch)

        # 如果已处理列表为空，尝试从输出目录读取
        if not previous:
            optimized_path = os.path.join(self.output_dir, "综合优化结果.md")
            if os.path.exists(optimized_path):
                with open(optimized_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # 按章节标题拆分
                sections = re.split(r"(?=^#\s*第\d+章)", content, flags=re.MULTILINE)
                for sec in sections:
                    sec = sec.strip()
                    if sec:
                        m = re.search(r"#\s*第(\d+)章\s*(.*)", sec)
                        if m:
                            ch_num = int(m.group(1))
                            if ch_num < current_int:
                                ch_title = m.group(2).strip()
                                # 去掉标题行
                                ch_content = sec[sec.find("\n"):].strip()
                                previous.append({
                                    "num": str(ch_num).zfill(2),
                                    "title": ch_title,
                                    "content": ch_content
                                })

        # 按章节号排序
        previous.sort(key=lambda x: int(x.get("num", "0")))
        return previous

    def _advance_to_next(self, current_num: str, total: int, chapters_list: Optional[List] = None) -> None:
        """推进到下一章（顺序编号，+1即可）"""
        next_num = int(current_num) + 1
        if next_num > total:
            self.memory_manager.update_memory({
                "pending_chapter": "无",
                "current_chapter": "全部完成",
            })
        else:
            next_label = f"第{str(next_num).zfill(2)}章"
            self.memory_manager.update_memory({
                "pending_chapter": next_label,
                "current_chapter": next_label,
            })

    def _get_total_chapters(self) -> int:
        """获取章节总数"""
        if self._mode == "novel":
            return self.novel_parser.get_chapter_count()
        return self.chapter_reader.get_chapter_count()

    def _update_memory_after_chapter(
        self,
        chapter_num: str,
        total_chapters: int,
        original_content: str,
        optimized_content: str,
        state_update: Optional[Dict] = None,
    ) -> None:
        """
        处理完一章后更新 memory.md

        Args:
            state_update: AI 返回的结构化状态更新字典
        """
        chapter_label = f"第{chapter_num}章"

        # 顺序编号，直接 +1
        next_num = int(chapter_num) + 1
        next_label = f"第{str(next_num).zfill(2)}章" if next_num <= total_chapters else "无"

        updates = {
            "optimized_chapter": chapter_label,
            "pending_chapter": next_label if next_label != "无" else "全部完成",
            "current_chapter": next_label if next_label != "无" else "全部完成",
        }

        if state_update:
            # 使用 AI 返回的结构化状态更新
            state_keys = {
                "story_time": "story_time",
                "story_location": "story_location",
                "characters": "characters",
                "organizations": "organizations",
                "items": "items",
                "body_status": "body_status",
                "finance": "finance",
                "skills": "skills",
                "weapons": "weapons",
                "other_items": "other_items",
                "key_settings": "key_settings",
            }
            for state_key, memory_key in state_keys.items():
                if state_key in state_update and state_update[state_key]:
                    updates[memory_key] = state_update[state_key]

            # 处理上一章结尾状态
            if "prev_chapter_end" in state_update:
                updates["prev_chapter_end"] = state_update["prev_chapter_end"]
        else:
            # 无状态更新时，不修改已有状态字段（保留现有记忆）
            # 只更新必要的进度字段
            pass

        self.memory_manager.update_memory(updates)

    def _update_check_memory_after_chapter(
        self,
        chapter_num: str,
        check_memory: Dict[str, Any],
        state_update: Optional[Dict] = None,
    ) -> None:
        """
        处理完一章后更新 memory_check.md 实体记忆库

        从 state_update 中提取实体分类记录（如 characters_check, buildings, sects 等）
        并合并到 memory_check.md 中

        Args:
            chapter_num: 当前章节编号
            check_memory: 当前的 memory_check 数据
            state_update: AI 返回的结构化状态更新字典
        """
        if not state_update:
            return

        # 收集 AI 返回的实体数据
        entity_keys = [
            "characters_check", "buildings", "sects", "organizations_check",
            "items_check", "finance_check", "pills", "skills_check",
            "character_relationships", "character_sect_relations",
            "conflicts", "events", "timeline",
        ]

        entity_updates = {}
        for key in entity_keys:
            if key in state_update and state_update[key]:
                # 标准化的 key 映射
                key_map = {
                    "characters_check": "characters",
                    "organizations_check": "organizations",
                    "items_check": "items",
                    "finance_check": "finance",
                    "skills_check": "skills",
                }
                target_key = key_map.get(key, key)
                entity_updates[target_key] = state_update[key]

        # 合并并更新（即使无实体数据也会更新已处理章节计数）
        merged = self.check_manager.merge_entity_updates(
            chapter_num, check_memory, entity_updates
        )
        if merged:
            self.check_manager.update_check_memory(merged)
            if entity_updates:
                print(f"   📋 实体记忆库已更新")

    def _extract_number(self, text: str) -> Optional[str]:
        """从文本中提取数字"""
        if not text:
            return None
        m = re.search(r"(\d+)", text)
        if m:
            return m.group(1).zfill(2)
        return None

    def _extract_time_from_text(self, text: str) -> Optional[str]:
        """从文本中提取时间信息"""
        patterns = [
            r"(清晨|早晨|早上|上午|中午|午后|下午|傍晚|黄昏|晚上|夜晚|深夜|午夜|黎明|拂晓)",
            r"(\d+)日[之后前后]?",
            r"(\d+)天[之后前后]?",
            r"(\d+)月[之后前后]?",
            r"(\d+)年[之后前后]?",
            r"(次日|三日后|七日后|半月后|一个月后|一年后)",
            r"([\u4e00-\u9fff]+时节|[\u4e00-\u9fff]+季节|[\u4e00-\u9fff]+之末|[\u4e00-\u9fff]+之初)",
        ]
        for pattern in patterns:
            m = re.search(pattern, text[:500])
            if m:
                return m.group(0)
        return None

    def _extract_location_from_text(self, text: str) -> Optional[str]:
        """从文本中提取地点信息"""
        patterns = [
            r"(位于|在|来到|抵达|到达|回到|前往|赶往)([\u4e00-\u9fff]+)",
            r"([\u4e00-\u9fff]+(?:城|镇|村|山|谷|洞|殿|堂|楼|阁|府|院|林|原|海|河|湖))",
        ]
        for pattern in patterns:
            m = re.search(pattern, text[:500])
            if m:
                return m.group(0)
        return None

    def _build_prev_chapter_end(self, optimized_text: str) -> Dict[str, str]:
        """分析优化后的文本结尾部分，构建上一章结尾状态"""
        end_text = optimized_text[-500:] if len(optimized_text) > 500 else optimized_text

        time_info = self._extract_time_from_text(end_text) or "（见正文）"
        location_info = self._extract_location_from_text(end_text) or "（见正文）"

        char_pattern = r"([\u4e00-\u9fff]{2,4})(?:说道|沉声道|笑道|怒道|喝道|开口|点头|摇头|转身|抬头|皱眉)"
        chars = re.findall(char_pattern, end_text)
        chars_str = "、".join(set(chars)) if chars else "（见正文）"

        return {
            "time": time_info,
            "location": location_info,
            "characters": chars_str,
            "plot_progress": f"第{self._extract_current_chapter()}章结束，人物状态:{chars_str}",
            "item_info_status": "（见优化后章节内容）",
        }

    def _extract_current_chapter(self) -> str:
        """从 memory 获取当前章节"""
        memory = self.memory_manager.read_memory()
        return self._extract_number(memory.get("current_chapter", "无")) or "?"

    def _get_novel_name(self) -> str:
        """获取原小说名称（不含路径和扩展名）"""
        if self._mode == "novel" and self.novel_file:
            return os.path.splitext(os.path.basename(self.novel_file))[0]
        # 目录模式：使用 chapters_dir 的名称
        chapters_dir = self.config.get("chapters_dir", "chapters")
        return f"目录模式({chapters_dir})"

    def _write_combined_files(self) -> None:
        """将累计的所有审核报告和优化结果写入综合文件（支持增量累积）"""
        novel_name = self._get_novel_name()
        header = f"# {novel_name}\n\n"

        # 写综合优化结果（累积模式）
        optimized_path = os.path.join(self.output_dir, "综合优化结果.md")
        all_optimized = self._merge_with_existing(
            optimized_path, self._all_optimized, header, "第"
        )
        with open(optimized_path, "w", encoding="utf-8") as f:
            f.write(header)
            f.write("\n\n---\n\n".join(all_optimized))
            f.write("\n")
        print(f"📖 综合优化结果已保存: {optimized_path}")
        print(f"   共 {len(all_optimized)} 章")

        # 写综合审核报告（累积模式）
        report_path = os.path.join(self.output_dir, "综合审核报告.md")
        all_reports = self._merge_with_existing(
            report_path, self._all_reports, header, "第"
        )
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(header)
            f.write("\n\n---\n\n".join(all_reports))
            f.write("\n")
        print(f"📋 综合审核报告已保存: {report_path}")
        print(f"   共 {len(all_reports)} 章")

    def _merge_with_existing(
        self, filepath: str, new_entries: list, header: str,
        chapter_prefix: str = "第"
    ) -> list:
        """
        将新条目与已有文件中的条目合并，按章节编号去重

        Args:
            filepath: 已有输出文件路径
            new_entries: 当前会话新增条目列表
            header: 文件头（去头后的内容是实际章节条目）
            chapter_prefix: 章节标题前缀，用于提取章节号

        Returns:
            合并后的有序条目列表
        """
        import re as _re

        # 提取新条目的章节编号
        def get_chapter_num(text: str) -> str:
            m = _re.search(r"#\s*(第(\d+)章)", text)
            if m:
                return m.group(2).zfill(2)
            return ""

        new_map = {}
        for entry in new_entries:
            num = get_chapter_num(entry)
            if num:
                new_map[num] = entry

        # 读取已有文件中的条目
        existing_map = {}
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            # 去掉文件头
            body = content
            if body.startswith(header):
                body = body[len(header):]
            # 按章节标题正则拆分（# 第XX章 作为章节边界）
            if body:
                sections = _re.split(r"(?=^#\s*第\d+章)", body, flags=_re.MULTILINE)
                for sec in sections:
                    sec = sec.strip()
                    if sec:
                        num = get_chapter_num(sec)
                        if num:
                            existing_map[num] = sec

        # 合并（新条目覆盖旧条目）
        existing_map.update(new_map)

        # 按章节号排序返回
        sorted_items = sorted(existing_map.items(), key=lambda x: int(x[0]))
        return [item[1] for item in sorted_items]
