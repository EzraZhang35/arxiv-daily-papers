# arXiv 论文日报 — 搭建与使用指南

> 最后更新：2026-08-06

---

## 一、项目概述

每天自动从 arXiv 爬取 **Agent、Reinforcement Learning、Tool-use** 方向的最新论文，精选 10-20 篇，生成：
- Markdown 日报文件（`papers/YYYY-MM-DD.md`）
- 静态网页浏览（`index.html`）
- README 论文索引

### 核心技术栈
| 层 | 技术 |
|---|------|
| 数据源 | arXiv REST API（免费，无需 Key） |
| 爬取脚本 | Python 3 + feedparser + requests |
| 定时任务 | GitHub Actions（cron: `0 22 * * *` UTC） |
| 前端展示 | 纯 HTML + marked.js（GitHub Pages 免费托管） |

---

## 二、文件结构

```
arxiv-daily-papers/
├── fetch_papers.py              # 核心脚本
├── config.yaml                  # 查询/评分/排除规则配置
├── requirements.txt             # Python 依赖
├── index.html                   # 网页前端
├── README.md                    # 仓库首页（自动更新索引）
├── SETUP_GUIDE.md               # 本文档
├── .github/workflows/
│   └── daily-fetch.yml          # GitHub Actions 定时任务
└── papers/                      # 每日日报
    ├── 2026-08-05.md
    ├── 2026-08-06.md
    └── ...
```

---

## 三、本地使用

### 3.1 安装依赖

```bash
cd arxiv-daily-papers
pip install -r requirements.txt
```

依赖清单：
```
feedparser>=6.0    # 解析 arXiv Atom 格式返回
pyyaml>=6.0        # 读取 YAML 配置文件
requests>=2.31     # HTTP 请求
```

### 3.2 拉取今天的论文

```bash
python fetch_papers.py
```

### 3.3 常用参数

```bash
# 指定日期（测试历史数据）
python fetch_papers.py --date 2026-08-01

# 搜索最近 3 天的论文
python fetch_papers.py --days 3

# 调整精选数量（默认 18 篇）
python fetch_papers.py --top 25
```

### 3.4 本地预览网页

```bash
python -m http.server 8080
# 打开浏览器访问 http://localhost:8080
```

`index.html` 功能：
- 日期选择器切换日期
- 关键词实时过滤（标题/摘要/作者）
- 点击展开摘要全文
- 暗色/亮色主题自适应

---

## 四、部署到 GitHub

### 4.1 首次推送

```bash
# 在 GitHub 上创建一个新仓库（如 arxiv-daily-papers）

cd arxiv-daily-papers
git init
git add .
git commit -m "Initial commit: arXiv daily paper fetcher"
git remote add origin https://github.com/EzraZhang35/arxiv-daily-papers.git
git push -u origin main
```

### 4.2 启用 GitHub Pages

1. 进入仓库 → **Settings** → **Pages**
2. Source: `Deploy from a branch`
3. Branch: `main`, folder: `/ (root)`
4. Save → 等待 1-2 分钟部署

网页地址：`https://ezrazhang35.github.io/arxiv-daily-papers/`

### 4.3 手动触发测试

1. 进入仓库 → **Actions** → **Daily Paper Fetch**
2. 点击 **Run workflow** → **Run workflow**

### 4.4 定时任务说明

- 默认：每天 **UTC 22:00** = 北京时间 **次日 06:00**
- 修改时间：编辑 `.github/workflows/daily-fetch.yml` 中的 `cron` 字段

---

## 五、配置说明（config.yaml）

### 5.1 查询关键词

```yaml
queries:
  - label: "Agent + RL (cs.AI/cs.LG/cs.MA)"
    keywords: >
      (("reinforcement+learning"+AND+agent)+OR+...)
    categories:
      - cs.AI
      - cs.LG
```

每个查询组包含：
| 字段 | 说明 |
|------|------|
| `label` | 显示用的查询名称 |
| `keywords` | arXiv API 搜索语法（支持 AND/OR/分组） |
| `categories` | arXiv 分类过滤（如 cs.AI, cs.CL） |

