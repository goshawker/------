/**
 * app.js - 阅文作品AI生成平台 前端应用
 *
 * 使用 Vue 3 + WebSocket 实现实时交互
 */

const { createApp, ref, computed, watch, nextTick, onMounted, onUnmounted } = Vue;

const API_BASE = window.location.origin;
const WS_URL = API_BASE.replace(/^http/, 'ws') + '/ws';

// ---- 默认配置 ----
const DEFAULT_CONFIG = {
    model_a: { api_key: '', base_url: 'https://api.openai.com/v1', model_name: 'gpt-4o', temperature: 0.8, max_tokens: 16384 },
    model_b: { api_key: '', base_url: 'https://api.openai.com/v1', model_name: 'gpt-4o', temperature: 0.8, max_tokens: 16384 },
    model_c: { api_key: '', base_url: 'https://api.openai.com/v1', model_name: 'gpt-4o', temperature: 0.8, max_tokens: 16384 },
    model_d: { api_key: '', base_url: 'https://api.openai.com/v1', model_name: 'gpt-4o', temperature: 0.8, max_tokens: 16384 },
    model_e: { api_key: '', base_url: 'https://api.openai.com/v1', model_name: 'gpt-4o', temperature: 0.8, max_tokens: 16384 },
    model_f: { api_key: '', base_url: 'https://api.openai.com/v1', model_name: 'gpt-4o', temperature: 0.8, max_tokens: 16384 },
    chapter_gen_prompt: '',
    chapter_review_prompt: '',
    content_gen_prompt: '',
    review_optimize_prompt: '',
};

