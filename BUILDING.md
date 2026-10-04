# 构建与本地检查

版本由 [VERSION](VERSION) 给出，当前为 `v0.1.0-rc.1`。构建只产生本地材料；它不会自行创建 Git 标签或公开 Release。发布目标为 [awei0728/kcsz-course-survey](https://github.com/awei0728/kcsz-course-survey)，[固定版本预发布入口](https://github.com/awei0728/kcsz-course-survey/releases/tag/v0.1.0-rc.1)在本次发布完成后可用。原创代码采用 [MIT](LICENSE)，来源内容排除范围见 [SOURCES.md](SOURCES.md)。

## 运行要求

使用已有 Python 3.10+，无需第三方 Python 包。当前实际测试版本为 3.14.7 和 3.12.14；最低 3.10 尚未实际运行。模型由宿主管理，构建和 Python 核心不调用模型或外部服务。

以下 PowerShell 命令中的 `$skillRoot` 是实际解压或源码目录，`$pythonPath` 是当前可用解释器的路径；不是固定安装路径。可从任何工作目录调用：

```powershell
$skillRoot = (Resolve-Path ".\kcsz-course-survey").Path
$pythonPath = (Get-Command python).Source
& $pythonPath -B "$skillRoot\scripts\survey_data.py" validate
& $pythonPath -B -m unittest discover -s "$skillRoot\tests" -v
& $pythonPath -B "$skillRoot\scripts\build_release.py"
```

如果当前目录没有源码文件夹，先将 `$skillRoot` 赋为实际目录；其余命令仍可在无关工作目录运行。测试及构建需要目录可写；不更改宿主权限。可用 `--output-dir` 指定另一可写的构建父目录。

构建默认创建一个新的 `release-candidate/<版本>-<运行标识>/`，包括：

```text
source/kcsz-course-survey/                 独立公开源码候选
kcsz-course-survey-v0.1.0-rc.1-workbuddy.zip
manifest.json                            逐文件字节数、SHA-256和来源类别
SHA256SUMS                               源码、ZIP、manifest及Release说明的校验值
release-notes.md                          对应本次构建的预发布说明附件
```

成功结果为 UTF-8 JSON，含源码、ZIP、manifest、校验文件及 Release 说明的真实绝对路径。构建退出码 0 表示本地完成，1 表示构建失败；它不改变查询/导出的结果信封或退出码。失败目录保留 `BUILD-INCOMPLETE`，不能交付为完成候选。重复运行创建新目录；显式 `--candidate-id` 已存在则拒绝覆盖。

## 白名单与可复现性

白名单在 [scripts/build_release.py](scripts/build_release.py) 的 `PUBLIC_FILES` 明确列出，16份问卷及2份PDF另有固定清单。源码快照与ZIP使用同一43项白名单。不遍历复制父仓库或整个Skill，不靠事后删除私密文件；未列出的文件不会进入候选。包括入口、必要引用、5个脚本（含构建）、18份数据JSON、2份原PDF、5份测试、README、LICENSE、来源说明、版本与构建说明、[RELEASE_NOTES.md](RELEASE_NOTES.md)及忽略规则。候选根另外保存 release-notes.md 附件，其内容与源码 RELEASE_NOTES.md 字节一致并纳入校验文件。

不打包 `.git`、虚拟环境、缓存、历史 `output`、`tmp`、规划/审计报告、本机配置、用户会话或其他Skill。PDF是明确列出的运行完整性校验依赖；缺失或哈希不符则构建失败，不能省略后跳过检查。构建也检查catalog、呈现规则及本地Markdown链接完整性。

ZIP保持已成功加载包的 `kcsz-course-survey/SKILL.md` 层级，所有文件按相对路径排序；文件时间固定为1980-01-01，权限和压缩等级固定。相同输入字节、相同Python/zlib构建环境重复构建应有相同ZIP、manifest及SHA256SUMS；源文件mtime、构建输出目录和运行标识不进入包内容。跨压缩库版本不保证ZIP字节相同，逐文件内容哈希仍可比较。

## 安装包与验证范围

新包包含开发测试及构建说明，便于独立复查。它们不是运行核心依赖。核心依赖及迁移方法见 [references/runtime.md](references/runtime.md)，宿主加载见 [references/workbuddy.md](references/workbuddy.md)。

本地检查需要独立解压，换一个工作目录执行validate，再实际生成创造力和工程伦理TXT；将正文、数量及来源映射与当前有效实现比较。即使这些检查通过，也不能据此称新包已在WorkBuddy重新加载，或16版已通过问卷星实际导入。当前反馈范围见 [references/import-feedback.md](references/import-feedback.md)。

本次用户已确认目标账号及公开仓库、原创代码 MIT、两份 PDF 可以公开，并授权源码提交、推送和预发布。来源材料及逐字题项并不因进入仓库就获得 MIT，完整边界保留在 SOURCES 中。构建不会初始化 Git、创建标签、登录、创建远程仓库、提交、推送或发布 Release；这些操作需要在独立发布工作区完成，ZIP、manifest、SHA256SUMS 等附件不提交进源码历史。
