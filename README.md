# 课程思政问卷助手

`kcsz-course-survey` 根据教师的自然语言需求，调用武汉大学两辑《课程思政教学评价指南》的正式题库，生成供教师自行导入问卷星的 UTF-8 TXT。宿主模型理解项目、版本、课程与前后测场景；Python 程序负责查询、校验和固定内容导出。

当前拟发布版本为 **v0.1.0-rc.1 预发布候选**，版本文件见 [VERSION](VERSION)。源码仓库为 [awei0728/kcsz-course-survey](https://github.com/awei0728/kcsz-course-survey)，[预发布页面](https://github.com/awei0728/kcsz-course-survey/releases/tag/v0.1.0-rc.1)及[WorkBuddy 安装 ZIP 下载入口](https://github.com/awei0728/kcsz-course-survey/releases/download/v0.1.0-rc.1/kcsz-course-survey-v0.1.0-rc.1-workbuddy.zip)在本次发布完成后可用。

项目原创代码采用 [MIT](LICENSE)。用户已确认两份来源 PDF 可以公开发布；原 PDF、量规原文、逐字转录题项及对应来源内容不纳入项目 MIT 授权范围，保留原作者与出版方的权利和来源。完整边界见 [SOURCES.md](SOURCES.md)。

## 可以做什么

- 查询已收录的评价项目及真实版本。
- 按选定项目和版本生成完整问卷；课程名称与前测、后测等场景只进入标题，不改测量内容。
- 同时交付学生问卷 TXT、教师说明与来源映射。

保留原题、选项顺序、响应尺度和原文明示分组。未收录项目不自行编题；不支持学科化改编、多量表合并、答卷分析、自动计分或在线创建问卷。反向题保留原题干，学生端隐藏教师标记，不执行反向计分。

**学生核心素养**原卷评价指标合理性，不能直接解释为学生个人素养水平测量；明确要求测个人能力时，Skill 应说明用途不匹配，不改写为能力自评。

第一版验收宿主为 **WorkBuddy**。teach_claw 的接入和运行验证留到后续版本，当前没有宣称支持。

## 收录项目与验证范围

全部 12 个项目、16 个来源版本已收录，当前规则可生成全部版本的候选 TXT。下表名称、ID 与版本来自 [正式目录](data/catalog.json)，`original` 表示该项目唯一来源版本；工程伦理的补全与适配不增加来源版本。

| 评价项目 | 稳定 ID | 来源版本 | 问卷星实际导入反馈 |
| --- | --- | --- | --- |
| 批判性思维 | `critical-thinking` | A卷、B卷 | 两版待逐版反馈 |
| 学习自我效能感 | `learning-self-efficacy` | A卷、B卷 | 两版待逐版反馈 |
| 专业认同感 | `professional-identity` | A卷、B卷 | 两版待逐版反馈 |
| 爱国主义态度 | `patriotism` | 原版 `original` | 待反馈 |
| 学生核心素养 | `core-literacy` | 原版 `original` | 待反馈 |
| 科学精神 | `scientific-spirit` | A卷、B卷 | 两版待逐版反馈 |
| 创造力 | `creativity` | 原版 `original` | 用户反馈通过 |
| 学习风格和学习投入度 | `learning-style-engagement` | 原版 `original` | 待反馈 |
| 合作和社交能力 | `cooperation-social` | 原版 `original` | 待反馈 |
| 思考方式和问题解决能力 | `thinking-problem-solving` | 原版 `original` | 待反馈 |
| 文化认同 | `cultural-identity` | 原版 `original` | 待反馈 |
| 工程伦理 | `engineering-ethics` | 原版 `original`，采用补全适配呈现 | 当前修正版用户反馈通过 |

“已收录”“已生成”“用户反馈导入通过”和“宿主实际运行通过”是不同证据。用户反馈的问卷星通过范围是创造力与工程伦理修正版共 2 版，其余 14 版仍待逐版反馈。此前安装包的 WorkBuddy 加载及创造力自然语言生成流程获用户反馈通过；本候选包未重新在 WorkBuddy 加载，当前仅做本地检查。详细记录见 [验证与反馈](references/import-feedback.md)。

## 在 WorkBuddy 安装与使用

先准备已有 WorkBuddy 环境和可用 Python。Skill 不另行要求模型 API Key 或问卷星 API Key，沿用宿主当前配置的模型。

1. 从 [v0.1.0-rc.1 预发布页面](https://github.com/awei0728/kcsz-course-survey/releases/tag/v0.1.0-rc.1)取得 `kcsz-course-survey-v0.1.0-rc.1-workbuddy.zip`；也可使用[固定版本下载入口](https://github.com/awei0728/kcsz-course-survey/releases/download/v0.1.0-rc.1/kcsz-course-survey-v0.1.0-rc.1-workbuddy.zip)。发布完成前这些远端入口尚不可用。不要只上传 `SKILL.md`，运行还需要脚本、数据、引用说明及两份原 PDF。
2. 在 WorkBuddy 打开“技能”，点击“添加技能”，选择“上传技能”，拖拽 ZIP 或点击“选择文件”导入。
3. 在已安装技能中找到并启用 `kcsz-course-survey`。新建任务，选择“做一做（Craft）”，并在对话中选择该已安装技能。
4. 使用已有模型发送下列请求。宿主应先查正式目录，再调用 Python 程序并返回实际文件。

上传与启用步骤依据 [WorkBuddy 官方技能说明](https://www.workbuddy.ai/docs/zh/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)；任务模式与选择技能依据 [官方任务栏说明](https://www.workbuddy.ai/docs/zh/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Task-Bar)，核查日期 2026-10-04。目录层级沿用此前用户成功加载的 `kcsz-course-survey/SKILL.md`，不要求手工写入猜测的安装路径。更详细的调用与交付边界见 [WorkBuddy 说明](references/workbuddy.md)。

可以直接发送：

```text
帮我生成一份用于 Python 课程前测的学生创造力问卷。
生成批判性思维B卷，用于Python课程后测。
有哪些评价项目可用？
生成工程伦理问卷。
```

单一来源版本直接生成，不必提供课程、场景或输出目录。多版本项目没有明确卷别时会询问选择；**前测不自动对应 A卷，后测不自动对应 B卷**。例如“生成批判性思维前测问卷”仍需要选 A 或 B。

## 文件在哪里

每次导出建立独立目录，不覆盖已有文件；默认位于实际加载的 Skill 根目录下 `output/`，也可以在请求中明确给出可写输出目录。安装目录只读时，应选择其他可写位置。宿主以程序结果中 `artifacts[].path` 为准返回完整实际路径或真实附件，不能凭目录名字猜位置。

| 文件 | 用途 |
| --- | --- |
| `survey.pending-import.txt` | 学生题面；UTF-8 TXT，供问卷星文本导入使用，主交付文件 |
| `teacher-notes.md` | 教师侧来源、疑点、反向标记、批准补全规则与导入限制，不粘贴进学生问卷 |
| `manifest.json` | 项目与版本、规则、数量、文件校验信息，以及源题 ID 到导出题号、矩阵行或子题的映射 |

WorkBuddy 支持文件展示时，以其实际文件机制返回 TXT；若当前会话只能提供本地文件，回复应列出完整本地路径。官方 [快速开始](https://www.workbuddy.ai/docs/workbuddy/Quickstart)介绍结果面板的文件与预览，但本 Skill 不编造下载链接或附件 API。

## 导入问卷星

1. 打开 TXT，按 UTF-8 读取并复制全文，保留原换行。不要复制教师说明或 manifest。
2. 在问卷星打开 [官方“从文本创建问卷”](https://www.wjx.cn/help/help.aspx?helpid=138)所示入口，粘贴全文并查看识别结果；入口位置以平台当时页面及官方图示为准。
3. 在投入教学使用前，逐题核对指导语、题型、矩阵行列、评分范围、开放填写槽位及选项顺序。尤其检查工程伦理参考项目仅作为说明展示，两题各为一个普通文本框。

本项目不登录问卷星、不自动创建或发布问卷。官方说明核查日期为 2026-10-04；具体图片语法曾受访问限制，不能将本地文本检查等同于平台实际识别通过。当前 2 版的导入成功依据为用户反馈，其余 14 版需要逐版核对。

## 工程伦理的适配边界

标题明确使用“大学生工程伦理问卷（作答规则补全版）”。第 3、4 题采用独立参考说明段落、`【A】`等代码、中文逗号分隔排序代码，以及原文短题干普通填空；原参考内容与顺序保留。完整问卷当前为 **11 道作答题、19 个作答字段**，说明段落不计作答题。

这属于基础题型适配，保留所选项目与重要性顺序的信息需求。重复、漏项、未知代码和“其他”说明缺失由教师人工核对；不宣称普通文本框具备原排序控件的自动校验能力，不使用付费选项引用、条件必填、计算公式或自动评分。

## Python 与独立调用

核心需要已有 **Python 3.10 或更新版本**，只使用标准库和本目录模块。此前本地验证实际使用 Python **3.14.7、3.12.14**；最低 3.10 依据所用接口确定，未把它表述为已实际测试版本。无需安装 PDF 提取库：运行读取两份 PDF 字节以校验来源 SHA-256，并不解析 PDF。

保留源码内部目录后可整体迁移，不依赖开发机盘符或父仓库模块。两份原 PDF 是现有校验依赖，不能删去后忽略错误。依赖说明见 [runtime.md](references/runtime.md)。

下面从已经解压、含 `SKILL.md` 的根目录运行；随后也可以从任意工作目录使用确定的脚本路径。参数独立传递，不将自然语言拼接为可执行 Shell 代码。

```powershell
$surveyRoot = (Get-Location).Path
$surveyPython = (Get-Command python -CommandType Application -ErrorAction Stop).Source
& $surveyPython -B (Join-Path $surveyRoot 'scripts/survey_data.py') validate
& $surveyPython -B (Join-Path $surveyRoot 'scripts/survey_data.py') list
& $surveyPython -B (Join-Path $surveyRoot 'scripts/survey_export.py') --project creativity --course 'Python课程' --scenario '前测'
& $surveyPython -B (Join-Path $surveyRoot 'scripts/survey_export.py') --project critical-thinking --version B
```

程序返回 UTF-8 JSON，生成文件由 `artifacts` 定位。退出码 0 只表示本地操作成功，2 表示请求或版本等错误，4 表示数据、呈现或目标格式问题，5 表示输出失败。不要将失败结果或旧文件当作本轮成功；详细接口见 [公共调用](references/public-call.md)。`model_trace=[]` 表示核心未调用模型，不表示宿主没有参与需求理解。

开发与可复现构建见 [BUILDING.md](BUILDING.md)，本次预发布说明见 [RELEASE_NOTES.md](RELEASE_NOTES.md)。原创代码采用 [MIT](LICENSE)；第三方来源 PDF、量规原文、转录题项及含来源内容的派生材料保留原权利，许可范围分别见 [SOURCES.md](SOURCES.md)。