const app = createApp({
    setup() {
        // ---- 响应式状态 ----
        const config = ref(JSON.parse(JSON.stringify(DEFAULT_CONFIG)));
        const manualOutline = ref('');
        const totalChapters = ref(10);
        const minWords = ref(3000);
        const novelPlot = ref('');
        const sidebarCollapsed = ref(sessionStorage.getItem('novel_sidebar') === 'true');
        const sidebarTab = ref(sessionStorage.getItem('novel_sidebar_tab') || 'config');
        const chapterTab = ref(sessionStorage.getItem('novel_tab') || 'all');
        const logs = ref(loadLogsFromStorage());
        const logConsole = ref(null);

        function loadLogsFromStorage() {
            try {
                const saved = sessionStorage.getItem('novel_logs');
                return saved ? JSON.parse(saved) : [];
            } catch { return []; }
        }

        function saveLogsToStorage() {
            try {
                sessionStorage.setItem('novel_logs', JSON.stringify(logs.value.slice(-500)));
            } catch { /* quota exceeded, ignore */ }
        }

        // 流水线状态
        const state = ref({
            status: 'idle',
            current_step: 0,
            step_names: ['大纲优化', '正文生成', '正文审核', '正文优化'],
            progress: 0,
            error_message: '',
        });

        // 章节数据
        const chapters = ref([]);
        const outlineChapters = ref([]);

        // 章节选择（用于重生成）
        const selectedChapters = ref(new Set());
        const selectedCount = computed(() => selectedChapters.value.size);
        const canRegenerate = computed(() =>
            selectedChapters.value.size > 0 &&
            state.value.status !== 'running' &&
            chapters.value.length > 0
        );

        // 抽屉
        const drawerOpen = ref(false);
        const drawerChapter = ref({});
        const drawerViewMode = ref('diff'); // 'diff' | 'original' | 'optimized'

        // 通知
        const notificationShow = ref(false);
        const notificationTitle = ref('');
        const notificationMessage = ref('');
        const notificationClass = ref('');

        // WebSocket
        let ws = null;
        let wsReconnectTimer = null;
        let wsPingTimer = null;
        let lastPong = Date.now();

        // ---- 工具函数 ----

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // ---- 计算属性 ----

        const diffResult = computed(() => {
            const original = drawerChapter.value.content || '';
            const optimized = drawerChapter.value.optimized_content || '';
            if (!original || !optimized) return { html: '', addCount: 0, delCount: 0 };
            const changes = Diff.diffChars(original, optimized);
            let html = '';
            let addCount = 0;
            let delCount = 0;
            for (const part of changes) {
                const escaped = escapeHtml(part.value);
                if (part.added) {
                    addCount += part.value.length;
                    html += '<span class="diff-add">' + escaped + '</span>';
                } else if (part.removed) {
                    delCount += part.value.length;
                    html += '<span class="diff-del">' + escaped + '</span>';
                } else {
                    html += escaped;
                }
            }
            return { html, addCount, delCount };
        });

        const diffHtml = computed(() => diffResult.value.html);
        const diffAddCount = computed(() => diffResult.value.addCount);
        const diffDelCount = computed(() => diffResult.value.delCount);

        const statusText = computed(() => {
            const map = {
                idle: '就绪',
                running: '运行中',
                paused: '已暂停',
                completed: '已完成',
                error: '出错',
                cancelled: '已取消',
            };
            return map[state.value.status] || state.value.status;
        });

        const stateMessage = computed(() => {
            if (state.value.status === 'idle' && state.value.current_step >= 1) return '大纲已完成，可以开始正文生成';
            if (state.value.status === 'idle') return '等待开始...';
            if (state.value.status === 'completed') return '全部完成！';
            if (state.value.status === 'error') return '出错: ' + state.value.error_message;
            if (state.value.status === 'paused') return '已暂停';
            const stepName = state.value.step_names[state.value.current_step] || '';
            return stepName ? `正在 ${stepName}...` : '运行中...';
        });

        const canStartGenerate = computed(() => {
            return outlineChapters.value.length > 0 &&
                   state.value.status !== 'running';
        });
        const canStartReview = computed(() => {
            return chapters.value.length > 0 &&
                   state.value.status !== 'running' &&
                   chapters.value.some(ch => ch.has_content);
        });
        const canStartOptimize = computed(() => {
            return chapters.value.length > 0 &&
                   state.value.status !== 'running' &&
                   chapters.value.some(ch => ch.has_review);
        });
        const canStartChapterReview = computed(() => {
            return outlineChapters.value.length > 0 &&
                   state.value.status !== 'running';
        });
        const canStartChapterOptimize = computed(() => {
            return outlineChapters.value.length > 0 &&
                   state.value.status !== 'running' &&
                   !!state.value.outline_review_report;
        });
        const canStartReviewAndOptimize = computed(() => {
            return chapters.value.length > 0 &&
                   state.value.status !== 'running' &&
                   chapters.value.some(ch => ch.has_content);
        });

        // ---- 方法 ----

        function stepClass(idx) {
            if (state.value.status === 'error') return 'error';
            if (idx < state.value.current_step) return 'completed';
            if (idx === state.value.current_step && state.value.status === 'running') return 'active';
            if (idx === state.value.current_step && state.value.status === 'completed') return 'completed';
            return 'pending';
        }

        function addLog(text, level = 'info') {
            const now = new Date();
            const time = now.toLocaleTimeString('zh-CN', { hour12: false });
            logs.value.push({ time, text, level });
            saveLogsToStorage();
            // 自动滚到底部
            nextTick(() => {
                if (logConsole.value) {
                    logConsole.value.scrollTop = logConsole.value.scrollHeight;
                }
            });
        }

        function showNotification(title, message, type = 'info') {
            notificationTitle.value = title;
            notificationMessage.value = message;
            notificationClass.value = type;
            notificationShow.value = true;
            setTimeout(() => {
                notificationShow.value = false;
            }, 4000);
        }

        // ---- WebSocket ----

        function connectWS() {
            if (ws && ws.readyState === WebSocket.OPEN) return;

            try {
                ws = new WebSocket(WS_URL);

                ws.onopen = () => {
                    addLog('WebSocket 连接已建立', 'success');
                    // 心跳：每30秒发送 ping 防止连接空闲断开
                    if (wsPingTimer) clearInterval(wsPingTimer);
                    wsPingTimer = setInterval(() => {
                        if (ws && ws.readyState === WebSocket.OPEN) {
                            ws.send('ping');
                        }
                    }, 30000);
                    // 重连后刷新状态和章节，检测服务端是否已重置
                    fetchState();
                    refreshChapters();
                };

                ws.onmessage = (event) => {
                    try {
                        const msg = JSON.parse(event.data);

                        if (msg.type === 'pong') {
                            lastPong = Date.now();
                            return;
                        }

                        handleWSMessage(msg);
                    } catch (e) {
                        console.error('WS parse error:', e);
                    }
                };

                ws.onclose = () => {
                    addLog('WebSocket 连接已断开，3秒后重连...', 'warning');
                    ws = null;
                    if (wsPingTimer) clearInterval(wsPingTimer);
                    // 总是尝试重连
                    wsReconnectTimer = setTimeout(connectWS, 3000);
                };

                ws.onerror = (err) => {
                    console.error('WebSocket error:', err);
                };
            } catch (e) {
                console.error('WebSocket connect error:', e);
            }
        }

        function handleWSMessage(msg) {
            const { type, data } = msg;

            switch (type) {
                case 'log':
                    if (data && data.message) {
                        addLog(data.message, 'info');
                    }
                    break;

                case 'log_replace':
                    if (data && data.message) {
                        const now = new Date();
                        const time = now.toLocaleTimeString('zh-CN', { hour12: false });
                        if (logs.value.length > 0) {
                            logs.value[logs.value.length - 1] = { time, text: data.message, level: 'info' };
                        } else {
                            logs.value.push({ time, text: data.message, level: 'info' });
                        }
                        saveLogsToStorage();
                    }
                    break;

                case 'progress':
                    if (data.state) {
                        state.value = { ...state.value, ...data.state };
                    }
                    if (data.message) {
                        addLog(data.message, 'info');
                    }
                    break;

                case 'chapter_outline':
                    const chapterData = {
                        ...data,
                        outline_reviewed: data.step === 'outline_reviewed' || data.step === 'outline_optimized',
                        outline_optimized: data.step === 'outline_optimized',
                    };
                    const statusLabel = chapterData.outline_optimized ? '已优化' : (chapterData.outline_reviewed ? '已审核' : '已生成');
                    addLog(`大纲${statusLabel}: 第${data.index}章 - ${data.title}`, 'success');
                    // 仅更新大纲列表（不修改 chapters.value，避免与后端数据冲突导致重复）
                    const idxOutline = outlineChapters.value.findIndex(c => c.index === data.index);
                    if (idxOutline >= 0) {
                        outlineChapters.value[idxOutline] = chapterData;
                    } else {
                        outlineChapters.value.push(chapterData);
                        outlineChapters.value.sort((a, b) => a.index - b.index);
                    }
                    break;

                case 'chapter_content':
                    if (data.content_preview) {
                        addLog(`正文已生成: 第${data.index}章 - ${data.title}`, 'success');
                    } else {
                        addLog(`正在重生成: 第${data.index}章 - ${data.title}...`, 'info');
                    }
                    refreshChapters();
                    break;

                case 'review_result':
                    addLog(`审核完成: 第${data.index}章`, 'info');
                    refreshChapters();
                    break;

                case 'optimize_result':
                    addLog(`优化完成: 第${data.index}章`, 'success');
                    refreshChapters();
                    break;

                case 'complete':
                    if (data.state) {
                        state.value = { ...state.value, ...data.state };
                    }
                    addLog('🎉 ' + (data.message || '全部完成！'), 'success');
                    showNotification('完成', data.message || '全部完成！', 'success');
                    refreshChapters();
                    break;

                case 'error':
                    if (data.state) {
                        state.value = { ...state.value, ...data.state };
                    }
                    addLog('❌ ' + data.message, 'error');
                    showNotification('错误', data.message, 'error');
                    refreshChapters();
                    break;
            }
        }

        // ---- API 调用 ----

        async function fetchConfig() {
            try {
                const res = await fetch(API_BASE + '/api/config');
                if (res.ok) {
                    const data = await res.json();
                    // 保留用户已输入的完整 key（masked 部分使用原有值）
                    for (const key of ['model_a', 'model_b', 'model_c', 'model_d', 'model_e', 'model_f']) {
                        if (data[key]) {
                            const maskedKey = data[key].api_key || '';
                            const currentKey = config.value[key]?.api_key || '';
                            // 如果后端返回的 key 比当前 key 长（包含完整 key）
                            // 或者当前 key 是空的，使用后端返回的
                            // 否则保留当前用户的输入
                            if (maskedKey && !currentKey) {
                                config.value[key].api_key = maskedKey;
                            }
                            config.value[key].base_url = data[key].base_url || config.value[key].base_url;
                            config.value[key].model_name = data[key].model_name || config.value[key].model_name;
                        }
                    }
                    if (data.total_chapters) totalChapters.value = data.total_chapters;
                    if (data.min_words) minWords.value = data.min_words;
                    if (data.plot !== undefined) novelPlot.value = data.plot;
                    if (data.chapter_gen_prompt !== undefined) config.value.chapter_gen_prompt = data.chapter_gen_prompt;
                    if (data.chapter_review_prompt !== undefined) config.value.chapter_review_prompt = data.chapter_review_prompt;
                    if (data.content_gen_prompt !== undefined) config.value.content_gen_prompt = data.content_gen_prompt;
                    if (data.review_optimize_prompt !== undefined) config.value.review_optimize_prompt = data.review_optimize_prompt;
                    addLog('配置已加载', 'info');
                }
            } catch (e) {
                console.error('Failed to load config:', e);
            }
        }

        async function saveConfig() {
            try {
                const payload = {
                    model_a: config.value.model_a,
                    model_b: config.value.model_b,
                    model_c: config.value.model_c,
                    model_d: config.value.model_d,
                    model_e: config.value.model_e,
                    model_f: config.value.model_f,
                    min_words: minWords.value,
                    total_chapters: totalChapters.value,
                    plot: novelPlot.value,
                    chapter_gen_prompt: config.value.chapter_gen_prompt,
                    chapter_review_prompt: config.value.chapter_review_prompt,
                    content_gen_prompt: config.value.content_gen_prompt,
                    review_optimize_prompt: config.value.review_optimize_prompt,
                };
                const res = await fetch(API_BASE + '/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                if (res.ok) {
                    showNotification('成功', '配置已保存', 'success');
                    addLog('配置已保存', 'success');
                } else {
                    showNotification('错误', '保存配置失败', 'error');
                }
            } catch (e) {
                showNotification('错误', '保存配置失败: ' + e.message, 'error');
            }
        }

        function syncAllModels() {
            const eConfig = { ...config.value.model_e };
            for (const key of ['model_a', 'model_b', 'model_c', 'model_d', 'model_f']) {
                config.value[key].api_key = eConfig.api_key;
                config.value[key].base_url = eConfig.base_url;
                config.value[key].model_name = eConfig.model_name;
                config.value[key].temperature = eConfig.temperature;
                config.value[key].max_tokens = eConfig.max_tokens;
            }
            showNotification('成功', '所有模型(A-F)已同步为章节生成(A)的配置', 'success');
            addLog('所有模型已同步为章节生成(A)的配置', 'success');
        }

        async function pausePipeline() {
            try {
                const res = await fetch(API_BASE + '/api/pause', { method: 'POST' });
                if (res.ok) {
                    state.value.status = 'paused';
                    addLog('流水线已暂停', 'warning');
                }
            } catch (e) {
                console.error('Pause failed:', e);
            }
        }

        async function resumePipeline() {
            try {
                const res = await fetch(API_BASE + '/api/resume', { method: 'POST' });
                if (res.ok) {
                    state.value.status = 'running';
                    addLog('流水线已恢复', 'success');
                }
            } catch (e) {
                console.error('Resume failed:', e);
            }
        }

        async function cancelPipeline() {
            try {
                const res = await fetch(API_BASE + '/api/cancel', { method: 'POST' });
                if (res.ok) {
                    state.value.status = 'cancelled';
                    state.value.current_step = 0;
                    
                    addLog('流水线已取消', 'warning');
                }
            } catch (e) {
                console.error('Cancel failed:', e);
            }
        }

        async function resetPipeline() {
            if (!confirm('确定要初始化吗？这将清空所有已生成的章节、大纲和缓存数据。')) {
                return;
            }

            try {
                const res = await fetch(API_BASE + '/api/reset', { method: 'POST' });
                if (res.ok) {
                    // 清空前端数据
                    chapters.value = [];
                    outlineChapters.value = [];
                    selectedChapters.value = new Set();
                    // 保留手动输入大纲内容
                    
                    logs.value = [];
                    sessionStorage.removeItem('novel_logs');
                    state.value.progress = 0;
                    state.value.current_step = 0;
                    state.value.error_message = '';
                    state.value.status = 'idle';
                    addLog('已初始化，运行缓存已清空', 'success');
                    showNotification('完成', '运行缓存已清空', 'success');
                } else {
                    const err = await res.json();
                    addLog('初始化失败: ' + (err.detail || '未知错误'), 'error');
                }
            } catch (e) {
                addLog('初始化失败: ' + e.message, 'error');
            }
        }

        async function refreshChapters() {
            try {
                const res = await fetch(API_BASE + '/api/chapters');
                if (res.ok) {
                    const data = await res.json();
                    chapters.value = data.chapters || [];
                    if (data.outline) {
                        outlineChapters.value = data.outline;
                    }
                }
            } catch (e) {
                console.error('Failed to load chapters:', e);
            }
        }

        async function openDrawer(ch) {
            drawerViewMode.value = 'diff';
            const outlineReport = state.value.outline_review_report || '';
            drawerChapter.value = {
                ...ch,
                outline_review_report: outlineReport,
            };

            // Try to get full content if it's a chapter with content
            if (ch.index && (ch.has_content || ch.content === undefined)) {
                try {
                    const res = await fetch(API_BASE + '/api/chapter/' + ch.index);
                    if (res.ok) {
                        const data = await res.json();
                        drawerChapter.value = {
                            ...ch,
                            ...data,
                            outline_review_report: outlineReport,
                        };
                    }
                } catch (e) {
                    console.error('Failed to load chapter detail:', e);
                }
            }

            drawerOpen.value = true;
        }

        function closeDrawer() {
            drawerOpen.value = false;
        }

        function toggleChapterSelection(index) {
            const newSet = new Set(selectedChapters.value);
            if (newSet.has(index)) {
                newSet.delete(index);
            } else {
                newSet.add(index);
            }
            selectedChapters.value = newSet;
        }

        function selectAllChapters() {
            const newSet = new Set();
            chapters.value.forEach(ch => newSet.add(ch.index));
            selectedChapters.value = newSet;
        }

        function deselectAllChapters() {
            selectedChapters.value = new Set();
        }

        async function regenerateSelectedChapters() {
            if (selectedChapters.value.size === 0) return;

            const indices = Array.from(selectedChapters.value).sort((a, b) => a - b);
            if (!confirm(`确定要重生成选中的 ${indices.length} 个章节吗？这将重新生成正文内容和审核结果。`)) {
                return;
            }

            addLog(`🔄 开始重生成 ${indices.length} 个章节...`, 'info');
            state.value.status = 'running';
            state.value.current_step = 3;

            try {
                const res = await fetch(API_BASE + '/api/regenerate-chapters', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ chapter_indices: indices }),
                });
                if (res.ok) {
                    addLog('重生成已启动', 'success');
                    selectedChapters.value = new Set();
                } else {
                    const err = await res.json();
                    addLog('启动重生成失败: ' + (err.detail || '未知错误'), 'error');
                    showNotification('错误', '启动重生成失败: ' + (err.detail || '未知错误'), 'error');
                    state.value.status = 'error';
                }
            } catch (e) {
                addLog('启动重生成失败: ' + e.message, 'error');
                showNotification('错误', '启动重生成失败: ' + e.message, 'error');
                state.value.status = 'error';
            }
        }

        async function regenerateSingleChapter(index) {
            selectedChapters.value = new Set([index]);
            await regenerateSelectedChapters();
        }

        async function exportNovel() {
            try {
                const res = await fetch(API_BASE + '/api/export/download');
                if (!res.ok) {
                    const errText = await res.text().catch(() => '');
                    showNotification('错误', `导出失败 (${res.status}): ${errText.slice(0, 80)}`, 'error');
                    return;
                }
                const blob = await res.blob();
                // Get filename from Content-Disposition header
                const disposition = res.headers.get('Content-Disposition') || '';
                const match = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
                const filename = match ? match[1].replace(/['"]/g, '') : 'novel.md';

                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);

                showNotification('成功', '小说导出完成', 'success');
                addLog('小说已导出: ' + filename, 'success');
            } catch (e) {
                showNotification('错误', '导出失败: ' + e.message, 'error');
            }
        }

        async function submitManualOutline() {
            if (!manualOutline.value.trim()) {
                showNotification('提示', '请输入大纲内容', 'warning');
                return;
            }

            // 清空前端数据（全新开始）
            chapters.value = [];
            outlineChapters.value = [];
            selectedChapters.value = new Set();
            logs.value = [];
            sessionStorage.removeItem('novel_logs');
            state.value.progress = 0;
            state.value.current_step = 1;  // 提交大纲后可直接开始正文生成
            state.value.error_message = '';
            state.value.status = 'idle';
            

            // 从大纲文本中自动计算章节数
            const chapterMatches = manualOutline.value.match(/第\d+章/g);
            totalChapters.value = chapterMatches ? chapterMatches.length : 10;

            addLog('📋 提交手动大纲...', 'info');

            try {
                const res = await fetch(API_BASE + '/api/submit-outline', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        outline_text: manualOutline.value,
                        total_chapters: totalChapters.value,
                        min_words: minWords.value,
                        plot: novelPlot.value,
                    }),
                });

                if (res.ok) {
                    const data = await res.json();
                    addLog(`✅ 大纲提交成功，共解析出 ${data.chapters?.length || 0} 章`, 'success');
                    showNotification('成功', `大纲提交成功，共 ${data.chapters?.length || 0} 章`, 'success');
                    // 刷新章节数据
                    await refreshChapters();
                } else {
                    const err = await res.json();
                    addLog('提交大纲失败: ' + (err.detail || '未知错误'), 'error');
                    showNotification('错误', '提交大纲失败: ' + (err.detail || '未知错误'), 'error');
                }
            } catch (e) {
                addLog('提交大纲失败: ' + e.message, 'error');
                showNotification('错误', '提交大纲失败: ' + e.message, 'error');
            }
        }

        async function startGenerateChapters() {
            if (!outlineChapters.value.length) {
                showNotification('提示', '请先提交大纲', 'warning');
                return;
            }

            state.value.progress = 0;
            state.value.current_step = 1;
            state.value.error_message = '';
            state.value.status = 'running';

            addLog('✏️ 开始正文生成...', 'info');

            try {
                const res = await fetch(API_BASE + '/api/generate-chapters', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                if (res.ok) {
                    addLog('正文生成已启动', 'success');
                } else {
                    const err = await res.json();
                    addLog('启动失败: ' + (err.detail || '未知错误'), 'error');
                    showNotification('错误', '启动失败: ' + (err.detail || '未知错误'), 'error');
                    state.value.status = 'idle';
                }
            } catch (e) {
                addLog('启动失败: ' + e.message, 'error');
                showNotification('错误', '启动失败: ' + e.message, 'error');
                state.value.status = 'idle';
            }
        }

        async function startReviewChapters() {
            if (!chapters.value.length) {
                showNotification('提示', '请先生成正文', 'warning');
                return;
            }

            state.value.progress = 0;
            state.value.current_step = 2;
            state.value.error_message = '';
            state.value.status = 'running';

            addLog('🔍 开始正文审核...', 'info');

            try {
                const res = await fetch(API_BASE + '/api/review-chapters', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                if (res.ok) {
                    addLog('正文审核已启动', 'success');
                } else {
                    const err = await res.json();
                    addLog('启动失败: ' + (err.detail || '未知错误'), 'error');
                    showNotification('错误', '启动失败: ' + (err.detail || '未知错误'), 'error');
                    state.value.status = 'idle';
                }
            } catch (e) {
                addLog('启动失败: ' + e.message, 'error');
                showNotification('错误', '启动失败: ' + e.message, 'error');
                state.value.status = 'idle';
            }
        }

        async function startOptimizeChapters() {
            if (!chapters.value.length) {
                showNotification('提示', '请先生成并审核正文', 'warning');
                return;
            }

            state.value.progress = 0;
            state.value.current_step = 3;
            state.value.error_message = '';
            state.value.status = 'running';

            addLog('🔄 开始正文优化...', 'info');

            try {
                const res = await fetch(API_BASE + '/api/optimize-chapters', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                if (res.ok) {
                    addLog('正文优化已启动', 'success');
                } else {
                    const err = await res.json();
                    addLog('启动失败: ' + (err.detail || '未知错误'), 'error');
                    showNotification('错误', '启动失败: ' + (err.detail || '未知错误'), 'error');
                    state.value.status = 'idle';
                }
            } catch (e) {
                addLog('启动失败: ' + e.message, 'error');
                showNotification('错误', '启动失败: ' + e.message, 'error');
                state.value.status = 'idle';
            }
        }

        async function startGenerateChaptersV2() {
            if (!novelPlot.value.trim()) {
                showNotification('提示', '请填写小说剧情/大纲', 'warning');
                return;
            }

            state.value.progress = 0;
            state.value.current_step = 0;
            state.value.error_message = '';
            state.value.status = 'running';

            addLog('📖 开始章节生成（AI生成大纲）...', 'info');

            try {
                const res = await fetch(API_BASE + '/api/generate-chapters-v2', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                if (res.ok) {
                    addLog('章节生成已启动', 'success');
                } else {
                    const err = await res.json();
                    addLog('启动失败: ' + (err.detail || '未知错误'), 'error');
                    showNotification('错误', '启动失败: ' + (err.detail || '未知错误'), 'error');
                    state.value.status = 'idle';
                }
            } catch (e) {
                addLog('启动失败: ' + e.message, 'error');
                showNotification('错误', '启动失败: ' + e.message, 'error');
                state.value.status = 'idle';
            }
        }

        async function startReviewAndOptimize() {
            if (!chapters.value.length) {
                showNotification('提示', '请先生成正文', 'warning');
                return;
            }

            state.value.progress = 0;
            state.value.current_step = 3;
            state.value.error_message = '';
            state.value.status = 'running';

            addLog('🎯 开始审核&优化...', 'info');

            try {
                const res = await fetch(API_BASE + '/api/review-and-optimize', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                if (res.ok) {
                    addLog('审核&优化已启动', 'success');
                } else {
                    const err = await res.json();
                    addLog('启动失败: ' + (err.detail || '未知错误'), 'error');
                    showNotification('错误', '启动失败: ' + (err.detail || '未知错误'), 'error');
                    state.value.status = 'idle';
                }
            } catch (e) {
                addLog('启动失败: ' + e.message, 'error');
                showNotification('错误', '启动失败: ' + e.message, 'error');
                state.value.status = 'idle';
            }
        }

        async function startReviewChaptersV2() {
            if (!outlineChapters.value.length) {
                showNotification('提示', '请先生成章节大纲', 'warning');
                return;
            }

            state.value.progress = 0;
            state.value.current_step = 0;
            state.value.error_message = '';
            state.value.status = 'running';

            addLog('📋 开始章节审核...', 'info');

            try {
                const res = await fetch(API_BASE + '/api/review-chapters-v2', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                if (res.ok) {
                    addLog('章节审核已启动', 'success');
                } else {
                    const err = await res.json();
                    addLog('启动失败: ' + (err.detail || '未知错误'), 'error');
                    showNotification('错误', '启动失败: ' + (err.detail || '未知错误'), 'error');
                    state.value.status = 'idle';
                }
            } catch (e) {
                addLog('启动失败: ' + e.message, 'error');
                showNotification('错误', '启动失败: ' + e.message, 'error');
                state.value.status = 'idle';
            }
        }

        async function startOptimizeChaptersV2() {
            if (!outlineChapters.value.length) {
                showNotification('提示', '请先生成章节大纲', 'warning');
                return;
            }

            state.value.progress = 0;
            state.value.current_step = 0;
            state.value.error_message = '';
            state.value.status = 'running';

            addLog('🔧 开始章节优化...', 'info');

            try {
                const res = await fetch(API_BASE + '/api/optimize-chapters-v2', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                if (res.ok) {
                    addLog('章节优化已启动', 'success');
                } else {
                    const err = await res.json();
                    addLog('启动失败: ' + (err.detail || '未知错误'), 'error');
                    showNotification('错误', '启动失败: ' + (err.detail || '未知错误'), 'error');
                    state.value.status = 'idle';
                }
            } catch (e) {
                addLog('启动失败: ' + e.message, 'error');
                showNotification('错误', '启动失败: ' + e.message, 'error');
                state.value.status = 'idle';
            }
        }

        async function saveProject() {
            try {
                const res = await fetch(API_BASE + '/api/save/download');
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    showNotification('错误', '保存失败: ' + (err.detail || '未知错误'), 'error');
                    return;
                }

                // 获取文件名
                const disposition = res.headers.get('Content-Disposition') || '';
                const match = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
                const filename = match ? match[1].replace(/['"]/g, '') : 'novel.novel';

                // 触发浏览器下载（原生保存对话框）
                const blob = await res.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                setTimeout(() => URL.revokeObjectURL(url), 10000);

                showNotification('成功', '项目进度已保存', 'success');
                addLog('项目进度已保存: ' + filename, 'success');
            } catch (e) {
                showNotification('错误', '保存失败: ' + e.message, 'error');
            }
        }

        async function loadProject() {
            if (!confirm('确定要加载已保存的进度吗？当前未保存的数据将会丢失。')) {
                return;
            }

            // 创建文件选择器
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.novel';

            input.onchange = async () => {
                const file = input.files[0];
                if (!file) return;

                try {
                    const formData = new FormData();
                    formData.append('file', file);

                    const res = await fetch(API_BASE + '/api/save/upload', {
                        method: 'POST',
                        body: formData,
                    });

                    if (res.ok) {
                        // 刷新前端数据
                        await fetchState();
                        await refreshChapters();
                        await fetchConfig();
                        state.value.status = 'idle';

                        // 显示恢复结果
                        const data = await res.clone().json().catch(() => ({}));
                        const chapterCount = data.chapter_count || chapters.value.length;
                        const stepName = data.current_step_name || '';
                        const hasContent = data.has_content || chapters.value.some(ch => ch.has_content);
                        const hasOutline = data.has_outline || outlineChapters.value.length > 0;

                        let detailMsg = `章节数: ${chapterCount}`;
                        if (hasOutline) detailMsg += `, 大纲: 已完成`;
                        if (hasContent) detailMsg += `, 正文: 已生成`;
                        detailMsg += `, 进度: ${stepName}`;

                        addLog(`项目进度已恢复: ${file.name}`, 'success');
                        addLog(detailMsg, 'info');
                        showNotification('成功', `已恢复 ${file.name}\n${detailMsg}`, 'success');
                    } else {
                        const err = await res.json();
                        addLog('加载失败: ' + (err.detail || '未知错误'), 'error');
                        showNotification('错误', '加载失败: ' + (err.detail || '未知错误'), 'error');
                    }
                } catch (e) {
                    addLog('加载失败: ' + e.message, 'error');
                    showNotification('错误', '加载失败: ' + e.message, 'error');
                }
            };

            input.click();
        }

        async function fetchState() {
            try {
                const res = await fetch(API_BASE + '/api/state');
                if (res.ok) {
                    const data = await res.json();
                    state.value = { ...state.value, ...data };
                }
            } catch (e) {
                console.error('Failed to load state:', e);
            }
        }

        // ---- 工具函数 ----

        function formatWordCount(count) {
            if (!count || count === 0) return '-';
            if (count < 1000) return count + '字';
            return (count / 1000).toFixed(1) + 'k';
        }

        // ---- 持久化 UI 状态 ----

        watch(sidebarCollapsed, (val) => {
            sessionStorage.setItem('novel_sidebar', val);
        });

        watch(chapterTab, (val) => {
            sessionStorage.setItem('novel_tab', val);
        });

        watch(manualOutline, (val) => {
            try {
                sessionStorage.setItem('novel_manual_outline', val);
            } catch { /* quota exceeded */ }
        });

        watch(novelPlot, (val) => {
            try {
                sessionStorage.setItem('novel_plot', val);
            } catch { /* quota exceeded */ }
        });

        watch(sidebarTab, (val) => {
            try {
                sessionStorage.setItem('novel_sidebar_tab', val);
            } catch { /* quota exceeded */ }
        });

        // ---- 生命周期 ----

        onMounted(async () => {
            // 恢复手动大纲输入
            try {
                const savedOutline = sessionStorage.getItem('novel_manual_outline');
                if (savedOutline) manualOutline.value = savedOutline;
            } catch { /* ignore */ }
            // 恢复小说剧情输入
            try {
                const savedPlot = sessionStorage.getItem('novel_plot');
                if (savedPlot) novelPlot.value = savedPlot;
            } catch { /* ignore */ }

            await fetchConfig();
            await fetchState();
            await refreshChapters();
            connectWS();

            // 恢复状态
            if (state.value.status === 'running' || state.value.status === 'paused') {
                addLog('检测到流水线正在运行，恢复监听...', 'info');
            }
        });

        onUnmounted(() => {
            if (ws) {
                ws.close();
                ws = null;
            }
            if (wsReconnectTimer) {
                clearTimeout(wsReconnectTimer);
            }
            if (wsPingTimer) {
                clearInterval(wsPingTimer);
            }
        });

        return {
            config,
            manualOutline,
            novelPlot,
            totalChapters,
            minWords,
            sidebarCollapsed,
            sidebarTab,
            chapterTab,
            state,
            chapters,
            outlineChapters,
            logs,
            logConsole,
            drawerOpen,
            drawerChapter,
            drawerViewMode,
            diffHtml,
            diffAddCount,
            diffDelCount,
            notificationShow,
            notificationTitle,
            notificationMessage,
            notificationClass,
            statusText,
            stateMessage,
            canStartGenerate,
            canStartReview,
            canStartOptimize,
            canStartChapterReview,
            canStartChapterOptimize,
            canStartReviewAndOptimize,
            stepClass,
            submitManualOutline,
            startGenerateChapters,
            startGenerateChaptersV2,
            startReviewChapters,
            startReviewChaptersV2,
            startOptimizeChapters,
            startOptimizeChaptersV2,
            startReviewAndOptimize,
            pausePipeline,
            resumePipeline,
            cancelPipeline,
            saveConfig,
            syncAllModels,
            saveProject,
            loadProject,
            openDrawer,
            closeDrawer,
            exportNovel,
            regenerateSelectedChapters,
            regenerateSingleChapter,
            resetPipeline,
            selectedChapters,
            selectedCount,
            canRegenerate,
            toggleChapterSelection,
            selectAllChapters,
            deselectAllChapters,
            formatWordCount,
        };
    }
});

app.mount('#app');
