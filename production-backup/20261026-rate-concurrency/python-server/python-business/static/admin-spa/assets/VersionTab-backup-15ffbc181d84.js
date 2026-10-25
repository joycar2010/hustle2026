import { r as interop } from './rolldown-runtime-S-ySWqyJ.js';
import { jt as getReact, E as RefreshCw, c as Upload, w as RotateCcw, d as Trash2 } from './vendor-CzHMRLXu.js';
import { mn as client, ft as getSystemInfo, dt as getServiceVersions, bt as gitRollback, vt as gitDelete, gn as useToastStore, t as Card, r as CardHeader, i as CardTitle, n as CardContent, o as Button, a as Input } from './index-C6b-aXaW-backup-15ffbc181d.js';
import { t as Badge } from './badge-CUWShJKC-backup-15ffbc181d.js';
const React = interop(getReact(), 1);
const { useState, useEffect, useRef } = React;
export async function gitPush(body) {
    const { data } = await client.post('/api/admin/system/git-push', body, { timeout: 15000, __noRetry: true });
    return data;
}
export async function getGitPushStatus() {
    const { data } = await client.get('/api/admin/system/backup-status', { timeout: 10000, __noRetry: true, __silent: true });
    return data;
}
export async function getGitHistory(refresh = false) {
    const { data } = await client.get('/api/admin/system/git-history', {
        params: refresh ? { force: true } : undefined,
        timeout: 15000, __noRetry: true, __silent: true,
    });
    return data;
}
function VersionTab() {
    const [info, setInfo] = useState(null);
    const [services, setServices] = useState([]);
    const [commits, setCommits] = useState([]);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [loadError, setLoadError] = useState('');
    const [pushMsg, setPushMsg] = useState('');
    const [defaultMessage, setDefaultMessage] = useState('自动使用最近一轮修复内容简介');
    const [job, setJob] = useState({ status: 'idle' });
    const [submitting, setSubmitting] = useState(false);
    const [mutating, setMutating] = useState(false);
    const mounted = useRef(true);
    const submittingRef = useRef(false);
    const refreshSequence = useRef(0);
    const verifiedJob = useRef('');
    const verifying = useRef(false);
    const announceJob = useRef(false);
    const addToast = useToastStore((s) => s.addToast);
    const pushing = submitting || mutating || job.status === 'running' || job.status === 'queued';
    const loadVersionData = async (force = false) => {
        const sequence = ++refreshSequence.current;
        setRefreshing(true);
        const results = await Promise.allSettled([getSystemInfo(), getGitHistory(force), getServiceVersions()]);
        if (!mounted.current || sequence !== refreshSequence.current)
            return null;
        const [infoResult, commitsResult, versionsResult] = results;
        const errors = [];
        if (infoResult.status === 'fulfilled')
            setInfo(infoResult.value);
        else
            errors.push('系统版本');
        if (commitsResult.status === 'fulfilled')
            setCommits(commitsResult.value);
        else
            errors.push('GitHub 提交历史');
        if (versionsResult.status === 'fulfilled')
            setServices(versionsResult.value.services || []);
        else
            errors.push('服务版本');
        setLoadError(errors.length ? `${errors.join('、')}刷新失败，已保留上次数据，请重试。` : '');
        setLoading(false);
        setRefreshing(false);
        return commitsResult.status === 'fulfilled' ? commitsResult.value : null;
    };
    const applyJob = async (next, announce = false) => {
        if (!mounted.current)
            return;
        setJob(next);
        if (next.default_message)
            setDefaultMessage(next.default_message);
        if (next.status === 'error') {
            if (announce || announceJob.current)
                addToast(`备份失败：${next.output || next.stage || '请重试'}`, 'error');
            announceJob.current = false;
            return;
        }
        const key = next.job_id || next.git_commit || '';
        if (next.status !== 'success' || !next.git_commit || !key || verifiedJob.current === key || verifying.current)
            return;
        verifying.current = true;
        try {
            const rows = await loadVersionData(true);
            if (!mounted.current)
                return;
            const visible = rows?.some((c) => c.hash.startsWith(next.git_commit) || next.git_commit.startsWith(c.hash));
            if (visible) {
                verifiedJob.current = key;
                setPushMsg('');
                if (announce || announceJob.current)
                    addToast(`完整备份已推送到 coin，提交 ${next.git_commit.slice(0, 8)} 已显示在历史中`, 'success');
                announceJob.current = false;
            }
            else {
                setLoadError(`备份 ${next.git_commit.slice(0, 8)} 已推送，提交历史尚未确认同步，系统会继续刷新。`);
            }
        }
        finally {
            verifying.current = false;
        }
    };
    useEffect(() => {
        mounted.current = true;
        let cancelled = false;
        let timer;
        let polls = 0;
        void loadVersionData();
        const poll = async () => {
            try {
                if (!submittingRef.current) {
                    const next = await getGitPushStatus();
                    if (!cancelled && !submittingRef.current) {
                        await applyJob(next);
                        if (!['running', 'queued'].includes(next.status) && ++polls % 5 === 0 && !verifying.current)
                            await loadVersionData();
                    }
                }
            }
            catch {
                if (!cancelled)
                    setLoadError('备份状态暂时无法获取，系统会继续查询；请勿重复提交。');
            }
            finally {
                if (!cancelled)
                    timer = setTimeout(poll, 3000);
            }
        };
        void poll();
        return () => { cancelled = true; mounted.current = false; if (timer)
            clearTimeout(timer); };
    }, []);
    const handlePush = async () => {
        if (submittingRef.current || pushing)
            return;
        submittingRef.current = true;
        setSubmitting(true);
        setLoadError('');
        verifiedJob.current = '';
        announceJob.current = true;
        try {
            const result = await gitPush({ message: pushMsg.trim() });
            await applyJob(result, true);
            if (['running', 'queued'].includes(result.status))
                addToast('完整备份任务已启动，进度与提交历史会自动刷新', 'info');
        }
        catch {
            setJob({ status: 'running', stage: '正在查询任务是否已受理，请勿重复点击' });
            addToast('推送请求结果暂未确认，正在查询服务器任务状态', 'info');
        }
        finally {
            submittingRef.current = false;
            if (mounted.current)
                setSubmitting(false);
        }
    };
    const handleRollback = async (hash, shortHash) => {
        if (!confirm(`确认滚回到提交 ${shortHash}？这将丢弃之后的所有提交。`))
            return;
        setMutating(true);
        try {
            const result = await gitRollback({ commit_hash: hash });
            addToast(result.status === 'success' ? '滚回成功' : `滚回失败: ${result.output?.slice(0, 120)}`, result.status === 'success' ? 'success' : 'error');
            await loadVersionData(true);
        }
        finally {
            if (mounted.current)
                setMutating(false);
        }
    };
    const handleDelete = async (hash, shortHash) => {
        if (!confirm(`确认撤销提交 ${shortHash}？将创建一个反转提交。`))
            return;
        setMutating(true);
        try {
            const result = await gitDelete({ commit_hash: hash });
            addToast(result.status === 'success' ? '删除成功' : `删除失败: ${result.output?.slice(0, 120)}`, result.status === 'success' ? 'success' : 'error');
            await loadVersionData(true);
        }
        finally {
            if (mounted.current)
                setMutating(false);
        }
    };
    const progress = job.status === 'success' ? 100 : Math.max(0, Math.min(99, job.progress || 0));
    if (loading)
        return React.createElement("div", { className: "text-muted-foreground py-8 text-center" }, "\u52A0\u8F7D\u4E2D...");
    return React.createElement("div", { className: "space-y-4" },
        loadError && React.createElement("div", { className: "flex items-center justify-between gap-3 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm" },
            React.createElement("span", { className: "text-warning" }, loadError),
            React.createElement(Button, { size: "sm", variant: "outline", disabled: refreshing, onClick: () => void loadVersionData(true) },
                React.createElement(RefreshCw, { className: "h-3.5 w-3.5" }),
                " \u91CD\u8BD5")),
        services.length > 0 && React.createElement("div", { className: "grid grid-cols-1 gap-3 lg:grid-cols-3" }, services.map((s) => React.createElement(Card, { key: s.service },
            React.createElement(CardContent, { className: "p-4 space-y-1.5" },
                React.createElement("div", { className: "flex items-center justify-between" },
                    React.createElement("p", { className: "text-sm font-medium" }, s.service),
                    React.createElement(Badge, { variant: ['running', 'active', 'deployed'].includes(s.status) ? 'default' : 'destructive' }, s.status)),
                React.createElement("p", { className: "text-xs text-muted-foreground" }, s.host),
                s.version && React.createElement("p", { className: "text-xs" },
                    "\u7248\u672C: ",
                    s.version),
                React.createElement("p", { className: "text-xs font-mono" },
                    "\u63D0\u4EA4: ",
                    s.git_commit || '-'),
                s.uptime && React.createElement("p", { className: "text-xs" },
                    "\u8FD0\u884C: ",
                    s.uptime),
                s.last_deploy && React.createElement("p", { className: "text-xs" },
                    "\u90E8\u7F72: ",
                    s.last_deploy))))),
        info && React.createElement("div", { className: "grid grid-cols-1 sm:grid-cols-2 gap-3 lg:grid-cols-3" },
            React.createElement(InfoCard, { label: "\u540E\u7AEF\u7248\u672C", value: info.backend_version }),
            React.createElement(InfoCard, { label: "Python", value: info.python_version }),
            React.createElement(InfoCard, { label: "\u8FD0\u884C\u65F6\u957F", value: info.uptime }),
            React.createElement(InfoCard, { label: "Git \u5206\u652F", value: info.git_branch || '-' }),
            React.createElement(InfoCard, { label: "\u6700\u65B0\u63D0\u4EA4", value: info.git_commit || '-' }),
            React.createElement(InfoCard, { label: "\u6570\u636E\u5E93", value: info.db_version })),
        React.createElement(Card, null,
            React.createElement(CardHeader, null,
                React.createElement(CardTitle, { className: "text-sm" }, "GitHub \u63A8\u9001")),
            React.createElement(CardContent, null,
                React.createElement("div", { className: "flex gap-2" },
                    React.createElement(Input, { placeholder: defaultMessage, value: pushMsg, onChange: (e) => setPushMsg(e.target.value), className: "flex-1", disabled: pushing }),
                    React.createElement(Button, { onClick: handlePush, disabled: pushing },
                        React.createElement(Upload, { className: "h-4 w-4" }),
                        " ",
                        pushing ? '备份中...' : '推送')),
                React.createElement("p", { className: "mt-2 text-xs text-muted-foreground" }, "\u5907\u4EFD\u4E24\u53F0\u670D\u52A1\u5668\u5F53\u524D\u524D\u540E\u7AEF\u6E90\u7801\u3001\u8FD0\u884C\u7A0B\u5E8F\u53CA\u524D\u7AEF dist\uFF1B\u5907\u6CE8\u7559\u7A7A\u65F6\u4F7F\u7528\u6700\u8FD1\u4E00\u8F6E\u4FEE\u590D\u5185\u5BB9\u7B80\u4ECB\u3002"),
                job.status !== 'idle' && React.createElement("div", { className: "mt-3 space-y-1", role: "status" },
                    React.createElement("div", { className: "flex items-center justify-between gap-3 text-xs text-muted-foreground" },
                        React.createElement("span", null, job.status === 'error' ? `备份失败：${job.output || job.stage || job.phase || '请重试'}` : job.stage || job.phase || (job.status === 'success' ? 'GitHub 备份完成' : '准备备份…')),
                        React.createElement("span", { className: "tabular-nums" },
                            progress,
                            "%")),
                    React.createElement("div", { className: "h-2 w-full overflow-hidden rounded-full bg-muted" },
                        React.createElement("div", { className: "h-full rounded-full bg-primary transition-all duration-300", style: { width: `${progress}%` } })),
                    job.git_commit && React.createElement("p", { className: "text-xs font-mono" },
                        "\u63D0\u4EA4\uFF1A",
                        job.git_commit.slice(0, 8),
                        job.message ? ` · ${job.message}` : '')))),
        React.createElement(Card, null,
            React.createElement(CardHeader, null,
                React.createElement(CardTitle, { className: "text-sm flex items-center justify-between" },
                    React.createElement("span", null,
                        "\u63D0\u4EA4\u5386\u53F2 ",
                        React.createElement("span", { className: "text-xs text-muted-foreground" }, "GitHub / coin")),
                    React.createElement(Button, { size: "sm", variant: "outline", onClick: () => void loadVersionData(true), disabled: refreshing },
                        React.createElement(RefreshCw, { className: "h-3.5 w-3.5" }),
                        " ",
                        refreshing ? '刷新中...' : '刷新'))),
            React.createElement(CardContent, { className: "p-0" },
                React.createElement("div", { className: "overflow-x-auto" },
                    React.createElement("table", { className: "w-full text-sm md:min-w-[600px]" },
                        React.createElement("thead", null,
                            React.createElement("tr", { className: "border-b text-left text-xs text-muted-foreground" },
                                React.createElement("th", { className: "px-4 py-3" }, "Hash"),
                                React.createElement("th", { className: "px-4 py-3" }, "\u6D88\u606F"),
                                React.createElement("th", { className: "px-4 py-3" }, "\u4F5C\u8005"),
                                React.createElement("th", { className: "px-4 py-3" }, "\u65F6\u95F4"),
                                React.createElement("th", { className: "px-4 py-3" }, "\u64CD\u4F5C"))),
                        React.createElement("tbody", null,
                            commits.length === 0 && React.createElement("tr", null,
                                React.createElement("td", { colSpan: 5, className: "px-4 py-4 text-center text-muted-foreground" }, loadError ? '提交历史暂时无法加载，请重试' : '暂无提交记录')),
                            commits.map((c) => React.createElement("tr", { key: c.hash, className: "border-b last:border-0 hover:bg-accent/50" },
                                React.createElement("td", { className: "px-4 py-2 font-mono text-xs" }, c.short_hash),
                                React.createElement("td", { className: "px-4 py-2 truncate max-w-xs", title: c.message }, c.message),
                                React.createElement("td", { className: "px-4 py-2 text-muted-foreground" }, c.author),
                                React.createElement("td", { className: "px-4 py-2 text-xs text-muted-foreground" }, c.date?.slice(0, 19)),
                                React.createElement("td", { className: "px-4 py-2" },
                                    React.createElement("div", { className: "flex gap-1" },
                                        React.createElement(Button, { size: "sm", variant: "ghost", disabled: pushing, onClick: () => void handleRollback(c.hash, c.short_hash), title: "\u6EDA\u56DE\u5230\u6B64\u63D0\u4EA4" },
                                            React.createElement(RotateCcw, { className: "h-3.5 w-3.5" })),
                                        React.createElement(Button, { size: "sm", variant: "ghost", disabled: pushing, onClick: () => void handleDelete(c.hash, c.short_hash), title: "\u64A4\u9500\u6B64\u63D0\u4EA4", className: "text-destructive hover:text-destructive" },
                                            React.createElement(Trash2, { className: "h-3.5 w-3.5" }))))))))))));
}
function InfoCard({ label, value }) {
    return (React.createElement(Card, null,
        React.createElement(CardContent, { className: "p-3" },
            React.createElement("p", { className: "text-xs text-muted-foreground" }, label),
            React.createElement("p", { className: "mt-0.5 text-sm font-medium" }, value))));
}
export { VersionTab };
