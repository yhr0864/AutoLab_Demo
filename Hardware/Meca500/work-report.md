# Meca500 PDF 手册自动检索系统 - 工作汇报

## 目标

使 Claude Code 在涉及 Meca500 相关问题时，自动检索 `mc-pm-meca500.pdf` 编程手册，基于手册原文回答问题，而非凭记忆猜测。

## 方案架构

```
PDF 文本提取（一次性） → Grep 关键词定位 → Read offset/limit 精准读取 → 综合回答 + 来源标注
```

核心思路：Claude Code 原生支持 Grep + Read(offset/limit)，无需引入 MCP Server、向量数据库或 RAG 框架。

## 实施内容

### 新增文件

| 文件 | 说明 |
|------|------|
| `MecaPortal/search/manual.txt` | pdftotext 提取的全文（~10,897 行），用于 Grep 检索 |
| `MecaPortal/search/extract.sh` | 重新提取脚本，PDF 更新后运行即可刷新 |
| `MecaPortal/CLAUDE.md` | 项目记忆，含触发规则 + 五步检索流程 + 章节速查表 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `.claude/settings.local.json` | 添加 pdftotext/Read/Grep 权限 |
| `.gitignore` | 排除 `manual.txt`（衍生文件） |

## 检索流程

```
Step 0  中英术语转换   画圆→circular/arc  夹爪→gripper  奇异点→singularity
Step 1  Grep -n 定位   获取关键词所在行号
Step 2  Read offset     只读命中的 ~80 行上下文，禁止整读全文
Step 3  交叉引用        相关命令递归检索
Step 4  综合回答        基于手册原文
Step 5  来源标注        回答末尾标注 📖 信息来源（文件/关键词/章节/检索方式）
```

## 关键设计决策

- **pdftotext** 替代 Python 库：Git Bash 已内置，零依赖
- **Grep + Read offset/limit** 替代全文读取：每次只读 80 行上下文
- **原则性触发** 替代关键词枚举：避免漏触发和维护成本
- **中英术语转换** 作为 Step 0：中文提问在英文手册里直接 Grep 命中率为零（已验证）
- **CLAUDE.md 放在 MecaPortal/**：仅在机械臂相关目录生效，不影响其他项目

## 验证结果

- Read offset/limit 精准读取 ✅
- 文本提取完整性（MoveLin 96 处命中） ✅
- 中英术语转换必要性确认 ✅
- extract.sh 重新生成正常 ✅
