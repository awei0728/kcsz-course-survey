# WorkBuddy安装与调用

本版为 `v0.2.0-rc.1`。此前包的WorkBuddy加载及创造力自然语言生成收到过用户成功反馈；本版沿用包层级，但未把历史反馈写成本版重新加载已通过。平台界面核查记录来自2026-10-04，实际操作以当前宿主为准。

## 安装

从 [本版发布页](https://github.com/awei0728/kcsz-course-survey/releases/tag/v0.2.0-rc.1)取得 [完整ZIP](https://github.com/awei0728/kcsz-course-survey/releases/download/v0.2.0-rc.1/kcsz-course-survey-v0.2.0-rc.1-workbuddy.zip)，在WorkBuddy“技能→添加技能→上传技能”导入并启用。新建“做一做（Craft）”任务，选择该Skill，沿用宿主已有模型。

操作依据为 [官方技能说明](https://www.workbuddy.ai/docs/zh/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market) 和 [官方任务栏说明](https://www.workbuddy.ai/docs/zh/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Task-Bar)。不把其他产品的安装目录、工具或路径占位符当作通用协议。

ZIP保留 `kcsz-course-survey/SKILL.md` 层级，包含脚本、两套数据、维度证据、学习通模板、必要引用及旧来源PDF。不要只上传SKILL.md或删除资料后跳过校验；资源依赖见 [runtime.md](runtime.md)。

## 新版自然语言流程

```text
生成创造力问卷，选8题，输出问卷星文本。
将爱国主义态度、创造力、学习自我效能感组合为10题问卷，输出学习通Excel。
有哪些价值目标可用？
```

宿主先按 [18目标组卷](candidate-surveys.md) 查询真实目标及主维度，再调用 `candidate_survey.py`。单目标默认全核心＋备份，指定题数从两库同权池抽取；多目标默认全核心，指定总题数仅从核心池抽取，最多6目标、同主维度最多3目标。未指定题数时不擅自截断，未指定格式时默认问卷星。

候选流程不追问A/B卷。只有用户明确原版或A/B卷时，才进入保留的12项目、16来源流程；前测、后测不自动决定卷别，课程/场景参数只属于旧来源标题流程。旧学生核心素养原卷是指标合理性判断，旧工程伦理仍使用作答规则补全及基础题型适配。

## 安全调用与交付

定位实际加载的Skill目录和可用Python3.10+，以独立argv传参，按 [公共调用说明](public-call.md) 读取UTF-8 JSON。确认 `ok/error/artifacts` 及实际文件存在后，返回 `role=primary` 的TXT或XLS，同时提供教师说明与来源映射；不能凭目录名推测路径或在错误后交付旧文件。

使用宿主当前真实的文件展示机制；若只能提供本地文件，返回完整实际路径，不编造下载链接或附件API。[官方快速开始](https://www.workbuddy.ai/docs/workbuddy/Quickstart)不构成Python附件协议。

当前482题仍为候选，默认交付审查稿；软件发布和抽中题目不会授予施测许可。两种格式的当次平台导入均待验证。旧问卷星创造力原版与工程伦理修正版2版的用户反馈不扩展到新版候选或全部旧来源版本，详见 [反馈记录](import-feedback.md)。

原创程序与原创说明采用 [MIT](../LICENSE)，来源内容和上传模板的范围见 [SOURCES](../SOURCES.md)。