### 5.2 评分规则

```yaml
score_rules:
  - keywords: ["reinforcement learning", "deep reinforcement learning"]
    weight: 3        # 标题匹配: 3分; 摘要匹配: 权重减半 (max(1, weight//2))
    field: title     # title 或 abstract
```

评分逻辑：
- 标题命中核心关键词：+3 分
- 标题命中次级关键词：+2 分
- 摘要命中：权重减半
- 多关键词累加

### 5.3 排除规则

```yaml
exclude_rules:
  - keywords: ["molecular agent", "drug agent", "anticancer"]
    field: title
```

匹配任一关键词的论文被排除（针对生物/化学/经济等非 CS 领域的 agent 论文）。

### 5.4 自定义指南

想增加新方向？在 `queries` 中添加新组：
```yaml
  - label: "RLHF & Alignment (cs.AI/cs.CL)"
    keywords: >
      (RLHF+OR+"reinforcement+learning+from+human+feedback"+OR+
       "preference+optimization"+OR+"DPO"+OR+"alignment")
    categories:
      - cs.AI
      - cs.CL
```

想在 `score_rules` 中给更高权重也加上对应规则。

---

## 六、脚本工作流程

```
启动 (python fetch_papers.py)
    │
    ▼
Phase 1: 多路查询 arXiv API
    ├── Q1: Agent + RL →                 30 results
    ├── Q2: Tool-use →                   30 results
    ├── Q3: LLM Agent →                  30 results
    └── Q4: Reasoning/Planning →         30 results
    │         └── 按 arXiv ID 去重 ──→  ~100 unique
    ▼
Phase 2: 日期过滤
    按 published date 筛选目标日期论文 →  ~40-50 papers
    │
    ▼
Phase 3: 硬排除 + 评分
    ├── hard_filter(): 排除生物/化学/经济 agent
    └── compute_relevance(): 关键词命中打分
    │
    ▼
Phase 4: 排序 + 精选 Top-N
    按 score 降序 → 取前 18 篇
    │
    ▼
Phase 5: 生成输出
    ├── papers/YYYY-MM-DD.md（Markdown 日报）
    └── README.md（更新论文索引）
```

---

## 七、Markdown 日报格式

每份日报包含：

1. **⭐ Highlights**：score ≥ 5 的推荐论文表格
2. **📋 All Papers**：全部论文表格（含分数、作者、分类）
3. **📖 Detailed Entries**：每篇论文的详细信息（作者列表、分类、arXiv ID、摘要前 5 句、命中关键词）

---

## 八、常见问题

### Q1: 为什么脚本返回 0 篇论文？
- arXiv API 有频率限制，两次请求间隔 ≥ 3 秒（已内置）
- 目标日期可能没有新论文（周末/假期提交量少）
- 尝试 `--days 2` 扩大搜索范围

### Q2: 如何添加新的搜索方向？
编辑 `config.yaml`，在 `queries` 中添加新组，在 `score_rules` 中添加对应评分规则。

### Q3: 如何修改每天推送的时间？
编辑 `.github/workflows/daily-fetch.yml`：
```yaml
schedule:
  - cron: '0 22 * * *'   # UTC 22:00
```
改为你需要的时间（UTC 时间）。

### Q4: GitHub Actions 跑失败了？
- 检查 Actions 日志
- 常见原因：arXiv API 暂时不可用（等 1 小时再试）、依赖安装失败
- 可手动触发重试

### Q5: 网页显示不出来？
- 确认 GitHub Pages 已启用
- 确认仓库是 Public（免费版 Pages 仅支持公开仓库）
- 等待 1-2 分钟部署延迟

---

## 九、相关的 arXiv API 参考

| 信息 | 值 |
|------|----|
| API 端点 | `https://export.arxiv.org/api/query` |
| 认证 | 无需 |
| 速率限制 | 建议 ≥ 3 秒间隔 |
| 返回格式 | Atom XML（用 feedparser 解析） |
| 官方文档 | https://info.arxiv.org/help/api/ |
