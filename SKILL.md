---
name: kcsz-course-survey
description: "课程思政问卷助手：从三个一级维度的18个价值目标中选择单个或多个目标，按核心/备份候选规则组卷，导出问卷星文本或学习通Excel；也可查询、导出保留的旧来源版本。"
---

# 课程思政问卷助手

宿主当前模型理解请求，Python负责本地选题、校验和导出，不调用内部模型API。默认使用18目标候选数据层；明确要求A/B卷或原版来源时使用保留的12项目、16来源版本入口。

## 价值目标组卷

读取[18目标调用与格式说明](references/candidate-surveys.md)。从用户请求提取价值目标及输出格式，用`candidate_survey.py --list`核对真实目录及主归属，不以来源辑别或题内维度代替一级维度。

- 单目标：默认使用该目标全部核心和备份候选；用户指定题数时从两库合并池抽取，不优先核心。
- 多目标：最多6个，同一主归属维度最多3个，默认使用各目标全部核心候选；用户指定题数时只能从核心池抽取。关联维度不影响上限。
- 指定题数用`--question-count N`，表示整份问卷总数。多目标按目标尽量均衡分配，每个目标至少1题；超出候选容量或少于目标数时返回错误，不补题或加入备份。未指定题数时不要擅自缩减。需要复现或更换抽题结果时使用`--seed`，详见调用说明。
- 问卷星选择`--format wjx`，学习通选择`--format chaoxing`；未指定格式时默认问卷星。`--goal`可重复指定，名称、稳定标识或原始项目编号均由程序解析。参数不足时只询问缺少的目标，不编造项目。
- 调用`candidate_survey.py`按用户选择的范围及题数生成问卷。当前交接题库均未获正式施测许可，默认生成`review`候选审查稿；选题不改变审批，不按风险或核心身份提升许可。`--purpose survey`由程序检查每道入选题，阻断时向用户说明具体原因。
- 检查JSON的`ok/error/artifacts`，返回真实主文件和教师说明、来源映射。问卷星主文件为UTF-8 TXT；学习通主文件为真正的`.xls`，沿用户模板的测评题结构，正确答案为空，不自动计分。平台实际导入状态须按证据报告。

原始来源30字段、五类独立确认、项目内维度与一级组织维度分别保留。新候选题文和量尺来自交接数据，不自动继承原量表效度、不统一加总或产生阈值，不自动解决科研诚信历史双量尺冲突。学生题面不展示候选ID、风险、核心/备份或一级维度标签。

```powershell
& $pythonPath -B (Join-Path $skillRoot 'scripts/candidate_survey.py') --goal '创造力' --format wjx
& $pythonPath -B (Join-Path $skillRoot 'scripts/candidate_survey.py') --goal '创造力' --goal '批判性思维' --format chaoxing
& $pythonPath -B (Join-Path $skillRoot 'scripts/candidate_survey.py') --goal '创造力' --goal '批判性思维' --question-count 10 --format chaoxing
```

## 保留的来源版本流程

TeachClaw固定命令默认使用新版18目标；仅显式`--原版`或`--版本 A/B`进入保留的来源版本。详情见[TeachClaw接入说明](references/teach-claw.md)。OpenClaw的WSL控制面通过既有统一Windows Runner调用survey环境，不直接用WSL Python运行业务，也不另建单Skill解释器桥接。插件已处理的命令不重复生成或回传。其他宿主的来源版本流程如下。

## 执行流程

1. 从请求提取评价项目、明确版本、课程、前测/后测等场景、明确输出位置。不要将整句自然语言传给项目查询，不把相关概念猜作已确认别名。
2. 定位已加载的本文件所在目录为实际Skill根目录，选择当前可用的Python解释器。按[公共调用说明](references/public-call.md)安全传递参数，先用`survey_data.py find`或`list`核实真实项目和版本。
3. 单一来源版本直接使用，不追问课程、场景等可选信息；多版本未指定时展示查询返回的版本并简短询问。前测不对应A卷，后测不对应B卷。名称含糊时展示正式目录中的真实候选；未收录则明确说明，不编题。
4. 参数足够就调用`survey_export.py`完整导出。未给输出位置时省略`--output-dir`，程序默认实际Skill目录下的`output`。正常业务生成不使用导入测试子集参数。
5. 读取UTF-8 JSON结果，检查`ok`、`error`及`artifacts`；确认产物实际存在且可读后，以`role=primary`的TXT为主返回，教师说明和manifest为辅助。按[导入反馈记录](references/import-feedback.md)简短说明项目、版本及真实验收状态。

## 来源版本内容边界

- 课程和场景仅进入现有标题参数，不改题干、选项、原序、分组或响应尺度。不得合并量规、增删测量题项、学科化改编、计分或分析答卷，不在线创建问卷。
- 学生核心素养原卷评价指标合理性；用户明确要求测学生个人能力时解释不匹配，不改成个人能力自评，也不直接为该目的导出。
- 工程伦理使用当前补全及基础题型适配整卷：q003/q004题前独立参考说明、【代码】、中文逗号、短题干普通填空。教师须人工核对排序及“其他”说明；不恢复排序控件、条件必填或付费引用。
- 保留原题干，包括否定表达；学生端隐藏教师标记，不反向赋值。原文疑点在教师说明保留，不静默修正。

## 命令与交付

下面两个变量表示已经确认的实际路径，不是宿主内置占位符；详细的解释器选择、参数数组及错误处理见[公共调用说明](references/public-call.md)。

```powershell
& $pythonPath -B (Join-Path $skillRoot 'scripts/survey_data.py') list
& $pythonPath -B (Join-Path $skillRoot 'scripts/survey_data.py') find '创造力'
& $pythonPath -B (Join-Path $skillRoot 'scripts/survey_export.py') --project creativity --version original --course 'Python课程' --scenario '前测'
```

不得将用户原话拼成Shell代码。宿主支持附件时使用其真实附件机制；仅能访问本地文件时返回完整实际路径并说明是本地文件。不能编造下载链接。`model_trace=[]`表示核心程序未调用模型，不表示宿主未参与需求理解。

加载或迁移前读取[运行文件与依赖](references/runtime.md)。核查宿主接入时分别读取[WorkBuddy](references/workbuddy.md)或[TeachClaw／teach_claw](references/teach-claw.md)，不要把不同宿主的路径、工具或模板当作通用协议。
