---
name: kcsz-course-survey
description: "课程思政问卷助手：根据自然语言生成课程评价问卷、查询可用量规和问卷版本，依据武汉大学两辑《课程思政教学评价指南》的正式题库导出供用户自行导入问卷星的UTF-8文本。适用于创造力、批判性思维、工程伦理等已收录评价项目的课程前测、后测或普通问卷生成。"
---

# 课程思政问卷助手

宿主当前模型理解请求；本Skill的Python程序查询正式12项目、16来源版本，校验并确定性导出。沿用宿主已有模型，不调用内部模型API。

## 执行流程

1. 从请求提取评价项目、明确版本、课程、前测/后测等场景、明确输出位置。不要将整句自然语言传给项目查询，不把相关概念猜作已确认别名。
2. 定位已加载的本文件所在目录为实际Skill根目录，选择当前可用的Python解释器。按[公共调用说明](references/public-call.md)安全传递参数，先用`survey_data.py find`或`list`核实真实项目和版本。
3. 单一来源版本直接使用，不追问课程、场景等可选信息；多版本未指定时展示查询返回的版本并简短询问。前测不对应A卷，后测不对应B卷。名称含糊时展示正式目录中的真实候选；未收录则明确说明，不编题。
4. 参数足够就调用`survey_export.py`完整导出。未给输出位置时省略`--output-dir`，程序默认实际Skill目录下的`output`。正常业务生成不使用导入测试子集参数。
5. 读取UTF-8 JSON结果，检查`ok`、`error`及`artifacts`；确认产物实际存在且可读后，以`role=primary`的TXT为主返回，教师说明和manifest为辅助。按[导入反馈记录](references/import-feedback.md)简短说明项目、版本及真实验收状态。

## 内容边界

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
