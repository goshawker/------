#!/usr/bin/env python3
"""
run.py - 阅文作品AI生成平台 启动入口

启动 FastAPI 服务并打开浏览器。
"""

import os
import sys
import webbrowser
import uvicorn

# 确保当前目录在路径中
sys.path.insert(0, os.path.dirname(__file__))


def main():
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    # 生产环境应设置 ENV=production 以禁用 reload
    reload = os.getenv("ENV", "development").lower() != "production"

    url = f"http://{host}:{port}"
    print(f"""
╔══════════════════════════════════════════════════╗
║           阅文作品AI生成平台                        ║
║            Novel Generation Platform             ║
╠══════════════════════════════════════════════════╣
║  访问地址: {url}                        ║
║                                                  ║
║  功能:                                            ║
║  1. 提交大纲 → 正文生成 (Model C)                  ║
║  2. 正文审核 (Model D)                            ║
║  3. 正文优化 (Model C)                            ║
║  4. 导出完整小说/审核报告                          ║
║  reload: {'开启 (开发模式)' if reload else '关闭 (生产模式)'}                          ║
╚══════════════════════════════════════════════════╝
""")

    # 自动打开浏览器
    webbrowser.open(url)

    # 启动 uvicorn
    uvicorn.run(
        "novel_api.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
