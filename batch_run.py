#!/usr/bin/env python3
"""
批量（重新）处理八部血狱 第15章 ~ 第50章

在执行批量审核前，将 memory.md 重置到第14章结束状态，
使 AI 在审核第15章时拥有正确的上下文。
"""
import os
import re
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

from system import NovelReviewSystem
from memory_manager import MemoryManager


def reset_memory_to_chapter_14():
    """
    将 memory.md 重置到第14章结束后的状态。

    第14章结尾：叶寒、段无双、沈音尘三人从大漠/古墓死劫中脱出，
    站在山坡上看到河谷村庄炊烟，各怀心思走向村庄。
    """
    mm = MemoryManager("memory.md")

    # 重置进度到第14章已完成、第15章待处理
    progress_updates = {
        "optimized_chapter": "第14章",
        "pending_chapter": "第15章",
        "current_chapter": "第15章",
    }
    mm.update_memory(progress_updates)

    # 重置 prev_chapter_end —— 用 memory.md 提供的更新入口
    # 先读出完整 memory，然后直接写文件
    with open("memory.md", "r", encoding="utf-8") as f:
        content = f.read()

    # 替换上一章结尾状态段落
    new_prev_end = """## 上一章结尾状态
- 时间: 傍晚时分，从大漠出来后数日
- 地点: 祁连山支脉外的山坡上，前方河谷中有村庄炊烟
- 在场人物: 叶寒、段无双、沈音尘
- 关键情节进展: 叶寒、段无双、沈音尘三人从古墓/死劫中脱出，翻过祁连山支脉后在一处山坡上望见河谷村庄；三人各怀心思走向人间炊烟，第十四章完
- 关键物品和信息状态: 半块血玉佩（叶寒脖子上）；沈音尘看叶寒后背被毒血浸透的衣服；古墓残图信息三人各掌握一部分"""

    content = re.sub(
        r"## 上一章结尾状态\n(?:- .+\n?)*",
        new_prev_end + "\n",
        content,
        flags=re.MULTILINE,
    )

    with open("memory.md", "w", encoding="utf-8") as f:
        f.write(content)

    print("📝 memory.md 已重置到第14章结尾状态")


def main():
    print("=" * 60)
    print("   重新审核八部血狱 第15章 ~ 第50章")
    print("=" * 60)

    # 1. 重置记忆到第14章结尾
    reset_memory_to_chapter_14()

    # 2. 配置系统
    config = {
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "novel_file": "input/八部血狱.txt",
    }

    print(f"🔧 API Base: {config['base_url']}")
    print(f"🤖 Model: {config['model']}")
    print()

    system = NovelReviewSystem(config)

    # 3. 逐章处理
    for i in range(15, 51):
        ch = str(i).zfill(2)
        print(f"\n{'#' * 60}")
        print(f"   开始处理 第{ch}章")
        print(f"{'#' * 60}")
        try:
            system.run_single(ch)
        except Exception as e:
            print(f"\n❌ 第{ch}章处理失败: {e}")
            print("   终止批量处理。")
            sys.exit(1)

    print("\n" + "=" * 60)
    print("   第15章 ~ 第50章 全部重新审核完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
