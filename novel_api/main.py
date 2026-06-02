"""
main.py - FastAPI 应用主入口

提供 REST API + WebSocket 端点，以及静态文件服务。
"""

from __future__ import annotations

import os
import io
import uuid
import shutil
import asyncio
import json
import tempfile
import datetime
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from novel_api.models import ExportRequest, RegenerateRequest, UpdateOutlineRequest, SubmitOutlineRequest, PipelineState
from novel_api.config_manager import ConfigManager
from novel_api.pipeline import NovelPipeline
from novel_api.websocket_manager import WebSocketManager


# 全局状态
ws_manager = WebSocketManager()
config_manager = ConfigManager()
pipeline = NovelPipeline(ws_manager)

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    # 启动时自动从磁盘恢复状态
    try:
        restored = pipeline._try_restore_state_from_disk(pipeline.state)
        if restored:
            print("[启动] 已自动恢复上次保存的流水线状态")
        else:
            print("[启动] 无已保存的状态，从头开始")
    except Exception as e:
        print(f"[启动] 状态恢复失败: {e}")
    yield


app = FastAPI(
    title="阅文作品AI生成平台",
    description="小说生成、审核、导出一体化的闭环系统",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------- REST API --------

@app.get("/api/config")
async def get_config():
    """获取当前配置"""
    cfg = config_manager.load()
    return config_manager.to_api_response(cfg)


@app.post("/api/config")
async def update_config(data: Dict[str, Any]):
    """更新配置"""
    cfg = config_manager.update_from_frontend(data)
    return config_manager.to_api_response(cfg)


def _validate_chapter_count(total_chapters: int):
    """校验章节数是否在合理范围内"""
    if total_chapters < 1 or total_chapters > 500:
        raise HTTPException(status_code=400, detail="章节数必须在 1-500 之间")


@app.post("/api/generate-chapters")
async def generate_chapters():
    """仅运行正文生成（需先完成大纲）"""
    if pipeline.state.status == "running":
        raise HTTPException(status_code=400, detail="流水线正在运行中")

    # 验证大纲存在
    outline = pipeline.state.optimized_outline or pipeline.state.outline
    if not outline or not outline.chapters:
        raise HTTPException(status_code=400, detail="大纲尚未提交，请先提交大纲")

    cfg = config_manager.load()
    asyncio.create_task(pipeline.start_generate_chapters(cfg))

    return {"status": "started", "message": "正文生成已启动"}


@app.post("/api/generate-chapters-v2")
async def generate_chapters_v2():
    """章节生成：使用 model_e 和章节生成提示词生成章节大纲"""
    if pipeline.state.status == "running":
        raise HTTPException(status_code=400, detail="流水线正在运行中")

    cfg = config_manager.load()
    asyncio.create_task(pipeline.start_generate_chapters_v2(cfg))

    return {"status": "started", "message": "章节生成已启动"}


@app.post("/api/review-and-optimize")
async def review_and_optimize():
    """审核&优化：使用 model_f 对已生成的章节进行审核和优化（合并步骤）"""
    if pipeline.state.status == "running":
        raise HTTPException(status_code=400, detail="流水线正在运行中")

    if not pipeline.state.chapters:
        raise HTTPException(status_code=400, detail="没有已生成的章节，请先执行正文生成")

    cfg = config_manager.load()
    asyncio.create_task(pipeline.start_review_and_optimize(cfg))

    return {"status": "started", "message": "审核&优化已启动"}


@app.post("/api/review-chapters-v2")
async def review_chapters_v2():
    """章节审核：使用 model_f 审核章节大纲（名称+简介）"""
    if pipeline.state.status == "running":
        raise HTTPException(status_code=400, detail="流水线正在运行中")

    outline = pipeline.state.optimized_outline or pipeline.state.outline
    if not outline or not outline.chapters:
        raise HTTPException(status_code=400, detail="没有已生成的章节大纲，请先执行章节生成")

    cfg = config_manager.load()
    asyncio.create_task(pipeline.start_review_chapters_v2(cfg))

    return {"status": "started", "message": "章节审核已启动"}


@app.post("/api/optimize-chapters-v2")
async def optimize_chapters_v2():
    """章节优化：使用 model_f 优化章节大纲"""
    if pipeline.state.status == "running":
        raise HTTPException(status_code=400, detail="流水线正在运行中")

    outline = pipeline.state.optimized_outline or pipeline.state.outline
    if not outline or not outline.chapters:
        raise HTTPException(status_code=400, detail="没有已生成的章节大纲，请先执行章节生成")

    cfg = config_manager.load()
    asyncio.create_task(pipeline.start_optimize_chapters_v2(cfg))

    return {"status": "started", "message": "章节优化已启动"}


@app.post("/api/review-chapters")
async def review_chapters():
    """仅运行正文审核（需先有已生成的正文）"""
    if pipeline.state.status == "running":
        raise HTTPException(status_code=400, detail="流水线正在运行中")

    if not pipeline.state.chapters:
        raise HTTPException(status_code=400, detail="没有已生成的章节，请先执行正文生成")

    cfg = config_manager.load()
    asyncio.create_task(pipeline.start_review_chapters(cfg))

    return {"status": "started", "message": "正文审核已启动"}


@app.post("/api/optimize-chapters")
async def optimize_chapters():
    """仅运行正文优化（需先有已审核的正文）"""
    if pipeline.state.status == "running":
        raise HTTPException(status_code=400, detail="流水线正在运行中")

    if not pipeline.state.chapters:
        raise HTTPException(status_code=400, detail="没有已生成的章节，请先执行正文生成")

    cfg = config_manager.load()
    asyncio.create_task(pipeline.start_optimize_chapters(cfg))

    return {"status": "started", "message": "正文优化已启动"}


@app.post("/api/submit-outline")
async def submit_outline(req: SubmitOutlineRequest):
    """提交手动输入的大纲，解析并存入 pipeline 状态"""
    if pipeline.state.status == "running":
        raise HTTPException(status_code=400, detail="流水线正在运行中")

    if not req.outline_text.strip():
        raise HTTPException(status_code=400, detail="大纲内容不能为空")
    _validate_chapter_count(req.total_chapters)

    try:
        pipeline.submit_manual_outline(
            outline_text=req.outline_text,
            total_chapters=req.total_chapters,
            min_words=req.min_words,
            plot=req.plot,
        )
        # 更新配置
        pipeline.state.total_chapters = req.total_chapters
        pipeline.state.min_words = req.min_words
        pipeline.state.plot = req.plot

        # 保存配置到文件
        cfg = config_manager.load()
        cfg.total_chapters = req.total_chapters
        cfg.min_words = req.min_words
        cfg.plot = req.plot
        config_manager.save(cfg)

        # 构建返回数据
        outline_chapters = []
        if pipeline.state.outline:
            for ch in pipeline.state.outline.chapters:
                outline_chapters.append({
                    "index": ch.index,
                    "title": ch.title,
                    "summary": ch.summary,
                })

        return {
            "status": "submitted",
            "message": f"大纲提交成功，共解析出 {len(outline_chapters)} 章",
            "chapters": outline_chapters,
            "total_chapters": len(outline_chapters),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"大纲解析失败: {str(e)}")


@app.post("/api/pause")
async def pause_pipeline():
    """暂停流水线"""
    pipeline.pause()
    return {"status": "paused"}


@app.post("/api/resume")
async def resume_pipeline():
    """恢复流水线"""
    pipeline.resume()
    return {"status": "resumed"}


@app.post("/api/cancel")
async def cancel_pipeline():
    """取消流水线"""
    pipeline.cancel()
    return {"status": "cancelled"}


@app.post("/api/reset")
async def reset_pipeline():
    """初始化：清空所有运行缓存数据"""
    if pipeline.state.status == "running":
        raise HTTPException(status_code=400, detail="流水线正在运行中，请先取消")

    # 清空 memory 文件
    memory_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory_web.md")
    if os.path.exists(memory_path):
        os.remove(memory_path)

    # 重置 pipeline 状态
    pipeline._generation += 1
    pipeline.state = PipelineState()
    pipeline._cancelled = False
    pipeline._pause_event.set()
    pipeline._llm_clients = {}

    return {"status": "reset", "message": "运行缓存已清空"}


@app.post("/api/regenerate-chapters")
async def regenerate_chapters(req: RegenerateRequest):
    """重生成指定章节（内容 + 审核）"""
    if not req.chapter_indices:
        raise HTTPException(status_code=400, detail="未指定章节")

    if not pipeline.state.chapters:
        raise HTTPException(status_code=400, detail="没有已生成的章节")

    # 验证所有索引有效
    existing = {ch.index for ch in pipeline.state.chapters}
    invalid = [i for i in req.chapter_indices if i not in existing]
    if invalid:
        raise HTTPException(status_code=400, detail=f"章节不存在: {invalid}")

    if pipeline.state.status == "running":
        raise HTTPException(status_code=400, detail="流水线正在运行中，请等待当前任务完成")

    cfg = config_manager.load()
    asyncio.create_task(pipeline.regenerate_chapters(req.chapter_indices, cfg))

    return {"status": "started", "message": f"已启动 {len(req.chapter_indices)} 个章节的重生成"}


@app.patch("/api/chapter-outline/{index}")
async def update_chapter_outline(index: int, req: UpdateOutlineRequest):
    """更新指定章节的大纲（标题+简介）"""
    if pipeline.state.status == "running":
        raise HTTPException(status_code=400, detail="流水线正在运行中")

    updated = pipeline.update_chapter_outline(index, req.title, req.summary)
    if not updated:
        raise HTTPException(status_code=404, detail=f"章节 第{index}章 不存在")

    return {"status": "updated", "index": index}


@app.get("/api/state")
async def get_state():
    """获取当前状态"""
    return pipeline.state.model_dump()


@app.get("/api/chapters")
async def get_chapters():
    """获取所有章节列表（摘要信息）"""
    # 大纲是否已审核（optimized_outline 存在即表示已审核）
    outline_reviewed = bool(pipeline.state.optimized_outline)
    # 去重：同 index 保留最后一条（最新的）
    seen = {}
    for ch in pipeline.state.chapters:
        seen[ch.index] = {
            "index": ch.index,
            "title": ch.title,
            "summary": ch.summary,
            "has_content": bool(ch.content),
            "has_review": bool(ch.review_report),
            "has_optimized": bool(ch.optimized_content),
            "content_length": len(ch.content) if ch.content else 0,
            "outline_reviewed": outline_reviewed,
            "outline_optimized": outline_reviewed,
        }
    chapters = list(seen.values())
    chapters.sort(key=lambda c: c["index"])

    # 优先展示优化后大纲（与正文生成的标题保持一致）
    display_outline = pipeline.state.optimized_outline or pipeline.state.outline

    has_optimized = bool(pipeline.state.optimized_outline)
    outline_chapters = []
    if display_outline:
        for ch in display_outline.chapters:
            outline_chapters.append({
                "index": ch.index,
                "title": ch.title,
                "summary": ch.summary,
                "outline_reviewed": outline_reviewed,
                "outline_optimized": has_optimized,
            })

    optimized_chapters = []
    if pipeline.state.optimized_outline:
        for ch in pipeline.state.optimized_outline.chapters:
            optimized_chapters.append({
                "index": ch.index,
                "title": ch.title,
                "summary": ch.summary,
            })

    return {
        "outline": outline_chapters,
        "optimized_outline": optimized_chapters,
        "chapters": chapters,
        "novel_title": display_outline.title if display_outline else "",
    }


@app.get("/api/chapter/{index}")
async def get_chapter(index: int):
    """获取单个章节的完整内容"""
    for ch in pipeline.state.chapters:
        if ch.index == index:
            return {
                "index": ch.index,
                "title": ch.title,
                "summary": ch.summary,
                "content": ch.content,
                "review_report": ch.review_report,
                "optimized_content": ch.optimized_content,
            }
    raise HTTPException(status_code=404, detail=f"章节 第{index}章 不存在")


@app.get("/api/export/novel")
async def export_novel():
    """导出完整小说"""
    content = pipeline.get_novel_content()
    return {"content": content, "filename": f"{pipeline.state.outline.title if pipeline.state.outline else '小说'}.md"}


@app.get("/api/export/review")
async def export_review():
    """导出审核报告"""
    content = pipeline.get_review_report()
    return {"content": content, "filename": "审核报告.md"}


@app.get("/api/export/download")
async def export_download():
    """下载完整小说 Markdown 文件"""
    content = pipeline.get_novel_content()
    if not content:
        raise HTTPException(status_code=400, detail="没有可导出的内容")

    novel_title = pipeline.state.outline.title if pipeline.state.outline else "小说"
    filename = f"{novel_title}.md"
    download_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output", filename)
    os.makedirs(os.path.dirname(download_path), exist_ok=True)
    with open(download_path, "w", encoding="utf-8") as f:
        f.write(content)

    return FileResponse(
        download_path,
        media_type="text/markdown; charset=utf-8",
        filename=filename,
    )


@app.post("/api/save")
async def save_project():
    """保存当前项目状态"""
    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
    os.makedirs(output_dir, exist_ok=True)

    # 保存小说内容
    novel_content = pipeline.get_novel_content()
    if novel_content:
        title = pipeline.state.outline.title if pipeline.state.outline else "小说"
        novel_path = os.path.join(output_dir, f"{title}.md")
        with open(novel_path, "w", encoding="utf-8") as f:
            f.write(novel_content)

    # 保存审核报告
    report_content = pipeline.get_review_report()
    if report_content:
        report_path = os.path.join(output_dir, "审核报告.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)

    # 保存状态快照
    state_path = os.path.join(output_dir, "pipeline_state.json")
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(pipeline.state.model_dump(), f, ensure_ascii=False, indent=2)

    # 保存 memory 文件
    memory_src = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory_web.md")
    if os.path.exists(memory_src):
        memory_dst = os.path.join(output_dir, "memory_web.md")
        shutil.copy2(memory_src, memory_dst)

    return {"status": "saved", "path": output_dir}


@app.post("/api/load")
async def load_project():
    """加载保存的项目状态"""
    if pipeline.state.status == "running":
        raise HTTPException(status_code=400, detail="流水线正在运行中，请先取消")

    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
    state_path = os.path.join(output_dir, "pipeline_state.json")

    if not os.path.exists(state_path):
        raise HTTPException(status_code=400, detail="没有找到已保存的进度文件")

    # 递增 generation 废弃旧任务
    pipeline._generation += 1
    pipeline._cancelled = False
    pipeline._pause_event.set()

    # 反序列化状态
    with open(state_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    pipeline.state = PipelineState(**data)
    pipeline.state.status = "idle"

    # 状态迁移：旧格式 → 新6步states
    NEW_STEPS = ["大纲优化", "正文生成", "正文审核", "正文优化"]
    if len(pipeline.state.step_names) == 4:
        old_step = pipeline.state.current_step
        pipeline.state.step_names = list(NEW_STEPS)
        mapping = {0: 0, 1: 0, 2: 1, 3: 2}
        pipeline.state.current_step = mapping.get(old_step, old_step)
        pipeline.state.outline_review_report = ""
    elif len(pipeline.state.step_names) == 5:
        old_step = pipeline.state.current_step
        pipeline.state.step_names = list(NEW_STEPS)
        mapping = {0: 0, 1: 0, 2: 1, 3: 2, 4: 3}
        pipeline.state.current_step = mapping.get(old_step, old_step)
    elif len(pipeline.state.step_names) == 6:
        old_step = pipeline.state.current_step
        pipeline.state.step_names = list(NEW_STEPS)
        mapping = {0: 0, 1: 0, 2: 0, 3: 1, 4: 2, 5: 3}
        pipeline.state.current_step = mapping.get(old_step, old_step)

    # 恢复 memory 文件
    memory_src = os.path.join(output_dir, "memory_web.md")
    if os.path.exists(memory_src):
        memory_dst = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory_web.md")
        shutil.copy2(memory_src, memory_dst)

    return {"status": "loaded", "message": "项目进度已恢复"}


@app.get("/api/save/download")
async def save_download():
    """下载保存文件（浏览器原生保存对话框）"""
    # 构建保存数据
    save_data = {
        "version": "1.0",
        "saved_at": datetime.datetime.now().isoformat(),
        "app_title": "阅文作品AI生成平台",
        "pipeline_state": pipeline.state.model_dump(),
        "memory_content": "",
        "config": {},
    }

    # 读取 memory 文件
    memory_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory_web.md")
    if os.path.exists(memory_path):
        with open(memory_path, "r", encoding="utf-8") as f:
            save_data["memory_content"] = f.read()

    # 读取配置
    try:
        cfg = config_manager.load()
        save_data["config"] = cfg.model_dump()
    except Exception:
        pass

    # 写入临时文件
    tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".novel", delete=False)
    json.dump(save_data, tmp, ensure_ascii=False, indent=2)
    tmp_path = tmp.name
    tmp.close()

    # 文件名
    title = (pipeline.state.optimized_outline or pipeline.state.outline)
    title_str = title.title if title else "小说"
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{title_str}_{timestamp}.novel"

    return FileResponse(
        tmp_path,
        media_type="application/octet-stream",
        filename=filename,
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/api/save/upload")
async def save_upload(file: UploadFile = File(...)):
    """上传并加载保存文件"""
    if pipeline.state.status == "running":
        raise HTTPException(status_code=400, detail="流水线正在运行中，请先取消")

    if not file.filename or not file.filename.endswith(".novel"):
        raise HTTPException(status_code=400, detail="请选择有效的 .novel 文件")

    # 读取上传文件
    try:
        content = await file.read()
        save_data = json.loads(content.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="文件格式错误，无法解析")

    # 验证数据完整性
    if "pipeline_state" not in save_data:
        raise HTTPException(status_code=400, detail="保存文件不包含有效的项目状态")

    # 递增 generation 废弃旧任务
    pipeline._generation += 1
    pipeline._cancelled = False
    pipeline._pause_event.set()

    # 反序列化状态
    pipeline.state = PipelineState(**save_data["pipeline_state"])
    pipeline.state.status = "idle"

    # 状态迁移：旧格式 → 新6步states
    NEW_STEPS = ["大纲优化", "正文生成", "正文审核", "正文优化"]
    if len(pipeline.state.step_names) == 4:
        old_step = pipeline.state.current_step
        pipeline.state.step_names = list(NEW_STEPS)
        mapping = {0: 0, 1: 0, 2: 1, 3: 2}
        pipeline.state.current_step = mapping.get(old_step, old_step)
        pipeline.state.outline_review_report = ""
    elif len(pipeline.state.step_names) == 5:
        old_step = pipeline.state.current_step
        pipeline.state.step_names = list(NEW_STEPS)
        mapping = {0: 0, 1: 0, 2: 1, 3: 2, 4: 3}
        pipeline.state.current_step = mapping.get(old_step, old_step)
    elif len(pipeline.state.step_names) == 6:
        old_step = pipeline.state.current_step
        pipeline.state.step_names = list(NEW_STEPS)
        mapping = {0: 0, 1: 0, 2: 0, 3: 1, 4: 2, 5: 3}
        pipeline.state.current_step = mapping.get(old_step, old_step)

    # 恢复 memory 文件
    memory_content = save_data.get("memory_content", "")
    if memory_content:
        memory_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory_web.md")
        with open(memory_path, "w", encoding="utf-8") as f:
            f.write(memory_content)

    # 恢复配置
    config_data = save_data.get("config", {})
    if config_data:
        config_manager.update_from_frontend(config_data)

    # 统计恢复结果
    chapter_count = len(pipeline.state.chapters)
    has_outline = bool(pipeline.state.outline or pipeline.state.optimized_outline)
    has_content = any(ch.content for ch in pipeline.state.chapters)
    step_name = pipeline.state.step_names[pipeline.state.current_step] if pipeline.state.current_step < len(pipeline.state.step_names) else "完成"
    print(f"[进度恢复] 章节数: {chapter_count}, 大纲: {'有' if has_outline else '无'}, 正文: {'有' if has_content else '无'}, 步骤: {step_name}")

    return {
        "status": "loaded",
        "message": "项目进度已恢复",
        "chapter_count": chapter_count,
        "has_outline": has_outline,
        "has_content": has_content,
        "current_step": pipeline.state.current_step,
        "current_step_name": step_name,
    }


# -------- WebSocket --------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 端点 - 实时推送进度"""
    await ws_manager.connect(websocket)
    try:
        while True:
            # 保持连接，接收客户端消息
            data = await websocket.receive_text()
            # 处理客户端消息（如心跳）
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception:
        await ws_manager.disconnect(websocket)


# -------- 静态文件服务 --------

@app.get("/")
async def serve_index():
    """服务前端页面"""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(
            content,
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
    return HTMLResponse("<h1>阅文作品AI生成平台</h1><p>前端文件未找到</p>")


@app.get("/{path:path}")
async def serve_static(path: str):
    """服务静态文件（防路径遍历）"""
    # 安全: 规范化路径，防止 ../ 越权访问
    safe_path = os.path.normpath(os.path.join(FRONTEND_DIR, path))
    if not safe_path.startswith(os.path.normpath(FRONTEND_DIR)):
        return HTMLResponse(f"<h1>403</h1><p>禁止访问</p>", status_code=403)
    if os.path.exists(safe_path) and os.path.isfile(safe_path):
        return FileResponse(
            safe_path,
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
    # 回退到 index.html（支持 SPA 路由）
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse(f"<h1>404</h1><p>{path} 未找到</p>", status_code=404)
