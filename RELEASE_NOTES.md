# v0.1.0-rc.1 — 课程思政问卷助手

这是 `kcsz-course-survey` 的首个预发布版，面向高校教师。宿主模型理解自然语言需求，调用正式题库及标准库Python程序，生成供教师自行导入问卷星的UTF-8 TXT。

## 内容与使用

- 收录武汉大学两辑《课程思政教学评价指南》的12个正式项目、16个来源版本；保留原题、选项、尺度与明确分组。
- 提供项目查询、版本选择、数据校验及问卷文本导出，同时交付独立教师说明和来源映射。
- 第一版验收宿主为WorkBuddy，teach_claw接入留待后续版本。
- 多版本未指定时选择A/B卷；前测、后测不自动对应卷别。课程和场景只进入标题。
- 不提供学科化改编、问卷合并、计分、答卷分析、在线创建问卷或内部模型API；不另行要求模型或问卷星API Key。

从本Release下载 `kcsz-course-survey-v0.1.0-rc.1-workbuddy.zip`，在WorkBuddy“技能→添加技能→上传技能”上传并启用。完整步骤见[README](https://github.com/awei0728/kcsz-course-survey/blob/v0.1.0-rc.1/README.md)。

首个使用口令：

> 帮我生成一份用于 Python 课程前测的学生创造力问卷。

## 验证范围

此前安装包的WorkBuddy加载与创造力生成流程已获**用户反馈通过**；本次重新构建包尚未在WorkBuddy重新加载。问卷星实际导入的用户通过反馈仅覆盖创造力原版与工程伦理当前修正版，其他14版仍待逐版反馈。程序本地生成成功不等于问卷星自动导入或全部宿主验收通过。

工程伦理标题保留“作答规则补全版”。第3、4题使用独立参考段落、【代码】、中文逗号排序代码及短题干普通填空；整卷为11道作答题、19个作答字段、4个说明段落。重复、漏项、未知代码和“其他”说明需人工核对，没有排序控件、付费引用、条件必填或自动评分能力。

学生核心素养原卷评价指标合理性，不直接用作学生个人能力自评。未收录项目不自行编题。

## 运行与附件

Python要求3.10+，使用标准库及同目录模块；已测试环境为3.14.7与3.12.14。运行包包含两份原PDF，以供来源字节与SHA-256完整性校验；保持其原名及内容。

Release附件：

- `kcsz-course-survey-v0.1.0-rc.1-workbuddy.zip`：完整WorkBuddy安装包，保持 `kcsz-course-survey/SKILL.md` 层级。
- `manifest.json`：公开相对路径清单、来源类别、版本与SHA-256。
- `SHA256SUMS`：源码文件、安装ZIP、manifest和Release说明的校验信息。
- `release-notes.md`：本说明的独立副本。

源码位于[公开仓库](https://github.com/awei0728/kcsz-course-survey)。GitHub自动提供标签对应的源码下载；安装ZIP作为Release附件，不进入源码提交历史。

## 许可与来源

项目原创代码、测试、Skill指令及原创说明采用MIT，版权行为 `Copyright (c) 2026 awei0728`。

两份来源PDF、量规原文、逐字转录题项/选项/指导语及对应来源内容**不纳入项目MIT授权范围**，保留原作者及出版方的权利归属与来源说明。题库、教师说明、来源映射、派生呈现规则及生成TXT中所含的来源内容也不因此获得MIT授权。

用户已确认两份PDF可以公开发布；这是本轮用户确认，不是虚构授权书、第三方开放许可证或学校背书。详细界限见[SOURCES.md](https://github.com/awei0728/kcsz-course-survey/blob/v0.1.0-rc.1/SOURCES.md)及[LICENSE](https://github.com/awei0728/kcsz-course-survey/blob/v0.1.0-rc.1/LICENSE)。
