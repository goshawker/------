#!/usr/bin/env python3
"""
main.py - 小说审核与优化系统 主入口

用法：
    python main.py                              # 目录模式
    python main.py --novel-file 小说.txt        # 整本小说模式
    python main.py --single 01                  # 处理单个章节（默认审核+优化）
    python main.py --single 01 --mode generate  # 正文生成模式
    python main.py --single 01 --mode review    # 正文审核模式
    python main.py --single 01 --mode optimize  # 正文优化模式
    python main.py --help                       # 查看帮助
"""

import os
import sys
import argparse

from dotenv import load_dotenv

from system import NovelReviewSystem


def load_config() -> dict:
    """加载配置（.env + config.json）"""
    # 加载 .env（优先）
    load_dotenv()

    # 配置字典（从 .env 读取）
    config = {
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "novel_file": os.getenv("NOVEL_FILE", ""),
    }

    # 从 config.json 加载（补充）
    config_file = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(config_file):
        import json

        with open(config_file, "r", encoding="utf-8") as f:
            file_config = json.load(f)
        # .env 的值优先于 config.json
        for k, v in file_config.items():
            if k not in config or not config[k]:
                config[k] = v

    # 验证 API Key
    api_key = config.get("api_key", "")
    if not api_key or api_key == "YOUR_API_KEY":
        _print_api_key_error()
        sys.exit(1)

    return config


def _print_api_key_error():
    """打印 API Key 配置错误信息"""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    print("=" * 60)
    print("   错误: 未配置 OpenAI API Key")
    print("=" * 60)
    print()
    print("请按以下步骤配置：")
    print()
    print(f"1. 打开 .env 文件：")
    print(f"   open {env_path}")
    print()
    print("2. 将 YOUR_API_KEY 替换为你的实际 API Key：")
    print("   OPENAI_API_KEY=sk-your-actual-api-key")
    print()
    print("3. 也可自定义模型（默认 gpt-4o）：")
    print("   OPENAI_MODEL=gpt-4o")
    print()
    print("4. 整本小说模式需设置文件路径：")
    print("   NOVEL_FILE=/path/to/novel.txt")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="传统武侠小说审核与优化系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例：
  python main.py --novel-file 小说.txt           整本小说模式，自动解析章节
  python main.py                                    目录模式，从 chapters/ 读文件
  python main.py --single 01                        只处理第01章（默认审核+优化）
  python main.py --single 01 --mode generate        正文生成（从大纲生成新章节）
  python main.py --single 01 --mode review          正文审核（仅审核，输出报告）
  python main.py --single 01 --mode optimize        正文优化（审核+优化）
        """,
    )
    parser.add_argument(
        "--novel-file",
        type=str,
        default=None,
        help="整本小说文件路径（.txt 或 .md），设置后自动解析章节",
    )
    parser.add_argument(
        "--single",
        type=str,
        help="处理单个章节，传入章节序号（如 01）或标签（如 第01章）",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["generate", "review", "optimize", "review_optimize"],
        default="review_optimize",
        help="处理模式: generate=正文生成, review=正文审核, optimize=正文优化, review_optimize=审核+优化(默认)",
    )
    parser.add_argument(
        "--chapters-dir",
        type=str,
        default=None,
        help="指定章节目录（默认: chapters）",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="指定输出目录（默认: output）",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="指定 AI 模型（默认: gpt-4o，可通过 .env 的 OPENAI_MODEL 配置）",
    )

    args = parser.parse_args()

    # 加载配置
    config = load_config()

    # 命令行参数覆盖
    if args.novel_file:
        config["novel_file"] = args.novel_file
    if args.chapters_dir:
        config["chapters_dir"] = args.chapters_dir
    if args.output_dir:
        config["output_dir"] = args.output_dir
    if args.model:
        config["model"] = args.model

    # 打印模式信息
    novel_file = config.get("novel_file", "")
    if novel_file:
        print(f"🔧 模式: 整本小说 → {novel_file}")
    else:
        print("🔧 模式: 目录模式 → chapters/")
    print(f"🤖 模型: {config.get('model', 'gpt-4o')}")

    # 创建系统实例
    system = NovelReviewSystem(config)

    # 运行
    if args.single:
        system.run_single(args.single, mode=args.mode)
    else:
        system.run()


if __name__ == "__main__":
    main()
