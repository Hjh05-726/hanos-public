# 可重复的公开版本发布

源码公开采用 PolyForm Noncommercial 1.0.0。发布不应带上开发者的私人知识目录、安装配置、运行日志或旧的私有 Git 历史。

## 公开文件的唯一清单

`release-files.txt` 逐个列出可发布文件；`.gitignore` 明确放行这些文件与父目录。测试会校验二者和 Git 文件集合一致。添加公共文件时同步更新清单、忽略规则及目录集合，禁止用通配符放行整个私人目录。

从包含本地开发内容的仓库导出全新目录：

```bash
python3 scripts/release.py export --output /absolute/path/to/new-public-source
```

输出必须是源码之外的新目录。导出不含 `.git`，不会复制未列入清单的笔记，也不会改写原仓库。导出后在新目录建立独立 Git 历史，使用准备对外公开的提交署名；检查邮箱和标签署名。

## 版本规则

`VERSION` 是版本号唯一来源，预览版使用例如 `0.1.0-preview.1`，标签对应 `v0.1.0-preview.1`。每次发布在 CHANGELOG 中写明变化、迁移和已知限制。配置的 schema version 与产品版本不是同一个字段。

在干净、已提交的公开 checkout 中：

```bash
python3 scripts/release.py check
python3 -m unittest discover -s tests -v
python3 scripts/release.py build --output /absolute/path/to/new-release-output
```

生成版本化 ZIP、逐文件 `source-manifest.json` 和 `SHA256SUMS`。构建拒绝脏工作区及已有输出目录，ZIP 固定文件顺序、时间戳与文件权限；相同工具环境和输入得到相同结果。不要把整个开发目录手工压缩后上传。

只有下载 ZIP 时，安装无需 Git。贡献测试与发布构建需要带有效 HEAD 的 Git checkout。

## 自动检查

`.github/workflows/ci.yml` 在 push、PR 和手动触发时运行：

- Linux / macOS 与选定 Python 版本的回归测试；Node.js 用于 HTML 交互测试。
- 精确公共文件清单检查及版本包构建。
- 官方 Gitleaks 工具下载校验及完整 Git 历史扫描。
- 上传有保留期限的构建产物，默认不创建公开 Release、不推送标签。

CI 使用只读仓库权限和固定 Action 提交。工作流存在不等于运行通过，首次推送后必须查看远端运行结果。凭据扫描也不能代替对项目名称、邮箱、截图内容和历史的人工隐私检查。

## 原生客户端验收

需要已登录的 Codex，使用用户已配置的模型和额度，离线 CI 不运行此步骤：

```bash
python3 tests/behavioral-evals/run_journey.py --workspace /absolute/path/to/new-empty-eval
```

该命令在新目录安装 Skill 和虚构知识，验证读取、记录、找回、保留历史的纠正、拒绝记录、HTML 生成。脚本保存每步结果、客户端身份和原始日志。原始日志可能含本机路径，留在本机，公开只保留脱敏结论和哈希。这个六步流程不等于 `cases.json` 中九个共享行为用例全部执行。

## 最后发布门槛

1. 确认公开仓库名称、维护者身份和许可证；确认旧版本授权不被误称为撤回。
2. 确认工作区、索引、全部将公开的 Git 历史、附件和示例无个人资料。
3. 测试与 CI 通过；检查 README、版本、变更记录和客户端支持范围一致。
4. 在仓库 Security 设置启用并实测私密漏洞报告入口，再公开仓库；不能使用公开 Issue 收集漏洞细节。
5. 按获授权的目标推送提交和版本标签，在对应提交创建标为 pre-release 的 GitHub Release，附 ZIP、校验值、版本说明与已知限制。
6. 从 Release 下载一次源码包，核对 SHA256SUMS，在新的本地 home 安装并运行 doctor。记录实际发布 URL、提交和资产哈希。

如果公开目标或对外发布尚未确认，完成以上本地准备并保留候选包，停在远端写入前。
