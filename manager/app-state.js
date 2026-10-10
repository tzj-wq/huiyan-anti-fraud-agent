(function () {
    const STORAGE_KEY = 'huiyan-fraud-platform-state-v1';

    const DEFAULT_STATE = {
        meta: {
            projectName: '慧眼识诈',
            projectCode: 'SE2026-13',
            owner: 'easy组',
            userName: '系统管理员',
            userRole: 'Easy组 负责人',
            systemVersion: 'V1.1',
            updatedAt: '2026-04-14 10:24:55'
        },
        dashboard: {
            transactionsBase: 1284592,
            transactionDelta: 12.5,
            tpr: 97.82,
            p99: 1.24,
            timeWindow: '1h',
            regionStats: {
                '1h': [
                    { city: '上海', value: 950, level: 'critical' },
                    { city: '深圳', value: 890, level: 'high' },
                    { city: '成都', value: 760, level: 'high' },
                    { city: '北京', value: 710, level: 'high' },
                    { city: '杭州', value: 540, level: 'medium' },
                    { city: '武汉', value: 320, level: 'medium' }
                ],
                '24h': [
                    { city: '上海', value: 3220, level: 'critical' },
                    { city: '深圳', value: 2960, level: 'critical' },
                    { city: '成都', value: 2410, level: 'high' },
                    { city: '北京', value: 2280, level: 'high' },
                    { city: '杭州', value: 1620, level: 'medium' },
                    { city: '武汉', value: 980, level: 'medium' }
                ]
            },
            fraudComposition: [
                { name: '洗钱交易', value: 1048 },
                { name: '盗卡刷卡', value: 735 },
                { name: '协同攻击', value: 580 },
                { name: '营销薅羊毛', value: 484 },
                { name: '虚假交易', value: 300 }
            ]
        },
        strategy: {
            environment: 'prod',
            threshold: 60,
            maxDepth: 5,
            rlhfEnabled: false,
            lastValidation: {
                status: 'success',
                message: '规则语法校验通过，可进入沙箱压测。'
            },
            draftRule: JSON.stringify({
                strategyName: 'high-risk-transfer-v1',
                trigger: 'amount > 500000 && velocityScore >= 0.82',
                action: 'manual_review',
                whitelistBypass: true,
                requireEvidence: ['名单命中', '行为异常', '图谱关联']
            }, null, 2),
            agents: [
                {
                    id: 'list-match',
                    name: '名单匹配 Agent',
                    color: '#1d4ed8',
                    status: 'ACTIVE',
                    priority: 'P0',
                    active: true,
                    weight: 28,
                    latency: 8,
                    prompt: '对比 CMARC 与内外部黑白名单，要求命中准确率 100%，响应延迟低于 10ms。'
                },
                {
                    id: 'transaction-analysis',
                    name: '交易分析 Agent',
                    color: '#0f766e',
                    status: 'ACTIVE',
                    priority: 'P0',
                    active: true,
                    weight: 22,
                    latency: 15,
                    prompt: '分析交易金额、频率、时间窗口与地域切换，捕捉异常波动和高危组合。'
                },
                {
                    id: 'behavior-modeling',
                    name: '行为建模 Agent',
                    color: '#7c3aed',
                    status: 'ACTIVE',
                    priority: 'P1',
                    active: true,
                    weight: 18,
                    latency: 240,
                    prompt: '识别自动化脚本、页面操作熵异常和登录到提现的非人类路径模式。'
                },
                {
                    id: 'graph-trace',
                    name: '图关联溯源 Agent',
                    color: '#ea580c',
                    status: 'ACTIVE',
                    priority: 'P0',
                    active: true,
                    weight: 32,
                    latency: 850,
                    prompt: '执行多跳转账子图匹配，识别辐射型和循环型洗钱网络结构。'
                }
            ],
            versions: [
                {
                    id: 'V1.1',
                    status: 'active',
                    publishedAt: '2026-04-14 10:24',
                    recall: 97.4,
                    fpr: 0.04,
                    p99: '1.24s',
                    notes: '现网稳定版本，支持人工仲裁阈值与证据链落库。'
                },
                {
                    id: 'V1.0',
                    status: 'archived',
                    publishedAt: '2026-04-10 15:30',
                    recall: 96.8,
                    fpr: 0.06,
                    p99: '1.18s',
                    notes: '首个发布版本，未启用 A/B 实验对照流程。'
                }
            ],
            abTests: [
                {
                    id: 'AB-20260414-01',
                    name: '高危名单增强实验',
                    baseline: 'V1.1',
                    challenger: 'V1.2-rc1',
                    status: 'running',
                    sampleSize: 1200,
                    recallDelta: 1.2,
                    fprDelta: -0.01,
                    latencyDelta: 120,
                    recommendation: '建议发布'
                }
            ],
            sandbox: {
                sampleSize: 1000,
                tpr: 97.4,
                precision: 99.1,
                p99Buckets: [20, 40, 90, 50, 10]
            }
        },
        cases: [
            {
                id: 'CASE-98214',
                accountName: '张*强',
                phone: '138****9281',
                uid: '8219401',
                region: '上海',
                riskScore: 98,
                fraudType: '团伙洗钱',
                status: '待审理',
                severity: 'critical',
                amount: 1240000,
                consensus: 100,
                time: '2026-04-14 10:24:12',
                recommendedAction: '自动拦截',
                needsArbitration: false,
                features: ['IP段聚集', '快速提现', '设备共用'],
                verdict: '',
                reviewComment: '',
                evidenceChain: [
                    { agent: '名单匹配 Agent', time: '10:24:12.001', summary: '命中 CMARC-2026-X01 风险标识，关联 IP 曾参与 2026-03 团伙欺诈活动。', scoreText: '初步风险评分: 90/100', color: 'red' },
                    { agent: '行为建模 Agent', time: '10:24:12.145', summary: '登录到提现仅耗时 1.2s，避开业务引导，符合自动化脚本特征。', scoreText: '补充风险评分: +5', color: 'blue' },
                    { agent: '图关联溯源 Agent', time: '10:24:12.450', summary: '与 12 个二级风险节点存在资金往来，形成辐射型洗钱结构。', scoreText: '确定性权重提升至: 98%', color: 'purple' },
                    { agent: '决策审批 Agent', time: '10:24:12.800', summary: '5 票赞成，触发自动拦截并生成证据包入库。', scoreText: '审批结果: 欺诈拦截', color: 'green' }
                ]
            },
            {
                id: 'CASE-98213',
                accountName: '王*',
                phone: '155****0023',
                uid: '9284121',
                region: '深圳',
                riskScore: 84,
                fraudType: '异地登录',
                status: '处理中',
                severity: 'high',
                amount: 368000,
                consensus: 74,
                time: '2026-04-14 10:22:05',
                recommendedAction: '人工复核',
                needsArbitration: false,
                features: ['跨省登录', '夜间异常', '设备指纹漂移'],
                verdict: '待观察',
                reviewComment: '需补充近 24 小时设备登录轨迹。',
                evidenceChain: [
                    { agent: '交易分析 Agent', time: '10:22:05.021', summary: '同账号 20 分钟内在深圳和哈尔滨两地发起登录。', scoreText: '基础风险评分: 68/100', color: 'teal' },
                    { agent: '行为建模 Agent', time: '10:22:05.102', summary: '输入节奏与历史画像偏差 47%，设备指纹有重置痕迹。', scoreText: '补充风险评分: +9', color: 'purple' },
                    { agent: '决策审批 Agent', time: '10:22:05.500', summary: '建议转人工复核，等待补充证据。', scoreText: '审批结果: 待观察', color: 'green' }
                ]
            },
            {
                id: 'CASE-98210',
                accountName: 'LUCAS H.',
                phone: '177****2198',
                uid: '7728101',
                region: '成都',
                riskScore: 65,
                fraudType: '营销薅羊毛',
                status: '待审理',
                severity: 'medium',
                amount: 52800,
                consensus: 58,
                time: '2026-04-14 09:58:32',
                recommendedAction: '人工仲裁',
                needsArbitration: true,
                features: ['优惠券套取', '设备复用', '低频多账号'],
                verdict: '',
                reviewComment: '',
                evidenceChain: [
                    { agent: '交易分析 Agent', time: '09:58:32.018', summary: '促销时段内多次小额拆单，金额分布呈规则化。', scoreText: '基础风险评分: 52/100', color: 'teal' },
                    { agent: '名单匹配 Agent', time: '09:58:32.080', summary: '未命中黑名单，灰度观察名单命中同设备 2 个账号。', scoreText: '补充风险评分: +6', color: 'red' },
                    { agent: '决策审批 Agent', time: '09:58:32.390', summary: '一致性低于人工仲裁阈值，自动挂起待人工处理。', scoreText: '审批结果: 需仲裁', color: 'green' }
                ]
            },
            {
                id: 'CASE-98196',
                accountName: '陈*',
                phone: '136****6501',
                uid: '6651219',
                region: '杭州',
                riskScore: 91,
                fraudType: '盗卡刷卡',
                status: '已完成',
                severity: 'critical',
                amount: 852000,
                consensus: 92,
                time: '2026-04-14 09:11:46',
                recommendedAction: '自动拦截',
                needsArbitration: false,
                verdict: '欺诈',
                reviewComment: '已确认盗刷，封禁卡组织通道。',
                features: ['异国 MCC', '高频失败尝试', '终端陌生'],
                evidenceChain: [
                    { agent: '名单匹配 Agent', time: '09:11:46.011', summary: '境外卡组织风险库命中高危商户标签。', scoreText: '基础风险评分: 81/100', color: 'red' },
                    { agent: '交易分析 Agent', time: '09:11:46.102', summary: '5 分钟内失败 13 次后完成 2 次扣款。', scoreText: '补充风险评分: +10', color: 'teal' },
                    { agent: '决策审批 Agent', time: '09:11:46.402', summary: '通过自动封禁并通知卡组织。', scoreText: '审批结果: 已拦截', color: 'green' }
                ]
            }
        ],
        data: {
            lists: [
                {
                    id: 'list-black-high',
                    name: '高风险黑名单',
                    level: 'L3',
                    category: '黑名单',
                    count: 12401,
                    updatedAt: '2026-04-14 08:20',
                    owner: '系统管理员',
                    status: '同步完成',
                    desc: '高危欺诈主体名单，适用于自动拦截。',
                    maskedFields: '身份证、手机号、设备ID',
                    hitRate: '14.8%'
                },
                {
                    id: 'list-white-core',
                    name: '核心免审白名单',
                    level: 'L1',
                    category: '白名单',
                    count: 5200,
                    updatedAt: '2026-04-13 09:15',
                    owner: '风控运营',
                    status: '已审核',
                    desc: '核心可信主体名单，满足快速放行策略。',
                    maskedFields: '手机号、卡号后四位',
                    hitRate: '6.2%'
                },
                {
                    id: 'list-grey-watch',
                    name: '灰度观察名单',
                    level: 'L2',
                    category: '观察名单',
                    count: 82901,
                    updatedAt: '2026-04-14 05:10',
                    owner: '策略分析师',
                    status: '待复核',
                    desc: '用于人工观察和规则迭代的灰度池。',
                    maskedFields: '姓名、设备ID',
                    hitRate: '22.4%'
                }
            ],
            apiEndpoints: [
                { id: 'api-cmarc', name: 'CMARC 预警中心 API', reqPerSec: 124.5, p99: 12, successRate: 100, status: 'Online' },
                { id: 'api-credit', name: '第三方征信 API (百行)', reqPerSec: 42.1, p99: 245, successRate: 99.8, status: 'Online' },
                { id: 'api-id', name: '公安部身份校验', reqPerSec: 1204, p99: 8, successRate: 100, status: 'Online' },
                { id: 'api-oversea', name: '境外卡组织风险库', reqPerSec: 15.2, p99: 1400, successRate: 94.2, status: 'Slow' }
            ],
            knowledgePool: [
                {
                    id: 'KP-20260414-01',
                    title: '异地登录误报样本',
                    source: '人工复核',
                    updatedAt: '2026-04-14 09:40',
                    summary: '用于优化行为建模 Agent 的低时延异地登录判定阈值。'
                }
            ],
            auditLogs: [
                { id: 'AUD-1', time: '2026-04-14 10:12:01', module: '策略配置', action: 'Update', target: '策略-Agent 决策权重', user: 'Admin_01', ip: '10.24.1.192', detail: '调整图关联溯源 Agent 权重至 32%' },
                { id: 'AUD-2', time: '2026-04-14 09:55:12', module: '基础数据', action: 'Delete', target: '黑名单-测试白名单_V2', user: 'Admin_01', ip: '10.24.1.192', detail: '删除过期测试名单' },
                { id: 'AUD-3', time: '2026-04-14 09:42:45', module: '系统任务', action: 'Create', target: '全局数据库镜像', user: 'System', ip: 'localhost', detail: '自动备份完成' }
            ]
        }
    };

    function clone(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function mergeDefaults(base, source) {
        if (Array.isArray(base)) {
            return Array.isArray(source) ? source : clone(base);
        }
        if (base && typeof base === 'object') {
            const output = {};
            const sourceObject = source && typeof source === 'object' ? source : {};
            const keys = new Set([...Object.keys(base), ...Object.keys(sourceObject)]);
            keys.forEach((key) => {
                output[key] = mergeDefaults(base[key], sourceObject[key]);
            });
            return output;
        }
        return source === undefined ? base : source;
    }

    function loadState() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) {
                const initialState = clone(DEFAULT_STATE);
                localStorage.setItem(STORAGE_KEY, JSON.stringify(initialState));
                return initialState;
            }
            return mergeDefaults(DEFAULT_STATE, JSON.parse(raw));
        } catch (error) {
            const fallbackState = clone(DEFAULT_STATE);
            localStorage.setItem(STORAGE_KEY, JSON.stringify(fallbackState));
            return fallbackState;
        }
    }

    function saveState(state) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
        return state;
    }

    function updateState(mutator) {
        const state = loadState();
        const nextState = mutator(state) || state;
        saveState(nextState);
        return nextState;
    }

    function nowLabel() {
        return new Date().toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        }).replace(/\//g, '-');
    }

    function formatNumber(value) {
        return Number(value || 0).toLocaleString('zh-CN');
    }

    function formatCurrency(value) {
        return `¥ ${Number(value || 0).toLocaleString('zh-CN', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        })}`;
    }

    function formatPercent(value, digits) {
        return `${Number(value || 0).toFixed(digits === undefined ? 1 : digits)}%`;
    }

    function pushAuditLog(state, entry) {
        state.data.auditLogs.unshift({
            id: `AUD-${Date.now()}`,
            time: nowLabel(),
            user: '系统管理员',
            ip: '10.24.1.192',
            module: '系统',
            action: 'Update',
            target: '未命名操作',
            detail: '',
            ...entry
        });
        state.data.auditLogs = state.data.auditLogs.slice(0, 30);
        return state;
    }

    function pushKnowledgeEntry(state, entry) {
        state.data.knowledgePool.unshift({
            id: `KP-${Date.now()}`,
            updatedAt: nowLabel(),
            source: '人工复核',
            title: '未命名知识条目',
            summary: '',
            ...entry
        });
        state.data.knowledgePool = state.data.knowledgePool.slice(0, 20);
        return state;
    }

    function getStatusTone(status) {
        const tones = {
            '待审理': { badge: 'bg-amber-100 text-amber-700', label: '待审理' },
            '处理中': { badge: 'bg-blue-100 text-blue-700', label: '处理中' },
            '已完成': { badge: 'bg-emerald-100 text-emerald-700', label: '已完成' },
            'Online': { badge: 'bg-emerald-100 text-emerald-700', label: 'Online' },
            'Slow': { badge: 'bg-amber-100 text-amber-700', label: 'Slow' },
            'Offline': { badge: 'bg-red-100 text-red-700', label: 'Offline' }
        };
        return tones[status] || { badge: 'bg-slate-100 text-slate-700', label: status };
    }

    function getSeverityTone(severity) {
        const tones = {
            critical: { badge: 'bg-red-100 text-red-700', dot: 'bg-red-500' },
            high: { badge: 'bg-orange-100 text-orange-700', dot: 'bg-orange-500' },
            medium: { badge: 'bg-yellow-100 text-yellow-700', dot: 'bg-yellow-500' },
            low: { badge: 'bg-slate-100 text-slate-700', dot: 'bg-slate-400' }
        };
        return tones[severity] || tones.low;
    }

    window.PlatformStore = {
        STORAGE_KEY,
        DEFAULT_STATE: clone(DEFAULT_STATE),
        loadState,
        saveState,
        updateState,
        clone,
        nowLabel,
        formatNumber,
        formatCurrency,
        formatPercent,
        pushAuditLog,
        pushKnowledgeEntry,
        getStatusTone,
        getSeverityTone
    };
})();
